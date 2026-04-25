<p align="center">
  <img src="../SyncWatch.ico" alt="SyncWatch Logo" width="96" />
</p>

<h1 align="center">SyncWatch</h1>
<p align="center"><strong>Watch Together, Perfectly Synced.</strong></p>

<p align="center">
  SyncWatch is a desktop application that lets multiple users watch media files together in perfect synchronization through VLC media player. It combines real-time WebSocket communication with ngrok tunneling so friends can watch together — no matter where they are.
</p>

---

## Table of Contents

- [Features](#features)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
  - [From Source](#from-source)
  - [Portable Build](#portable-build)
- [Getting Started](#getting-started)
  - [Hosting a Room](#hosting-a-room)
  - [Joining a Room](#joining-a-room)
- [Settings](#settings)
- [Room Controls](#room-controls)
  - [User List](#user-list)
  - [Chat & GIFs](#chat--gifs)
  - [Ready System](#ready-system)
  - [Permissions & Moderation](#permissions--moderation)
- [Architecture](#architecture)
- [Protocol Reference](#protocol-reference)
- [Security](#security)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **Real-time Sync** | Playback position, play/pause, and seek are synchronized across all users via WebSocket heartbeats |
| **Ready System** | All-or-nothing model — one user not ready pauses the entire room |
| **File Matching** | Detects file name, size, and duration mismatches between users |
| **Permissions** | Fine-grained per-user controls: chat, kick, make-ready, mute |
| **Chat** | Real-time text chat with timestamp and username |
| **GIF Support** | Detects Giphy, Tenor, Imgur, and Discord CDN links — displays animated GIFs in chat and as VLC video overlay |
| **Token Encryption** | AES-256-GCM encrypted room tokens for secure sharing |
| **ngrok Tunneling** | Automatic NAT/firewall traversal — no port forwarding required |
| **On-Screen Display** | Persistent and temporary OSD messages rendered directly inside VLC |
| **Themes** | Dark mode (Tokyonight-inspired) and Light mode with instant switching |
| **Portable** | Single-folder build via PyInstaller — runs from USB with no installation |

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        HOST MACHINE                             │
│                                                                 │
│  ┌──────────┐    ┌─────────────┐    ┌────────────────────────┐  │
│  │   VLC    │◄──►│ SyncWatch   │◄──►│  WebSocket Server      │  │
│  │ (HTTP +  │    │  (PySide6)  │    │  (asyncio, port 8765)  │  │
│  │  RC API) │    └─────────────┘    └────────┬───────────────┘  │
│  └──────────┘                                │                  │
│                                              │ ngrok tunnel     │
└──────────────────────────────────────────────┼──────────────────┘
                                               │
                                    ┌──────────┴──────────┐
                                    │   Public Internet    │
                                    │  (wss://xxx.ngrok)   │
                                    └──────────┬──────────┘
                                               │
                ┌──────────────────────────────┼──────────────────┐
                │               GUEST MACHINES                    │
                │                              │                  │
                │  ┌──────────┐    ┌───────────┴─┐               │
                │  │   VLC    │◄──►│  SyncWatch   │               │
                │  │ (HTTP +  │    │  (PySide6)   │               │
                │  │  RC API) │    └──────────────┘               │
                │  └──────────┘                                   │
                └─────────────────────────────────────────────────┘
```

1. **Host** creates a room → local WebSocket server starts → ngrok exposes it publicly
2. **Host** receives an encrypted token and shares it with friends
3. **Guests** paste the token → it decrypts to the ngrok WebSocket URL → they connect
4. **VLC** is controlled on each machine via its HTTP and RC interfaces
5. Playback state (position, play/pause, seek) is broadcast in real-time to keep everyone in sync

---

## Requirements

- **Windows** 10/11 (primary platform)
- **VLC media player** (auto-detected, or set manually in Settings)
- **ngrok account** — free tier works (host needs an [ngrok auth token](https://dashboard.ngrok.com/get-started/your-authtoken))
- **Python 3.10+** (only if running from source)

---

## Installation

### From Source

```bash
# Clone or download the project
cd SyncWatch

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### Portable Build

Build a standalone portable folder that runs without Python installed:

```bash
cd SyncWatch
python build_portable.py
```

This produces a `SyncWatchLz/` folder with the following structure:

```
SyncWatchLz/
├── SyncWatch.exe           ← Main executable (run this)
├── LICENSE                  ← MIT license
├── README.md                ← This documentation
├── SyncWatch.ico            ← Application icon
└── _internal/               ← Runtime files (Python, DLLs, packages)
    ├── *.dll                   (system & Python DLLs)
    ├── *.pyd                   (compiled Python extensions)
    ├── resources/
    │   └── syncwatch_osd.lua   (VLC OSD script)
    └── ...                     (bundled packages & data)
```

> **Note:** Only run `SyncWatch.exe` from the root folder. The `_internal` folder contains runtime dependencies and should not be modified.

---

## Getting Started

### Hosting a Room

1. Open **SyncWatch**
2. Go to the **Host** tab
3. Fill in the fields:
   - **NGROK TOKEN** — your ngrok auth token ([get it here](https://dashboard.ngrok.com/get-started/your-authtoken))
   - **USERNAME** — your display name
   - **ROOM NAME** — name for your room
   - **PASSWORD** — (optional) protect the room with a password
   - **MAX USERS** — maximum number of users allowed (2–50)
   - **SHARE ROOM INFO** — let guests see the token and password
   - **USER FEATURES** — let guests kick, mute, and manage ready states
4. Click **Create Room**
5. Share the **Room Token** (and password, if set) with your friends

### Joining a Room

1. Open **SyncWatch**
2. Go to the **Join** tab
3. Fill in the fields:
   - **ROOM TOKEN** — paste the token the host shared
   - **USERNAME** — your display name
   - **PASSWORD** — if the room is password-protected
4. Click **Join Room**

---

## Settings

Access the **Settings** tab in the main window:

| Setting | Description | Default |
|---|---|---|
| **VLC Path** | Path to `vlc.exe`. Auto-detected on Windows. | Auto |
| **Server Port** | Local WebSocket server port (host only). | `8765` |
| **Theme** | Toggle between **Dark** and **Light** mode. | Dark |

Settings are saved automatically and persist across sessions.

---

## Room Controls

Once you've created or joined a room, the **Room Window** opens:

### User List

Located on the left panel:

- **★** — Host indicator
- **●** — You (highlighted in orange)
- **🟢 Ready** — User has the correct file loaded and is ready
- **🔴 Not ready** — User has no file or hasn't marked ready
- **🔴 Different file** — User's file doesn't match the host's file

Right-click a user for actions (if you have permissions):
- **Kick** — Remove user from the room
- **Make Ready / Make Not Ready** — Force user's ready state
- **Mute / Unmute** — Mute a user's chat

### Chat & GIFs

Located on the right panel:

- Type messages and press **Enter** to send
- Messages appear with timestamps and usernames
- System events (user joined, paused, seeked, etc.) appear as system messages
- **GIF support**: Paste a link from Giphy, Tenor, Imgur, or Discord CDN — it renders as an animated GIF in chat **and** as a temporary overlay on the VLC video

### Ready System

The Ready system ensures everyone is watching the same thing:

1. Click **Load File** to open a media file in VLC
2. Once a file is loaded, the **Ready** button becomes active
3. Click **Ready** to signal you're ready to watch
4. When **all users** are ready, playback begins automatically
5. If anyone pauses, changes files, or becomes not-ready, the room pauses for everyone

### Permissions & Moderation

The host always has full control. Additional permissions can be granted:

| Permission | Description |
|---|---|
| **Chat** | Send text messages (enabled by default for all) |
| **Kick** | Remove users from the room |
| **Make Ready** | Force other users' ready state |
| **Mute User** | Mute individual users' chat |

- The host can **Mute All** non-host chat from the room header
- Enable **User Features** when creating the room to give guests kick/ready/mute permissions

---

## Architecture

### Components

| Component | File | Role |
|---|---|---|
| Entry Point | `main.py` | Application init, Qt setup, icon, font |
| Server | `core/server.py` | Asyncio WebSocket server, room state, sync logic |
| Client | `core/client.py` | WebSocket client with Qt signal integration |
| Protocol | `core/protocol.py` | Message type definitions, `UserInfo` dataclass |
| VLC Control | `core/vlc_controller.py` | HTTP + RC + Lua interfaces to VLC |
| Ngrok | `core/ngrok_manager.py` | Public tunnel management via pyngrok |
| Token Utils | `core/token_utils.py` | AES-256-GCM token encryption/decryption |
| Main Window | `ui/main_window.py` | Host/Join/Settings tabs |
| Room Window | `ui/room_window.py` | Active session UI (users, chat, controls) |
| Styles | `ui/styles.py` | Dark/Light theme QSS stylesheets |
| OSD Script | `resources/syncwatch_osd.lua` | VLC Lua extension for on-screen display |

### VLC Integration

SyncWatch controls VLC through **three interfaces simultaneously**:

1. **HTTP/JSON API** — Primary control: play, pause, seek, load files. Polled every 150ms for state changes.
2. **RC (Telnet) Interface** — Used for logo sub-filter commands (GIF overlay display).
3. **Lua Script** — Custom `syncwatch_osd.lua` monitors a temp file and renders OSD text inside VLC.

### Sync Engine

- The **host is authoritative** for play/pause state
- Non-host state updates are checked for drift (>2 seconds triggers correction)
- Seek events are broadcast to all users except the one who seeked
- A command queue with verification ensures VLC reaches the target position (up to 8 retries)

---

## Protocol Reference

SyncWatch uses a **WebSocket protocol** with JSON-serialized messages.

### Client → Server

| Type | Purpose |
|---|---|
| `JOIN` | Connect with username, room, password |
| `STATE_UPDATE` | Report playback state (position, paused, heartbeat) |
| `CHAT` | Send chat message (max 500 characters) |
| `FILE_INFO` | Report loaded file metadata (name, size, duration) |
| `READY` | Toggle ready/not-ready state |
| `KICK` | Remove a user from the room |
| `SET_PERMISSION` | Grant/revoke a user's permissions |
| `MAKE_READY` / `MAKE_NOT_READY` | Force a user's ready state |
| `MUTE_CHAT` / `MUTE_USER` | Mute chat globally or per-user |

### Server → Client

| Type | Purpose |
|---|---|
| `WELCOME` | Room state on connection (users, position, host file) |
| `USER_JOINED` / `USER_LEFT` | User roster updates |
| `SYNC` | Broadcast playback position/state |
| `CHAT_BROADCAST` | Relay chat message to all |
| `USER_UPDATE` | User status changed (ready, file info) |
| `KICKED` | Notification that you've been removed |
| `PERMISSION_UPDATE` | Permission changes |
| `CHAT_MUTED` | Chat mute state changed |
| `ALL_READY` | Everyone is ready — playback can begin |
| `ERROR` | Validation or connection error |

---

## Security

- **Token Encryption**: Room tokens are encrypted with **AES-256-GCM** using PBKDF2-HMAC-SHA256 key derivation (100,000 iterations). Each token uses a random salt and nonce, ensuring the same URL produces a different token every time.
- **Room Passwords**: Optional password protection for rooms, validated server-side.
- **Chat Limits**: Messages are capped at 500 characters to prevent abuse.
- **Connection Timeout**: 15-second timeout for the initial JOIN handshake.
- **Username Validation**: Server enforces unique usernames within a room.

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| PySide6 | ≥ 6.5.0 | Qt for Python — GUI framework |
| websockets | ≥ 12.0 | Async WebSocket client & server |
| pyngrok | ≥ 7.0.0 | Programmatic ngrok tunnel management |
| cryptography | ≥ 42.0.0 | AES-256-GCM token encryption |

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

**Copyright (c) 2026 OBITOLZ**

Contact: Telegram [@OBITOLZ](https://t.me/OBITOLZ)
