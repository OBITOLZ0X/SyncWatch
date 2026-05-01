"""
SyncWatch - WebSocket client with Qt signal integration.
"""
import asyncio
import json
import logging
from threading import Thread
from typing import Optional

import websockets
from PySide6.QtCore import QObject, Signal

from .protocol import MsgType, encode, decode

log = logging.getLogger(__name__)


class SyncClient(QObject):
    """WebSocket client that emits Qt signals for GUI updates."""

    # Signals
    connected = Signal()
    disconnected = Signal()
    error_received = Signal(str)
    welcome_received = Signal(dict)
    user_joined = Signal(dict)
    user_left = Signal(str)
    sync_received = Signal(dict)
    chat_received = Signal(str, str)     # username, message
    user_updated = Signal(dict)
    kicked = Signal(str)                 # reason
    permission_updated = Signal(dict)
    chat_muted_changed = Signal(bool)    # muted state
    all_ready = Signal()
    host_transferred = Signal(str)       # new_host username
    cleanup_response = Signal(dict)      # response from CLEANUP_RESPONSE

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._running = False
        self._had_error = False

    def connect_to_server(self, url: str, username: str, room: str, password: str = "",
                          is_host: bool = False, max_users: int = 10,
                          share_info: bool = True, features_enabled: bool = False,
                          room_token: str = ""):
        """Connect to a SyncWatch server in a background thread."""
        self._running = True
        self._thread = Thread(
            target=self._run_loop,
            args=(url, username, room, password, is_host, max_users, share_info, features_enabled, room_token),
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self, url: str, username: str, room: str, password: str,
                  is_host: bool = False, max_users: int = 10,
                  share_info: bool = True, features_enabled: bool = False,
                  room_token: str = ""):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(
                self._connect(url, username, room, password, is_host, max_users, share_info, features_enabled, room_token)
            )
        except Exception as e:
            log.error(f"Client loop error: {e}")
            if not self._had_error:
                self.error_received.emit(str(e))
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
            if not self._had_error:
                self.disconnected.emit()

    async def _connect(self, url: str, username: str, room: str, password: str,
                       is_host: bool = False, max_users: int = 10,
                       share_info: bool = True, features_enabled: bool = False,
                       room_token: str = ""):
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=60,
                additional_headers={"User-Agent": "SyncWatch/1.0"},
            ) as ws:
                self._ws = ws

                # Send join message
                join_kwargs = dict(
                    username=username,
                    room=room,
                    password=password,
                    is_host=is_host,
                )
                # Send room configuration fields for server mode
                if is_host:
                    join_kwargs["max_users"] = max_users
                    join_kwargs["share_info"] = share_info
                    join_kwargs["features_enabled"] = features_enabled
                    join_kwargs["room_token"] = room_token
                await ws.send(encode(MsgType.JOIN, **join_kwargs))

                self.connected.emit()
                log.info(f"Connected as '{username}'")

                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        msg = decode(raw)
                        self._dispatch(msg)
                    except json.JSONDecodeError:
                        log.warning("Received invalid JSON")

        except websockets.InvalidStatusCode as e:
            self.error_received.emit(f"Connection rejected (HTTP {e.status_code})")
        except websockets.InvalidURI:
            self.error_received.emit("Invalid server URL")
        except ConnectionRefusedError:
            self.error_received.emit("Connection refused - server may be offline")
        except Exception as e:
            self.error_received.emit(f"Connection error: {e}")
        finally:
            self._ws = None

    def _dispatch(self, msg: dict):
        """Dispatch a received message to the appropriate signal."""
        msg_type = msg.get("type")
        log.info("Received message type: %s", msg_type)

        if msg_type == MsgType.WELCOME:
            log.info("WELCOME users: %s", list(msg.get("users", {}).keys()))
            self.welcome_received.emit(msg)
        elif msg_type == MsgType.USER_JOINED:
            log.info("USER_JOINED: %s", msg.get("username"))
            self.user_joined.emit(msg)
        elif msg_type == MsgType.USER_LEFT:
            self.user_left.emit(msg.get("username", ""))
        elif msg_type == MsgType.SYNC:
            self.sync_received.emit(msg)
        elif msg_type == MsgType.CHAT_BROADCAST:
            self.chat_received.emit(msg.get("username", ""), msg.get("message", ""))
        elif msg_type == MsgType.USER_UPDATE:
            self.user_updated.emit(msg)
            # If this user became the new host and has a room_token, emit it
            if msg.get("room_token") and msg.get("username"):
                from PySide6.QtCore import Signal as _Sig
                # Emit the room token via a new signal if needed, but for now
                # the RoomWindow will handle it via user_updated signal
        elif msg_type == MsgType.KICKED:
            self.kicked.emit(msg.get("reason", ""))
        elif msg_type == MsgType.PERMISSION_UPDATE:
            self.permission_updated.emit(msg)
        elif msg_type == MsgType.CHAT_MUTED:
            self.chat_muted_changed.emit(msg.get("muted", False))
        elif msg_type == MsgType.ALL_READY:
            self.all_ready.emit()
        elif msg_type == MsgType.HOST_TRANSFERRED:
            self.host_transferred.emit(msg.get("new_host", ""))
        elif msg_type == MsgType.CLEANUP_RESPONSE:
            log.info("CLEANUP_RESPONSE: removed=%s online=%s", 
                     msg.get("removed"), msg.get("online"))
            self.cleanup_response.emit(msg)
        elif msg_type == MsgType.ERROR:
            self._had_error = True
            self.error_received.emit(msg.get("message", "Unknown error"))

    # --- Outgoing messages ---

    def send_state(self, position: float, paused: bool, heartbeat: bool = False):
        self._send(encode(MsgType.STATE_UPDATE, position=position, paused=paused, heartbeat=heartbeat))

    def send_chat(self, message: str):
        self._send(encode(MsgType.CHAT, message=message))

    def send_file_info(self, file_name: str, file_size: int, file_duration: float = 0.0):
        self._send(encode(
            MsgType.FILE_INFO,
            file_name=file_name,
            file_size=file_size,
            file_duration=file_duration,
        ))

    def send_ready(self, is_ready: bool):
        self._send(encode(MsgType.READY, is_ready=is_ready))

    def send_kick(self, target: str, reason: str = ""):
        self._send(encode(MsgType.KICK, target=target, reason=reason))

    def send_make_ready(self, target: str):
        self._send(encode(MsgType.MAKE_READY, target=target))

    def send_make_not_ready(self, target: str):
        self._send(encode(MsgType.MAKE_NOT_READY, target=target))

    def send_mute_chat(self, muted: bool):
        self._send(encode(MsgType.MUTE_CHAT, muted=muted))

    def send_ready_all(self):
        self._send(encode(MsgType.READY_ALL))

    def send_unready_all(self):
        self._send(encode(MsgType.UNREADY_ALL))

    def send_mute_user(self, target: str, muted: bool):
        self._send(encode(MsgType.MUTE_USER, target=target, muted=muted))

    def send_set_permission(self, target: str, permission: str, value: bool):
        self._send(encode(MsgType.SET_PERMISSION, target=target, permission=permission, value=value))

    def send_cleanup_request(self, servers: list):
        """Request a connected server to verify and remove dead servers from GitHub.
        
        The server will check all servers, remove offline ones from the GitHub JSON,
        and respond with CLEANUP_RESPONSE containing the result.
        """
        self._send(encode(MsgType.CLEANUP_REQUEST, servers=servers))

    def _send(self, message: str):
        if self._ws and self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._async_send(message), self._loop)

    async def _async_send(self, message: str):
        if self._ws:
            try:
                await self._ws.send(message)
            except Exception as e:
                log.error(f"Failed to send message: {e}")

    def disconnect(self):
        """Disconnect from the server."""
        self._running = False
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._close(), self._loop)

    async def _close(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running
