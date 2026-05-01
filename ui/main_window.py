"""
SyncWatch - Main window with tabbed Host / Join / Settings panels.

Uses QSettings for persistent storage instead of a JSON file.
Supports creating rooms on external servers only (no self-hosting with ngrok).
"""
import logging
from threading import Thread

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QFileDialog, QMessageBox, QStackedWidget,
    QFrame, QSizePolicy, QDialog, QApplication,
    QScrollArea, QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, QTimer, QSettings, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QFont, QPainter, QPen, QColor, QIcon, QPixmap, QPainterPath

from . import styles
from .room_window import RoomWindow
from core.client import SyncClient
from core.vlc_controller import VLCController
from core.token_utils import decode_token, encode_server_token
from core.paths import get_settings_path
from core.servers_manager import ServersManager

log = logging.getLogger(__name__)


# ── Loading overlay components ────────────────────────────

class _SpinnerWidget(QWidget):
    """Animated spinning arc."""

    def __init__(self, parent=None, size=52):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(25)

    def _tick(self):
        self._angle = (self._angle - 10) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(styles.ACCENT), 4, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        r = self.rect().adjusted(8, 8, -8, -8)
        p.drawArc(r, self._angle * 16, 270 * 16)
        p.end()


# ── Scan progress widget (shown inline inside server list) ───

class ScanProgressWidget(QFrame):
    """Inline widget showing spinner and real-time progress during server scan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scanProgressWidget")
        self.setStyleSheet(f"""
            QFrame#scanProgressWidget {{
                background-color: {styles.BG_OVERLAY};
                border: 1px solid {styles.BORDER};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; }}
        """)

        inner = QVBoxLayout(self)
        inner.setAlignment(Qt.AlignCenter)
        inner.setSpacing(12)
        inner.setContentsMargins(24, 24, 24, 24)

        self._spinner = _SpinnerWidget(self, size=36)
        inner.addWidget(self._spinner, alignment=Qt.AlignCenter)

        self._title = QLabel("Scanning servers\u2026")
        self._title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self._title.setStyleSheet(f"color: {styles.TEXT};")
        self._title.setAlignment(Qt.AlignCenter)
        inner.addWidget(self._title)

        # Progress bar
        self._progress_frame = QFrame()
        self._progress_frame.setFixedHeight(5)
        self._progress_frame.setStyleSheet(f"""
            background-color: {styles.BG_SURFACE};
            border-radius: 3px;
        """)
        pf_lay = QVBoxLayout(self._progress_frame)
        pf_lay.setContentsMargins(0, 0, 0, 0)
        self._progress_bar = QFrame()
        self._progress_bar.setFixedHeight(5)
        self._progress_bar.setStyleSheet(f"""
            background-color: {styles.ACCENT};
            border-radius: 3px;
        """)
        self._progress_bar.setFixedWidth(0)
        pf_lay.addWidget(self._progress_bar)
        inner.addWidget(self._progress_frame)

        self._status = QLabel("Preparing\u2026")
        self._status.setFont(QFont("Segoe UI", 10))
        self._status.setStyleSheet(f"color: {styles.TEXT_DIM};")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        inner.addWidget(self._status)

    def update_progress(self, current: int, total: int, srv: dict, status_msg: str):
        """Update with latest scan progress."""
        bar_width = int(self._progress_frame.width() * (current / total)) if total > 0 and self._progress_frame.width() > 0 else 0
        self._progress_bar.setFixedWidth(max(bar_width, 0))
        self._title.setText(f"Scanning server {current}/{total}")
        self._status.setText(status_msg)

    def reset_progress(self):
        self._progress_bar.setFixedWidth(0)
        self._title.setText("Scanning servers\u2026")
        self._status.setText("Preparing\u2026")

    def refresh_styles(self):
        """Re-apply theme styles after theme change."""
        self.setStyleSheet(f"""
            QFrame#scanProgressWidget {{
                background-color: {styles.BG_OVERLAY};
                border: 1px solid {styles.BORDER};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; }}
        """)
        self._title.setStyleSheet(f"color: {styles.TEXT};")
        self._progress_frame.setStyleSheet(f"""
            background-color: {styles.BG_SURFACE};
            border-radius: 3px;
        """)
        self._progress_bar.setStyleSheet(f"""
            background-color: {styles.ACCENT};
            border-radius: 3px;
        """)
        self._status.setStyleSheet(f"color: {styles.TEXT_DIM};")


class LoadingDialog(QDialog):
    """Modal loading overlay with spinner and status text (for room validation)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(420, 210)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._frame = QFrame()
        self._frame.setObjectName("loadingFrame")
        self._frame.setStyleSheet(f"""
            QFrame#loadingFrame {{
                background-color: {styles.BG_SURFACE};
                border: 2px solid {styles.BORDER};
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; }}
        """)
        lay.addWidget(self._frame)

        inner = QVBoxLayout(self._frame)
        inner.setAlignment(Qt.AlignCenter)
        inner.setSpacing(14)
        inner.setContentsMargins(32, 28, 32, 28)

        self._spinner = _SpinnerWidget(self._frame)
        inner.addWidget(self._spinner, alignment=Qt.AlignCenter)

        self._title = QLabel("Please wait\u2026")
        self._title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._title.setStyleSheet(f"color: {styles.TEXT};")
        self._title.setAlignment(Qt.AlignCenter)
        inner.addWidget(self._title)

        self._status = QLabel("")
        self._status.setFont(QFont("Segoe UI", 11))
        self._status.setStyleSheet(f"color: {styles.TEXT_DIM};")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        inner.addWidget(self._status)

    def set_title(self, text: str):
        self._title.setText(text)

    def set_status(self, text: str):
        self._status.setText(text)

    def refresh_styles(self):
        """Re-apply theme styles after theme change."""
        self._frame.setStyleSheet(f"""
            QFrame#loadingFrame {{
                background-color: {styles.BG_SURFACE};
                border: 2px solid {styles.BORDER};
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; }}
        """)
        self._title.setStyleSheet(f"color: {styles.TEXT};")
        self._status.setStyleSheet(f"color: {styles.TEXT_DIM};")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget():
            pr = self.parentWidget().geometry()
            self.move(
                pr.x() + (pr.width() - self.width()) // 2,
                pr.y() + (pr.height() - self.height()) // 2,
            )


# ── Server list item widget (modern card) ─────────────────

