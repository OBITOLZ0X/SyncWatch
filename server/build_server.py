"""
Build script for SyncWatch Server — cross-platform.

Creates a clean portable folder:

  Windows:  server/SyncWatchServer/
            ├── server.exe
            ├── .env.example
            └── _internal/

  Linux:    server/SyncWatchServer/
            ├── server  (binary)
            ├── .env.example
            └── _internal/

Usage:
    python build_server.py [--clean]
"""

import os
import sys
import shutil
import subprocess
import platform

APP_NAME = "SyncWatchServer"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_candidates = [os.path.join(SCRIPT_DIR, "server.py"), os.path.join(SCRIPT_DIR, "server host.py")]
ENTRY = next((p for p in _candidates if os.path.isfile(p)), _candidates[0])
OUTPUT_DIR = os.path.join(SCRIPT_DIR, APP_NAME)
DIST_TEMP = os.path.join(SCRIPT_DIR, "_build_server_dist")
BUILD_TEMP = os.path.join(SCRIPT_DIR, "_build_server_work")

IS_WINDOWS = platform.system() == "Windows"
EXE_IN = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
EXE_OUT = "server.exe" if IS_WINDOWS else "server"


def find_icon():
    candidates = [
        os.path.join(SCRIPT_DIR, "SyncWatch.ico"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "SyncWatch.ico"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "assets", "icon.ico"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def clean():
    for d in (DIST_TEMP, BUILD_TEMP):
        if os.path.isdir(d):
            shutil.rmtree(d)
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)


def build():
    sep = ";" if IS_WINDOWS else ":"
    add_data = []
    icon = find_icon()
    if icon:
        add_data.append(f"--add-data={icon}{sep}.")
        if IS_WINDOWS:
            add_data.append(f"--icon={icon}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        f"--distpath={DIST_TEMP}",
        f"--workpath={BUILD_TEMP}",
        "--specpath", SCRIPT_DIR,
        "--collect-all", "pyngrok",
        "--collect-all", "certifi",
        "--hidden-import", "cryptography",
        "--hidden-import", "certifi",
        "--hidden-import", "dotenv",
        *add_data,
        ENTRY,
    ]

    print(f"\n{'='*60}")
    print(f"Building SyncWatch Server on {platform.system()}...")
    print(f"{'='*60}\n")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print("\n[ERROR] PyInstaller build failed.")
        sys.exit(1)


def package():
    src = os.path.join(DIST_TEMP, APP_NAME)
    if not os.path.isdir(src):
        print(f"[ERROR] Build output not found: {src}")
        sys.exit(1)

    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)

    shutil.move(src, OUTPUT_DIR)

    # Rename exe
    old_exe = os.path.join(OUTPUT_DIR, EXE_IN)
    new_exe = os.path.join(OUTPUT_DIR, EXE_OUT)
    if os.path.isfile(old_exe):
        os.rename(old_exe, new_exe)
        if not IS_WINDOWS:
            os.chmod(new_exe, 0o755)

    # Copy .env.example next to binary
    for name in (".env.example",):
        src_file = os.path.join(SCRIPT_DIR, name)
        if os.path.isfile(src_file):
            shutil.copy2(src_file, os.path.join(OUTPUT_DIR, name))

    print(f"\n{'='*60}")
    print(f"  Server build ready: {OUTPUT_DIR}")
    print(f"{'='*60}\n")
    print("  Layout:")
    for entry in sorted(os.listdir(OUTPUT_DIR)):
        tag = "/" if os.path.isdir(os.path.join(OUTPUT_DIR, entry)) else ""
        print(f"    {entry}{tag}")
    print(f"\n  -> Run: {new_exe}")
    print("\n  Tips:")
    print("    - Copy .env.example to .env and fill tokens:")
    print("        SYNCWATCH_GITHUB_TOKEN=ghp_xxx")
    print("        SYNCWATCH_NGROK_TOKEN=xxx")
    print("        SYNCWATCH_PORT=8765")
    print("    - Then run: ./server  (Linux)  or  server.exe (Windows)")


def cleanup():
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
