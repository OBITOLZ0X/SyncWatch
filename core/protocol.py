"""
SyncWatch Protocol - Message definitions and serialization.
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Any


class MsgType:
    """All message types for client-server communication."""
    # Client -> Server
    JOIN = "join"
    STATE_UPDATE = "state_update"
    CHAT = "chat"
    FILE_INFO = "file_info"
    READY = "ready"
    KICK = "kick"
    SET_PERMISSION = "set_permission"
    MAKE_READY = "make_ready"
    MAKE_NOT_READY = "make_not_ready"
    READY_ALL = "ready_all"
    UNREADY_ALL = "unready_all"
    MUTE_CHAT = "mute_chat"
    MUTE_USER = "mute_user"
    HOST_TRANSFERRED = "host_transferred"

    # Server -> Client
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
    USER_LIST = "user_list"

    # Server cleanup (client -> server)
    CLEANUP_REQUEST = "cleanup_request"
    CLEANUP_RESPONSE = "cleanup_response"

    # Room count query (client -> server)
    ROOM_COUNT_REQUEST = "room_count_request"
    ROOM_COUNT_RESPONSE = "room_count_response"


@dataclass
class UserInfo:
    """Represents a user in a room."""
    username: str
    is_host: bool = False
    is_ready: bool = False
    file_name: str = ""
    file_size: int = 0
    file_duration: float = 0.0
    join_time: float = 0.0
    permissions: Dict[str, bool] = field(default_factory=lambda: {
        "chat": True,
        "kick": False,
        "make_ready": False,
        "mute_user": False,
    })

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "is_host": self.is_host,
            "is_ready": self.is_ready,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "file_duration": self.file_duration,
            "join_time": self.join_time,
            "permissions": dict(self.permissions),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserInfo":
        return cls(
            username=data["username"],
            is_host=data.get("is_host", False),
            is_ready=data.get("is_ready", False),
            file_name=data.get("file_name", ""),
            file_size=data.get("file_size", 0),
            file_duration=data.get("file_duration", 0.0),
            join_time=data.get("join_time", 0.0),
            permissions=data.get("permissions", {"chat": True, "kick": False, "make_ready": False, "mute_user": False}),
        )


def encode(msg_type: str, **kwargs) -> str:
    """Encode a message to JSON string."""
    return json.dumps({"type": msg_type, **kwargs})


def decode(data: str) -> Dict[str, Any]:
    """Decode a JSON string to message dict."""
    return json.loads(data)
