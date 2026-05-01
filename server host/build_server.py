"""
Build script for SyncWatch Server portable executable.

Creates a clean portable folder:

  SyncWatchServer/
  ├── server.exe          ← Run this (no arguments needed if .env is present)
  ├── .env                ← Optional: put your tokens here
  └── _internal/          ← Runtime files (do not modify)
      └── ...

Usage:
    python build_server.py
"""
import os
import shutil
import subprocess
import sys

APP_NAME = "SyncWatchServer"

# ── Paths ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(SCRIPT_DIR, "server.py")
ICON = os.path.join(SCRIPT_DIR, "SyncWatch.ico")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, APP_NAME)
DIST_TEMP = os.path.join(SCRIPT_DIR, "_build_server_dist")
BUILD_TEMP = os.path.join(SCRIPT_DIR, "_build_server_work")


def clean():
    """Remove previous build artifacts."""
    for d in (DIST_TEMP, BUILD_TEMP):
        if os.path.isdir(d):
            shutil.rmtree(d)
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)


def build():
    """Run PyInstaller to create the portable server build."""
    add_data = []
    if os.path.isfile(ICON):
        add_data.append(f"--add-data={ICON};.")
        add_data.append(f"--icon={ICON}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        # Server needs console to show logs
        # "--windowed",   # <-- no console, remove comment for hidden
        f"--distpath={DIST_TEMP}",
        f"--workpath={BUILD_TEMP}",
        "--specpath", SCRIPT_DIR,
        # Collect all necessary packages
        "--collect-all", "pyngrok",
        "--hidden-import", "cryptography",
        # Not strictly needed (we parse .env manually),
        # but bundle if available:
        "--hidden-import", "dotenv",
        *add_data,
        ENTRY,
    ]

    print(f"\n{'='*60}")
    print("Building SyncWatch Server portable\u2026")
    print(f"{'='*60}\n")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print("\n[ERROR] PyInstaller build failed.")
        sys.exit(1)


def package():
    """
    Reorganise PyInstaller output into a clean portable layout.
    """
    src = os.path.join(DIST_TEMP, APP_NAME)
    if not os.path.isdir(src):
        print(f"[ERROR] Build output not found: {src}")
        sys.exit(1)

    # Remove old output
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)

    # Move the whole PyInstaller output to the final location
    shutil.move(src, OUTPUT_DIR)

    # ── Rename exe to "server" ─────────────────────────
    old_exe = os.path.join(OUTPUT_DIR, f"{APP_NAME}.exe")
    new_exe = os.path.join(OUTPUT_DIR, "server.exe")
    if os.path.isfile(old_exe):
        os.rename(old_exe, new_exe)

    # ── Copy .env next to server.exe (if it exists) ────
    env_src = os.path.join(SCRIPT_DIR, ".env")
    env_dst = os.path.join(OUTPUT_DIR, ".env")
    if os.path.isfile(env_src):
        shutil.copy2(env_src, env_dst)
        print(f"  Copied .env to: {env_dst}")

    # ── Print final layout ─────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Portable server build ready: {OUTPUT_DIR}")
    print(f"{'='*60}")
    print()
    print("  Layout:")
    for entry in sorted(os.listdir(OUTPUT_DIR)):
        tag = "/" if os.path.isdir(os.path.join(OUTPUT_DIR, entry)) else ""
        print(f"    {entry}{tag}")
    print()
    print(f"  -> Run: {new_exe}")
    print()
    print("  Tips:")
    print("    - Place a .env file next to server.exe with:")
    print("        SYNCWATCH_GITHUB_TOKEN=ghp_xxx")
    print("        SYNCWATCH_NGROK_TOKEN=xxx")
    print("        SYNCWATCH_PORT=8765")
    print("    - Then just run: server.exe")
    print()


def cleanup():
    """Remove temporary build directories."""
    for d in (DIST_TEMP, BUILD_TEMP):
        if os.path.isdir(d):
            shutil.rmtree(d)
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)


if __name__ == "__main__":
    clean()
    build()
    package()
    cleanup()
    print("\nDone!")