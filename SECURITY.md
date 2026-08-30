# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.x     | ✅ Yes             |
| < 2.0   | ⚠️ Best effort     |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please report privately:

- **GitHub:** Use [Security Advisories](https://github.com/OBITOLZ0X/SyncWatch/security/advisories/new) (preferred)
- **Email:** Open an issue with title `[SECURITY]` and minimal details — maintainer will contact you for a private channel

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response

- Acknowledgment within **48 hours**
- Fix + release as soon as possible (target: 7 days for critical)
- Credit in release notes if desired

## Security Notes

- Room tokens use **AES-256-GCM**; the ciphertext is deterministic but requires the master secret to decrypt
- Passwords are **never** embedded in tokens — users enter them separately
- `syncwatch_servers.json` on GitHub is encrypted at rest; only clients with the key can decode it
- Server discovery pings use TCP connect time — no credentials are sent during scanning
