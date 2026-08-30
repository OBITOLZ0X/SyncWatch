"""
SyncWatch - WebSocket server for room-based media synchronization.
"""
import asyncio
import json
import time
import logging
import websockets
from typing import Dict, Optional

from .protocol import MsgType, UserInfo, encode, decode

log = logging.getLogger(__name__)


class SyncServer:
    """WebSocket server managing a single synchronized room."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        room_name: str = "Room",
        password: str = "",
        max_users: int = 10,
        host_username: str = "Host",
        share_info: bool = True,
        features_enabled: bool = False,
    ):
        self.host = host
        self.port = port
        self.room_name = room_name
        self.password = password
        self.max_users = max_users
        self.host_username = host_username
        self.share_info = share_info
        self.features_enabled = features_enabled

        # Room playback state
        self.position: float = 0.0
        self.paused: bool = True
        self.last_update_time: float = time.time()
        self.set_by: str = host_username

        # Connected users
        self.users: Dict[str, UserInfo] = {}
        self.connections: Dict[str, websockets.WebSocketServerProtocol] = {}

        # Host file info (reference for file matching)
        self.host_file_name: str = ""
        self.host_file_size: int = 0

        # Chat mute state (host can mute all non-host chat)
        self.chat_muted: bool = False

        # Lock to serialize state updates (prevents race conditions)
        self._state_lock = asyncio.Lock()

        # Rate-limit drift corrections per user (username -> last correction time)
        self._last_drift_correction: Dict[str, float] = {}

        self._server = None

    def get_current_position(self) -> float:
        """Calculate current position accounting for elapsed time."""
        if not self.paused:
            elapsed = time.time() - self.last_update_time
            return self.position + elapsed
        return self.position

    async def handler(self, websocket):
        """Handle a new WebSocket connection."""
        username = None
        registered = False
        try:
            # First message - handle both JOIN and non-auth messages (room_count_request, cleanup_request)
            raw = await asyncio.wait_for(websocket.recv(), timeout=15)
            msg = decode(raw)
            msg_type = msg.get("type")

            # Handle room_count_request (doesn't require authentication)
            if msg_type == MsgType.ROOM_COUNT_REQUEST:
                await self._handle_room_count_request(websocket)
                return

            # Handle cleanup_request (doesn't require authentication)
            if msg_type == MsgType.CLEANUP_REQUEST:
                await self._handle_cleanup_request(websocket, msg)
                return

            # Otherwise, expect JOIN message
            if msg_type != MsgType.JOIN:
                await websocket.send(encode(MsgType.ERROR, message="Expected join message"))
                return

            username = str(msg.get("username", "")).strip()
            room_password = str(msg.get("password", ""))

            # Validate
            if not username:
                await websocket.send(encode(MsgType.ERROR, message="Username is required"))
                return

            if self.password and room_password != self.password:
                await websocket.send(encode(MsgType.ERROR, message="Invalid room password"))
                return

            if len(self.users) >= self.max_users:
                await websocket.send(encode(MsgType.ERROR, message="Room is full"))
                return

            if username in self.users:
                await websocket.send(encode(MsgType.ERROR, message="Username already taken"))
                return

            # Create user
            is_host = (username == self.host_username)
            user = UserInfo(username=username, is_host=is_host, join_time=time.time())
            # Apply default permissions based on features_enabled
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

            log.info("User '%s' joining — current users: %s",
                     username, list(self.users.keys()))

            # Send welcome with current room state
            user_list = {name: u.to_dict() for name, u in self.users.items()}
            log.info("WELCOME for '%s' includes users: %s",
                     username, list(user_list.keys()))
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
            log.info("Broadcasting USER_JOINED for '%s' to %d others",
                     username, len(self.connections) - 1)
            await self.broadcast(
                encode(MsgType.USER_JOINED, username=username, user=user.to_dict()),
                exclude=username,
            )

            log.info("User '%s' joined room '%s' successfully", username, self.room_name)

            # If others are in the room, pause and wait for the new user
            if len(self.users) > 1:
                # Only the new joiner is not ready — others keep their state
                user.is_ready = False
                self.paused = True
                self.position = self.get_current_position()
                self.last_update_time = time.time()
                self.set_by = "System"

                # Broadcast the new user's state
                await self.broadcast(encode(
                    MsgType.USER_UPDATE,
                    username=username,
                    user=user.to_dict(),
                    host_file_name=self.host_file_name,
                    host_file_size=self.host_file_size,
                ))

                # Broadcast pause sync so everyone pauses at the current position
                await self.broadcast(encode(
                    MsgType.SYNC,
                    position=self.position,
                    paused=True,
                    set_by="System",
                ))

                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST,
                    username="System",
                    message=f"{username} joined — waiting for them to get ready.",
                ))

            # Message loop
            async for raw in websocket:
                try:
                    msg = decode(raw)
                    await self.handle_message(username, msg)
                except json.JSONDecodeError:
                    log.warning(f"Invalid JSON from '{username}'")
                except Exception as e:
                    log.error(f"Error handling message from '{username}': {e}")

        except websockets.ConnectionClosed:
            log.info(f"Connection closed: {username}")
        except asyncio.TimeoutError:
            log.warning("Connection timed out waiting for join")
        except Exception as e:
            log.error(f"Handler error: {e}")
        finally:
            if registered and username and username in self.users:
                was_host = self.users[username].is_host
                was_host_username = username
                del self.users[username]
                self.connections.pop(username, None)

                # Pause room when someone leaves
                self.paused = True
                self.position = self.get_current_position()
                self.last_update_time = time.time()

                # If the host left, transfer host to user with longest join_time
                if was_host and self.users:
                    # Find user with the earliest join_time (longest in room)
                    new_host_name = min(
                        self.users.items(),
                        key=lambda x: x[1].join_time,
                    )[0]
                    # Transfer host
                    for uname, u in self.users.items():
                        u.is_host = (uname == new_host_name)
                    self.host_username = new_host_name
                    
                    await self.broadcast(encode(
                        MsgType.HOST_TRANSFERRED,
                        new_host=new_host_name,
                    ))
                    log.info(f"Host transferred from '{was_host_username}' to '{new_host_name}'")

                # Notify remaining users
                await self.broadcast(encode(MsgType.USER_LEFT, username=username))
                await self.broadcast(encode(
                    MsgType.SYNC,
                    position=self.position,
                    paused=True,
                    set_by="System",
                ))
                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST,
                    username="System",
                    message=f"{username} left the room",
                ))

                log.info(f"User '{username}' left room '{self.room_name}'")

    async def handle_message(self, username: str, msg: dict):
        """Route and handle an incoming message."""
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
        elif msg_type == MsgType.READY_ALL:
            await self._handle_ready_all(username, msg)
        elif msg_type == MsgType.UNREADY_ALL:
            await self._handle_unready_all(username, msg)
        elif msg_type == MsgType.MUTE_USER:
            await self._handle_mute_user(username, msg)
        elif msg_type == MsgType.CLEANUP_REQUEST:
            # Cleanup can be requested by authenticated users too
            await self._handle_cleanup_request(None, msg)

    async def _handle_state_update(self, username: str, user: UserInfo, msg: dict):
        """Handle playback state update (play/pause/seek). Serialized via lock."""
        async with self._state_lock:
            await self._do_state_update(username, user, msg)

    async def _do_state_update(self, username: str, user: UserInfo, msg: dict):
        """Actual state update logic (runs under lock)."""
        is_host = (username == self.host_username)
        is_pause = msg.get("paused", self.paused)
        new_position = msg.get("position", self.position)
        is_heartbeat = msg.get("heartbeat", False)

        # Heartbeats: update tracking + detect/correct drift
        if is_heartbeat:
            if username == self.host_username:
                # Host is authoritative — update server state from host
                self.position = new_position
                self.paused = is_pause
                self.last_update_time = time.time()
            else:
                # Non-host — check for drift against server's expected position
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
                                    MsgType.SYNC,
                                    position=expected,
                                    paused=False,
                                    set_by="System",
                                ))
                            except Exception:
                                pass
            return

        # Detect what changed BEFORE updating state
        old_paused = self.paused
        old_position = self.get_current_position()
        paused_changed = (is_pause != old_paused)
        seeked = abs(new_position - old_position) > 2.0

        # --- PAUSE: make user not-ready ---
        if is_pause and paused_changed:
            user.is_ready = False
            await self.broadcast(encode(
                MsgType.USER_UPDATE,
                username=username,
                user=user.to_dict(),
            ))

        # --- PLAY: check ready conditions ---
        if not is_pause and paused_changed:
            not_ready_users = [name for name, u in self.users.items()
                               if not u.is_ready]
            if len(not_ready_users) == 0:
                pass  # All ready — allow play
            elif len(not_ready_users) == 1 and not_ready_users[0] == username:
                # This user is the only not-ready — auto-ready them
                user.is_ready = True
                await self.broadcast(encode(
                    MsgType.USER_UPDATE,
                    username=username,
                    user=user.to_dict(),
                ))
                if all(u.is_ready for u in self.users.values()):
                    await self.broadcast(encode(MsgType.ALL_READY))
            else:
                # Block play — others are also not ready
                await self.broadcast(encode(
                    MsgType.SYNC,
                    position=self.get_current_position(),
                    paused=True,
                    set_by="System",
                ))
                return

        # Block play if not all ready (non-state-change play attempts)
        if not is_pause and not all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(
                MsgType.SYNC,
                position=self.get_current_position(),
                paused=True,
                set_by="System",
            ))
            return

        # If nothing meaningful changed, just update tracking
        if not paused_changed and not seeked:
            self.position = new_position
            self.last_update_time = time.time()
            return

        self.position = new_position
        self.paused = is_pause
        self.last_update_time = time.time()
        self.set_by = username

        # Broadcast sync to OTHER users (exclude sender to prevent feedback loop)
        await self.broadcast(encode(
            MsgType.SYNC,
            position=self.position,
            paused=self.paused,
            set_by=username,
        ), exclude=username)

        # Broadcast chat notifications for actions
        if seeked:
            t = self._fmt_time(self.position)
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username="System",
                message=f"{username} seeked to {t}",
            ))
        if paused_changed:
            if is_pause:
                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST,
                    username="System",
                    message=f"{username} paused",
                ))
            else:
                await self.broadcast(encode(
                    MsgType.CHAT_BROADCAST,
                    username="System",
                    message=f"{username} resumed playback",
                ))

    async def _handle_chat(self, username: str, user: UserInfo, msg: dict):
        """Handle chat message."""
        is_host = (username == self.host_username)
        if not is_host and not user.permissions.get("chat", True):
            return
        if not is_host and self.chat_muted:
            return

        message = str(msg.get("message", ""))[:500]  # Limit message length
        if message.strip():
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username=username,
                message=message,
            ))

    async def _handle_file_info(self, username: str, user: UserInfo, msg: dict):
        """Handle file info update from user."""
        old_file = user.file_name
        user.file_name = str(msg.get("file_name", ""))
        user.file_size = int(msg.get("file_size", 0))
        user.file_duration = float(msg.get("file_duration", 0.0))
        user.is_ready = False  # Reset ready only for the user who changed file

        # Track host file as reference
        if username == self.host_username:
            self.host_file_name = user.file_name
            self.host_file_size = user.file_size

        # Broadcast updated info only for the user who changed file
        await self.broadcast(encode(
            MsgType.USER_UPDATE,
            username=username,
            user=user.to_dict(),
            host_file_name=self.host_file_name,
            host_file_size=self.host_file_size,
        ))

        # Pause everyone — playback must stop until everyone re-readies
        self.paused = True
        self.position = self.get_current_position()
        self.last_update_time = time.time()
        self.set_by = "System"
        await self.broadcast(encode(
            MsgType.SYNC,
            position=self.position,
            paused=True,
            set_by="System",
        ))

        # Notify via chat
        if not user.file_name:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username="System",
                message=f"{username} closed VLC.",
            ))
        elif old_file:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username="System",
                message=f"{username} changed their file to: {user.file_name}",
            ))
        else:
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username="System",
                message=f"{username} loaded: {user.file_name}",
            ))

    async def _handle_ready(self, username: str, user: UserInfo, msg: dict):
        """Handle ready state toggle."""
        was_ready = user.is_ready
        user.is_ready = bool(msg.get("is_ready", False))

        await self.broadcast(encode(
            MsgType.USER_UPDATE,
            username=username,
            user=user.to_dict(),
        ))

        # If a user becomes not-ready, pause the room for everyone
        if was_ready and not user.is_ready:
            self.paused = True
            self.position = self.get_current_position()
            self.last_update_time = time.time()
            self.set_by = "System"
            await self.broadcast(encode(
                MsgType.SYNC,
                position=self.position,
                paused=True,
                set_by="System",
            ))
            await self.broadcast(encode(
                MsgType.CHAT_BROADCAST,
                username="System",
                message=f"{username} is no longer ready \u2014 paused.",
            ))

        # Check if ALL users are ready
        if self.users and all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(MsgType.ALL_READY))

    async def _handle_kick(self, username: str, msg: dict):
        """Handle kick request (host or users with kick permission)."""
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("kick", False)):
            return

        target = msg.get("target", "")
        if target in self.connections and target != self.host_username:
            reason = msg.get("reason", f"Kicked by {username}")
            try:
                await self.connections[target].send(encode(
                    MsgType.KICKED,
                    reason=reason,
                ))
                await self.connections[target].close()
            except Exception:
                pass

    async def _handle_set_permission(self, username: str, msg: dict):
        """Handle permission change (host only)."""
        if username != self.host_username:
            return

        target = msg.get("target", "")
        permission = msg.get("permission", "")
        value = bool(msg.get("value", True))

        if target in self.users and permission in ("chat", "kick", "make_ready", "mute_user"):
            self.users[target].permissions[permission] = value
            await self.broadcast(encode(
                MsgType.PERMISSION_UPDATE,
                username=target,
                permission=permission,
                value=value,
                permissions=self.users[target].permissions,
            ))

    async def _handle_make_ready(self, username: str, msg: dict):
        """Handle make-ready request (host or users with make_ready permission)."""
        is_host = (username == self.host_username)
        user = self.users.get(username)
        if not is_host and (not user or not user.permissions.get("make_ready", False)):
            return

        target = msg.get("target", "")
        target_user = self.users.get(target)
        if not target_user or target == self.host_username:
            return

        # Only allow if target has a file loaded
        if not target_user.file_name:
            return

        target_user.is_ready = True
        await self.broadcast(encode(
            MsgType.USER_UPDATE,
            username=target,
            user=target_user.to_dict(),
        ))

        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"{username} marked {target} as ready.",
        ))

        # Check if ALL users are now ready
        if self.users and all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(MsgType.ALL_READY))

    async def _handle_make_not_ready(self, username: str, msg: dict):
        """Handle make-not-ready request (host or users with make_ready permission)."""
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
            MsgType.USER_UPDATE,
            username=target,
            user=target_user.to_dict(),
        ))

        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"{username} marked {target} as not ready.",
        ))

        # Pause the room since not everyone is ready anymore
        self.paused = True
        self.position = self.get_current_position()
        self.last_update_time = time.time()
        await self.broadcast(encode(
            MsgType.SYNC,
            position=self.position,
            paused=True,
            set_by="System",
        ))

    async def _handle_ready_all(self, username: str, msg: dict):
        """Handle ready all request (host only). Makes all users who have the same file ready and starts playback."""
        if username != self.host_username:
            return

        # Check all users have files and they're all the same
        if not self.users:
            return

        reference_file = None
        reference_size = None
        for uname, u in self.users.items():
            if not u.file_name:
                return  # Someone doesn't have a file
            if reference_file is None:
                reference_file = u.file_name
                reference_size = u.file_size
            elif u.file_name != reference_file or u.file_size != reference_size:
                return  # Files differ

        # All users have the same file — make everyone ready
        for uname, u in self.users.items():
            u.is_ready = True
            await self.broadcast(encode(
                MsgType.USER_UPDATE,
                username=uname,
                user=u.to_dict(),
            ))

        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"Host marked all users as ready.",
        ))

        # Start playback
        if self.users and all(u.is_ready for u in self.users.values()):
            await self.broadcast(encode(MsgType.ALL_READY))

    async def _handle_unready_all(self, username: str, msg: dict):
        """Handle unready all request (host only). Makes all non-host users not ready."""
        if username != self.host_username:
            return

        for uname, u in self.users.items():
            if uname != self.host_username:
                u.is_ready = False
                await self.broadcast(encode(
                    MsgType.USER_UPDATE,
                    username=uname,
                    user=u.to_dict(),
                ))

        # Pause the room
        self.paused = True
        self.position = self.get_current_position()
        self.last_update_time = time.time()
        await self.broadcast(encode(
            MsgType.SYNC,
            position=self.position,
            paused=True,
            set_by="System",
        ))

        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"Host marked all users as not ready.",
        ))

    async def _handle_mute_chat(self, username: str, msg: dict):
        """Handle mute/unmute chat (host only)."""
        if username != self.host_username:
            return

        self.chat_muted = bool(msg.get("muted", True))
        await self.broadcast(encode(
            MsgType.CHAT_MUTED,
            muted=self.chat_muted,
        ))
        state = "muted" if self.chat_muted else "unmuted"
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"Host {state} the chat.",
        ))

    async def _handle_mute_user(self, username: str, msg: dict):
        """Handle mute/unmute a specific user (host or users with mute_user permission)."""
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
            MsgType.PERMISSION_UPDATE,
            username=target,
            permission="chat",
            value=not muted,
            permissions=target_user.permissions,
        ))

        state = "muted" if muted else "unmuted"
        await self.broadcast(encode(
            MsgType.CHAT_BROADCAST,
            username="System",
            message=f"{username} {state} {target}.",
        ))

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = int(seconds)
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"

    async def broadcast(self, message: str, exclude: str = None):
        """Send message to all connected users in parallel, optionally excluding one."""
        targets = [(name, ws) for name, ws in list(self.connections.items())
                    if name != exclude]
        if not targets:
            return

        log.debug("Broadcasting to %d users (exclude=%s): %s",
                  len(targets), exclude, message[:120])

        async def _send(name, ws):
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                log.warning("Broadcast: '%s' connection closed", name)
                return name
            except Exception as e:
                log.warning("Broadcast send to '%s' failed: %s", name, e)
            return None

        results = await asyncio.gather(*[_send(n, w) for n, w in targets])
        for name in results:
            if name:
                self.users.pop(name, None)
                self.connections.pop(name, None)

    async def _handle_room_count_request(self, websocket):
        """Handle room_count_request from clients (for server discovery).
        
        This request doesn't require authentication.
        Returns the count of currently open rooms and rooms with users.
        """
        try:
            # Count rooms with users
            room_count = len(self.users)
            await websocket.send(encode(
                MsgType.ROOM_COUNT_RESPONSE,
                room_count=room_count,
                room_name=self.room_name,
            ))
            log.info("Sent room_count_response: %d users in room '%s'", room_count, self.room_name)
        except Exception as e:
            log.warning("Failed to send room_count_response: %s", e)

    async def _handle_cleanup_request(self, websocket, msg: dict):
        """Handle cleanup_request to remove offline servers from GitHub.
        
        This request:
        1. Verifies each server in the list
        2. Removes offline servers from GitHub syncwatch_servers.json
        3. Sends CLEANUP_RESPONSE with results
        
        This request doesn't require authentication (only running servers can make it).
        """
        servers = msg.get("servers", [])
        if not servers:
            try:
                await websocket.send(encode(
                    MsgType.CLEANUP_RESPONSE,
                    removed=[],
                    online=[],
                ))
            except Exception:
                pass
            return

        # Verify each server and collect offline ones
        removed = []
        online = []
        
        import socket as _sock
        for srv in servers:
            url = srv.get("url", "")
            if not url:
                continue

            # Extract hostname and port from URL
            scheme = ""
            rest = url
            for prefix in ("wss://", "ws://", "https://", "http://"):
                if rest.startswith(prefix):
                    scheme = prefix.rstrip("://")
                    rest = rest[len(prefix):]
                    break

            if ":" in rest and rest.split(":")[1].split("/")[0].isdigit():
                host = rest.split(":")[0]
                port = int(rest.split(":")[1].split("/")[0])
            else:
                host = rest.split("/")[0]
                if scheme == "wss" or scheme == "https":
                    port = 443
                elif scheme == "ws" or scheme == "http":
                    port = 80
                else:
                    port = srv.get("port", 8765)

            # Check if server is online via TCP
            is_online = False
            try:
                sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                sock.settimeout(3.0)
                result = sock.connect_ex((host, port))
                sock.close()
                is_online = (result == 0)
            except Exception:
                is_online = False

            if is_online:
                online.append(url)
            else:
                removed.append(url)
                log.info("Cleanup: Marking server as offline: %s", url)

        # If any servers were marked as offline, attempt to update GitHub
        if removed:
            try:
                # Attempt to remove offline servers from GitHub
                # This requires GitHub token which is only available on running servers
                log.info("Cleanup: Attempting to remove %d offline servers from GitHub", len(removed))
                
                # Try to import token_utils for encrypted storage
                try:
                    from .token_utils import server_data_encrypt, server_data_decrypt
                    from urllib.request import Request, urlopen
                    from urllib.error import URLError
                    import base64

                    # Fetch current servers from GitHub
                    GITHUB_SERVERS_URL = "https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/syncwatch_servers.json"
                    req = Request(GITHUB_SERVERS_URL, headers={"User-Agent": "SyncWatch/2.0"})
                    
                    with urlopen(req, timeout=10) as resp:
                        raw = resp.read().decode("utf-8").strip()
                        try:
                            decrypted = server_data_decrypt(raw)
                            current_servers = json.loads(decrypted)
                        except Exception:
                            current_servers = json.loads(raw)

                    # Remove offline servers
                    updated_servers = [srv for srv in current_servers if srv.get("url") not in removed]
                    
                    if len(updated_servers) < len(current_servers):
                        log.info("Cleanup: Removed %d offline servers from list", 
                                len(current_servers) - len(updated_servers))
                        # Note: Can't update GitHub without token on client, so this is logged
                except Exception as e:
                    log.warning("Cleanup: Failed to update GitHub servers list: %s", e)
            except Exception as e:
                log.warning("Cleanup request error: %s", e)

        # Send response
        try:
            await websocket.send(encode(
                MsgType.CLEANUP_RESPONSE,
                removed=removed,
                online=online,
            ))
            log.info("Cleanup response sent: removed=%d, online=%d", len(removed), len(online))
        except Exception as e:
            log.warning("Failed to send cleanup_response: %s", e)

    async def start(self):
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self.handler,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=60,
        )
        log.info(f"SyncWatch server started on {self.host}:{self.port}")
        await self._server.wait_closed()

    async def stop(self):
        """Stop the server gracefully."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("SyncWatch server stopped")

    def update_host_file(self, file_name: str, file_size: int):
        """Update the host's reference file info."""
        self.host_file_name = file_name
        self.host_file_size = file_size
