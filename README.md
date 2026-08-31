<p align="center">
  <img src="assets/icon.png" alt="SyncWatch Logo" width="128" height="128">
</p>

<h1 align="center">SyncWatch</h1>
<p align="center"><strong>Watch Together, Perfectly Synced.</strong></p>
<p align="center">Synchronized video playback for friends — VLC & MPV support, encrypted rooms, global server discovery.</p>

<p align="center">
  <a href="https://github.com/OBITOLZ0X/SyncWatch/actions/workflows/build.yml"><img src="https://github.com/OBITOLZ0X/SyncWatch/actions/workflows/build.yml/badge.svg" alt="Build"></a>
  <a href="https://github.com/OBITOLZ0X/SyncWatch/releases"><img src="https://img.shields.io/github/v/release/OBITOLZ0X/SyncWatch?label=latest%20release&color=brightgreen" alt="Release"></a>
  <a href="https://github.com/OBITOLZ0X/SyncWatch/blob/main/LICENSE"><img src="https://img.shields.io/github/license/OBITOLZ0X/SyncWatch?color=blue" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python"></a>
  <a href="https://github.com/OBITOLZ0X/SyncWatch/releases"><img src="https://img.shields.io/github/downloads/OBITOLZ0X/SyncWatch/total?color=orange" alt="Downloads"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-AI-8A2BE2?style=for-the-badge&logo=openai&logoColor=white" alt="Made with AI">
  <img src="https://img.shields.io/badge/Managed%20by-AI%20Agent-00BFFF?style=for-the-badge&logo=robot&logoColor=white" alt="Managed by AI">
</p>

> 🤖 **This project was built entirely by AI — from code to builds, releases & repo management.**  
> The AI agent handles everything: features, fixes, cross-platform builds, installers (`install.sh` / `install.ps1`), GitHub Actions, and releases. Human is the owner & reviewer.

<p align="center">
  <a href="#-quick-install">Quick Install</a> •
  <a href="#-features">Features</a> •
  <a href="#-download">Downloads</a> •
  <a href="#-how-it-works">How it Works</a> •
  <a href="#-development">Development</a>
</p>

---

## ⚡ Quick Install

### Linux — One-Line Installer (curl | bash)

```bash
curl -fsSL https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | bash
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | bash
```

This will:
- Detect your architecture (`x86_64` / `arm64`)
- Download the latest Linux release
- Install to `~/.local/bin` (no sudo needed) or `/usr/local/bin` (with sudo)
- Create a desktop entry (`.desktop` file) for your app launcher
- Add `syncwatch` to your PATH

**With sudo (system-wide):**

```bash
curl -fsSL https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | sudo bash
```

**Update / Uninstall:**

```bash
syncwatch --version          # check version
curl -fsSL https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | bash   # update

~/.local/bin/syncwatch-uninstall   # uninstall
```

---

### Windows — One-Line Installer (PowerShell)

> **Run PowerShell as Administrator** for system-wide install, or regular PowerShell for user install.

```powershell
irm https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.ps1 | iex
```

