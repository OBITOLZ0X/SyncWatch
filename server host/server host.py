"""
SyncWatch Server - Multi-room public sync server.

Usage:
    python server.py [--port PORT] [--github-token TOKEN]

When --github-token is provided, the server registers itself in the
syncwatch_servers.json file on GitHub so clients can discover it.
"""
import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Optional

import ssl

# ── Disable SSL verification for servers that lack CA certs (e.g. Windows RDP) ──
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import websockets

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SyncWatchServer")

# ── Load .env file (manually, no dependency needed) ──
def _load_dotenv_file(env_path: str) -> bool:
    """Manually parse a .env file and set os.environ if NOT already set.
    
    ⚠ Never overrides existing environment variables (e.g. from a hosting
    platform like Railway). The .env file only provides fallback defaults.
    """
    if not os.path.isfile(env_path):
        return False
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Remove surrounding quotes if present
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key and key not in os.environ:  # ← Don't override existing env vars
                    os.environ[key] = val
        return True
    except Exception:
        return False


def _load_env_file():
    """Load .env from multiple locations to support both script and PyInstaller EXE.
    
    First tries to use python-dotenv if available, then falls back to manual parsing.
    """
    # Possible locations for .env (in priority order)
    candidates = []

    # 1. PyInstaller EXE directory (r"C:\...\SyncWatchLz")
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, ".env"))
        # Also check _internal alongside server EXE
        internal_dir = os.path.join(exe_dir, "_internal")
        candidates.append(os.path.join(internal_dir, ".env"))

    # 2. Current working directory
    candidates.append(os.path.join(os.getcwd(), ".env"))

    # 3. Script directory (for development)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, ".env"))
    except Exception:
        pass

    # Try each location — deduplicate while preserving order
    seen = set()
    for env_path in candidates:
        normalized = os.path.normcase(os.path.normpath(env_path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(env_path):
            # Try dotenv first, fallback to manual
            try:
                from dotenv import load_dotenv
                if load_dotenv(env_path):
                    log.info("Loaded .env from: %s", env_path)
                    return True
            except ImportError:
                pass
            # Manual parse
            if _load_dotenv_file(env_path):
                log.info("Loaded .env (manual) from: %s", env_path)
                return True

    return False


env_loaded = _load_env_file()
if not env_loaded:
    # Final fallback: try CWD with dotenv
    try:
        from dotenv import load_dotenv
        if load_dotenv():
            log.info("Loaded .env from current directory")
    except ImportError:
        pass
    # Final manual fallback
    if _load_dotenv_file(os.path.join(os.getcwd(), ".env")):
        log.info("Loaded .env (manual) from current directory")


# ── Protocol constants (mirror core/protocol.py) ─────────
class MsgType:
    JOIN = "join"
    STATE_UPDATE = "state_update"
    CHAT = "chat"
    FILE_INFO = "file_info"
    READY = "ready"
    KICK = "kick"
    SET_PERMISSION = "set_permission"
    MAKE_READY = "make_ready"
    MAKE_NOT_READY = "make_not_ready"
    MUTE_CHAT = "mute_chat"
    MUTE_USER = "mute_user"
    WELCOME = "welcome"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    SYNC = "sync"
    CHAT_BROADCAST = "chat_broadcast"
    USER_UPDATE = "user_update"
    KICKED = "kicked"
    PERMISSION_UPDATE = "permission_update"
    CHAT_MUTED = "chat_muted"
    ERROR = "error"
    ALL_READY = "all_ready"
    CLEANUP_REQUEST = "cleanup_request"
    CLEANUP_RESPONSE = "cleanup_response"

    # Room count query
    ROOM_COUNT_REQUEST = "room_count_request"
    ROOM_COUNT_RESPONSE = "room_count_response"


def encode(msg_type: str, **kwargs) -> str:
    return json.dumps({"type": msg_type, **kwargs})


def decode(data: str) -> dict:
    return json.loads(data)


# ── Room state (per-session) ────────────────────────────
@dataclass
class UserInfo:
    username: str
    is_host: bool = False
    is_ready: bool = False
    file_name: str = ""
    file_size: int = 0
    file_duration: float = 0.0
    join_time: float = 0.0  # timestamp when user joined
    permissions: Dict[str, bool] = field(default_factory=lambda: {
        "chat": True, "kick": False, "make_ready": False, "mute_user": False,
    })

    def to_dict(self) -> dict:
        return {
            "username": self.username, "is_host": self.is_host,
            "is_ready": self.is_ready, "file_name": self.file_name,
            "file_size": self.file_size, "file_duration": self.file_duration,
            "permissions": dict(self.permissions),
        }


class Room:
    """A single synchronized room within the multi-room server."""

    def __init__(self, room_name: str, password: str = "",
                 max_users: int = 10, host_username: str = "Host",
                 share_info: bool = True, features_enabled: bool = False,
                 room_token: str = "", server: 'SyncWatchServer' = None):
        self.room_name = room_name
        self.password = password
        self.max_users = max_users
        self.host_username = host_username
        self.share_info = share_info
        self.features_enabled = features_enabled
        self.room_token = room_token

        self.position: float = 0.0
        self.paused: bool = True
        self.last_update_time: float = time.time()
        self.set_by: str = host_username

        self.users: Dict[str, UserInfo] = {}
        self.connections: Dict[str, websockets.WebSocketServerProtocol] = {}

        self.host_file_name: str = ""
        self.host_file_size: int = 0
        self.chat_muted: bool = False

        self._parent_server = server  # Reference to SyncWatchServer for cleanup
        self._state_lock = asyncio.Lock()
        self._last_drift_correction: Dict[str, float] = {}

    def get_current_position(self) -> float:
        if not self.paused:
            return self.position + (time.time() - self.last_update_time)
        return self.position

    async def handle_connection(self, websocket, username: str, password: str, is_host: bool):
        """Handle a new user joining this room."""
        registered = False
        try:
            # Validate
            if not username:
                await websocket.send(encode(MsgType.ERROR, message="Username is required"))
                return

            if self.password and password != self.password:
                await websocket.send(encode(MsgType.ERROR, message="Invalid room password"))
                return

            if len(self.users) >= self.max_users:
                await websocket.send(encode(MsgType.ERROR, message="Room is full"))
                return

            if username in self.users:
                await websocket.send(encode(MsgType.ERROR, message="Username already taken"))
                return

            user = UserInfo(username=username, is_host=is_host, join_time=time.time())
            if not is_host:
                user.permissions["kick"] = self.features_enabled
                user.permissions["make_ready"] = self.features_enabled
                user.permissions["mute_user"] = self.features_enabled
            else:
                user.permissions["kick"] = True
                user.permissions["make_ready"] = True
                user.permissions["mute_user"] = True
            self.users[username] = user
            self.connections[username] = websocket
            registered = True

            log.info("[%s] User '%s' joined — total: %d",
                     self.room_name, username, len(self.users))

            # Send welcome
            user_list = {n: u.to_dict() for n, u in self.users.items()}
            await websocket.send(encode(
                MsgType.WELCOME,
                room=self.room_name,
                host=self.host_username,
                users=user_list,
                position=self.get_current_position(),
                paused=self.paused,
                host_file_name=self.host_file_name,
                host_file_size=self.host_file_size,
                share_info=self.share_info,
                features_enabled=self.features_enabled,
                chat_muted=self.chat_muted,
            ))

            # Notify others
            await self.broadcast(
                encode(MsgType.USER_JOINED, username=username, user=user.to_dict()),
                exclude=username,
            )

            log.info("[%s] User '%s' joined successfully", self.room_name, username)

            # If others exist, pause for new user
            if len(self.users) > 1:
                user.is_ready = False
                self.paused = True
                self.position = self.get_current_position()
                self.last_update_time = time.time()
                self.set_by = "System"

                await self.broadcast(encode(
                    MsgType.USER_UPDATE, username=username, user=user.to_dict(),
                    host_file_name=self.host_file_name, host_file_size=self.host_file_size,
                ))
                await self.broadcast(encode(
                    MsgType.SYNC, position=self.position, paused=True, set_by="System",
                ))
                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST, username="System",
                    message=f"{username} joined — waiting for them to get ready.",
                ))

            # Message loop
            async for raw in websocket:
                try:
                    msg = decode(raw)
                    await self.handle_message(username, msg)
                except json.JSONDecodeError:
                    log.warning("[%s] Invalid JSON from '%s'", self.room_name, username)
                except Exception as e:
                    log.error("[%s] Error handling message from '%s': %s",
                              self.room_name, username, e)
        except websockets.ConnectionClosed:
            log.info("[%s] Connection closed: %s", self.room_name, username)
        finally:
            if registered and username in self.users:
                was_host = (username == self.host_username)
                del self.users[username]
                self.connections.pop(username, None)

                self.paused = True
                self.position = self.get_current_position()
                self.last_update_time = time.time()

                # ── Host transfer: if the host left, give host to the longest-connected user ──
                if was_host and self.users:
                    # Find user with earliest join_time (longest connected)
                    new_host = min(self.users.items(), key=lambda item: item[1].join_time)
                    new_username = new_host[0]
                    new_user = new_host[1]
                    # Set new host
                    new_user.is_host = True
                    new_user.permissions["kick"] = True
                    new_user.permissions["make_ready"] = True
                    new_user.permissions["mute_user"] = True
                    self.host_username = new_username
                    self.set_by = new_username
                    log.info("[%s] Host transferred to '%s' (was '%s')",
                             self.room_name, new_username, username)

                    # Notify everyone about new host, include room_token for the new host
                    await self.broadcast(encode(
                        MsgType.USER_UPDATE, username=new_username, user=new_user.to_dict(),
                        room_token=self.room_token,
                    ))
                    await self.broadcast(encode(
                        MsgType.CHAT_BROADCAST, username="System",
                        message=f"Host left — {new_username} is now the new host.",
                    ))

                await self.broadcast(encode(MsgType.USER_LEFT, username=username))
                await self.broadcast(encode(
                    MsgType.SYNC, position=self.position, paused=True, set_by="System",
                ))
                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST, username="System",
                    message=f"{username} left the room",
                ))
                log.info("[%s] User '%s' left", self.room_name, username)

                # Fix 3: Clean up empty rooms (room is deleted from server's _rooms dict
                # by the calling code in global_handler)

    async def handle_message(self, username: str, msg: dict):
        msg_type = msg.get("type")
        user = self.users.get(username)
        if not user:
            return

        if msg_type == MsgType.STATE_UPDATE:
            await self._handle_state_update(username, user, msg)
        elif msg_type == MsgType.CHAT:
            await self._handle_chat(username, user, msg)
        elif msg_type == MsgType.FILE_INFO:
            await self._handle_file_info(username, user, msg)
        elif msg_type == MsgType.READY:
            await self._handle_ready(username, user, msg)
        elif msg_type == MsgType.KICK:
            await self._handle_kick(username, msg)
        elif msg_type == MsgType.SET_PERMISSION:
            await self._handle_set_permission(username, msg)
        elif msg_type == MsgType.MAKE_READY:
            await self._handle_make_ready(username, msg)
        elif msg_type == MsgType.MAKE_NOT_READY:
            await self._handle_make_not_ready(username, msg)
        elif msg_type == MsgType.MUTE_CHAT:
            await self._handle_mute_chat(username, msg)
        elif msg_type == MsgType.MUTE_USER:
            await self._handle_mute_user(username, msg)
        elif msg_type == MsgType.CLEANUP_REQUEST:
            await self._handle_cleanup_request(username, msg)

    # ── Message handlers (same logic as original SyncServer) ──

    async def _handle_state_update(self, username: str, user: UserInfo, msg: dict):
        async with self._state_lock:
            await self._do_state_update(username, user, msg)

    async def _do_state_update(self, username: str, user: UserInfo, msg: dict):
        is_host = (username == self.host_username)
        is_pause = msg.get("paused", self.paused)
        new_position = msg.get("position", self.position)
        is_heartbeat = msg.get("heartbeat", False)

        if is_heartbeat:
            if username == self.host_username:
                self.position = new_position
                self.paused = is_pause
                self.last_update_time = time.time()
            else:
                if not is_pause and not self.paused:
                    expected = self.get_current_position()
                    drift = abs(new_position - expected)
                    now = time.time()
                    last_corr = self._last_drift_correction.get(username, 0)
                    if drift > 2.0 and (now - last_corr) > 5.0:
                        self._last_drift_correction[username] = now
                        ws = self.connections.get(username)
                        if ws:
                            try:
                                await ws.send(encode(
                                    MsgType.SYNC, position=expected,
                                    paused=False, set_by="System",
                                ))
                            except Exception:
                                pass
            return

        old_paused = self.paused
        old_position = self.get_current_position()
        paused_changed = (is_pause != old_paused)
        seeked = abs(new_position - old_position) > 2.0

        if is_pause and paused_changed:
            user.is_ready = False
            await self.broadcast(encode(
                MsgType.USER_UPDATE, username=username, user=user.to_dict(),
            ))

        if not is_pause and paused_changed:
            not_ready_users = [n for n, u in self.users.items() if not u.is_ready]
            if len(not_ready_users) == 0:
                pass
            elif len(not_ready_users) == 1 and not_ready_users[0] == username:
                user.is_ready = True
                await self.broadcast(encode(
                    MsgType.USER_UPDATE, username=username, user=user.to_dict(),
                ))
                if all(u.is_ready for u in self.users.values()):
                    await self.broadcast(encode(MsgType.ALL_READY))
            else:
                await self.broadcast(encode(
                    MsgType.SYNC, position=self.get_current_position(),
                    paused=True, set_by="System",
                ))
                return

        if not is_pause and not all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(
                MsgType.SYNC, position=self.get_current_position(),
                paused=True, set_by="System",
            ))
            return

        if not paused_changed and not seeked:
            self.position = new_position
            self.last_update_time = time.time()
            return

        self.position = new_position
        self.paused = is_pause
        self.last_update_time = time.time()
        self.set_by = username

        await self.broadcast(encode(
            MsgType.SYNC, position=self.position, paused=self.paused, set_by=username,
        ), exclude=username)

        if seeked:
            t = self._fmt_time(self.position)
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} seeked to {t}",
            ))
        if paused_changed:
            action = "paused" if is_pause else "resumed playback"
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} {action}",
            ))

    async def _handle_chat(self, username: str, user: UserInfo, msg: dict):
        is_host = (username == self.host_username)
        if not is_host and not user.permissions.get("chat", True):
            return
        if not is_host and self.chat_muted:
            return
        message = str(msg.get("message", ""))[:500]
        if message.strip():
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username=username, message=message,
            ))

    async def _handle_file_info(self, username: str, user: UserInfo, msg: dict):
        old_file = user.file_name
        user.file_name = str(msg.get("file_name", ""))
        user.file_size = int(msg.get("file_size", 0))
        user.file_duration = float(msg.get("file_duration", 0.0))
        user.is_ready = False

        if username == self.host_username:
            self.host_file_name = user.file_name
            self.host_file_size = user.file_size

        await self.broadcast(encode(
            MsgType.USER_UPDATE, username=username, user=user.to_dict(),
            host_file_name=self.host_file_name, host_file_size=self.host_file_size,
        ))

        self.paused = True
        self.position = self.get_current_position()
        self.last_update_time = time.time()
        self.set_by = "System"
        await self.broadcast(encode(
            MsgType.SYNC, position=self.position, paused=True, set_by="System",
        ))

        if not user.file_name:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} closed VLC.",
            ))
        elif old_file:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} changed their file to: {user.file_name}",
            ))
        else:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} loaded: {user.file_name}",
            ))

    async def _handle_ready(self, username: str, user: UserInfo, msg: dict):
        was_ready = user.is_ready
        user.is_ready = bool(msg.get("is_ready", False))
        await self.broadcast(encode(
            MsgType.USER_UPDATE, username=username, user=user.to_dict(),
        ))
        if was_ready and not user.is_ready:
            self.paused = True
            self.position = self.get_current_position()
            self.last_update_time = time.time()
            self.set_by = "System"
            await self.broadcast(encode(
                MsgType.SYNC, position=self.position, paused=True, set_by="System",
            ))
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST, username="System",
                message=f"{username} is no longer ready — paused.",
            ))
        if self.users and all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(MsgType.ALL_READY))

    async def _handle_kick(self, username: str, msg: dict):
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("kick", False)):
            return
        target = msg.get("target", "")
        if target in self.connections and target != self.host_username:
            reason = msg.get("reason", f"Kicked by {username}")
            try:
                await self.connections[target].send(encode(MsgType.KICKED, reason=reason))
                await self.connections[target].close()
            except Exception:
                pass

    async def _handle_set_permission(self, username: str, msg: dict):
        if username != self.host_username:
            return
        target = msg.get("target", "")
        permission = msg.get("permission", "")
        value = bool(msg.get("value", True))
        if target in self.users and permission in ("chat", "kick", "make_ready", "mute_user"):
            self.users[target].permissions[permission] = value
            await self.broadcast(encode(
                MsgType.PERMISSION_UPDATE, username=target, permission=permission,
                value=value, permissions=self.users[target].permissions,
            ))

    async def _handle_make_ready(self, username: str, msg: dict):
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("make_ready", False)):
            return
        target = msg.get("target", "")
        target_user = self.users.get(target)
        if not target_user or target == self.host_username:
            return
        if not target_user.file_name:
            return
        target_user.is_ready = True
        await self.broadcast(encode(
            MsgType.USER_UPDATE, username=target, user=target_user.to_dict(),
        ))
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST, username="System",
            message=f"{username} marked {target} as ready.",
        ))
        if self.users and all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(MsgType.ALL_READY))

    async def _handle_make_not_ready(self, username: str, msg: dict):
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("make_ready", False)):
            return
        target = msg.get("target", "")
        target_user = self.users.get(target)
        if not target_user or target == self.host_username:
            return
        target_user.is_ready = False
        await self.broadcast(encode(
            MsgType.USER_UPDATE, username=target, user=target_user.to_dict(),
        ))
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST, username="System",
            message=f"{username} marked {target} as not ready.",
        ))
        self.paused = True
        self.position = self.get_current_position()
        self.last_update_time = time.time()
        await self.broadcast(encode(
            MsgType.SYNC, position=self.position, paused=True, set_by="System",
        ))

    async def _handle_mute_chat(self, username: str, msg: dict):
        if username != self.host_username:
            return
        self.chat_muted = bool(msg.get("muted", True))
        await self.broadcast(encode(MsgType.CHAT_MUTED, muted=self.chat_muted))
        state = "muted" if self.chat_muted else "unmuted"
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST, username="System",
            message=f"Host {state} the chat.",
        ))

    async def _handle_mute_user(self, username: str, msg: dict):
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("mute_user", False)):
            return
        target = msg.get("target", "")
        target_user = self.users.get(target)
        if not target_user or target == self.host_username:
            return
        muted = bool(msg.get("muted", True))
        target_user.permissions["chat"] = not muted
        await self.broadcast(encode(
            MsgType.PERMISSION_UPDATE, username=target, permission="chat",
            value=not muted, permissions=target_user.permissions,
        ))
        state = "muted" if muted else "unmuted"
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST, username="System",
            message=f"{username} {state} {target}.",
        ))

    async def broadcast(self, message: str, exclude: str = None):
        targets = [(n, ws) for n, ws in list(self.connections.items()) if n != exclude]
        if not targets:
            return

        async def _send(name, ws):
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                log.warning("[%s] Broadcast: '%s' connection closed", self.room_name, name)
                return name
            except Exception as e:
                log.warning("[%s] Broadcast send to '%s' failed: %s", self.room_name, name, e)
            return None

        results = await asyncio.gather(*[_send(n, w) for n, w in targets])
        for name in results:
            if name:
                self.users.pop(name, None)
                self.connections.pop(name, None)

    async def _handle_cleanup_request(self, username: str, msg: dict):
        """Handle a CLEANUP_REQUEST from a connected client.
        
        Only the host can trigger this. The Room delegates to the parent
        SyncWatchServer which verifies dead servers via TCP ping and removes
        them from GitHub.
        """
        if username != self.host_username:
            return

        if not self._parent_server:
            ws = self.connections.get(username)
            if ws:
                try:
                    await ws.send(encode(
                        MsgType.CLEANUP_RESPONSE,
                        removed=0, online=0, error="Server has no GitHub token",
                    ))
                except Exception:
                    pass
            return

        log.info("[%s] Host '%s' requested server cleanup", self.room_name, username)
        ws = self.connections.get(username)

        # Run cleanup in executor to avoid blocking the event loop
        def _do_cleanup():
            try:
                result = self._parent_server.cleanup_dead_servers()
                return result
            except Exception as e:
                return {"removed": 0, "online": 0, "error": str(e)}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_cleanup)

        if ws:
            try:
                await ws.send(encode(MsgType.CLEANUP_RESPONSE, **result))
            except Exception:
                pass

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = int(seconds)
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"


