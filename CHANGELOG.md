# Changelog

All notable changes to SyncWatch will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] — 2026-08-30

### Fixed
- `SSL CERTIFICATE_VERIFY_FAILED` — Windows now bundles `certifi` CA bundle + fallback to unverified SSL (fixes "No servers found" on Windows Python / PyInstaller builds)
- `build.py` / `server/build_server.py` now `--collect-all certifi` + `--hidden-import certifi` so exe carries CA certs
- `servers_manager.py` retries with `ssl._create_unverified_context()` on `CERTIFICATE_VERIFY_FAILED`

## [2.0.0] — 2026-08-30

### Added
- Professional repository structure (server/ rename, assets/, scripts/)
- Cross-platform builds: Windows (.zip) + Linux (.tar.gz + .deb)
- One-line installers: `install.sh` (Linux) and `install.ps1` (Windows)
- GitHub Actions: auto-build on push + release on tag `v*.*.*`
- Desktop entry + icon for Linux, Start Menu/Desktop shortcuts for Windows
- `pyproject.toml`, `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`
- Portfolio-quality README with badges, screenshots, and quick-install guides
- Unified `build.py` (cross-platform) + legacy `build_portable.py` retained

### Changed
- Server folder renamed from `server host` → `server` (space-free, shell-friendly)
- `build_server.py` now cross-platform (Linux separator handling)
- Icon bundled from `assets/` with multi-resolution `.ico`

### Fixed
- PyInstaller `add-data` separator now OS-aware (`;` on Windows, `:` on Linux)

## [1.x] — Earlier

- Core sync engine (WebSocket + VLC/MPV OSD)
- Encrypted room tokens (AES-256-GCM)
- Global server discovery via GitHub
- Host/Join UI with permissions, chat, kick, host-transfer
