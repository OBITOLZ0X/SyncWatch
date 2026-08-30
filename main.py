"""
SyncWatch - Watch Together, Perfectly Synced.
"""
import sys
import os
import logging

# Fix for PyInstaller --windowed mode: sys.stdout/stderr are None,
# which crashes libraries (e.g. pyngrok) that write to them.
if getattr(sys, "frozen", False):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

# Set Windows taskbar app ID so the icon displays correctly
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SyncWatch.SyncWatch.2")

# Add project root to path early so core.paths is importable
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.paths import get_log_path

# Configure logging — file (always in _data/logs/) + console
_log_handlers: list[logging.Handler] = [logging.StreamHandler()]
_log_handlers.append(logging.FileHandler(get_log_path(), encoding="utf-8"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
)

# Silence noisy third-party loggers that leak sensitive URLs and paths
for _name in ("pyngrok", "pyngrok.ngrok", "pyngrok.process", "pyngrok.process.ngrok",
              "websockets", "websockets.server", "websockets.client"):
    logging.getLogger(_name).setLevel(logging.ERROR)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon

from ui.main_window import MainWindow
from ui import styles


def _icon_path() -> str:
    """Resolve the application icon path for both dev and frozen builds."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "SyncWatch.ico")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SyncWatch")
    app.setOrganizationName("SyncWatch")

    # Prevent app from quitting when room window closes — MainWindow handles exit
    app.setQuitOnLastWindowClosed(False)

    # Set application icon (taskbar + window title)
    icon_file = _icon_path()
    if os.path.isfile(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Apply theme stylesheet
    app.setStyleSheet(styles.get_style())

    # Open main window directly — no splash screen
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    # Support --version and --help without launching GUI (for installers & CLI)
    if "--version" in sys.argv or "-v" in sys.argv:
        try:
            from core.__version__ import __version__
        except ImportError:
            __version__ = "2.0.0"
        print(f"SyncWatch {__version__}")
        sys.exit(0)
    if "--help" in sys.argv or "-h" in sys.argv:
        print("SyncWatch — Watch Together, Perfectly Synced.")
        print("")
        print("Usage:  SyncWatch [options]")
        print("        python main.py [options]")
        print("")
        print("Options:")
        print("  --version, -v   Show version and exit")
        print("  --help, -h      Show this help and exit")
        sys.exit(0)
    main()