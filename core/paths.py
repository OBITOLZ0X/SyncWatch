"""
SyncWatch - Centralized application data directory.

All settings, logs, cache, and temp files are stored under one folder:

  Portable (frozen):  <exe_dir>/_data/
  Development:        %APPDATA%/SyncWatch/   (Windows)
                      ~/.config/SyncWatch/   (Linux/macOS)

Layout:
  _data/
  ├── settings.ini        ← QSettings INI file
  ├── logs/
  │   └── syncwatch.log
  └── cache/
      ├── gifs/           ← downloaded GIF cache
      ├── syncwatch_osd_<pid>.txt
      └── sw_logo_<pid>/  ← VLC logo frames
"""
import os
import sys

APP_NAME = "SyncWatch"

_data_dir: str | None = None


def get_data_dir() -> str:
    """Return (and create) the root application data directory."""
    global _data_dir
    if _data_dir is not None:
        return _data_dir

    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        _data_dir = os.path.join(base, "_data")
    else:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get(
                "XDG_CONFIG_HOME",
                os.path.join(os.path.expanduser("~"), ".config"),
            )
        _data_dir = os.path.join(base, APP_NAME)

    os.makedirs(_data_dir, exist_ok=True)
    return _data_dir


def get_settings_path() -> str:
    """Path to the QSettings INI file."""
    return os.path.join(get_data_dir(), "settings.ini")


def get_log_dir() -> str:
    d = os.path.join(get_data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def get_log_path() -> str:
    return os.path.join(get_log_dir(), "syncwatch.log")


def get_cache_dir() -> str:
    d = os.path.join(get_data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def get_gif_cache_dir() -> str:
    d = os.path.join(get_cache_dir(), "gifs")
    os.makedirs(d, exist_ok=True)
    return d


def get_osd_path() -> str:
    return os.path.join(get_cache_dir(), f"syncwatch_osd_{os.getpid()}.txt")


def get_gif_frame_dir() -> str:
    d = os.path.join(get_cache_dir(), f"sw_logo_{os.getpid()}")
    os.makedirs(d, exist_ok=True)
    return d