Or if `irm` is blocked:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.ps1 | iex"
```

This will:
- Download the latest Windows release (`SyncWatch-Windows.zip`)
- Extract to `$env:LOCALAPPDATA\SyncWatch`
- Create Start Menu shortcut & Desktop shortcut (optional)
- Add to PATH

**Uninstall:** Run `SyncWatch-Uninstall.ps1` from the install directory or delete `%LOCALAPPDATA%\SyncWatch`.

---

### Manual Download

| Platform | File | Download |
|----------|------|----------|
| **Windows** | `SyncWatch-Windows.zip` (portable, no install) | [Latest Release](https://github.com/OBITOLZ0X/SyncWatch/releases/latest) |
| **Linux** | `SyncWatch-Linux.tar.gz` (portable) | [Latest Release](https://github.com/OBITOLZ0X/SyncWatch/releases/latest) |
| **Linux** | `SyncWatch.deb` (Debian/Ubuntu) | [Latest Release](https://github.com/OBITOLZ0X/SyncWatch/releases/latest) |
| **Server Only** | `SyncWatchServer-*` | [Latest Release](https://github.com/OBITOLZ0X/SyncWatch/releases/latest) |

> 💡 **Portable = No installation needed.** Just extract and run `SyncWatch` / `SyncWatch.exe`.

---

## ✨ Features

- **🎬 Perfect Sync** — Frame-accurate playback synchronization across all participants (host controls, guests follow)
- **🔐 Encrypted Rooms** — Room tokens (`SW-...`) are AES-256-GCM encrypted; passwords never leave your device
- **🌍 Global Server Discovery** — Automatic server list from GitHub with latency-based sorting & live room counts
- **🎥 VLC & MPV** — Native OSD integration for both players (VLC Lua + MPV overlay)
- **💬 Built-in Chat** — Real-time chat with mute, permissions, kick/host-transfer
- **🎨 Modern UI** — Dark theme, responsive layout, animated spinners, GIF support
- **🔒 Permissions** — Host can grant/revoke: chat, kick, make-ready, mute
- **📡 NAT Bypass** — Optional ngrok tunneling for self-hosted servers behind NAT
- **🪶 Lightweight** — Pure Python + PySide6, <50MB portable builds
- **🖥️ Cross-Platform** — Windows 10/11 & Linux (x86_64, ARM64)

---

## 📸 Screenshots

| Host Panel | Room Window |
|------------|-------------|
| *Create rooms on public servers* | *Synced playback + chat* |

> *Screenshots coming soon — contributions welcome!*

---

## 🚀 How It Works

```
┌─────────────┐        WebSocket (wss://)        ┌─────────────┐
│  SyncWatch  │ ◄──────────────────────────────► │   Server    │
│   Client    │        Encrypted Room Token      │  (Python)   │
│  (VLC/MPV)  │  ───  Chat / Sync / Control  ──►│  + ngrok    │
└─────────────┘                                  └──────┬──────┘
                                                        │
                                               syncwatch_servers.json
                                               (GitHub - encrypted)
                                                        │
┌─────────────┐                                  ┌──────▼──────┐
│  SyncWatch  │ ◄────── Server Discovery ───────► │   GitHub    │
│   Client    │        (fetch + ping sort)       │  (raw CDN)  │
└─────────────┘                                  └─────────────┘
```

1. **Server** registers itself in `syncwatch_servers.json` on GitHub (encrypted)
2. **Clients** fetch the server list, measure TCP latency, sort by proximity
3. **Host** creates a room → gets an `SW-...` token to share
4. **Guests** paste the token → auto-resolve server + room, join instantly
5. **Playback** is synced via `STATE_UPDATE` messages (play/pause/seek)

---

## 📦 Project Structure

```
SyncWatch/
├── core/                 # Shared logic (client, protocol, crypto, ping)
│   ├── client.py         # WebSocket client (Qt signals)
│   ├── protocol.py       # Message types & serialization
│   ├── servers_manager.py# GitHub discovery + latency checks
│   ├── token_utils.py    # AES-256-GCM token encode/decode
│   ├── vlc_controller.py # VLC Lua OSD bridge
│   ├── mpv_controller.py # MPV IPC bridge
│   └── paths.py          # Cross-platform data dirs
├── ui/                   # PySide6 GUI
│   ├── main_window.py    # Host/Join/Settings tabs
│   ├── room_window.py    # Synced room + chat
│   └── styles.py         # Dark theme tokens
├── resources/            # VLC/MPV Lua scripts
│   ├── syncwatch_osd.lua
│   └── syncwatch_osd_mpv.lua
├── server/               # Standalone sync server
│   ├── server.py         # Multi-room WebSocket server (+ ngrok)
│   ├── build_server.py   # PyInstaller build for server
│   └── .env.example      # Config template
├── scripts/              # One-line installers
│   ├── install.sh        # Linux (curl | bash)
│   └── install.ps1       # Windows (irm | iex)
├── assets/               # Icons & branding
├── .github/workflows/    # CI: auto-build + release
├── main.py               # Entry point
├── build.py              # Unified portable builder (Win/Linux)
└── requirements.txt
```

---

## 🛠️ Development

### Requirements

- Python 3.10+
- VLC **or** MPV installed (for playback)
- Git

### Setup

```bash
git clone https://github.com/OBITOLZ0X/SyncWatch.git
cd SyncWatch
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

### Run the Server (optional self-host)

```bash
cd server
cp .env.example .env   # edit tokens
pip install -r requirements.txt
python server.py --port 8765
```

### Build Portable Executables

```bash
# Client (auto-detects OS, builds to dist/)
pip install pyinstaller
python build.py              # or: python build_portable.py (legacy)

# Server
python server/build_server.py
```

**Outputs:**
- Windows: `dist/SyncWatch/SyncWatch.exe` → `SyncWatchLz/` (portable folder)
- Linux: `dist/SyncWatch/SyncWatch` → `SyncWatch-Linux.tar.gz`

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork → Branch (`feat/my-feature`)
2. Commit with clear messages
3. Test on both VLC & MPV if touching playback
4. Open a Pull Request

---

## 🔒 Security

- Room tokens use **AES-256-GCM** with deterministic nonces
- Passwords are **never** embedded in tokens
- See [SECURITY.md](SECURITY.md) to report vulnerabilities

---

## 📄 License

MIT © [OBITOLZ0X](https://github.com/OBITOLZ0X) — See [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

- [PySide6](https://doc.qt.io/qtforpython/) — Qt for Python
- [websockets](https://websockets.readthedocs.io/) — WebSocket library
- [pyngrok](https://pyngrok.readthedocs.io/) — NAT tunneling
- [VLC](https://www.videolan.org/) & [MPV](https://mpv.io/) — Media players

<p align="center"><sub>Built with ❤️ for friends who love watching together.</sub></p>
