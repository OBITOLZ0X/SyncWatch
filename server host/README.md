# SyncWatch Server

Standalone multi-room WebSocket server for SyncWatch.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your tokens:
#   SYNCWATCH_GITHUB_TOKEN=ghp_xxx   (for server discovery)
#   SYNCWATCH_NGROK_TOKEN=xxx        (optional, for NAT bypass)
#   SYNCWATCH_PORT=8765

# 2. Install deps
pip install -r requirements.txt

# 3. Run
python server.py

# Or build portable binary
python build_server.py
./SyncWatchServer/server   # Linux
SyncWatchServer\server.exe # Windows
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SYNCWATCH_GITHUB_TOKEN` | Yes (for public discovery) | GitHub PAT with `repo` scope |
| `SYNCWATCH_NGROK_TOKEN` | No | ngrok authtoken for public tunnel |
| `SYNCWATCH_PORT` | No | Port (default `8765`) |

## Docker (coming soon)

```bash
docker run -e SYNCWATCH_GITHUB_TOKEN=ghp_xxx -p 8765:8765 ghcr.io/obitolz0x/syncwatch-server
```

## Notes

- The old folder `server host/` (with space) has been renamed to `server/` for shell compatibility. Please update your paths.