# ── Multi-room server ────────────────────────────────────
class SyncWatchServer:
    """Multi-room WebSocket server that manages many rooms."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765,
                 github_token: str = "", ngrok_token: str = ""):
        self.host = host
        self.port = port
        self.github_token = github_token
        self.ngrok_token = ngrok_token
        self._rooms: Dict[str, Room] = {}
        self._server = None
        self._public_url: str = ""
        self._country: str = "Unknown"
        self._ngrok_manager = None

    def get_public_ip(self) -> str:
        """Get the server's public IP address."""
        try:
            req = urllib.request.Request(
                "https://api.ipify.org?format=json",
                headers={"User-Agent": "SyncWatchServer/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("ip", "0.0.0.0")
        except Exception as e:
            log.warning("Failed to get public IP: %s", e)
        return "0.0.0.0"

    def encrypt_servers_data(self, raw_json: str) -> str:
        """Encrypt server list JSON using AES-256-GCM.
        
        Inlined here so server.py works standalone without core/token_utils.py.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import hashlib, base64, os
            key = hashlib.sha256(b"SyncWatch-Server-Data-2026").digest()
            nonce = os.urandom(12)
            ciphertext = AESGCM(key).encrypt(nonce, raw_json.encode("utf-8"), None)
            raw = nonce + ciphertext
            return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        except Exception as e:
            log.warning("Encryption failed (%s), using plaintext", e)
            return raw_json

    def decrypt_servers_data(self, encrypted: str) -> str:
        """Decrypt server list JSON using AES-256-GCM.
        
        Inlined here so server.py works standalone without core/token_utils.py.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import hashlib, base64
            key = hashlib.sha256(b"SyncWatch-Server-Data-2026").digest()
            pad = 4 - len(encrypted) % 4
            if pad != 4:
                encrypted += "=" * pad
            raw = base64.urlsafe_b64decode(encrypted)
            nonce = raw[:12]
            ciphertext = raw[12:]
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception:
            # Fallback: try as plain JSON (legacy / unencrypted)
            return encrypted

    def get_country(self) -> str:
        """Get the server's country from IP geolocation."""
        # Try ip-api.com over HTTP (free tier)
        try:
            req = urllib.request.Request(
                "http://ip-api.com/json/?fields=country",
                headers={"User-Agent": "SyncWatchServer/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                country = data.get("country", "")
                if country:
                    return country
        except Exception:
            pass

        log.warning("Failed to get country from geolocation API")
        return "Unknown"

    def register_on_github(self, retries: int = 3):
        """Register this server in the syncwatch_servers.json on GitHub.
        
        Read-modify-write pattern with SHA conflict retry:
        - Fetches all existing servers from GitHub
        - Adds/updates THIS server's entry (by URL)
        - Writes back the complete list
        - Retries on SHA conflict (409) up to `retries` times
        
        This ensures multiple servers can register concurrently without
        overwriting each other's data.
        """
        if not self.github_token:
            log.info("No GitHub token provided — skipping server registration")
            return

        # Use ngrok URL if tunnel was started, otherwise fall back to public IP
        if not self._public_url:
            self._public_url = f"ws://{self.get_public_ip()}:{self.port}"
        self._country = self.get_country()

        # Resolve public IP once (cache it to avoid repeated HTTP calls)
        public_ip = self.get_public_ip()

        server_entry = {
            "url": self._public_url,
            "country": self._country,
            "port": self.port,
            "host": public_ip,
            "status": "online",
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        log.info("Registering server: %s [%s]", self._public_url, self._country)

        repo_url = "https://api.github.com/repos/OBITOLZ0X/SyncWatch/contents/syncwatch_servers.json"
        headers = {
            "Authorization": f"token {self.github_token}",
            "User-Agent": "SyncWatchServer/1.0",
            "Accept": "application/vnd.github.v3+json",
        }

        for attempt in range(retries):
            servers = []
            sha = ""

            try:
                # Get current file content + SHA
                req = urllib.request.Request(repo_url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                    sha = data.get("sha", "")
                    content_b64 = data.get("content", "")
                    import base64
                    try:
                        if content_b64:
                            raw_decoded = base64.b64decode(content_b64).decode("utf-8")
                            if raw_decoded.strip():
                                # Data on GitHub is encrypted — decrypt first
                                try:
                                    decrypted = self.decrypt_servers_data(raw_decoded)
                                    servers = json.loads(decrypted)
                                except Exception:
                                    # Fallback: try as plain JSON (legacy entries)
                                    servers = json.loads(raw_decoded)
                    except (json.JSONDecodeError, Exception) as e:
                        log.warning("Could not parse existing servers JSON (%s), starting fresh", e)
                        servers = []
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 404:
                    # File doesn't exist yet — will be created
                    log.info("syncwatch_servers.json does not exist yet — will create it")
                elif e.code == 401:
                    log.error("GitHub authentication failed (HTTP 401). "
                              "Your GITHUB_TOKEN may be expired or lacks 'repo' scope. "
                              "Server will run without registration.")
                    return  # Unrecoverable — don't retry, don't fall through to warning
                else:
                    log.warning("Failed to fetch servers file (HTTP %d): %s", e.code, body)
                    continue  # Retry
            except Exception as e:
                log.warning("Failed to fetch servers file: %s", e)
                continue  # Retry

            # Remove old entry if this server already exists (by URL), then add new one
            servers = [s for s in servers if s.get("url") != self._public_url]
            servers.append(server_entry)
            servers = servers[-50:]

            # Encrypt and encode
            new_content_json = json.dumps(servers, indent=2, ensure_ascii=False)
            encrypted = self.encrypt_servers_data(new_content_json)
            import base64
            new_content_b64 = base64.b64encode(encrypted.encode("utf-8")).decode()

            payload_dict = {
                "message": f"Register server: {self._public_url}",
                "content": new_content_b64,
            }
            if sha:
                payload_dict["sha"] = sha

            payload = json.dumps(payload_dict).encode()

            req = urllib.request.Request(
                repo_url,
                data=payload,
                headers={**headers, "Content-Type": "application/json"},
                method="PUT",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode())
                    log.info("Server registered on GitHub successfully: %s",
                             result.get("content", {}).get("sha", "")[:8])
                    return  # Success — exit
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                if e.code == 409:
                    # SHA conflict — another server wrote between our read and write
                    log.info("SHA conflict (attempt %d/%d) — retrying read-modify-write...",
                             attempt + 1, retries)
                    continue  # Retry the whole cycle
                log.error("Failed to register server (HTTP %d): %s", e.code, body)
                return  # Non-retryable error
            except Exception as e:
                log.error("Failed to register server: %s", e)
                return

        log.warning("Failed to register server after %d attempts", retries)

    def remove_from_github(self):
        """Remove this server from the GitHub JSON on shutdown."""
        if not self.github_token or not self._public_url:
            return

        log.info("Removing server from GitHub: %s", self._public_url)
        repo_url = "https://api.github.com/repos/OBITOLZ0X/SyncWatch/contents/syncwatch_servers.json"
        headers = {
            "Authorization": f"token {self.github_token}",
            "User-Agent": "SyncWatchServer/1.0",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            req = urllib.request.Request(repo_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                sha = data.get("sha", "")
                import base64
                content_b64 = data.get("content", "")
                raw_decoded = base64.b64decode(content_b64).decode("utf-8")
                # Data on GitHub is encrypted — decrypt first
                try:
                    decrypted = self.decrypt_servers_data(raw_decoded)
                    servers = json.loads(decrypted)
                except Exception:
                    # Fallback: try as plain JSON (legacy entries)
                    servers = json.loads(raw_decoded)
        except Exception as e:
            log.warning("Could not fetch servers file for removal: %s", e)
            return

        servers = [s for s in servers if s.get("url") != self._public_url]
        new_content_json = json.dumps(servers, indent=2, ensure_ascii=False)
        encrypted = self.encrypt_servers_data(new_content_json)
        import base64
        new_content_b64 = base64.b64encode(encrypted.encode()).decode()

        payload = json.dumps({
            "message": f"Remove server: {self._public_url}",
            "content": new_content_b64,
            "sha": sha,
        }).encode()

        req = urllib.request.Request(
            repo_url, data=payload,
            headers={**headers, "Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                log.info("Server removed from GitHub successfully")
        except Exception as e:
            log.error("Failed to remove server from GitHub: %s", e)

    def cleanup_dead_servers(self) -> dict:
        """Fetch all servers from GitHub, verify with TCP ping, remove offline ones.
        
        Called by a Room when its host requests cleanup. This runs in an executor
        to avoid blocking the event loop. Returns {"removed": N, "online": M, "error": ""}
        """
        if not self.github_token:
            return {"removed": 0, "online": 0, "error": "No GitHub token configured"}

        log.info("Cleanup: fetching servers list from GitHub\u2026")
        repo_url = "https://api.github.com/repos/OBITOLZ0X/SyncWatch/contents/syncwatch_servers.json"
        headers = {
            "Authorization": f"token {self.github_token}",
            "User-Agent": "SyncWatchServer/1.0",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            req = urllib.request.Request(repo_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                sha = data.get("sha", "")
                import base64
                content_b64 = data.get("content", "")
                raw = base64.b64decode(content_b64).decode("utf-8").strip()
                # Try decrypt first (inlined — no dependency on core/token_utils.py)
                try:
                    decrypted = self.decrypt_servers_data(raw)
                    servers = json.loads(decrypted)
                except Exception:
                    servers = json.loads(raw)
        except Exception as e:
            log.error("Cleanup: failed to fetch servers: %s", e)
            return {"removed": 0, "online": 0, "error": str(e)}

        if not isinstance(servers, list) or not servers:
            return {"removed": 0, "online": 0, "error": "No servers found"}

        # Check each server with TCP ping (same logic as ServersManager._check_servers)
        import socket as _sock
        import threading as _threading

        results = [None] * len(servers)
        def _check(idx: int, srv: dict):
            url = srv.get("url", "")
            # Extract hostname from URL
            rest = url
            for prefix in ("wss://", "ws://", "https://", "http://"):
                if rest.startswith(prefix):
                    rest = rest[len(prefix):]
                    break
            if ":" in rest and rest.split(":")[1].split("/")[0].isdigit():
                host = rest.split(":")[0]
                port = int(rest.split(":")[1].split("/")[0])
            else:
                host = rest.split("/")[0]
                port = 443 if url.startswith("wss://") or url.startswith("https://") else 80

            try:
                sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                sock.settimeout(3.0)
                result = sock.connect_ex((host, port))
                sock.close()
                srv["status"] = "online" if result == 0 else "offline"
            except Exception:
                srv["status"] = "offline"
            results[idx] = srv

        threads = []
        for i, srv in enumerate(servers):
            t = _threading.Thread(target=_check, args=(i, srv), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=4.0)

        checked = [r for r in results if r is not None]
        online = [s for s in checked if s.get("status") == "online"]
        offline = [s for s in checked if s.get("status") != "online"]

        if not offline:
            log.info("Cleanup: all %d servers are online", len(online))
            return {"removed": 0, "online": len(online), "error": ""}

        log.info("Cleanup: %d online, %d offline — removing offline servers", len(online), len(offline))

        # Write back only online servers
        try:
            new_content = json.dumps(online, indent=2, ensure_ascii=False)
            encrypted = self.encrypt_servers_data(new_content)
            new_b64 = base64.b64encode(encrypted.encode("utf-8")).decode()
            payload = json.dumps({
                "message": f"Cleanup: removed {len(offline)} dead servers, {len(online)} remain",
                "content": new_b64,
                "sha": sha,
            }).encode()
            req = urllib.request.Request(
                repo_url, data=payload,
                headers={**headers, "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                log.info("Cleanup: GitHub update successful, SHA=%s",
                         result.get("content", {}).get("sha", "")[:8])
                return {"removed": len(offline), "online": len(online), "error": ""}
        except Exception as e:
            log.error("Cleanup: failed to update GitHub: %s", e)
            return {"removed": 0, "online": len(online), "error": str(e)}

    async def global_handler(self, websocket):
        """Handle a new WebSocket connection - parse room from JOIN."""
        room_name = None
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=15)
            msg = decode(raw)

            # ROOM_COUNT_REQUEST — simple query, no room needed
            if msg.get("type") == MsgType.ROOM_COUNT_REQUEST:
                await websocket.send(encode(
                    MsgType.ROOM_COUNT_RESPONSE,
                    room_count=len(self._rooms),
                    rooms=[{
                        "name": r.room_name,
                        "users": len(r.users),
                        "max_users": r.max_users,
                    } for r in self._rooms.values()],
                ))
                await websocket.close()
                return

            if msg.get("type") != MsgType.JOIN:
                await websocket.send(encode(MsgType.ERROR, message="Expected join message"))
                return

            username = str(msg.get("username", "")).strip()
            password = str(msg.get("password", ""))
            room_name = str(msg.get("room", "")).strip()

            if not room_name:
                await websocket.send(encode(MsgType.ERROR, message="Room name is required"))
                return

            # Check if this is the host creating the room or a joiner
            # Host flag comes from the token/room creation flow
            is_host = bool(msg.get("is_host", False))

            # Validate room access
            if room_name in self._rooms:
                room = self._rooms[room_name]
                # Room exists — if this user claims to be host, reject (room already has a host)
                if is_host:
                    await websocket.send(encode(
                        MsgType.ERROR,
                        message=f"Room '{room_name}' already exists. Use Join with the room token instead."
                    ))
                    return
            else:
                # Room doesn't exist — only host can create it
                if not is_host:
                    await websocket.send(encode(
                        MsgType.ERROR,
                        message=f"Room '{room_name}' not found. Make sure the host has created it."
                    ))
                    return
                # First user creates the room as host
                room_token = str(msg.get("room_token", ""))
                room = Room(
                    room_name=room_name,
                    password=password,
                    max_users=int(msg.get("max_users", 10)),
                    host_username=username,
                    share_info=bool(msg.get("share_info", True)),
                    features_enabled=bool(msg.get("features_enabled", False)),
                    room_token=room_token,
                    server=self,
                )
                self._rooms[room_name] = room
                is_host = True
                log.info("[%s] Room created by '%s'", room_name, username)

            await room.handle_connection(websocket, username, password, is_host)

            # After connection ends, clean up empty rooms
            if room_name in self._rooms and not self._rooms[room_name].users:
                del self._rooms[room_name]
                log.info("[%s] Room deleted (empty)", room_name)

        except asyncio.TimeoutError:
            log.warning("Connection timed out waiting for join")
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            log.error("Global handler error: %s", e)

    async def start_ngrok_tunnel(self):
        """Start ngrok tunnel to bypass NAT."""
        if not self.ngrok_token:
            return None
        try:
            from pyngrok import ngrok, conf
            log.info("Starting ngrok tunnel\u2026")
            pyngrok_config = conf.get_default()
            pyngrok_config.auth_token = self.ngrok_token
            tunnel = ngrok.connect(self.port, "http", pyngrok_config=pyngrok_config)
            raw_url = tunnel.public_url
            # Convert HTTP to WS
            if raw_url.startswith("https://"):
                ws_url = "wss://" + raw_url[8:]
            elif raw_url.startswith("http://"):
                ws_url = "ws://" + raw_url[7:]
            else:
                ws_url = raw_url
            log.info("ngrok tunnel: %s", ws_url)
            self._ngrok_manager = tunnel
            self._public_url = ws_url  # override with ngrok public URL
            return ws_url
        except ImportError:
            log.warning("pyngrok not installed. Install with: pip install pyngrok")
        except Exception as e:
            log.warning("Failed to start ngrok tunnel: %s", e)
        return None

    async def start(self):
        """Start the multi-room WebSocket server."""
        # Start ngrok tunnel if configured (bypasses NAT for remote access)
        if self.ngrok_token:
            await self.start_ngrok_tunnel()
        # Register on GitHub (with ngrok URL if available, otherwise public IP)
        self.register_on_github()

        self._server = await websockets.serve(
            self.global_handler,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=60,
        )

        addr = f"{self.host}:{self.port}"
        log.info("══════════════════════════════════════════════")
        log.info("  SyncWatch Server Started")
        log.info("  Listening on: %s", addr)
        if self._public_url:
            log.info("  Public URL:   %s", self._public_url)
        if self._country:
            log.info("  Country:      %s", self._country)
        log.info("══════════════════════════════════════════════")

        await self._server.wait_closed()

    async def stop(self):
        """Stop the server gracefully."""
        # Remove from GitHub
        self.remove_from_github()

        # Stop ngrok tunnel
        if self._ngrok_manager:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(self._ngrok_manager.public_url)
                ngrok.kill()
                log.info("ngrok tunnel stopped")
            except Exception:
                pass
            self._ngrok_manager = None

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("SyncWatch Server stopped")


# ── Main entry point ─────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SyncWatch Multi-Room Server")
    parser.add_argument("--port", "-p", type=int,
                        default=int(os.environ.get("SYNCWATCH_PORT", 8765)),
                        dest="port_flag",
                        help="Server port (default: 8765, from SYNCWATCH_PORT env)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--github-token", "-t", type=str,
                        default=os.environ.get("SYNCWATCH_GITHUB_TOKEN", ""),
                        dest="github_token_flag",
                        help="GitHub token for server registration")
    parser.add_argument("--ngrok-token", "-n", type=str,
                        default=os.environ.get("SYNCWATCH_NGROK_TOKEN", ""),
                        dest="ngrok_token_flag",
                        help="ngrok token for public tunnel (bypasses NAT)")
    # Parse known args first to avoid positional/flag conflicts
    args, remaining = parser.parse_known_args()

    # Use flags by default
    final_port = args.port_flag
    final_github_token = args.github_token_flag
    final_ngrok_token = args.ngrok_token_flag

    # Parse remaining as positional (port first, then github token)
    # This allows: python server.py 8765 TOKEN
    # Without the port vs token ambiguity
    if remaining:
        for i, val in enumerate(remaining):
            if i == 0:
                # First positional = port
                try:
                    final_port = int(val)
                except ValueError:
                    # If it's not a number, it might be a github token
                    final_github_token = val
            elif i == 1:
                # Second positional = github token
                final_github_token = val

    server = SyncWatchServer(
        host=args.host,
        port=final_port,
        github_token=final_github_token,
        ngrok_token=final_ngrok_token,
    )

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        log.info("Shutting down...")
        asyncio.run(server.stop())


if __name__ == "__main__":
    main()