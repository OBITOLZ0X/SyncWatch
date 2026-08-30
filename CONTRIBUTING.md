# Contributing to SyncWatch

Thank you for considering contributing! 🎉

## Quick Start

```bash
git clone https://github.com/OBITOLZ0X/SyncWatch.git
cd SyncWatch
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Development Guidelines

### Code Style

- **Python 3.10+**, follow PEP 8
- Use `ruff` for linting (`pip install ruff && ruff check .`)
- Keep functions small and focused
- Add docstrings for public APIs

### Branch & Commit

- Branch from `main`: `feat/my-feature`, `fix/bug-name`, `docs/...`
- Write clear commits: `feat: add MPV subtitle sync` not `update`
- Keep PRs focused — one feature/fix per PR

### Testing

- Test with **both** VLC and MPV when touching playback code
- Test on Windows and Linux if possible
- Token/crypto changes must include round-trip tests:

```python
from core.token_utils import encode_token, decode_token
url = "wss://example.ngrok-free.app"
assert decode_token(encode_token(url)) == url
```

### UI Changes

- Use tokens from `ui/styles.py` (colors, radii, spacing)
- Support both light/dark via `styles` where applicable
- Keep layouts responsive (test at 960×540)

## Pull Request Process

1. Fork → Branch → Commit → Push
2. Open PR against `main` with a clear description
3. Link related issues (`Closes #123`)
4. Ensure CI passes (lint + smoke test)
5. Maintainer will review — be open to feedback

## Reporting Bugs

Include:
- OS + Python version (`python --version`, `uname -a`)
- Steps to reproduce
- Expected vs actual behavior
- Logs from `_data/logs/syncwatch.log`

## Feature Requests

Open an issue with:
- Use case (who benefits?)
- Proposed behavior
- Alternatives considered

## Security

See [SECURITY.md](SECURITY.md) — **do not** open public issues for vulnerabilities.

---

Thank you for making SyncWatch better! ❤️