class ServerCard(QFrame):
    """A single server card shown in the server list."""

    selected = Signal(dict)

    def __init__(self, server_data: dict, parent=None):
        super().__init__(parent)
        self._srv = server_data
        self._selected = False
        self.setObjectName("serverCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(68)

        # Determine status display
        ping_ms = server_data.get("ping_ms", -1)
        rooms = server_data.get("rooms")
        status_str = server_data.get("status", "unknown")
        is_online = status_str == "online" and isinstance(ping_ms, (int, float)) and ping_ms >= 0

        # IP display
        host_ip = server_data.get("host", "")
        url = server_data.get("url", "")
        ip_parts = host_ip.split(".")
        if len(ip_parts) == 4 and all(p.isdigit() for p in ip_parts):
            ip_text = f"{ip_parts[0]}.{ip_parts[1]}.***.***"
        elif host_ip:
            ip_text = host_ip
        else:
            ip_text = url.split("://")[-1].split("/")[0] if url else "?"

        port = server_data.get("port", 8765)
        country_code = server_data.get("country_code", "??")

        # Layout
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)

        # Status indicator dot — NEVER changes after creation
        self._dot = QFrame()
        self._dot.setFixedSize(12, 12)
        self._dot.setStyleSheet(f"""
            background-color: {styles.GREEN if is_online else styles.RED};
            border-radius: 6px;
        """)
        lay.addWidget(self._dot)

        # IP + ping area
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        self._ip_label = QLabel(f"{ip_text}:{port}")
        self._ip_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self._ip_label.setStyleSheet(f"color: {styles.TEXT}; background: transparent;")
        info_col.addWidget(self._ip_label)

        # Second row: country + ping
        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)

        self._country_label = QLabel(f"{country_code}")
        self._country_label.setFont(QFont("Segoe UI", 11))
        self._country_label.setStyleSheet(f"color: {styles.TEXT_DIM}; background: transparent;")
        sub_row.addWidget(self._country_label)

        self._ping_label = None
        if is_online:
            self._ping_label = QLabel(f"{ping_ms}ms")
            self._ping_label.setFont(QFont("Segoe UI", 11))
            self._ping_label.setStyleSheet(f"color: {styles.TEXT_DIM}; background: transparent;")
            sub_row.addWidget(self._ping_label)
            sub_row.addStretch()

        info_col.addLayout(sub_row)
        lay.addLayout(info_col, stretch=1)

        # Right side: rooms badge
        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_col.setSpacing(2)

        self._rooms_badge = None
        self._badge_text = None
        self._rooms_label = None
        self._online_label = None
        self._offline_label = None

        if is_online and isinstance(rooms, int) and rooms >= 0:
            self._rooms_badge = QFrame()
            self._rooms_badge.setFixedSize(40, 28)
            self._rooms_badge.setStyleSheet(f"""
                background-color: {styles.ACCENT};
                border-radius: 14px;
            """)
            r_lay = QVBoxLayout(self._rooms_badge)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setAlignment(Qt.AlignCenter)
            self._badge_text = QLabel(str(rooms))
            self._badge_text.setFont(QFont("Segoe UI", 11, QFont.Bold))
            self._badge_text.setStyleSheet(f"color: {styles.BTN_TEXT}; background: transparent;")
            self._badge_text.setAlignment(Qt.AlignCenter)
            r_lay.addWidget(self._badge_text)
            right_col.addWidget(self._rooms_badge, alignment=Qt.AlignRight)

            self._rooms_label = QLabel("rooms")
            self._rooms_label.setFont(QFont("Segoe UI", 9))
            self._rooms_label.setStyleSheet(f"color: {styles.TEXT_MUTED}; background: transparent;")
            self._rooms_label.setAlignment(Qt.AlignCenter)
            right_col.addWidget(self._rooms_label, alignment=Qt.AlignRight)
        elif is_online:
            self._online_label = QLabel("Online")
            self._online_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
            self._online_label.setStyleSheet(f"color: {styles.GREEN}; background: transparent;")
            self._online_label.setAlignment(Qt.AlignRight)
            right_col.addWidget(self._online_label)
        else:
            self._offline_label = QLabel("Offline")
            self._offline_label.setFont(QFont("Segoe UI", 11))
            self._offline_label.setStyleSheet(f"color: {styles.TEXT_MUTED}; background: transparent;")
            self._offline_label.setAlignment(Qt.AlignRight)
            right_col.addWidget(self._offline_label)

        lay.addLayout(right_col)

        # Apply default style (not selected, not hovered)
        self._refresh_style()

    def refresh_theme(self):
        """Re-apply all inline styles with current theme colors."""
        self._refresh_style()
        # Status dot
        is_online = isinstance(self._srv.get("ping_ms", -1), (int, float)) and self._srv.get("ping_ms", -1) >= 0
        self._dot.setStyleSheet(f"""
            background-color: {styles.GREEN if is_online else styles.RED};
            border-radius: 6px;
        """)
        # IP label
        self._ip_label.setStyleSheet(f"color: {styles.TEXT}; background: transparent;")
        # Country label
        self._country_label.setStyleSheet(f"color: {styles.TEXT_DIM}; background: transparent;")
        # Ping label
        if self._ping_label:
            self._ping_label.setStyleSheet(f"color: {styles.TEXT_DIM}; background: transparent;")
        # Rooms badge
        if self._rooms_badge:
            self._rooms_badge.setStyleSheet(f"""
                background-color: {styles.ACCENT};
                border-radius: 14px;
            """)
        if self._badge_text:
            self._badge_text.setStyleSheet(f"color: {styles.BTN_TEXT}; background: transparent;")
        if self._rooms_label:
            self._rooms_label.setStyleSheet(f"color: {styles.TEXT_MUTED}; background: transparent;")
        # Online label
        if self._online_label:
            self._online_label.setStyleSheet(f"color: {styles.GREEN}; background: transparent;")
        # Offline label
        if self._offline_label:
            self._offline_label.setStyleSheet(f"color: {styles.TEXT_MUTED}; background: transparent;")

    def _refresh_style(self):
        """Apply current state (selected/hovered) to the card stylesheet.
        
        The dot (self._dot) is NEVER touched here — it stays green/red
        from creation.
        """
        if self._selected:
            self.setStyleSheet(f"""
                QFrame#serverCard {{
                    background-color: {styles.BG_SELECTED};
                    border: 2px solid {styles.ACCENT};
                    border-radius: 10px;
                }}
                QFrame#serverCard:hover {{
                    background-color: {styles.BG_SELECTED};
                    border-color: {styles.ACCENT};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#serverCard {{
                    background-color: {styles.BG_OVERLAY};
                    border: 1px solid {styles.BORDER};
                    border-radius: 10px;
                }}
                QFrame#serverCard:hover {{
                    background-color: {styles.BG_HOVER};
                    border-color: {styles.ACCENT};
                }}
            """)

    def set_selected(self, state: bool):
        """Mark card as selected (highlighted) or not, without touching the dot."""
        self._selected = state
        self._refresh_style()

    def enterEvent(self, event):
        self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._refresh_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        self.selected.emit(self._srv)
        super().mouseReleaseEvent(event)


