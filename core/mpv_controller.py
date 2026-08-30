"""
SyncWatch - MPV media player controller via JSON IPC.

Launches MPV with its JSON IPC interface enabled (named pipe on Windows,
Unix socket on Linux/macOS), then controls playback (play, pause, seek,
load file) and monitors state changes through property observation.
OSD messages are delivered through a shared text file read by the
companion Lua script.

All IPC I/O (reads and writes) happens in a single background thread
so that blocking named-pipe operations never stall the Qt event loop.
"""
import json
import logging
import os
import queue
import random
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)


class MPVController(QObject):
    """Controls MPV media player through its JSON IPC interface."""

    # ── Signals (same API as VLCController) ───────────────
    file_changed = Signal(str, int, float)   # name, size, duration
    state_changed = Signal(bool, float)      # paused, position
    vlc_closed = Signal()                    # player closed
    vlc_ready = Signal()                     # player ready / connected

    # Internal: cross-thread signals
    _sig_enable_events = Signal()
    _sig_connect_ready = Signal()
    _sig_setup_done = Signal()          # emitted when observe_property setup finishes

    POLL_MS = 150
    _OSD_REFRESH_MS = 2000   # re-send persistent OSD every 2 s

    def __init__(self, mpv_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._mpv_path = mpv_path or self._find_mpv()
        self._process: Optional[subprocess.Popen] = None
        self._ipc_addr = self._make_ipc_address()

        # Playback state
        self._file_name = ""
        self._file_path = ""
        self._file_size = 0
        self._duration = 0.0
        self._position = 0.0
        self._paused = True
        self._connected = False
        self._suppress = False
        self._initial_file: Optional[str] = None
        self._connect_attempts = 0

        # Track the last position+paused we emitted via state_changed,
        # so we only fire when the player state genuinely deviates from
        # what was last reported (not from what we set internally).
        self._last_emitted_pos = 0.0
        self._last_emitted_paused = True

        # Queued command system (playback commands)
        self._cmd_queue: list = []
        self._cmd_busy = False

        # IPC — all I/O runs in one background thread
        self._sock: Optional[object] = None
        self._io_thread: Optional[threading.Thread] = None
        self._io_running = False

        # Outgoing command queue (thread-safe)
        self._write_queue: queue.Queue = queue.Queue()

        # Pending responses + request-id counter (both threads access)
        self._pending: dict = {}
        self._pending_lock = threading.Lock()
        self._req_id = 0
        self._req_lock = threading.Lock()

        # Observed property values (updated by I/O thread, read by poll timer)
        self._prop_position: float = 0.0
        self._prop_paused: bool = True
        self._prop_duration: float = 0.0
        self._prop_filename: str = ""

        # Persistent OSD (key → text dict, refreshed periodically)
        self._osd_persistent: dict = {}
        self._osd_temp: list = []
        self._osd_content: str = ""
        self._osd_tick_timer = QTimer(self)
        self._osd_tick_timer.setInterval(500)
        self._osd_tick_timer.timeout.connect(self._osd_tick)

        # Polling timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        # Wire cross-thread signals
        self._sig_enable_events.connect(self._deferred_enable_events)
        self._sig_connect_ready.connect(self._on_connect_ready)
        self._sig_setup_done.connect(self._on_setup_done)

    # ── MPV Discovery ─────────────────────────────────────

    @staticmethod
    def _find_mpv() -> str:
        """Auto-detect MPV executable on the current platform."""
        if sys.platform == "win32":
            # Check common install locations
            candidates = []
            # Standard install paths
            for base in [os.environ.get("PROGRAMFILES", ""),
                         os.environ.get("PROGRAMFILES(X86)", ""),
                         os.environ.get("PROGRAMW6432", ""),
                         os.environ.get("LOCALAPPDATA", ""),
                         r"C:\Program Files",
                         r"C:\Program Files (x86)"]:
                if base:
                    candidates.append(os.path.join(base, "mpv", "mpv.exe"))
                    candidates.append(os.path.join(base, "mpv.net", "mpvnet.exe"))
            # Check PATH
            for path_dir in os.environ.get("PATH", "").split(os.pathsep):
                candidates.append(os.path.join(path_dir, "mpv.exe"))

            for p in candidates:
                if os.path.isfile(p):
                    return p
        elif sys.platform == "darwin":
            for p in ("/Applications/mpv.app/Contents/MacOS/mpv",
                      "/opt/homebrew/bin/mpv",
                      "/usr/local/bin/mpv"):
                if os.path.isfile(p):
                    return p
        else:
            for p in ("/usr/bin/mpv", "/usr/local/bin/mpv", "/snap/bin/mpv"):
                if os.path.isfile(p):
                    return p
        return ""

    def _make_ipc_address(self) -> str:
        """Create a unique IPC address.
        
        Windows: ``\\\\.\\pipe\\syncwatch-mpv-XXXXX`` (named pipe)
        Other:   ``/tmp/syncwatch-mpv-XXXXX`` (Unix domain socket)
        """
        uid = random.randint(10000, 99999)
        if sys.platform == "win32":
            return rf"\\.\pipe\syncwatch-mpv-{uid}"
        else:
            return f"/tmp/syncwatch-mpv-{uid}"

    # ── Launch / Close ────────────────────────────────────

    def launch(self, file_path=None) -> bool:
        """Start MPV with the JSON IPC interface enabled."""
        if not self._mpv_path:
            log.error("MPV executable not found")
            return False

        args = [
            self._mpv_path,
            f"--input-ipc-server={self._ipc_addr}",
            "--idle=yes",
            "--no-terminal",
            "--osd-level=1",            # allow OSD messages
            "--osd-duration=5000",      # default OSD duration
            "--pause",                  # start paused
            "--keep-open=yes",          # don't close after playback ends
            "--reset-on-next-file=all", # reset state on new file
        ]

        if file_path:
            file_path = os.path.normpath(file_path)
            self._initial_file = file_path
            self._file_path = file_path
            self._file_size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
            self._file_name = os.path.basename(file_path)
            args.append(file_path)
            log.info("MPV launch with file: %s (exists=%s, size=%d)",
                     file_path, os.path.isfile(file_path), self._file_size)

        try:
            kw = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._process = subprocess.Popen(args, **kw)
            log.info(
                "MPV started (pid=%d, ipc=%s)",
                self._process.pid, self._ipc_addr,
            )
            self._connect_attempts = 0
            QTimer.singleShot(2000, self._try_connect)
            return True
        except Exception as exc:
            log.error("Failed to start MPV: %s", exc)
            return False

    # ── Connection Handshake ──────────────────────────────
    #
    # All blocking I/O (CreateFile, ReadFile, WriteFile) runs in the
    # I/O thread.  ``_try_connect`` spawns a short-lived connect thread;
    # on success ``_sig_connect_ready`` fires on the Qt thread, which
    # starts the permanent I/O thread that does everything else.

    def _try_connect(self):
        self._connect_attempts += 1
        log.info("MPV connection attempt %d ...", self._connect_attempts)
        t = threading.Thread(target=self._connect_worker, daemon=True)
        t.start()

    def _connect_worker(self):
        if self._connect_ipc():
            self._connected = True
            log.info("MPV IPC connected on attempt %d", self._connect_attempts)
            self._sig_connect_ready.emit()
        elif self._connect_attempts < 15:
            QTimer.singleShot(2000, self._try_connect)
        else:
            log.error("MPV IPC did not respond after %d attempts",
                      self._connect_attempts)

    def _on_connect_ready(self):
        """Called on the Qt main thread.  Starts the I/O thread which
        will send setup commands AND begin the event loop."""
        if not self._connected:
            return
        self._osd_tick_timer.start()
        self._io_running = True
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()

    # ── I/O Thread (all blocking pipe operations) ─────────

    def _io_loop(self):
        """Single background thread: send setup commands, then process
        outgoing queue and incoming responses forever."""
        # Phase 1: send setup commands
        self._send_from_thread(["observe_property", 1, "time-pos"])
        self._send_from_thread(["observe_property", 2, "pause"])
        self._send_from_thread(["observe_property", 3, "duration"])
        self._send_from_thread(["observe_property", 4, "filename"])

        # Fetch duration if launched with a file
        if self._initial_file:
            self._send_from_thread(["get_property", "duration"],
                                   callback=self._on_init_duration_cb)
            self._initial_file = None

        # Notify main thread: setup done (triggers vlc_ready + poll timer)
        self._sig_setup_done.emit()

        # Phase 2: event loop — read MPV responses, send queued commands
        buf = ""
        while self._io_running:
            # Drain the outgoing queue (non-blocking)
            self._drain_write_queue()

            # Read from MPV (blocking, but we're on a dedicated thread)
            chunk = self._ipc_read_line()
            if chunk:
                buf += chunk
                while "\n" in buf:
                    idx = buf.index("\n")
                    line = buf[:idx].strip()
                    buf = buf[idx + 1:]
                    if line:
                        self._process_line(line)
            else:
                # No data — brief sleep then check queue again
                time.sleep(0.03)

    def _drain_write_queue(self):
        """Send all pending commands from the queue (non-blocking)."""
        while True:
            try:
                cmd, cb = self._write_queue.get_nowait()
            except queue.Empty:
                break
            self._send_from_thread(cmd, callback=cb)

    def _send_from_thread(self, command: list,
                          callback: Optional[Callable] = None):
        """Send a JSON command from the I/O thread.  Synchronous
        ``WriteFile`` — safe because only this thread uses the pipe."""
        with self._req_lock:
            self._req_id += 1
            rid = self._req_id
        msg = json.dumps({"command": command, "request_id": rid}) + "\n"
        if callback:
            with self._pending_lock:
                self._pending[str(rid)] = callback
        self._ipc_write(msg)

    def _on_init_duration_cb(self, data):
        """Called from I/O thread when duration query returns."""
        if data is not None:
            self._duration = float(data)
        self._suppress = False
        self._last_emitted_pos = -999.0  # force emission on next poll so room sees file

    # ── Queued commands from Qt thread ────────────────────

    def _send_mpv_cmd(self, command: list, callback=None) -> Optional[str]:
        """Enqueue a command from the Qt thread.  Returns immediately.
        Does NOT touch ``_req_id`` — the I/O thread assigns IDs."""
        self._write_queue.put((command, callback))
        return None  # caller doesn't use the return value

    def _process_line(self, line: str):
        """Parse one JSON line from MPV and dispatch."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        # Events (property-change, start-file, end-file)
        event = msg.get("event")
        if event == "property-change":
            pid = msg.get("id")
            data = msg.get("data")
            if pid == 1 and data is not None:
                self._prop_position = float(data)
            elif pid == 2:
                self._prop_paused = bool(data)
            elif pid == 3 and data is not None:
                self._prop_duration = float(data)
            elif pid == 4 and data:
                self._prop_filename = str(data)
            return

        if event == "start-file":
            self._suppress = True
            self._sig_enable_events.emit()
            return

        if event == "end-file":
            return

        # Command responses
        req_id = msg.get("request_id")
        if req_id is not None:
            with self._pending_lock:
                cb = self._pending.pop(str(req_id), None)
            if cb:
                data = msg.get("data")
                err = msg.get("error")
                cb(data if err == "success" else None)

    def _on_setup_done(self):
        """Called on Qt main thread after I/O thread finishes setup."""
        if self._initial_file is not None:
            self._initial_file = None  # already handled
        self._timer.start(self.POLL_MS)
        self.vlc_ready.emit()

    def close(self):
        """Terminate MPV and clean up resources."""
        self._timer.stop()
        self._osd_tick_timer.stop()
        self._connected = False
        self._io_running = False

        # Clean up IPC (close pipe/socket)
        if self._sock:
            try:
                if sys.platform == "win32":
                    import win32file
                    win32file.CloseHandle(self._sock)
                else:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None

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

    # ── JSON IPC Communication ────────────────────────────
    #
    # Windows: ``\\\\.\\pipe\\syncwatch-mpv-XXXXX`` (named pipe)
    # Other:   ``/tmp/syncwatch-mpv-XXXXX`` (Unix domain socket)
    #
    # All blocking pipe I/O runs in the dedicated ``_io_loop``
    # thread.  The Qt thread only ever calls ``_send_mpv_cmd``
    # which enqueues a command into ``_write_queue`` and returns
    # immediately — it never touches the pipe directly.

    def _connect_ipc(self) -> bool:
        """Connect to MPV's IPC (named pipe on Windows, Unix socket elsewhere)."""
        if sys.platform == "win32":
            return self._connect_named_pipe()
        else:
            return self._connect_unix_socket()

    def _connect_named_pipe(self) -> bool:
        """Connect to a Windows named pipe (synchronous handle).
        The handle blocks on read/write — safe because only the
        I/O thread uses it."""
        try:
            import win32file
            import pywintypes

            handle = win32file.CreateFile(
                self._ipc_addr,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,                          # exclusive access
                None,                       # default security
                win32file.OPEN_EXISTING,    # pipe must already exist
                0,                          # synchronous I/O
                None,                       # no template
            )
            self._sock = handle
            return True
        except pywintypes.error as exc:
            log.debug("MPV named pipe not ready (attempt %d): %s",
                      self._connect_attempts, exc)
            return False
        except ImportError:
            log.error("pywin32 not installed — MPV IPC requires pywin32 on Windows")
            return False

    def _connect_unix_socket(self) -> bool:
        """Connect to a Unix domain socket."""
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect(self._ipc_addr)
            # Keep a timeout so the I/O loop can check _io_running
            s.settimeout(0.5)
            self._sock = s
            return True
        except OSError as exc:
            log.debug("MPV Unix socket not ready (attempt %d): %s",
                      self._connect_attempts, exc)
            return False

    # ── Pipe I/O (synchronous, I/O-thread only) ───────────

    def _ipc_write(self, data: str):
        """Write to the pipe.  Synchronous — may block briefly;
        only called from the I/O thread."""
        if not self._sock:
            return
        try:
            payload = data.encode("utf-8")
            if sys.platform == "win32":
                import win32file
                win32file.WriteFile(self._sock, payload)
            else:
                self._sock.send(payload)
        except Exception as exc:
            log.debug("MPV IPC write error: %s", exc)

    def _ipc_read_line(self) -> Optional[str]:
        """Read a chunk from the pipe.  Non-blocking on Windows
        (uses PeekNamedPipe first); timeout-based on Unix.
        Only called from the I/O thread."""
        if not self._sock:
            return None
        try:
            if sys.platform == "win32":
                import win32pipe
                import win32file
                import pywintypes

                # Check if data is available before reading
                try:
                    _, total, _ = win32pipe.PeekNamedPipe(self._sock, 0)
                    if total == 0:
                        return None  # no data — caller will sleep & re-check
                except pywintypes.error:
                    return None

                # Data available — read it (won't block)
                hr, data = win32file.ReadFile(self._sock, min(total, 65536))
                if data:
                    return data.decode("utf-8", errors="replace")
            else:
                data = self._sock.recv(65536)
                if data:
                    return data.decode("utf-8", errors="replace")
        except pywintypes.error as exc:
            if exc.winerror == 109:  # ERROR_BROKEN_PIPE
                return None
            log.debug("MPV IPC read error: %s", exc)
            return None
        except (BlockingIOError, socket.timeout):
            return None
        except OSError:
            return None
        return None

    # ── Periodic Status Polling ───────────────────────────

    def _poll(self):
        # Check whether MPV is still alive
        if self._process and self._process.poll() is not None:
            self._connected = False
            self._timer.stop()
            self.vlc_closed.emit()
            return

        if not self._connected:
            return

        # Sync our internal position with the latest from MPV
        self._position = self._prop_position
        self._paused = self._prop_paused

        # ── File change detection ──
        if self._prop_filename and self._prop_filename != self._file_name:
            old_name = self._file_name
            self._file_name = self._prop_filename
            log.info("MPV file changed: '%s' -> '%s'", old_name, self._file_name)
            self.file_changed.emit(
                self._file_name, self._file_size, self._duration,
            )
            # Reset emitted trackers on file change so new file state is reported
            self._last_emitted_pos = -999.0
            self._last_emitted_paused = not self._paused

        # ── Playback state ──
        if not self._suppress:
            pos = self._prop_position
            paused = self._prop_paused
            # Emit only when the real player state differs enough from
            # what we last told the world about.
            pos_changed = abs(pos - self._last_emitted_pos) >= 1.0
            pause_changed = paused != self._last_emitted_paused
            if pos_changed or pause_changed:
                self._last_emitted_pos = pos
                self._last_emitted_paused = paused
                self.state_changed.emit(paused, pos)

    # ── Playback Controls ─────────────────────────────────

    def set_paused(self, paused: bool):
        """Set the pause state.  Also record the fact that *we* changed it
        so the next poll doesn't re-emit the same state."""
        self._send_mpv_cmd(["set_property", "pause", paused])
        self._paused = paused
        self._last_emitted_paused = paused

    def set_position(self, seconds: float):
        """Seek to absolute position in seconds."""
        if abs(self._position - seconds) < 0.3:
            return
        self._suppress = True
        self._send_mpv_cmd(["seek", seconds, "absolute"])
        self._position = seconds
        self._last_emitted_pos = seconds  # we initiated this seek
        QTimer.singleShot(400, self._enable_events)

    # ── Queued Command System ─────────────────────────────

    def seek_to(self, seconds: float, paused: bool):
        """Queue a seek+pause command."""
        self._cmd_queue = [
            cmd for cmd in self._cmd_queue if cmd[0] != "seek_to"
        ]
        self._cmd_queue.append(("seek_to", seconds, paused))
        self._process_queue()

    def queue_pause(self, paused: bool):
        """Queue a pause command."""
        self._cmd_queue = [
            cmd for cmd in self._cmd_queue if cmd[0] != "pause"
        ]
        self._cmd_queue.append(("pause", paused))
        self._process_queue()

    def _process_queue(self):
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
        """Execute seek+pause with verification."""
        needs_seek = abs(self._position - seconds) > 0.5
        if needs_seek:
            self._suppress = True
            self._send_mpv_cmd(["seek", seconds, "absolute"])
            self._position = seconds
            self._last_emitted_pos = seconds
            self._last_emitted_paused = paused
            self._seek_target = seconds
            self._seek_paused = paused
            self._seek_retries = 0
            QTimer.singleShot(400, self._verify_seek)
        else:
            self._last_emitted_pos = self._position
            self._last_emitted_paused = paused
            self.set_paused(paused)
            self._cmd_done()

    def _verify_seek(self):
        """Check if MPV reached the seek target."""
        self._seek_retries += 1
        target = getattr(self, '_seek_target', 0)
        pos = self._prop_position
        paused = getattr(self, '_seek_paused', True)

        if abs(pos - target) < 3.0:
            self._position = pos
            self._last_emitted_pos = pos
            self._suppress = False
            self.set_paused(paused)
            self._cmd_done()
            return
        elif abs(pos - target) > 20.0 and self._seek_retries >= 2:
            log.info("Seek verify: user overrode seek (at %.1f, target %.1f)", pos, target)
            self._position = pos
            self._last_emitted_pos = pos
            self._suppress = False
            self.set_paused(paused)
            self._cmd_done()
            return
        elif self._seek_retries < 8:
            log.info("Seek verify: at %.1f, target %.1f — retry %d",
                     pos, target, self._seek_retries)
            self._send_mpv_cmd(["seek", target, "absolute"])
            QTimer.singleShot(400, self._verify_seek)
            return

        log.warning("Seek verify: giving up after %d retries", self._seek_retries)
        self._suppress = False
        self.set_paused(paused)
        self._cmd_done()

    def _cmd_done(self):
        self._cmd_busy = False
        self._process_queue()

    def _enable_events(self):
        self._suppress = False

    def _deferred_enable_events(self):
        """Called on the Qt main thread — defers _enable_events to let MPV settle."""
        QTimer.singleShot(600, self._enable_events)

    def load_file(self, file_path: str) -> bool:
        """Load a media file into MPV and pause it."""
        file_path = os.path.normpath(file_path)
        if not os.path.isfile(file_path):
            log.error("load_file: file not found: %s", file_path)
            return False

        self._file_path = file_path
        self._file_size = os.path.getsize(file_path)
        self._file_name = os.path.basename(file_path)

        self._suppress = True
        self._send_mpv_cmd(["loadfile", file_path, "replace"])
        self._paused = True

        # Pause after MPV has had time to open the file
        QTimer.singleShot(800, self._pause_after_load)
        QTimer.singleShot(2000, self._enable_events)
        return True

    def _pause_after_load(self):
        """Ensure video is paused at the start after loading."""
        self.set_paused(True)

    # ── OSD (same file-based system as VLC) ──────────────
    #
    # Works exactly like VLC: persistent entries (via ``osd_set``) and
    # temporary entries (via ``osd_push``) are written to a text file.
    # A timer re-reads the file every 500 ms and sends its contents to
    # MPV via ``show-text``.  This gives the **exact same** multi-line
    # OSD behaviour as VLC — temp messages on top, ``---`` separator,
    # persistent messages below.

    def show_osd(self, message: str, duration: float = 7.0):
        """Add a temporary OSD notification (same as VLC)."""
        self.osd_push(message, duration)

    def osd_push(self, message: str, duration: float = 7.0):
        """Add a temporary OSD message that auto-expires."""
        self._osd_temp.insert(0, (message, time.time() + duration))
        self._osd_temp = self._osd_temp[:6]
        self._osd_write()

    def osd_set(self, key: str, text: str):
        """Set / update a persistent OSD entry by key."""
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
        """Periodic cleanup of expired temporary messages + push to MPV."""
        now = time.time()
        before = len(self._osd_temp)
        self._osd_temp = [(t, exp) for t, exp in self._osd_temp if exp > now]
        if len(self._osd_temp) != before:
            self._osd_write()
        # Re-send the combined OSD content on every tick so persistent
        # entries stay on screen (MPV auto-fades after duration ms).
        self._osd_send_to_mpv()

    def _osd_write(self):
        """Combine all active OSD messages (same format as VLC) and write to file."""
        now = time.time()
        self._osd_temp = [(t, exp) for t, exp in self._osd_temp if exp > now]

        lines = []
        for text, _ in self._osd_temp:
            lines.append(text)
        if self._osd_temp and self._osd_persistent:
            lines.append("---")
        for text in self._osd_persistent.values():
            lines.append(text)

        self._osd_content = "\n".join(lines) if lines else ""

    def _osd_send_to_mpv(self):
        """Send the current combined OSD content to MPV via ``show-text``.
        Duration must span until the next tick so it never flickers off."""
        if not self._connected:
            return
        content = getattr(self, '_osd_content', None)
        if content:
            # 1200 ms — slightly more than the tick interval (500 ms)
            self._send_mpv_cmd(["show-text", content, 1200])
        else:
            self._send_mpv_cmd(["show-text", "", 1])

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
        return self._mpv_path

    # ── GIF on Video ──────────────────────────────────────

    def show_gif_on_video(self, gif_path: str, duration: float = 10.0,
                          username: str = ""):
        """Display a GIF on MPV's video.
        
        MPV does not support GIF overlay in the same way VLC does.
        This is a no-op for now — the GIF feature is VLC-specific.
        """
        log.debug("GIF on video not yet supported for MPV")
