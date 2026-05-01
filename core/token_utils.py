"""
SyncWatch - Token encoding/decoding for room sharing.

Encodes ngrok WebSocket URLs into compact, deterministic tokens
using AES-256-GCM so end users never see the raw tunnel address.

v2 improvements over v1:
  - Deterministic: same URL always produces the same token.
  - Compact: common URL prefixes/suffixes are stripped before encryption.
  - Fixed key (SHA-256 of master secret) — no per-token salt.
  - Nonce derived via HMAC of the plaintext — stored in the token.
  - Backward-compatible: decode_token transparently handles v1 tokens.
"""
import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MASTER_SECRET = b"SyncWatch-AES-2026"
_NONCE_LEN = 12

# ── v2: fixed key, deterministic nonce ────────────────────
_KEY = hashlib.sha256(_MASTER_SECRET).digest()

# Known prefixes / suffixes stripped to shrink the encrypted payload.
_URL_PREFIXES = ["wss://", "ws://", "https://", "http://"]
_URL_SUFFIX = ".ngrok-free.app"


def _compress_url(url: str) -> tuple:
    """Strip known prefix/suffix → (flags_byte, compressed_str)."""
    flags = 0
    for i, pfx in enumerate(_URL_PREFIXES):
        if url.startswith(pfx):
            flags |= (i + 1)   # 1..4
            url = url[len(pfx):]
            break
    if url.endswith(_URL_SUFFIX):
        flags |= 0x10
        url = url[: -len(_URL_SUFFIX)]
    return flags, url


def _decompress_url(flags: int, compressed: str) -> str:
    pfx_idx = flags & 0x0F
    if 1 <= pfx_idx <= len(_URL_PREFIXES):
        compressed = _URL_PREFIXES[pfx_idx - 1] + compressed
    if flags & 0x10:
        compressed += _URL_SUFFIX
    return compressed


# ── v2 encode / decode ────────────────────────────────────

def encode_token(url: str) -> str:
    """Encrypt a WebSocket URL into a compact, deterministic share token.

    Same URL always yields the same token.
    Token layout (base64):  nonce(12) | ciphertext+tag(var)
    """
    flags, compressed = _compress_url(url)
    plaintext = bytes([flags]) + compressed.encode("utf-8")
    # Deterministic nonce from URL content
    nonce = hmac.new(_MASTER_SECRET, url.encode("utf-8"), hashlib.sha256).digest()[:_NONCE_LEN]
    ciphertext = AESGCM(_KEY).encrypt(nonce, plaintext, None)
    raw = nonce + ciphertext
    return "SW-" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_server_token(server_url: str, room_name: str, room_password: str = "") -> str:
    """Encode a server URL + room name into a join token.

    Same server_url + room_name always yields the same token.
    The URL includes the room name as a query parameter.
    
    ⚠ Password is NEVER embedded in the token — the user must enter
    it manually in the Join panel. This ensures password security.
    """
    # Only room name in the token — NEVER the password
    full_url = f"{server_url.rstrip('/')}/?room={room_name}"
    return encode_token(full_url)


def decode_token(token: str) -> str:
    """Decrypt a share token back into the original WebSocket URL.

    Automatically detects v1 (salt-based) and v2 (compact) formats.
    Raises ValueError / cryptography.exceptions.InvalidTag on bad tokens.
    """
    token = token.strip()
    if token.startswith("SW-"):
        token = token[3:]
    # Restore base64 padding
    pad = 4 - len(token) % 4
    if pad != 4:
        token += "=" * pad
    raw = base64.urlsafe_b64decode(token)

    # Try v2 first (nonce(12) | ciphertext+tag)
    try:
        return _decode_v2(raw)
    except Exception:
        pass

    # Fallback: v1 format (salt(16) | nonce(12) | ciphertext+tag)
    return _decode_v1(raw)


def extract_server_token_info(token: str) -> dict:
    """Decode a server token and extract the server URL, room name and password."""
    url = decode_token(token)
    result = {"server_url": url, "room_name": "", "password": ""}

    # Parse query parameters
    if "/?" in url:
        base, qs = url.split("/?", 1)
        result["server_url"] = base
        params = {}
        for part in qs.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k] = v
        result["room_name"] = params.get("room", "")
        result["password"] = params.get("password", "")
    return result


def _decode_v2(raw: bytes) -> str:
    nonce = raw[:_NONCE_LEN]
    ciphertext = raw[_NONCE_LEN:]
    plaintext = AESGCM(_KEY).decrypt(nonce, ciphertext, None)
    flags = plaintext[0]
    compressed = plaintext[1:].decode("utf-8")
    return _decompress_url(flags, compressed)


def _decode_v1(raw: bytes) -> str:
    """Decode legacy v1 tokens (salt + nonce + ciphertext)."""
    _V1_SALT_LEN = 16
    salt = raw[:_V1_SALT_LEN]
    nonce = raw[_V1_SALT_LEN: _V1_SALT_LEN + _NONCE_LEN]
    ciphertext = raw[_V1_SALT_LEN + _NONCE_LEN:]
    key = hashlib.pbkdf2_hmac("sha256", _MASTER_SECRET, salt, 100_000)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ── Server data encryption (for syncwatch_servers.json on GitHub) ──
_SERVER_DATA_KEY = hashlib.sha256(b"SyncWatch-Server-Data-2026").digest()


def server_data_encrypt(raw_json: str) -> str:
    """Encrypt the server list JSON for storage on GitHub.

    Returns base64-encoded: nonce(12) | ciphertext+tag
    """
    import os
    nonce = os.urandom(12)
    ciphertext = AESGCM(_SERVER_DATA_KEY).encrypt(nonce, raw_json.encode("utf-8"), None)
    raw = nonce + ciphertext
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def server_data_decrypt(encrypted: str) -> str:
    """Decrypt the server list JSON from GitHub storage.

    Input: base64-encoded: nonce(12) | ciphertext+tag
    Returns plaintext JSON string, or raises on invalid input.
    """
    # Restore padding
    pad = 4 - len(encrypted) % 4
    if pad != 4:
        encrypted += "=" * pad
    raw = base64.urlsafe_b64decode(encrypted)
    nonce = raw[:12]
    ciphertext = raw[12:]
    plaintext = AESGCM(_SERVER_DATA_KEY).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
