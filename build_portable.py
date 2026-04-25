"""
Build script for SyncWatch portable executable.

Creates a clean portable folder with a professional layout:

  SyncWatchLz/
  ├── SyncWatch.exe          ← Run this
  ├── LICENSE
  ├── README.md
  └── _internal/             ← Runtime files (do not modify)
      ├── *.dll / *.pyd
      ├── resources/
      │   └── syncwatch_osd.lua
      └── ...

Usage:
    python build_portable.py
"""
import os
import shutil
import subprocess
import sys

APP_NAME = "SyncWatch"
IS_WINDOWS = sys.platform == "win32"
APP_FILENAME = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME

# ── Paths ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # parent of SyncWatch/
ENTRY = os.path.join(SCRIPT_DIR, "main.py")
ICON = os.path.join(ROOT_DIR, "SyncWatch.ico")
LUA_SCRIPT = os.path.join(SCRIPT_DIR, "resources", "syncwatch_osd.lua")
OUTPUT_DIR = os.path.join(ROOT_DIR, "SyncWatchLz")
LICENSE  = os.path.join(SCRIPT_DIR, "LICENSE")
README   = os.path.join(SCRIPT_DIR, "README.md")
DIST_TEMP = os.path.join(SCRIPT_DIR, "_build_dist")
BUILD_TEMP = os.path.join(SCRIPT_DIR, "_build_work")


def clean():
    """Remove previous build artifacts."""
    for d in (DIST_TEMP, BUILD_TEMP):
        if os.path.isdir(d):
            shutil.rmtree(d)
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)


def build():
    """Run PyInstaller to create the portable build."""
    # Only bundle files needed at runtime inside _internal
    add_data = []
    if os.path.isfile(LUA_SCRIPT):
        add_data.append(f"--add-data={LUA_SCRIPT};resources")
    if IS_WINDOWS and os.path.isfile(ICON):
        add_data.append(f"--add-data={ICON};.")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        "--windowed",                    # no console window
        f"--distpath={DIST_TEMP}",
        f"--workpath={BUILD_TEMP}",
        "--specpath", SCRIPT_DIR,
        # Collect all necessary packages and Qt runtime files
        "--collect-all", "pyngrok",
        "--collect-all", "PySide6",
        "--hidden-import", "cryptography",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        *([f"--icon={ICON}"] if IS_WINDOWS and os.path.isfile(ICON) else []),
        *add_data,
        ENTRY,
    ]

    print(f"\n{'='*60}")
    print("Building SyncWatch portable…")
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

    PyInstaller produces:
        _build_dist/SyncWatch/
        ├── SyncWatch.exe
        └── _internal/  (everything else)

    We reshape it into:
        SyncWatchLz/
        ├── SyncWatch.exe
        ├── LICENSE
        ├── README.md
        └── _internal/  (runtime files only)
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

    # ── Place root-level docs next to the .exe ─────────
    for src_file in (LICENSE, README):
        if os.path.isfile(src_file):
            shutil.copy2(src_file, OUTPUT_DIR)

    # ── Clean duplicates from _internal ────────────────
    # PyInstaller may place --add-data "." files inside _internal;
    # remove doc copies that belong only at the root.
    internal = os.path.join(OUTPUT_DIR, "_internal")
    for name in ("LICENSE", "README.md"):
        dup = os.path.join(internal, name)
        if os.path.isfile(dup):
            os.remove(dup)

    # ── Print final layout ─────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Portable build ready: {OUTPUT_DIR}")
    print(f"{'='*60}")
    print()
    print("  Layout:")
    for entry in sorted(os.listdir(OUTPUT_DIR)):
        tag = "/" if os.path.isdir(os.path.join(OUTPUT_DIR, entry)) else ""
        print(f"    {entry}{tag}")
    print()
    print(f"  -> Run: {os.path.join(OUTPUT_DIR, APP_FILENAME)}")


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
