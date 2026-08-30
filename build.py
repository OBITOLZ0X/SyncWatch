"""
Unified build script for SyncWatch — cross-platform.

Creates a clean portable folder:

  Windows:  SyncWatchLz/
            ├── SyncWatch.exe
            ├── LICENSE
            ├── README.md
            └── _internal/

  Linux:    SyncWatch-Linux/
            ├── SyncWatch   (binary, executable)
            ├── LICENSE
            ├── README.md
            └── _internal/

Usage:
    python build.py [--onefile] [--clean]

Options:
    --onefile   Build single-file executable (larger, slower startup)
    --clean     Remove previous build artifacts before building
"""

import os
import sys
import shutil
import subprocess
import platform
import argparse

APP_NAME = "SyncWatch"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(SCRIPT_DIR, "main.py")
ROOT_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "SyncWatch" else SCRIPT_DIR
# Find icon candidates (in order of preference)
ICON_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "SyncWatch.ico"),
    os.path.join(SCRIPT_DIR, "assets", "icon.ico"),
    os.path.join(SCRIPT_DIR, "server", "SyncWatch.ico"),
]
LICENSE_FILE = os.path.join(SCRIPT_DIR, "LICENSE")
README_FILE = os.path.join(SCRIPT_DIR, "README.md")

# Platform-specific
IS_WINDOWS = platform.system() == "Windows"
EXE_NAME = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
OUTPUT_DIR_NAME = "SyncWatchLz" if IS_WINDOWS else "SyncWatch-Linux"


def find_icon() -> str | None:
    for p in ICON_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def get_paths(onefile: bool = False):
    """Return (dist_temp, build_temp, output_dir, lua_script)."""
    if onefile:
        dist_temp = os.path.join(SCRIPT_DIR, "dist")
        build_temp = os.path.join(SCRIPT_DIR, "build")
        output_dir = os.path.join(SCRIPT_DIR, "dist")
    else:
        dist_temp = os.path.join(SCRIPT_DIR, "_build_dist")
        build_temp = os.path.join(SCRIPT_DIR, "_build_work")
        output_dir = os.path.join(SCRIPT_DIR, OUTPUT_DIR_NAME)
    lua_script = os.path.join(SCRIPT_DIR, "resources", "syncwatch_osd.lua")
    lua_mpv = os.path.join(SCRIPT_DIR, "resources", "syncwatch_osd_mpv.lua")
    return dist_temp, build_temp, output_dir, lua_script, lua_mpv


def clean(dist_temp: str, build_temp: str):
    for d in (dist_temp, build_temp):
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"  Cleaned {d}")
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)
        print(f"  Removed {spec}")


def build(dist_temp: str, build_temp: str, lua_script: str, lua_mpv: str, onefile: bool = False):
    sep = ";" if IS_WINDOWS else ":"
    add_data = []

    # Lua resources
    if os.path.isfile(lua_script):
        add_data.append(f"--add-data={lua_script}{sep}resources")
    if os.path.isfile(lua_mpv):
        add_data.append(f"--add-data={lua_mpv}{sep}resources")

    # Icon as data (fallback if PyInstaller icon fails on Linux)
    icon = find_icon()
    if icon and os.path.isfile(icon):
        # Also bundle icon as data for runtime _icon_path() lookup
        add_data.append(f"--add-data={icon}{sep}.")

    icon_arg = []
    if icon and IS_WINDOWS:
        icon_arg = [f"--icon={icon}"]
    elif icon:
        # On Linux PyInstaller ignores --icon, but we still bundle it
        pass

    mode_args = ["--onefile"] if onefile else ["--onedir"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        "--windowed" if IS_WINDOWS else "--console",  # windowed on Win, console on Linux (can hide)
        f"--distpath={dist_temp}",
        f"--workpath={build_temp}",
        "--specpath", SCRIPT_DIR,
        "--collect-all", "pyngrok",
        "--hidden-import", "cryptography",
        *icon_arg,
        *mode_args,
        *add_data,
        ENTRY,
    ]
    # On Linux, we want console hidden? Use windowed if available, but PySide6 needs display
    # Keep console for Linux so logs visible; user can use --windowed manually
    if not IS_WINDOWS and "--windowed" in cmd:
        cmd.remove("--windowed")

    print(f"\n{'='*60}")
    print(f"Building SyncWatch ({'onefile' if onefile else 'onedir'}) on {platform.system()}...")
    print(f"{'='*60}\n")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print("\n[ERROR] PyInstaller build failed.")
        sys.exit(1)


