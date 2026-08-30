# Changelog

All notable changes to SyncWatch will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.2] — 2026-08-30

### Fixed
- **Linux still failing after 2.0.1** — `servers_manager.py` now tries *all* SSL contexts sequentially: certifi → unverified → system default (was only retrying on exact string match; now unconditional fallback, handles `unable to get local issuer`, `self signed`, expired, and `URLError.reason` wrapping)
- `core/server.py` cleanup fetch also fixed with same multi-context loop
- Verified `v2.0.1` Linux tarball was 85.8MB but still failed on some distros missing `ca-certificates`; 2.0.2 forces unverified fallback so it works even without system CAs

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
