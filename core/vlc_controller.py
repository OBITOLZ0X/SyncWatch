"""
SyncWatch - VLC media player controller via HTTP/JSON interface.

Launches VLC with its built-in HTTP interface enabled, then controls
playback (play, pause, seek, load file) and monitors state changes
through periodic polling.  OSD messages are delivered through a
shared text file read by the companion Lua script.  GIF images are
displayed inside VLC's video via the logo sub-filter, controlled
through VLC's RC (telnet) interface.
"""
import base64
import json
import logging
import os
import random
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QImage

from .paths import get_osd_path, get_gif_frame_dir

log = logging.getLogger(__name__)

_LOGO_MAX_DIM = 180      # max gif width/height for the logo overlay


class VLCController(QObject):
    """Controls VLC media player through its built-in HTTP/JSON API."""

    # ── Signals ───────────────────────────────────────────
    file_changed = Signal(str, int, float)   # name, size, duration
    state_changed = Signal(bool, float)      # paused, position
    vlc_closed = Signal()
    vlc_ready = Signal()

    POLL_MS = 150

    def __init__(self, vlc_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._vlc_path = vlc_path or self._find_vlc()
        self._process: Optional[subprocess.Popen] = None
        self._port = random.randint(9100, 9899)
        self._rc_port = random.randint(9900, 9999)
        self._password = "syncwatch"
        self._auth = "Basic " + base64.b64encode(
            f":{self._password}".encode()
        ).decode()

        # Playback state
        self._file_name = ""
        self._file_path = ""
        self._file_size = 0
        self._duration = 0.0
        self._position = 0.0
        self._paused = True
        self._connected = False
        self._suppress = False
        self._initial_file: Optional[str] = None   # file passed on launch
        self._connect_attempts = 0

        # Command queue: prevents overlapping VLC commands
        self._cmd_queue: list = []    # [(command_type, args), ...]
        self._cmd_busy = False        # True while a command is being executed

        # OSD temp file (read by the Lua intf script inside VLC)
        self._osd_path = get_osd_path()

        # OSD — persistent + temporary text messages via Lua file
        self._osd_persistent: dict = {}      # key -> text (always shown)
        self._osd_temp: list = []             # [(text, expiry_timestamp), ...]
        self._osd_tick_timer = QTimer(self)
        self._osd_tick_timer.setInterval(500)
        self._osd_tick_timer.timeout.connect(self._osd_tick)

        # VLC RC (telnet) interface for logo sub-filter control
        self._rc_sock: Optional[socket.socket] = None

        # GIF-on-video via VLC logo sub-filter
        self._gif_frame_dir = get_gif_frame_dir()
        self._logo_clear_timer = QTimer(self)
        self._logo_clear_timer.setSingleShot(True)
        self._logo_clear_timer.timeout.connect(self._clear_logo)

        # Polling timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ── VLC Discovery ─────────────────────────────────────

    @staticmethod
    def _find_vlc() -> str:
        """Auto-detect VLC executable on the current platform."""
        if sys.platform == "win32":
            for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
                base = os.environ.get(var, "")
                if base:
                    p = os.path.join(base, "VideoLAN", "VLC", "vlc.exe")
                    if os.path.isfile(p):
                        return p
        elif sys.platform == "darwin":
            p = "/Applications/VLC.app/Contents/MacOS/VLC"
            if os.path.isfile(p):
                return p
        else:
            for p in ("/usr/bin/vlc", "/usr/local/bin/vlc", "/snap/bin/vlc"):
                if os.path.isfile(p):
                    return p
        return ""

    # ── Lua OSD Script Installation ───────────────────────

    @staticmethod
    def _resource_path(*parts) -> str:
        """Resolve a resource path, works both in dev and PyInstaller bundle."""
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, *parts)

    def _install_lua(self) -> bool:
        """Copy the SyncWatch OSD Lua script into VLC's user intf directory."""
        src = self._resource_path("resources", "syncwatch_osd.lua")
        if not os.path.isfile(src):
            return False

        if sys.platform == "win32":
            dst_dir = os.path.join(
                os.environ.get("APPDATA", ""), "vlc", "lua", "intf"
            )
        elif sys.platform == "darwin":
            dst_dir = os.path.expanduser(
                "~/Library/Application Support/org.videolan.vlc/lua/intf"
            )
        else:
            dst_dir = os.path.expanduser("~/.local/share/vlc/lua/intf")

        try:
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, "syncwatch_osd.lua"))
            return True
        except Exception as exc:
            log.warning("Lua OSD script install failed: %s", exc)
            return False

    # ── Launch / Close ────────────────────────────────────

    def launch(self, file_path=None) -> bool:
        """Start VLC with the HTTP control interface enabled."""
        if not self._vlc_path:
            log.error("VLC executable not found")
            return False

        lua_ok = self._install_lua()

        # VLC's HTTP API needs the lua/http source directory
        http_src = os.path.join(os.path.dirname(self._vlc_path), "lua", "http")

        env = os.environ.copy()
        env["SYNCWATCH_OSD_FILE"] = self._osd_path

        # Create a tiny transparent PNG so the logo sub-filter
        # initialises properly (empty --logo-file prevents loading).
        blank_logo = self._create_blank_logo()

        args = [
            self._vlc_path,
            "--extraintf", "http:rc",
            "--http-host", "127.0.0.1",
            "--http-port", str(self._port),
            "--http-password", self._password,
            "--rc-host", f"127.0.0.1:{self._rc_port}",
            "--rc-quiet",
            # Logo sub-filter for GIF display on video
            "--sub-source=logo",
            f"--logo-file={blank_logo}",
            "--logo-position=9",
            "--logo-opacity=0",
            "--logo-repeat=-1",
            "--no-video-title-show",
            "--no-qt-privacy-ask",
            "--no-random",
            "--no-loop",
            "--no-repeat",
            "--start-paused",
        ]

        if os.path.isdir(http_src):
            args += ["--http-src", http_src]

        if lua_ok:
            args += ["--control", "luaintf", "--lua-intf", "syncwatch_osd"]

        if file_path:
            file_path = os.path.normpath(file_path)
            self._initial_file = file_path
            self._file_path = file_path
            self._file_size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
            self._file_name = os.path.basename(file_path)
            args.append(file_path)
            log.info("VLC launch with file: %s (exists=%s, size=%d)",
                     file_path, os.path.isfile(file_path), self._file_size)

        try:
            kw = {
                "env": env,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._process = subprocess.Popen(args, **kw)
            log.info(
                "VLC started (pid=%d, http=%d, rc=%d, logo=%s)",
                self._process.pid, self._port, self._rc_port, blank_logo,
            )
            # Give VLC time to initialise, then start trying to connect
            self._connect_attempts = 0
            self._osd_persistent.clear()
            self._osd_temp.clear()
            QTimer.singleShot(2000, self._try_connect)
            return True
        except Exception as exc:
            log.error("Failed to start VLC: %s", exc)
            return False

    # ── Connection Handshake ──────────────────────────────

    def _try_connect(self):
        self._connect_attempts += 1
        log.info("VLC connection attempt %d ...", self._connect_attempts)
        status = self._http()
        if status:
            self._connected = True
            self._osd_tick_timer.start()
            # Connect to VLC's RC interface for logo control
            QTimer.singleShot(1000, self._rc_connect)
            log.info("VLC HTTP connected on attempt %d", self._connect_attempts)
            # If launched with a file, force pause and record duration
            if self._initial_file:
                self._duration = float(status.get("length", 0))
                self._suppress = True
                QTimer.singleShot(500, self._force_pause_initial)
                QTimer.singleShot(2500, self._enable_events)
                self._initial_file = None
            self._timer.start(self.POLL_MS)
            self.vlc_ready.emit()
        elif self._connect_attempts < 15:
            QTimer.singleShot(2000, self._try_connect)
        else:
            log.error("VLC HTTP interface did not respond after %d attempts", self._connect_attempts)

    def _force_pause_initial(self):
        """Force VLC to pause right after connecting (initial file load)."""
        s = self._http()
        if s and s.get("state") == "playing":
            self._http(params="command=pl_pause")
        self._paused = True

    def close(self):
        """Terminate VLC and clean up resources."""
        self._timer.stop()
        self._osd_tick_timer.stop()
        self._logo_clear_timer.stop()
        self._connected = False
        self._rc_disconnect()
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        try:
            os.remove(self._osd_path)
        except OSError:
            pass
        try:
            shutil.rmtree(self._gif_frame_dir, ignore_errors=True)
        except Exception:
            pass

    # ── HTTP/JSON API ─────────────────────────────────────

    def _http(self, params: str = ""):
        """Execute an authenticated request against VLC's status.json endpoint."""
        url = f"http://127.0.0.1:{self._port}/requests/status.json"
        if params:
            url += f"?{params}"
        req = Request(url)
        req.add_header("Authorization", self._auth)
        try:
            with urlopen(req, timeout=1.5) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            log.debug("VLC HTTP request failed: %s", exc)
            return None

    # ── Periodic Status Polling ───────────────────────────

    def _poll(self):
        # Check whether VLC is still alive
        if self._process and self._process.poll() is not None:
            self._connected = False
            self._timer.stop()
            self.vlc_closed.emit()
            return

        status = self._http()
        if not status:
            return

        state = status.get("state", "stopped")
        paused = state != "playing"
        position = float(status.get("time", 0))
        duration = float(status.get("length", 0))

        # Extract filename from VLC metadata
        meta = (
            status.get("information", {})
            .get("category", {})
            .get("meta", {})
        )
        filename = meta.get("filename", "")

        # ── File change detection ──
        if filename and filename != self._file_name:
            old_name = self._file_name
            self._file_name = filename
            self._duration = duration
            log.info("VLC file changed: '%s' -> '%s'", old_name, filename)
            self.file_changed.emit(filename, self._file_size, duration)

        self._duration = duration

        # ── Playback state ──
        if not self._suppress:
            old_paused = self._paused
            old_pos = self._position
            self._paused = paused
            self._position = position
            if paused != old_paused or abs(position - old_pos) > 5.0:
                self.state_changed.emit(paused, position)
        else:
            self._paused = paused
            self._position = position

    # ── Playback Controls ─────────────────────────────────

    def set_paused(self, paused: bool):
        """Set the pause state in VLC, toggling only if needed."""
        s = self._http()
        if not s:
            return
        currently_paused = s.get("state", "") != "playing"
        if paused != currently_paused:
            self._http(params="command=pl_pause")
        self._paused = paused

    def set_position(self, seconds: float):
        """Seek VLC to *seconds*. Skips if already close enough."""
        if abs(self._position - seconds) < 0.3:
            return
        self._suppress = True
        self._http(params=f"command=seek&val={int(seconds)}")
        self._position = seconds
        QTimer.singleShot(400, self._enable_events)

    # ── Queued Command System ─────────────────────────────

    def seek_to(self, seconds: float, paused: bool):
        """Queue a seek+pause command. Commands execute sequentially."""
        # Replace any pending seek_to in queue (only latest matters)
        self._cmd_queue = [
            cmd for cmd in self._cmd_queue if cmd[0] != "seek_to"
        ]
        self._cmd_queue.append(("seek_to", seconds, paused))
        self._process_queue()

    def queue_pause(self, paused: bool):
        """Queue a pause command. Commands execute sequentially."""
        # Replace any pending pause in queue
        self._cmd_queue = [
            cmd for cmd in self._cmd_queue if cmd[0] != "pause"
        ]
        self._cmd_queue.append(("pause", paused))
        self._process_queue()

    def _process_queue(self):
        """Process the next command in queue if not busy."""
        if self._cmd_busy or not self._cmd_queue:
            return

        self._cmd_busy = True
        cmd = self._cmd_queue.pop(0)

        if cmd[0] == "seek_to":
            _, seconds, paused = cmd
            self._exec_seek_to(seconds, paused)
        elif cmd[0] == "pause":
            _, paused = cmd
            self.set_paused(paused)
            self._cmd_done()

    def _exec_seek_to(self, seconds: float, paused: bool):
        """Execute a seek+pause with verification. Retries until VLC confirms position."""
        needs_seek = abs(self._position - seconds) > 0.5
        if needs_seek:
            self._suppress = True
            self._http(params=f"command=seek&val={int(seconds)}")
            self._position = seconds
            self._seek_target = seconds
            self._seek_paused = paused
            self._seek_retries = 0
            QTimer.singleShot(400, self._verify_seek)
        else:
            self.set_paused(paused)
            self._cmd_done()

    def _verify_seek(self):
        """Check if VLC reached the seek target. Retry if not."""
        self._seek_retries += 1
        s = self._http()
        if s:
            pos = float(s.get("time", 0))
            target = getattr(self, '_seek_target', 0)
            if abs(pos - target) < 3.0:
                # Seek confirmed — apply pause state
                self._position = pos
                self._suppress = False
                paused = getattr(self, '_seek_paused', True)
                self.set_paused(paused)
                self._cmd_done()
                return
            elif abs(pos - target) > 20.0 and self._seek_retries >= 2:
                # User likely seeked elsewhere manually — accept their position
                log.info("Seek verify: user overrode seek (at %.1f, target %.1f) — accepting", pos, target)
                self._position = pos
                self._suppress = False
                paused = getattr(self, '_seek_paused', True)
                self.set_paused(paused)
                self._cmd_done()
                return
            elif self._seek_retries < 8:
                # VLC not at target yet — retry the seek command
                log.info("Seek verify: at %.1f, target %.1f — retry %d",
                         pos, target, self._seek_retries)
                self._http(params=f"command=seek&val={int(target)}")
                QTimer.singleShot(400, self._verify_seek)
                return

        # Fallback: max retries reached or HTTP failed
        log.warning("Seek verify: giving up after %d retries", self._seek_retries)
        self._suppress = False
        paused = getattr(self, '_seek_paused', True)
        self.set_paused(paused)
        self._cmd_done()

    def _apply_pending_pause(self):
        """Legacy: no longer used (replaced by _verify_seek)."""
        pass

    def _cmd_done(self):
        """Mark current command as done and process next."""
        self._cmd_busy = False
        self._process_queue()

    def _enable_events(self):
        self._suppress = False

    def load_file(self, file_path: str) -> bool:
        """Load a media file into VLC and pause it at the beginning."""
        file_path = os.path.normpath(file_path)
        if not os.path.isfile(file_path):
            log.error("load_file: file not found: %s", file_path)
            return False

        self._file_path = file_path
        self._file_size = os.path.getsize(file_path)
        old_name = self._file_name
        self._file_name = os.path.basename(file_path)

        # Use file:/// URI for reliable cross-platform loading
        uri = "file:///" + file_path.replace("\\", "/")
        encoded = quote(uri, safe=":/%")
        log.info("load_file: sending in_play input=%s", encoded)
        self._suppress = True
        self._http(params=f"command=in_play&input={encoded}")

        # Pause after VLC has had time to open the file
        QTimer.singleShot(1000, self._pause_after_load)
        QTimer.singleShot(2000, self._enable_events)
        return True

    def _pause_after_load(self):
        """Ensure video is paused at the start after loading."""
        self.set_paused(True)

    # ── OSD (text via Lua file, native VLC rendering) ─────────

    def show_osd(self, message: str, duration: float = 7.0):
        """Add a temporary OSD notification (via Lua text file)."""
        self.osd_push(message, duration)

    def osd_push(self, message: str, duration: float = 7.0):
        """Add a temporary OSD message that auto-expires after *duration* s."""
        self._osd_temp.insert(0, (message, time.time() + duration))
        self._osd_temp = self._osd_temp[:6]
        self._osd_write()

    def osd_set(self, key: str, text: str):
        """Set / update a persistent OSD entry by key (stays until cleared)."""
        self._osd_persistent[key] = text
        self._osd_write()

    def osd_clear(self, key: str):
        """Remove a persistent OSD entry by key."""
        if key in self._osd_persistent:
            del self._osd_persistent[key]
            self._osd_write()

    def osd_clear_all(self):
        """Wipe every OSD message."""
        self._osd_persistent.clear()
        self._osd_temp.clear()
        self._osd_write()

    def _osd_tick(self):
        """Periodic cleanup of expired temporary messages."""
        now = time.time()
        before = len(self._osd_temp)
        self._osd_temp = [(t, exp) for t, exp in self._osd_temp if exp > now]
        if len(self._osd_temp) != before:
            self._osd_write()

    def _osd_write(self):
        """Combine all active OSD messages and write to the temp file."""
        now = time.time()
        self._osd_temp = [(t, exp) for t, exp in self._osd_temp if exp > now]

        lines = []
        for text, _ in self._osd_temp:
            lines.append(text)
        if self._osd_temp and self._osd_persistent:
            lines.append("---")
        for text in self._osd_persistent.values():
            lines.append(text)

        try:
            with open(self._osd_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except Exception:
            pass

    # ── Read-only Properties ──────────────────────────────

    @property
    def file_name(self) -> str:
        return self._file_name

    @property
    def file_path(self) -> str:
        return self._file_path

    @property
    def file_size(self) -> int:
        return self._file_size

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        return self._position

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def vlc_path(self) -> str:
        return self._vlc_path

    # ── GIF on Video (VLC logo sub-filter via RC interface) ──

    def _create_blank_logo(self) -> str:
        """Create a tiny transparent PNG so the logo filter initialises."""
        os.makedirs(self._gif_frame_dir, exist_ok=True)
        blank = os.path.join(self._gif_frame_dir, "_blank.png")
        if not os.path.isfile(blank):
            img = QImage(1, 1, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            img.save(blank, "PNG")
        return blank.replace("\\", "/")

    def show_gif_on_video(self, gif_path: str, duration: float = 10.0,
                          username: str = ""):
        """Display a GIF on VLC's video using the logo sub-filter."""
        if not self._process:
            return

        logo_path = self._prepare_logo(gif_path)
        if not logo_path:
            log.warning("GIF frame extraction failed for %s", gif_path)
            return

        log.info("Sending logo-file to VLC RC: %s", logo_path)
        # Ensure RC is connected before sending logo commands
        if not self._rc_sock:
            self._rc_connect()
        if not self._rc_sock:
            log.warning("Cannot show GIF on video: RC not connected")
            return

        # Show the GIF via VLC's logo sub-filter (single PNG frame)
        self._rc_send(f"logo-file {logo_path}")
        self._rc_send("logo-position 9")
        self._rc_send("logo-opacity 255")

        # Auto-hide after duration
        self._logo_clear_timer.stop()
        self._logo_clear_timer.start(int(duration * 1000))

    def _prepare_logo(self, gif_path: str) -> str:
        """Extract the first frame of a GIF as a PNG for the logo sub-filter.

        Uses QImage for reliable single-frame extraction (works with all
        GIF types including animated ones where QMovie.frameCount() == -1).
        Returns a file path with forward slashes for VLC RC.
        """
        try:
            img = QImage(gif_path)
            if img.isNull():
                return ""
            if img.width() > _LOGO_MAX_DIM or img.height() > _LOGO_MAX_DIM:
                img = img.scaled(
                    _LOGO_MAX_DIM, _LOGO_MAX_DIM,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            os.makedirs(self._gif_frame_dir, exist_ok=True)
            out = os.path.join(self._gif_frame_dir, "logo.png")
            img.save(out, "PNG")
            return out.replace("\\", "/")
        except Exception as exc:
            log.warning("Logo frame extraction failed: %s", exc)
            return ""

    def _clear_logo(self):
        """Hide the logo overlay in VLC."""
        self._rc_send("logo-opacity 0")

    # ── VLC RC (telnet) Interface ─────────────────────────

    def _rc_connect(self):
        """Establish a persistent TCP connection to VLC's RC interface."""
        if self._rc_sock:
            return
        for attempt in range(3):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect(("127.0.0.1", self._rc_port))
                # Drain the initial VLC banner / prompt
                try:
                    sock.recv(4096)
                except socket.timeout:
                    pass
                sock.settimeout(1.0)
                self._rc_sock = sock
                log.info("VLC RC connected on port %d (attempt %d)",
                         self._rc_port, attempt + 1)
                return
            except Exception as exc:
                log.debug("VLC RC connection attempt %d failed: %s",
                          attempt + 1, exc)
                time.sleep(0.5)
        log.warning("VLC RC connection failed after 3 attempts on port %d",
                     self._rc_port)

    def _rc_disconnect(self):
        """Close the RC socket."""
        if self._rc_sock:
            try:
                self._rc_sock.close()
            except Exception:
                pass
            self._rc_sock = None

    def _rc_send(self, command: str):
        """Send a command to VLC's RC interface. Reconnects on failure."""
        if not self._rc_sock:
            self._rc_connect()
        if not self._rc_sock:
            log.warning("RC send failed: no connection — cmd=%s", command[:80])
            return
        try:
            self._rc_sock.sendall(f"{command}\n".encode("utf-8"))
            log.debug("RC sent: %s", command[:120])
            # Drain any response
            try:
                self._rc_sock.recv(4096)
            except socket.timeout:
                pass
        except Exception:
            log.debug("RC send failed, reconnecting")
            self._rc_disconnect()
            self._rc_connect()
            if self._rc_sock:
                try:
                    self._rc_sock.sendall(f"{command}\n".encode("utf-8"))
                    try:
                        self._rc_sock.recv(4096)
                    except socket.timeout:
                        pass
                except Exception:
                    pass