def package(dist_temp: str, output_dir: str, onefile: bool = False):
    if onefile:
        # Single file mode: just report location
        exe_path = os.path.join(dist_temp, EXE_NAME)
        if not os.path.isfile(exe_path):
            print(f"[ERROR] Build output not found: {exe_path}")
            sys.exit(1)
        print(f"\n{'='*60}")
        print(f"  Single-file build ready: {exe_path}")
        print(f"{'='*60}")
        print(f"  Size: {os.path.getsize(exe_path) / (1024*1024):.1f} MB")
        return

    src = os.path.join(dist_temp, APP_NAME)
    if not os.path.isdir(src):
        print(f"[ERROR] Build output not found: {src}")
        sys.exit(1)

    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)

    shutil.move(src, output_dir)

    for src_file in (LICENSE_FILE, README_FILE):
        if os.path.isfile(src_file):
            shutil.copy2(src_file, output_dir)

    internal = os.path.join(output_dir, "_internal")
    for name in ("LICENSE", "README.md"):
        dup = os.path.join(internal, name)
        if os.path.isfile(dup):
            os.remove(dup)

    # Make binary executable on Linux
    exe_path = os.path.join(output_dir, EXE_NAME)
    if not IS_WINDOWS and os.path.isfile(exe_path):
        os.chmod(exe_path, 0o755)

    print(f"\n{'='*60}")
    print(f"  Portable build ready: {output_dir}")
    print(f"{'='*60}\n")
    print("  Layout:")
    for entry in sorted(os.listdir(output_dir)):
        tag = "/" if os.path.isdir(os.path.join(output_dir, entry)) else ""
        size = ""
        fp = os.path.join(output_dir, entry)
        if os.path.isfile(fp):
            size = f"  ({os.path.getsize(fp)/(1024*1024):.1f} MB)" if entry.endswith((".exe", "")) and not entry.startswith("_") else ""
        print(f"    {entry}{tag}{size}")
    print(f"\n  -> Run: {exe_path}")
    if not IS_WINDOWS:
        print(f"  -> Or archive: tar -czf SyncWatch-Linux.tar.gz -C {os.path.dirname(output_dir)} {os.path.basename(output_dir)}")


def cleanup(dist_temp: str, build_temp: str, onefile: bool = False):
    # Only clean temp dirs for onedir; keep dist for onefile
    if not onefile:
        for d in (dist_temp, build_temp):
            if os.path.isdir(d):
                # dist_temp is now empty after move, safe to remove
                try:
                    if d == dist_temp and not os.listdir(d):
                        os.rmdir(d)
                    elif d == build_temp:
                        shutil.rmtree(d)
                except: pass
    else:
        if os.path.isdir(build_temp):
            shutil.rmtree(build_temp)
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SyncWatch unified builder")
    parser.add_argument("--onefile", action="store_true", help="Build single-file executable")
    parser.add_argument("--clean", action="store_true", help="Clean before build")
    args = parser.parse_args()

    dist_temp, build_temp, output_dir, lua_script, lua_mpv = get_paths(onefile=args.onefile)

    if args.clean:
        clean(dist_temp, build_temp)

    # Also clean previous output
    if not args.onefile and os.path.isdir(output_dir):
        print(f"Removing previous output: {output_dir}")
        shutil.rmtree(output_dir)

    # Ensure clean spec
    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec):
        os.remove(spec)

    build(dist_temp, build_temp, lua_script, lua_mpv, onefile=args.onefile)
    package(dist_temp, output_dir, onefile=args.onefile)
    cleanup(dist_temp, build_temp, onefile=args.onefile)
    print("\nDone! 🎉")
