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

# Guard against running a Windows executable build on Linux directly.
if getattr(sys, "frozen", False) and sys.platform != "win32":
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    sys.stderr.write(
        "ERROR: This executable was built for Windows. "
        "Use a Linux build or run it through Wine/Proton instead.\n"
    )
    sys.exit(1)

from core.paths import get_log_path

# Configure logging — file (always in _data/logs/) + console
_log_handlers: list[logging.Handler] = [logging.StreamHandler()]
_log_handlers.append(logging.FileHandler(get_log_path(), encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
)

# Silence noisy third-party loggers that leak sensitive URLs and paths
for _name in ("pyngrok", "pyngrok.ngrok", "pyngrok.process", "pyngrok.process.ngrok",
              "websockets", "websockets.server", "websockets.client"):
    logging.getLogger(_name).setLevel(logging.ERROR)

from PySide6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import (
    QFont, QIcon, QPainter, QPen, QColor, QLinearGradient, QRadialGradient,
    QBrush, QPainterPath,
)

from ui.main_window import MainWindow
from ui import styles


# ── Splash screen ────────────────────────────────────────

_SPLASH_W, _SPLASH_H = 460, 320


class SplashWindow(QWidget):
    """Fully custom-painted splash screen — no child widgets, no style leaks."""

    def __init__(self, on_finished):
        super().__init__()
        self._on_finished = on_finished
        self.setFixedSize(_SPLASH_W, _SPLASH_H)
        self.setWindowTitle("SyncWatch")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Override any inherited stylesheet so nothing leaks into painting
        self.setStyleSheet("")

        # Center on screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width() - _SPLASH_W) // 2,
            screen.y() + (screen.height() - _SPLASH_H) // 2,
        )

        # Spinner animation
        self._angle = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._spin_tick)
        self._spin_timer.start(20)

        # Progress bar animation (0.0 → 1.0)
        self._progress = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._progress_tick)
        self._progress_timer.start(30)

        # Opacity for fade-out
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        # Auto-close after 2.2 seconds
        QTimer.singleShot(2200, self._fade_out)

    def _spin_tick(self):
        self._angle = (self._angle - 8) % 360
        self.update()

    def _progress_tick(self):
        self._progress = min(1.0, self._progress + 0.015)
        self.update()
        if self._progress >= 1.0:
            self._progress_timer.stop()

    # ── Painting ──────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        W, H = _SPLASH_W, _SPLASH_H
        radius = 24.0
        margin = 8  # shadow space

        # ── Drop shadow (soft dark glow) ──
        for i in range(4):
            shadow_color = QColor(0, 0, 0, 18 - i * 4)
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(
                QRectF(margin - i, margin - i, W - 2 * margin + 2 * i, H - 2 * margin + 2 * i),
                radius + i, radius + i,
            )
            p.fillPath(shadow_path, shadow_color)

        # ── Card background with gradient ──
        card = QRectF(margin, margin, W - 2 * margin, H - 2 * margin)
        bg_grad = QLinearGradient(card.topLeft(), card.bottomRight())
        bg_grad.setColorAt(0.0, QColor(styles.BG_SURFACE))
        bg_grad.setColorAt(1.0, QColor(styles.BG_DARK))
        card_path = QPainterPath()
        card_path.addRoundedRect(card, radius, radius)
        p.fillPath(card_path, QBrush(bg_grad))

        # ── Subtle border ──
        p.setPen(QPen(QColor(styles.BORDER), 1.2))
        p.drawRoundedRect(card, radius, radius)

        # ── Accent glow blob at top-center ──
        glow_cx = W / 2
        glow_cy = margin + 50
        glow_r = 120.0
        glow = QRadialGradient(glow_cx, glow_cy, glow_r)
        accent = QColor(styles.ACCENT)
        accent.setAlpha(28)
        glow.setColorAt(0.0, accent)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillPath(card_path, QBrush(glow))

        # ── Title "SyncWatch" ──
        title_font = QFont("Segoe UI", 34, QFont.ExtraBold)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(title_font)
        p.setPen(QColor(styles.ACCENT))
        title_rect = QRectF(0, margin + 36, W, 48)
        p.drawText(title_rect, Qt.AlignCenter, "SyncWatch")

        # ── Subtitle ──
        sub_font = QFont("Segoe UI", 11)
        p.setFont(sub_font)
        p.setPen(QColor(styles.TEXT_DIM))
        sub_rect = QRectF(0, margin + 86, W, 22)
        p.drawText(sub_rect, Qt.AlignCenter, "Watch Together, Perfectly Synced")

        # ── Spinning arc ──
        spinner_size = 44
        sx = (W - spinner_size) / 2
        sy = margin + 126
        spinner_rect = QRectF(sx + 5, sy + 5, spinner_size - 10, spinner_size - 10)
        pen = QPen(QColor(styles.ACCENT), 3.5, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(spinner_rect, int(self._angle * 16), 270 * 16)
        # Dim track
        track_pen = QPen(QColor(styles.BORDER), 1.5)
        p.setPen(track_pen)
        p.drawEllipse(spinner_rect)

        # ── Progress bar ──
        bar_w = 220
        bar_h = 4
        bar_x = (W - bar_w) / 2
        bar_y = margin + 192
        bar_radius = 2.0

        # Track
        track_rect = QRectF(bar_x, bar_y, bar_w, bar_h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(styles.BG_ELEVATED))
        p.drawRoundedRect(track_rect, bar_radius, bar_radius)

        # Fill
        fill_w = bar_w * self._progress
        if fill_w > 0:
            fill_grad = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
            fill_grad.setColorAt(0.0, QColor(styles.ACCENT))
            acc_hover = QColor(styles.ACCENT_HOVER)
            fill_grad.setColorAt(1.0, acc_hover)
            fill_rect = QRectF(bar_x, bar_y, fill_w, bar_h)
            p.setBrush(QBrush(fill_grad))
            p.drawRoundedRect(fill_rect, bar_radius, bar_radius)

        # ── "Loading…" text ──
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(styles.TEXT_MUTED))
        load_rect = QRectF(0, margin + 208, W, 18)
        p.drawText(load_rect, Qt.AlignCenter, "Loading\u2026")

        # ── Version ──
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(styles.TEXT_MUTED))
        ver_rect = QRectF(0, H - margin - 28, W, 16)
        p.drawText(ver_rect, Qt.AlignCenter, "v2.0")

        p.end()

    # ── Fade-out & finish ─────────────────────────────────

    def _fade_out(self):
        self._spin_timer.stop()
        self._progress_timer.stop()
        self._progress = 1.0
        self.update()
        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setDuration(450)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self._done)
        self._anim.start()

    def _done(self):
        self.close()
        self._on_finished()


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

    # Set application icon (taskbar + window title)
    icon_file = _icon_path()
    if os.path.isfile(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Apply theme stylesheet to the splash
    app.setStyleSheet(styles.get_style())

    # Keep references alive
    state = {}

    def _show_main():
        window = MainWindow()
        window.show()
        state["window"] = window  # prevent GC

    splash = SplashWindow(on_finished=_show_main)
    splash.show()
    state["splash"] = splash

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