class MainWindow(QWidget):
    """Start screen — Host (on servers), Join, or configure Settings."""

    _sig_servers_ready = Signal(list)  # servers list from background thread
    _sig_scan_progress = Signal(int, int, dict, str)  # current, total, srv, msg

    def __init__(self, prefetched_servers=None, prefetch_done=True,
                 prefetch_current=0, prefetch_total=0, prefetch_msg=""):
        super().__init__()
        self.setWindowTitle("SyncWatch")
        self.setStyleSheet(styles.get_style())
        self.setMinimumSize(520, 600)
        self.resize(650, 840)

        # Center on screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width() - 650) // 2,
            screen.y() + (screen.height() - 840) // 2,
        )

        self._qsettings = QSettings(get_settings_path(), QSettings.IniFormat)
        self._room_window = None
        self._servers_manager = ServersManager()
        self._selected_server: dict = {}
        self._all_servers: list = []
        self._scanning = False

        # Validation state
        self._loading_dialog = None
        self._scan_progress_widget = None
        self._val_client = None
        self._val_params = {}
        self._val_handled = False
        self._val_timer = None
        self._room_closing_in_progress = False  # Prevents double-show between about_to_close and closed
        self._sig_servers_ready.connect(self._on_servers_fetched)
        self._sig_scan_progress.connect(self._on_scan_progress)

        self._build_ui()
        self._load_settings()

        # ── Apply pre-fetched data (from splash) ──────────
        self._prefetched_servers = prefetched_servers
        self._prefetch_done = prefetch_done
        self._prefetch_current = prefetch_current
        self._prefetch_total = prefetch_total
        self._prefetch_msg = prefetch_msg

        if prefetched_servers is not None:
            if prefetch_done:
                # Pre-fetch completed — populate the list immediately
                self._on_servers_fetched(prefetched_servers)
            else:
                # Pre-fetch still in progress — show scanning state
                self._scanning = True
                self._server_info_label.setText("Scanning servers\u2026")
                self._scan_progress_widget.reset_progress()
                self._scan_progress_widget.update_progress(
                    prefetch_current, prefetch_total, {},
                    prefetch_msg or "Initial scan from splash\u2026"
                )
                self._server_list_stack.setCurrentIndex(2)

                # Poll for pre-fetch completion (background thread can't emit signals)
                self._prefetch_poll_timer = QTimer(self)
                self._prefetch_poll_timer.timeout.connect(self._check_prefetch_done)
                self._prefetch_poll_timer.start(300)

    def _check_prefetch_done(self):
        """Periodic poll: check if the pre-fetch background thread finished."""
        if not getattr(self, '_prefetch_poll_timer', None):
            return

        try:
            import main as _main_mod
        except ImportError:
            self._prefetch_poll_timer.stop()
            return

        state = getattr(_main_mod, '_prefetch_state', None)
        if state is None:
            self._prefetch_poll_timer.stop()
            self._prefetch_poll_timer = None
            self._scanning = False
            self._refresh_server_list(force=True)
            return

        if state.get("prefetch_done", False):
            self._prefetch_poll_timer.stop()
            self._prefetch_poll_timer = None
            servers = state.get("prefetch_servers", [])
            if servers:
                self._on_servers_fetched(servers)
            else:
                self._scanning = False
                self._refresh_server_list(force=True)
        else:
            current = state.get("prefetch_current", 0)
            total = state.get("prefetch_total", 0)
            msg = state.get("prefetch_msg", "")
            if total > 0 and self._scan_progress_widget:
                try:
                    self._scan_progress_widget.update_progress(
                        current, total, {}, msg
                    )
                except RuntimeError:
                    pass

    # ──────────────────────────────────────────────────────
    #  UI
    # ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header ──
        header = QFrame()
        header.setObjectName("topBar")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(32, 22, 32, 12)
        h_lay.setSpacing(4)

        title = QLabel("SyncWatch")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        h_lay.addWidget(title)

        sub = QLabel("Watch Together, Perfectly Synced")
        sub.setObjectName("subtitleLabel")
        sub.setAlignment(Qt.AlignCenter)
        h_lay.addWidget(sub)

        root.addWidget(header)

        # ── Tab bar ──
        tab_bar = QFrame()
        tab_bar.setObjectName("topBar")
        tab_bar.setFixedHeight(44)
        tb_lay = QHBoxLayout(tab_bar)
        tb_lay.setContentsMargins(24, 0, 24, 0)
        tb_lay.setSpacing(0)

        self._nav_btns = []
        for label in ("Host", "Join", "Settings"):
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(QFont("Segoe UI", 11))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            tb_lay.addWidget(btn)
            self._nav_btns.append(btn)

        self._nav_btns[0].clicked.connect(lambda: self._switch(0))
        self._nav_btns[1].clicked.connect(lambda: self._switch(1))
        self._nav_btns[2].clicked.connect(lambda: self._switch(2))

        root.addWidget(tab_bar)

        # ── Stacked panels ──
        self._stack = QStackedWidget()
        self._stack.addWidget(self._panel_host())
        self._stack.addWidget(self._panel_join())
        self._stack.addWidget(self._panel_settings())
        root.addWidget(self._stack, stretch=1)

        self._switch(0)

    def _switch(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setObjectName("navBtnActive" if i == idx else "navBtn")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Refresh server list when switching to host tab (only if empty)
        if idx == 0 and not self._all_servers:
            # If pre-fetch is still pending (poll timer active), don't start a
            # redundant scan — the poll timer will populate the list when done.
            if not getattr(self, '_prefetch_poll_timer', None) or not self._prefetch_poll_timer.isActive():
                self._refresh_server_list()

    # ── Helper: labelled input ────────────────────────────

    @staticmethod
    def _field(label_text: str, widget, layout: QVBoxLayout):
        lbl = QLabel(label_text)
        lbl.setObjectName("fieldLabel")
        layout.addWidget(lbl)
        layout.addWidget(widget)
        layout.addSpacing(4)

    # ── Host Panel ────────────────────────────────────────

    def _panel_host(self) -> QWidget:
        """Host a room on an external server (Server mode only)."""
        p = QWidget()
        outer = QVBoxLayout(p)
        outer.setContentsMargins(28, 18, 28, 18)
        outer.setSpacing(0)

        # ── Server Card ──
        self._server_card = QFrame()
        self._server_card.setObjectName("card")
        sv_lay = QVBoxLayout(self._server_card)
        sv_lay.setContentsMargins(24, 16, 24, 16)
        sv_lay.setSpacing(4)

        sv_sec = QLabel("Create Room")
        sv_sec.setObjectName("sectionLabel")
        sv_lay.addWidget(sv_sec)
        sv_lay.addSpacing(8)

        # Search + refresh row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self._server_search = QLineEdit()
        self._server_search.setPlaceholderText("Search servers\u2026")
        self._server_search.textChanged.connect(self._filter_server_list)
        search_row.addWidget(self._server_search, stretch=1)

        self._server_refresh_btn = QPushButton()
        self._server_refresh_btn.setObjectName("refreshBtn")
        self._server_refresh_btn.setFixedSize(36, 36)
        # Draw a refresh icon with QPainter
        icon = self._make_refresh_icon(20, styles.BTN_TEXT)
        self._server_refresh_btn.setIcon(icon)
        self._server_refresh_btn.setIconSize(QSize(20, 20))
        self._server_refresh_btn.setToolTip("Refresh server list")
        self._server_refresh_btn.setCursor(Qt.PointingHandCursor)
        self._server_refresh_btn.setStyleSheet(f"""
            QPushButton#refreshBtn {{
                background-color: {styles.ACCENT};
                border: none;
                border-radius: 8px;
            }}
            QPushButton#refreshBtn:hover {{
                background-color: {styles.ACCENT_HOVER};
            }}
            QPushButton#refreshBtn:pressed {{
                background-color: {styles.BG_ELEVATED};
            }}
        """)
        self._server_refresh_btn.clicked.connect(lambda: self._refresh_server_list(force=True))
        search_row.addWidget(self._server_refresh_btn)

        sv_lay.addLayout(search_row)

        # Server list — QStackedWidget inside a proper bordered container
        self._server_list_container = QFrame()
        self._server_list_container.setObjectName("serverListContainer")
        self._server_list_container.setStyleSheet(f"""
            QFrame#serverListContainer {{
                background-color: {styles.BG_BASE};
                border: 2px solid {styles.BORDER};
                border-radius: 14px;
                padding: 4px;
            }}
        """)
        slc_lay = QVBoxLayout(self._server_list_container)
        slc_lay.setContentsMargins(6, 6, 6, 6)
        slc_lay.setSpacing(0)

        self._server_list_stack = QStackedWidget()
        self._server_list_stack.setMinimumHeight(170)

        # Page 0: loading spinner
        spinner_page = QWidget()
        sp_lay = QVBoxLayout(spinner_page)
        sp_lay.setAlignment(Qt.AlignCenter)
        sp_lay.setSpacing(12)
        sp_lay.setContentsMargins(0, 0, 0, 0)
        self._server_list_spinner = _SpinnerWidget(spinner_page, size=36)
        sp_lay.addWidget(self._server_list_spinner, alignment=Qt.AlignCenter)
        sp_lbl = QLabel("Fetching servers\u2026")
        sp_lbl.setAlignment(Qt.AlignCenter)
        sp_lbl.setFont(QFont("Segoe UI", 11))
        sp_lbl.setStyleSheet(f"color: {styles.TEXT_DIM}; background: transparent;")
        sp_lay.addWidget(sp_lbl, alignment=Qt.AlignCenter)
        self._server_list_stack.addWidget(spinner_page)

        # Page 1: actual list (scrollable cards)
        list_page = QFrame()
        list_page.setObjectName("serverListPage")
        list_page.setStyleSheet("QFrame#serverListPage { background: transparent; border: none; }")
        lp_lay = QVBoxLayout(list_page)
        lp_lay.setContentsMargins(0, 0, 0, 0)
        lp_lay.setSpacing(0)

        self._server_list_scroll = QScrollArea()
        self._server_list_scroll.setWidgetResizable(True)
        self._server_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._server_list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._server_list_scroll.setFrameShape(QFrame.NoFrame)
        self._server_list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._server_list_content = QWidget()
        self._server_list_content.setStyleSheet("background: transparent;")
        self._server_list_layout = QVBoxLayout(self._server_list_content)
        self._server_list_layout.setContentsMargins(0, 0, 0, 0)
        self._server_list_layout.setSpacing(10)
        self._server_list_layout.addStretch()

        self._server_list_scroll.setWidget(self._server_list_content)
        lp_lay.addWidget(self._server_list_scroll)

        self._server_list_stack.addWidget(list_page)

        # Page 2: scan progress inline (shown during scanning)
        self._scan_progress_widget = ScanProgressWidget()
        self._server_list_stack.addWidget(self._scan_progress_widget)

        slc_lay.addWidget(self._server_list_stack)
        self._server_list_stack.setCurrentIndex(1)
        sv_lay.addWidget(self._server_list_container)

        # Selected server info (smaller font)
        self._server_info_label = QLabel("Select a server from the list above")
        self._server_info_label.setObjectName("infoLabel")
        self._server_info_label.setWordWrap(True)
        font = self._server_info_label.font()
        font.setPointSize(9)
        self._server_info_label.setFont(font)
        sv_lay.addWidget(self._server_info_label)

        sv_lay.addSpacing(4)

        # Server room form — username + max users in one row
        srv_row0 = QHBoxLayout()
        srv_row0.setSpacing(12)

        sc_user = QVBoxLayout()
        self.h_user_server = QLineEdit()
        self.h_user_server.setPlaceholderText("Display name")
        self._field("USERNAME", self.h_user_server, sc_user)
        srv_row0.addLayout(sc_user)

        sc_max = QVBoxLayout()
        self.h_max_server = QSpinBox()
        self.h_max_server.setRange(2, 200)
        self.h_max_server.setValue(20)
        self.h_max_server.setButtonSymbols(QSpinBox.UpDownArrows)
        self._field("MAX USERS", self.h_max_server, sc_max)
        srv_row0.addLayout(sc_max)

        sv_lay.addLayout(srv_row0)

        srv_row = QHBoxLayout()
        srv_row.setSpacing(12)
        sc1 = QVBoxLayout()
        self.h_room_server = QLineEdit()
        self.h_room_server.setPlaceholderText("e.g. Movie Night")
        self._field("ROOM NAME", self.h_room_server, sc1)
        srv_row.addLayout(sc1)

        sc2 = QVBoxLayout()
        self.h_pass_server = QLineEdit()
        self.h_pass_server.setPlaceholderText("Optional")
        self.h_pass_server.setEchoMode(QLineEdit.Password)
        self._field("PASSWORD", self.h_pass_server, sc2)
        srv_row.addLayout(sc2)
        sv_lay.addLayout(srv_row)

        # Share info + features toggles
        srv_mr = QHBoxLayout()
        srv_mr.setSpacing(10)

        srv_f4 = QFrame()
        srv_f4.setObjectName("miniCard")
        srv_c4 = QVBoxLayout(srv_f4)
        srv_c4.setContentsMargins(8, 6, 8, 6)
        srv_c4.setSpacing(4)
        srv_lbl4 = QLabel("SHARE ROOM INFO")
        srv_lbl4.setObjectName("fieldLabel")
        srv_lbl4.setAlignment(Qt.AlignCenter)
        self._h_srv_share_on = True
        self.h_srv_share_info_btn = QPushButton("Enabled")
        self.h_srv_share_info_btn.setObjectName("toggleOn")
        self.h_srv_share_info_btn.setCursor(Qt.PointingHandCursor)
        self.h_srv_share_info_btn.setFixedHeight(32)
        self.h_srv_share_info_btn.clicked.connect(self._toggle_srv_share_info)
        srv_c4.addWidget(srv_lbl4)
        srv_c4.addWidget(self.h_srv_share_info_btn)
        srv_mr.addWidget(srv_f4, stretch=1)

        srv_f5 = QFrame()
        srv_f5.setObjectName("miniCard")
        srv_c5 = QVBoxLayout(srv_f5)
        srv_c5.setContentsMargins(8, 6, 8, 6)
        srv_c5.setSpacing(4)
        srv_lbl5 = QLabel("USER FEATURES")
        srv_lbl5.setObjectName("fieldLabel")
        srv_lbl5.setAlignment(Qt.AlignCenter)
        self._h_srv_features_on = False
        self.h_srv_features_btn = QPushButton("Disabled")
        self.h_srv_features_btn.setObjectName("toggleOff")
        self.h_srv_features_btn.setCursor(Qt.PointingHandCursor)
        self.h_srv_features_btn.setFixedHeight(32)
        self.h_srv_features_btn.clicked.connect(self._toggle_srv_features)
        srv_c5.addWidget(srv_lbl5)
        srv_c5.addWidget(self.h_srv_features_btn)
        srv_mr.addWidget(srv_f5, stretch=1)

        sv_lay.addLayout(srv_mr)
        sv_lay.addSpacing(8)

        self.btn_host_server = QPushButton("Create Room")
        self.btn_host_server.setObjectName("accentBtn")
        self.btn_host_server.setMinimumHeight(46)
        self.btn_host_server.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.btn_host_server.setCursor(Qt.PointingHandCursor)
        self.btn_host_server.clicked.connect(self._on_host_server)
        sv_lay.addWidget(self.btn_host_server)

        outer.addWidget(self._server_card, stretch=1)
        return p

    # ── Server list helpers (modern card-based) ───────────

    def _refresh_server_list(self, force: bool = False):
        """Fetch servers from GitHub, then scan sequentially with inline progress."""
        if self._scanning:
            return  # Already scanning

        self._scanning = True
        self._clear_server_cards()
        self._server_info_label.setText("Scanning servers\u2026")

        # Show the progress widget inside the server list area
        self._scan_progress_widget.reset_progress()
        self._server_list_stack.setCurrentIndex(2)

        def _worker():
            # Step 1: fetch from GitHub (network call)
            servers = self._servers_manager.fetch_servers(force=True)
            if not servers:
                self._sig_servers_ready.emit([])
                return

            # Step 2: sequential scan with progress
            def _progress_cb(current, total, srv, msg):
                self._sig_scan_progress.emit(current, total, srv, msg)

            self._servers_manager.scan_servers_sequential(servers, progress_callback=_progress_cb)
            self._sig_servers_ready.emit(servers)

        t = Thread(target=_worker, daemon=True)
        t.start()

    def _on_scan_progress(self, current: int, total: int, srv: dict, msg: str):
        """Update inline progress widget from background thread."""
        if self._scan_progress_widget and self._server_list_stack.currentIndex() == 2:
            try:
                self._scan_progress_widget.update_progress(current, total, srv, msg)
            except RuntimeError:
                pass

    def _on_servers_fetched(self, servers: list):
        """Populate the server list with modern cards."""
        self._scanning = False
        self._all_servers = list(servers)
        self._server_list_stack.setCurrentIndex(1)

        if not servers:
            err = self._servers_manager.get_last_error()
            self._server_info_label.setText(
                "No servers found. Try refreshing."
                + (f" ({err})" if err else "")
            )
            return

        # Auto-cleanup: if a room is connected, ask the server to remove dead servers
        if self._room_window:
            client = getattr(self._room_window, '_client', None)
            if client and client.is_connected:
                try:
                    client.cleanup_response.disconnect()
                except (RuntimeError, TypeError):
                    pass
                client.cleanup_response.connect(self._on_cleanup_result)
                self._servers_manager.cleanup_offline_servers(client, servers)
                log.info("Auto-cleanup request sent to connected server")

        search_text = self._server_search.text().strip().lower()
        self._rebuild_server_cards(servers, search_text)

    def _rebuild_server_cards(self, servers: list, search_text: str = ""):
        """Rebuild the card list from server data, applying search filter."""
        self._clear_server_cards()

        inserted = 0
        for srv in servers:
            country = srv.get("country", "Unknown")
            country_code = srv.get("country_code", country[:2].upper() if len(country) >= 2 else "??")
            host_ip = srv.get("host", "")
            url = srv.get("url", "")

            # Apply search filter
            if search_text:
                if (search_text not in country.lower()
                        and search_text not in url.lower()
                        and search_text not in host_ip):
                    continue

            card = ServerCard(srv)
            card.selected.connect(self._on_card_selected)
            self._server_list_layout.insertWidget(
                self._server_list_layout.count() - 1, card
            )
            inserted += 1

        # Update info label
        online_count = sum(1 for s in servers if isinstance(s.get("ping_ms"), (int, float)) and s.get("ping_ms", -1) >= 0)
        offline_count = len(servers) - online_count
        if inserted == 0:
            self._server_info_label.setText("No servers match your search.")
        else:
            self._server_info_label.setText(
                f"Found {len(servers)} server{'s' if len(servers) != 1 else ''}"
                f"  \u2022  {online_count} online"
                + (f", {offline_count} offline" if offline_count else "")
            )

    def _clear_server_cards(self):
        """Remove all server cards from the scroll layout."""
        self._selected_server = {}
        lay = self._server_list_layout
        while lay.count() > 1:  # keep the stretch
            item = lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _on_card_selected(self, srv: dict):
        """Handle selection of a server card."""
        self._selected_server = srv
        url = srv.get("url", "")
        country = srv.get("country", "Unknown")
        country_code = srv.get("country_code", "??")
        ping_ms = srv.get("ping_ms", -1)
        rooms = srv.get("rooms")
        host_ip = srv.get("host", "")
        url = srv.get("url", "")
        ip_parts = host_ip.split(".")
        port = srv.get("port", 8765)
        if len(ip_parts) == 4 and all(p.isdigit() for p in ip_parts):
            ip_text = f"{ip_parts[0]}.{ip_parts[1]}.***.***"
        elif host_ip:
            ip_text = host_ip
        else:
            ip_text = url.split("://")[-1].split("/")[0] if url else "?"

        # Update selection highlight on cards
        self._update_card_selection(srv)

    def _update_card_selection(self, selected_srv: dict):
        """Highlight the selected card using set_selected() — dot stays untouched."""
        lay = self._server_list_layout
        selected_url = selected_srv.get("url", "")
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, ServerCard):
                    srv_url = w._srv.get("url", "")
                    w.set_selected(srv_url == selected_url)

    def _filter_server_list(self):
        """Filter the existing server list using the search field (no re-fetch)."""
        search_text = self._server_search.text().strip().lower()
        if self._all_servers:
            self._rebuild_server_cards(self._all_servers, search_text)

    # ── Host mode switching ───────────────────────────────

    # ── Join Panel ────────────────────────────────────────

    def _panel_join(self) -> QWidget:
        p = QWidget()
        outer = QVBoxLayout(p)
        outer.setContentsMargins(28, 18, 28, 18)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(4)

        sec = QLabel("Join a Room")
        sec.setObjectName("sectionLabel")
        lay.addWidget(sec)
        lay.addSpacing(10)

        self.j_url = QLineEdit()
        self.j_url.setPlaceholderText("Paste the room token here")
        self._field("ROOM TOKEN", self.j_url, lay)

        self.j_user = QLineEdit()
        self.j_user.setPlaceholderText("Display name")
        self._field("USERNAME", self.j_user, lay)

        self.j_pass = QLineEdit()
        self.j_pass.setPlaceholderText("If required")
        self.j_pass.setEchoMode(QLineEdit.Password)
        self._field("PASSWORD", self.j_pass, lay)

        lay.addStretch()

        self.btn_join = QPushButton("Join Room")
        self.btn_join.setObjectName("greenBtn")
        self.btn_join.setMinimumHeight(46)
        self.btn_join.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.btn_join.setCursor(Qt.PointingHandCursor)
        self.btn_join.clicked.connect(self._on_join)
        lay.addWidget(self.btn_join)

        outer.addWidget(card)
        return p

    # ── Settings Panel ────────────────────────────────────

    def _panel_settings(self) -> QWidget:
        p = QWidget()
        outer = QVBoxLayout(p)
        outer.setContentsMargins(28, 18, 28, 18)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(4)

        sec = QLabel("Settings")
        sec.setObjectName("sectionLabel")
        lay.addWidget(sec)
        lay.addSpacing(10)

        vlc_row = QHBoxLayout()
        self.s_vlc = QLineEdit()
        self.s_vlc.setPlaceholderText("Auto-detected or browse manually")
        vlc_row.addWidget(self.s_vlc)
        browse = QPushButton("Browse")
        browse.setObjectName("accentBtn")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse_vlc)
        vlc_row.addWidget(browse)
        lbl_vlc = QLabel("VLC PATH")
        lbl_vlc.setObjectName("fieldLabel")
        lay.addWidget(lbl_vlc)
        lay.addLayout(vlc_row)
        lay.addSpacing(12)

        lay.addSpacing(8)
        theme_lbl = QLabel("THEME")
        theme_lbl.setObjectName("fieldLabel")
        lay.addWidget(theme_lbl)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        self.s_theme_dark = QPushButton("\u263E  Dark Mode")
        self.s_theme_dark.setObjectName("accentBtn")
        self.s_theme_dark.setCursor(Qt.PointingHandCursor)
        self.s_theme_dark.setMinimumHeight(38)
        self.s_theme_dark.clicked.connect(lambda: self._set_theme("dark"))
        theme_row.addWidget(self.s_theme_dark)

        self.s_theme_light = QPushButton("\u2600  Light Mode")
        self.s_theme_light.setCursor(Qt.PointingHandCursor)
        self.s_theme_light.setMinimumHeight(38)
        self.s_theme_light.clicked.connect(lambda: self._set_theme("light"))
        theme_row.addWidget(self.s_theme_light)
        lay.addLayout(theme_row)
        lay.addSpacing(4)

        lay.addStretch()

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("accentBtn")
        save_btn.setMinimumHeight(44)
        save_btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        lay.addWidget(save_btn)

        outer.addWidget(card)
        return p

    # ──────────────────────────────────────────────────────
    #  SETTINGS (QSettings)
    # ──────────────────────────────────────────────────────

    def _load_settings(self):
        s = self._qsettings
        self.s_vlc.setText(s.value("vlc_path", ""))
        username = s.value("username", "")
        self.h_user_server.setText(username)
        self.j_user.setText(username)
        # Restore last join token
        self.j_url.setText(s.value("last_join_token", ""))
        saved_theme = s.value("theme", "dark")
        self._set_theme(saved_theme)

    def _save_settings(self):
        s = self._qsettings
        s.setValue("vlc_path", self.s_vlc.text().strip())
        # Get username from whichever field is filled
        username = self.h_user_server.text().strip() or self.j_user.text().strip()
        s.setValue("username", username)
        s.setValue("theme", styles.current_theme())
        # Persist last join token so the field is pre-filled next time
        join_tok = self.j_url.text().strip()
        if join_tok:
            s.setValue("last_join_token", join_tok)

    def _on_save(self):
        self._save_settings()
        QMessageBox.information(self, "Settings", "Settings saved.")

    def _set_theme(self, name: str):
        styles.set_theme(name)
        self.setStyleSheet(styles.get_style())
        self._qsettings.setValue("theme", name)
        if name == "dark":
            self.s_theme_dark.setObjectName("accentBtn")
            self.s_theme_light.setObjectName("")
        else:
            self.s_theme_dark.setObjectName("")
            self.s_theme_light.setObjectName("accentBtn")
        self.s_theme_dark.style().unpolish(self.s_theme_dark)
        self.s_theme_dark.style().polish(self.s_theme_dark)
        self.s_theme_light.style().unpolish(self.s_theme_light)
        self.s_theme_light.style().polish(self.s_theme_light)

        # ── Refresh inline-styled widgets ──
        # Recreate refresh icon with new BTN_TEXT
        icon = self._make_refresh_icon(20, styles.BTN_TEXT)
        self._server_refresh_btn.setIcon(icon)

        # Refresh refresh button stylesheet
        self._server_refresh_btn.setStyleSheet(f"""
            QPushButton#refreshBtn {{
                background-color: {styles.ACCENT};
                border: none;
                border-radius: 8px;
            }}
            QPushButton#refreshBtn:hover {{
                background-color: {styles.ACCENT_HOVER};
            }}
            QPushButton#refreshBtn:pressed {{
                background-color: {styles.BG_ELEVATED};
            }}
        """)

        # Refresh server list container
        self._server_list_container.setStyleSheet(f"""
            QFrame#serverListContainer {{
                background-color: {styles.BG_BASE};
                border: 2px solid {styles.BORDER};
                border-radius: 14px;
                padding: 4px;
            }}
        """)

        # Refresh scan progress widget
        if self._scan_progress_widget:
            self._scan_progress_widget.refresh_styles()

        # Refresh loading dialog if shown
        if self._loading_dialog:
            self._loading_dialog.refresh_styles()

        # Refresh room window if open
        if self._room_window:
            self._room_window.refresh_theme()

        # Refresh all existing server cards
        lay = self._server_list_layout
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, ServerCard):
                    w.refresh_theme()

    def _toggle_srv_share_info(self):
        self._h_srv_share_on = not self._h_srv_share_on
        self._refresh_toggle(self.h_srv_share_info_btn, self._h_srv_share_on)

    def _toggle_srv_features(self):
        self._h_srv_features_on = not self._h_srv_features_on
        self._refresh_toggle(self.h_srv_features_btn, self._h_srv_features_on)

    @staticmethod
    def _refresh_toggle(btn: QPushButton, on: bool):
        btn.setText("Enabled" if on else "Disabled")
        btn.setObjectName("toggleOn" if on else "toggleOff")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _browse_vlc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select VLC Executable", "",
            "Executables (*.exe);;All Files (*)",
        )
        if path:
            self.s_vlc.setText(path)

    # ──────────────────────────────────────────────────────
    #  SERVER HOST ACTION
    # ──────────────────────────────────────────────────────

    def _on_host_server(self):
        username = self.h_user_server.text().strip()
        room = self.h_room_server.text().strip()
        password = self.h_pass_server.text()
        max_users = self.h_max_server.value()
        share_info = self._h_srv_share_on
        features_enabled = self._h_srv_features_on

        if not self._selected_server.get("url"):
            QMessageBox.warning(self, "Missing", "Select a server from the list.")
            return
        if not username:
            QMessageBox.warning(self, "Missing", "Enter a username.")
            return
        if not room:
            QMessageBox.warning(self, "Missing", "Enter a room name.")
            return

        # Force-disconnect any stale client/thread before starting a new connection
        if self._room_window:
            old_client = getattr(self._room_window, '_client', None)
            if old_client:
                old_client.disconnect()
            old_vlc = getattr(self._room_window, '_vlc', None)
            if old_vlc:
                old_vlc.close()
            self._room_window.close()
            self._room_window = None
        if self._val_client:
            self._val_client.disconnect()
            self._val_client = None

        self._save_settings()
        self.btn_host_server.setEnabled(False)

        server_url = self._selected_server["url"]
        server_port = self._selected_server.get("port", 8765)

        # Build the WebSocket URL from server entry
        connect_url = server_url
        if not connect_url.startswith(("ws://", "wss://")):
            if connect_url.startswith("https://"):
                connect_url = "wss://" + connect_url[8:]
            elif connect_url.startswith("http://"):
                connect_url = "ws://" + connect_url[7:]
            else:
                connect_url = "ws://" + connect_url

        self._server_connect_url = connect_url

        # Extract the base server URL (without ws:// prefix) for token generation
        token = encode_server_token(server_url, room, password)

        self._val_params = {
            'username': username, 'room': room,
            'password': password, 'max_users': max_users,
            'is_host': True, 'share_info': share_info,
            'features_enabled': features_enabled,
            'server_url': server_url, 'connect_url': connect_url,
            'is_server_mode': True,
            'room_token': token,
            'public_url': token,
        }
        self._val_handled = False
        self._show_loading("Creating Room on Server", "Connecting to server\u2026")

        self._open_room_validated(
            is_host=True, username=username, room_name=room,
            password=password, public_url=token, connect_url=connect_url,
            share_info=share_info, features_enabled=features_enabled,
            is_server_mode=True, room_token=token,
        )

    # ──────────────────────────────────────────────────────
    #  JOIN ACTION
    # ──────────────────────────────────────────────────────

    def _on_join(self):
        token = self.j_url.text().strip()
        username = self.j_user.text().strip()
        password = self.j_pass.text()

        if not token:
            QMessageBox.warning(self, "Missing", "Enter the room token.")
            return
        if not username:
            QMessageBox.warning(self, "Missing", "Enter a username.")
            return

        # Decode token to URL
        try:
            url = decode_token(token)
        except Exception:
            QMessageBox.warning(self, "Invalid Token", "The room token is invalid or corrupted.")
            return

        # Normalise URL
        if url.startswith("https://"):
            url = "wss://" + url[8:]
        elif url.startswith("http://"):
            url = "ws://" + url[7:]
        elif not url.startswith(("ws://", "wss://")):
            url = "wss://" + url

        # Extract room name from server token URL (NOT password — user MUST type it)
        room_name = ""
        join_url = url
        fallback_url = None
        if "/?" in url:
            base, qs = url.split("/?", 1)
            join_url = base
            params = {}
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
            room_name = params.get("room", "")
            # ⚠ Password is NEVER extracted from token — user must enter it manually

            # Try localhost fallback if same-machine connection (avoid hairpin NAT)
            import re as _re
            port_match = _re.search(r':(\d+)', join_url)
            port = int(port_match.group(1)) if port_match else 8765
            fallback_url = f"ws://localhost:{port}"

        self._save_settings()
        self.btn_join.setEnabled(False)

        self._val_params = {
            'username': username, 'password': password,
            'url': join_url, 'token': token, 'is_host': False,
            'room': room_name, 'connect_url': join_url,
            '_fallback_url': fallback_url,
        }
        self._val_handled = False
        self._show_loading("Joining Room", "Connecting to server\u2026")

        self._open_room_validated(
            is_host=False, username=username, room_name=room_name,
            password=password, public_url=token, connect_url=join_url,
        )

    # ──────────────────────────────────────────────────────
    #  ROOM (validated)
    # ──────────────────────────────────────────────────────

    def _open_room_validated(self, *, is_host, username, room_name,
                              password, public_url, connect_url,
                              share_info=True, features_enabled=False,
                              is_server_mode=False,
                              room_token=""):
        """Create room window (hidden) and validate the connection before showing."""
        vlc_path = self.s_vlc.text().strip() or None
        vlc = VLCController(vlc_path=vlc_path)
        client = SyncClient()

        # Pass room config in server mode
        max_users = 10
        if is_server_mode and is_host:
            max_users = self._val_params.get("max_users", 10)
            share_info = self._val_params.get("share_info", True)
            features_enabled = self._val_params.get("features_enabled", False)

        self._room_window = RoomWindow(
            client=client, vlc=vlc, is_host=is_host,
            username=username, room_name=room_name,
            password=password, public_url=public_url,
            share_info=share_info, features_enabled=features_enabled,
        )
        self._room_window.closed.connect(self._on_room_closed)
        self._room_window.about_to_close.connect(self._on_room_about_to_close)

        # Wire validation signals (room already wires its own in __init__)
        self._val_client = client
        client.welcome_received.connect(self._on_val_welcome)
        client.error_received.connect(self._on_val_error)
        client.disconnected.connect(self._on_val_disconnected)

        # Start timeout
        self._val_timer = QTimer(self)
        self._val_timer.setSingleShot(True)
        self._val_timer.timeout.connect(self._on_val_timeout)
        self._val_timer.start(15000)

        client.connect_to_server(
            connect_url, username, room_name, password,
            is_host=is_host,
            max_users=max_users,
            share_info=share_info,
            features_enabled=features_enabled,
            room_token=room_token,
        )

    # ── Validation handlers ───────────────────────────────

    def _on_val_welcome(self, _data):
        """Server accepted the join — fade out main, show the room."""
        if self._val_handled:
            return
        self._val_handled = True
        if self._val_timer:
            self._val_timer.stop()
        self._disconnect_val_signals()
        self._dismiss_loading()

        # Create fade-out effect on main window
        self._main_fade_effect = QGraphicsOpacityEffect(self)
        self._main_fade_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._main_fade_effect)
        self._main_fade_anim = QPropertyAnimation(self._main_fade_effect, b"opacity")
        self._main_fade_anim.setDuration(200)
        self._main_fade_anim.setStartValue(1.0)
        self._main_fade_anim.setEndValue(0.0)
        self._main_fade_anim.setEasingCurve(QEasingCurve.OutQuad)

        def _on_fade_done():
            self.hide()
            self.setGraphicsEffect(None)
            self._room_window.show()

        self._main_fade_anim.finished.connect(_on_fade_done)
        self._main_fade_anim.start()

    def _on_val_error(self, msg: str):
        """Server rejected the join or sent an error."""
        if self._val_handled:
            return

        # Connection-level errors (refused, offline) should try fallback URL
        is_connection_error = any(keyword in msg.lower() for keyword in [
            "connection refused", "connection error", "offline",
            "connection rejected", "server may be offline",
        ])

        if is_connection_error:
            retry_url = self._val_params.get("_fallback_url")
            if retry_url:
                log.info("Connection failed, trying fallback URL: %s", retry_url)
                # Prevent both _on_val_error AND _on_val_disconnected from
                # trying to start a fallback connection at the same time
                self._val_handled = True
                if self._val_timer:
                    self._val_timer.stop()
                self._disconnect_val_signals()
                if self._room_window:
                    self._room_window.close()
                    self._room_window = None
                params = dict(self._val_params)
                params["connect_url"] = retry_url
                params.pop("_fallback_url", None)
                self._val_params = params
                # Reset handled so the next connection can succeed
                self._val_handled = False
                if self._loading_dialog:
                    self._loading_dialog.set_status("Trying alternate connection\u2026")
                self._open_room_validated(
                    is_host=params.get("is_host", True),
                    username=params.get("username", ""),
                    room_name=params.get("room", ""),
                    password=params.get("password", ""),
                    public_url=params.get("public_url", ""),
                    connect_url=retry_url,
                    share_info=params.get("share_info", True),
                    features_enabled=params.get("features_enabled", False),
                    is_server_mode=params.get("is_server_mode", False),
                    room_token=params.get("room_token", ""),
                )
                return

        # ── Business logic errors (room not found, auth failure, etc.)
        #    Show immediately — no fallback ──
        self._val_handled = True
        if self._val_timer:
            self._val_timer.stop()
        self._disconnect_val_signals()
        self._dismiss_loading()
        if self._room_window:
            self._room_window.close()
            self._room_window = None
        QMessageBox.critical(self, "Connection Error", msg)

    def _on_val_disconnected(self):
        """Connection lost before welcome arrived.
        
        NOTE: Fallback URL is handled by _on_val_error which fires BEFORE
        disconnected. Do NOT retry fallback here — it creates a race condition
        with the fallback connection already in progress.
        """
        if self._val_handled:
            return

        self._val_handled = True
        if self._val_timer:
            self._val_timer.stop()
        self._disconnect_val_signals()
        self._dismiss_loading()
        if self._room_window:
            self._room_window.close()
            self._room_window = None
        QMessageBox.critical(
            self, "Connection Error",
            "Disconnected from server.\n"
            "Please check the token and try again.",
        )

    def _on_val_timeout(self):
        """Validation timed out."""
        if self._val_handled:
            return
        self._val_handled = True
        self._disconnect_val_signals()
        self._dismiss_loading()
        if self._val_client:
            self._val_client.disconnect()
            self._val_client = None
        if self._room_window:
            self._room_window.close()
            self._room_window = None
        QMessageBox.critical(
            self, "Timeout",
            "Connection timed out.\n"
            "Please check the token and try again.",
        )

    def _disconnect_val_signals(self):
        """Safely disconnect validation signal handlers."""
        if not self._val_client:
            return
        for sig, slot in [
            (self._val_client.welcome_received, self._on_val_welcome),
            (self._val_client.error_received, self._on_val_error),
            (self._val_client.disconnected, self._on_val_disconnected),
        ]:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._val_client = None

    # ── Loading helpers ───────────────────────────────────

    def _show_loading(self, title: str, status: str = ""):
        self._dismiss_loading()
        self._loading_dialog = LoadingDialog(self)
        self._loading_dialog.set_title(title)
        self._loading_dialog.set_status(status)
        self._loading_dialog.show()

    def _dismiss_loading(self):
        if self._loading_dialog:
            self._loading_dialog.close()
            self._loading_dialog.deleteLater()
            self._loading_dialog = None

    # ── Local IP detection for server connection ──────────

    # ── Cleanup helpers ───────────────────────────────────

    def _on_cleanup_result(self, data: dict):
        """Handle automatic cleanup response (silent — refresh if servers were removed)."""
        removed = data.get("removed", 0)
        log.info("Auto-cleanup result: %d servers removed", removed)
        if removed > 0:
            # Re-fetch silently to reflect the cleaned list
            self._refresh_server_list(force=True)

    def _on_room_about_to_close(self):
        """Room started fading out (direct user click) — start fading Main in immediately.
        
        Main appears with 0 opacity and fades in (200ms) while Room fades out (200ms).
        No delay — both start simultaneously so Room doesn't flash "under" Main.
        """
        # Prepare main window state immediately
        self._val_handled = True
        self._disconnect_val_signals()
        if self._room_window:
            old_client = getattr(self._room_window, '_client', None)
            if old_client:
                old_client.disconnect()
            old_vlc = getattr(self._room_window, '_vlc', None)
            if old_vlc:
                old_vlc.close()

        self._all_servers = []
        self._selected_server = {}
        self._clear_server_cards()
        self._server_info_label.setText("Select a server from the list above")
        self._server_search.clear()

        self.btn_host_server.setEnabled(True)
        self.btn_host_server.setText("Create Room on Server")
        self.btn_join.setEnabled(True)
        self.btn_join.setText("Join Room")

        # Show with 0 opacity — will fade in while Room fades out
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()

        self._fade_in_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in_anim.setDuration(200)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QEasingCurve.OutQuad)

        def _on_fade_done():
            self.setWindowOpacity(1.0)
            # Don't refresh servers yet — _on_room_closed will do that

        self._fade_in_anim.finished.connect(_on_fade_done)
        self._fade_in_anim.start()

    def _on_room_closed(self):
        """Room window fully closed — refresh the server list."""
        self._room_window = None
        # _on_room_about_to_close already showed Main and faded in
        # Now refresh servers (with a slight delay so fade-in finishes)
        QTimer.singleShot(50, lambda: self._refresh_server_list(force=True))

    @staticmethod
    def _make_refresh_icon(size: int, color_str: str) -> QIcon:
        """Draw a professional circular refresh icon (like iOS refresh icon) using QPainter."""
        # Create pixmap with higher DPI scaling for clarity
        pix = QPixmap(size * 2, size * 2)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        
        color = QColor(color_str)
        pen = QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)

        cx, cy = size, size  # Center at (size, size) since pix is 2x size
        r = size - 4  # arc radius

        # ─── Upper arc (from right to left, clockwise) ───
        p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2), 0 * 16, 180 * 16)

        # ─── Upper arrow head (pointing upper-right) ───
        arrow_len = 5
        arrow_x_top = cx + r - 2
        arrow_y_top = cy - r + 1
        p.drawLine(int(arrow_x_top - arrow_len), int(arrow_y_top - arrow_len), int(arrow_x_top), int(arrow_y_top))
        p.drawLine(int(arrow_x_top + arrow_len), int(arrow_y_top - arrow_len), int(arrow_x_top), int(arrow_y_top))

        # ─── Lower arc (from left to right, clockwise) ───
        p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2), 180 * 16, 180 * 16)

        # ─── Lower arrow head (pointing lower-left) ───
        arrow_x_bottom = cx - r + 2
        arrow_y_bottom = cy + r - 1
        p.drawLine(int(arrow_x_bottom + arrow_len), int(arrow_y_bottom + arrow_len), int(arrow_x_bottom), int(arrow_y_bottom))
        p.drawLine(int(arrow_x_bottom - arrow_len), int(arrow_y_bottom + arrow_len), int(arrow_x_bottom), int(arrow_y_bottom))

        p.end()
        
        # Scale down to original size for high-quality result
        scaled = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(scaled)

    def closeEvent(self, event):
        self._val_handled = True
        self._dismiss_loading()
        self._scanning = False
        if self._val_timer:
            self._val_timer.stop()
        if self._room_window:
            old_client = getattr(self._room_window, '_client', None)
            if old_client:
                old_client.disconnect()
            self._room_window.close()
        event.accept()
        # Only close app when MainWindow is closed, not RoomWindow
        QApplication.quit()