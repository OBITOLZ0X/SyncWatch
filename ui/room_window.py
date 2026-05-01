"""
SyncWatch - Room session window.
"""
import os
import re
import logging
import shutil
import time
from datetime import datetime
from hashlib import md5
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import URLError

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QSplitter, QFrame, QMenu, QApplication, QSizePolicy,
    QStyledItemDelegate, QStyle, QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect, QModelIndex, QUrl, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QTextCursor, QPen, QMovie, QTextDocument, QImage

from . import styles
from core.paths import get_gif_cache_dir

log = logging.getLogger(__name__)

# Prefix role + color role for custom delegate
_ROLE_PREFIX = Qt.UserRole + 1
_ROLE_PREFIX_COLOR = Qt.UserRole + 2
_ROLE_NAME_COLOR = Qt.UserRole + 3
_ROLE_FILE_LINE = Qt.UserRole + 4

# GIF URL detection
_GIF_URL_RE = re.compile(
    r'(https?://[^\s<>"]+\.gif\b(?:\?[^\s<>"]*)?)'                              # any direct .gif URL
    r'|(https?://(?:media\.giphy\.com|media\d*\.tenor\.com|i\.imgur\.com'         # known GIF hosts
    r'|cdn\.discordapp\.com|media\.discordapp\.net'                               # Discord CDN
    r'|c\.tenor\.com|media\.tenor\.com'                                           # Tenor variants
    r')/[^\s<>"]+)'
    r'|(https?://giphy\.com/gifs/[^\s<>"]+)'                                     # Giphy page URL
    r'|(https?://tenor\.com/(?:view|[a-z]{2}/view)/[^\s<>"]+)',                  # Tenor page URL
    re.IGNORECASE,
)
_MAX_GIF_SIZE = 10 * 1024 * 1024  # 10 MB
_MAX_ACTIVE_GIFS = 15


def _resolve_gif_url(url: str) -> str:
    """Convert page URLs (giphy.com/gifs, tenor.com/view) to direct media URLs."""
    # Giphy page: https://giphy.com/gifs/...-{id} -> direct media URL
    m = re.match(r'https?://giphy\.com/gifs/(?:.*-)?([a-zA-Z0-9]+)$', url)
    if m:
        return f"https://media.giphy.com/media/{m.group(1)}/giphy.gif"
    # Tenor page: scrape og:image from the HTML
    if re.match(r'https?://tenor\.com/', url):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with urlopen(req, timeout=10) as resp:
                html = resp.read(128 * 1024).decode("utf-8", errors="ignore")
            # Try any og:image (modern Tenor may serve .gif, .png, or .webp)
            og = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE,
            )
            if not og:
                og = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    html, re.IGNORECASE,
                )
            if og:
                return og.group(1)
        except Exception as e:
            log.debug("Tenor page scrape failed: %s", e)
    return url


class _UserItemDelegate(QStyledItemDelegate):
    """Draws user items with an orange prefix and status-colored name."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)

        # Draw selection / hover background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(styles.BG_ELEVATED))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(styles.BG_OVERLAY))

        rect = option.rect.adjusted(10, 0, -6, 0)
        prefix = index.data(_ROLE_PREFIX) or ""
        prefix_color = index.data(_ROLE_PREFIX_COLOR) or styles.ORANGE
        name_color = index.data(_ROLE_NAME_COLOR) or styles.TEXT
        display = index.data(Qt.DisplayRole) or ""
        file_line = index.data(_ROLE_FILE_LINE) or ""

        # --- Draw prefix (orange) ---
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(QPen(QColor(prefix_color)))
        prefix_rect = QRect(rect.x(), rect.y(), 20, rect.height() if not file_line else rect.height() // 2 + 4)
        painter.drawText(prefix_rect, Qt.AlignLeft | Qt.AlignVCenter, prefix)

        # --- Draw name + tag (status colour) ---
        name_font = QFont(font)
        name_font.setPointSize(10)
        is_bold = index.data(Qt.FontRole)
        if is_bold:
            name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QPen(QColor(name_color)))
        name_rect = QRect(rect.x() + 22, rect.y(), rect.width() - 22, rect.height() if not file_line else rect.height() // 2 + 4)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, display)

        # --- Draw file line (dim) ---
        if file_line:
            file_font = QFont(font)
            file_font.setPointSize(8)
            painter.setFont(file_font)
            painter.setPen(QPen(QColor(styles.TEXT_DIM)))
            file_rect = QRect(rect.x() + 22, rect.y() + rect.height() // 2 + 2, rect.width() - 22, rect.height() // 2 - 4)
            painter.drawText(file_rect, Qt.AlignLeft | Qt.AlignVCenter, file_line)

        painter.restore()

    def sizeHint(self, option, index):
        file_line = index.data(_ROLE_FILE_LINE)
        return QSize(0, 48 if file_line else 30)


class RoomWindow(QWidget):
    """Main session window for a SyncWatch room."""

    closed = Signal()
    about_to_close = Signal()  # Emitted BEFORE fade — MainWindow should start showing immediately
    _gif_ready = Signal(str, str, str)  # local_path, username, gif_url

    def __init__(
        self,
        client,
        vlc,
        is_host: bool,
        username: str,
        room_name: str,
        password: str,
        public_url: str,
        share_info: bool = True,
        features_enabled: bool = False,
    ):
        super().__init__()
        self._client = client
        self._vlc = vlc
        self._is_host = is_host
        self._username = username
        self._room_name = room_name or "Room"
        self._password = password
        self._public_url = public_url
        self._share_info = share_info
        self._features_enabled = features_enabled

        self._users: dict = {}
        self._is_ready = False
        self._host_username = username if is_host else ""
        self._host_file_name = ""
        self._host_file_size = 0
        self._syncing = False
        self._file_loaded = False
        self._all_ready = False

        self._last_sync_paused: bool = True
        self._last_sync_position: float = 0.0

        # Chat mute state
        self._chat_muted: bool = False

        # GIF support
        self._gif_movies: dict = {}  # resource_name -> QMovie
        self._gif_counter = 0
        self._gif_dir = get_gif_cache_dir()

        # Periodic sync heartbeat timer
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(1000)
        self._sync_timer.timeout.connect(self._sync_heartbeat)

        # Periodic file label refresh (updates position/duration in real time)
        self._file_label_timer = QTimer(self)
        self._file_label_timer.setInterval(500)
        self._file_label_timer.timeout.connect(self._refresh_file_label)

        self.setWindowTitle(f"SyncWatch \u2014 {self._room_name}")
        self.setMinimumSize(620, 500)
        self.resize(1100, 720)
        self.setStyleSheet(styles.get_style())

        self._build_ui()
        self._wire_signals()
        self._refresh_ready_btn()

    # ══════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        top = QFrame()
        top.setObjectName("topBar")
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(16, 10, 16, 10)
        top_lay.setSpacing(10)

        self._room_lbl = QLabel(self._room_name)
        self._room_lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self._room_lbl.setStyleSheet(f"color: {styles.YELLOW};")
        top_lay.addWidget(self._room_lbl)

        # Token display (host always sees it; others only if share_info enabled)
        show_token = self._public_url and (self._is_host or self._share_info)
        if show_token:
            self.token_display = QLineEdit(self._public_url)
            self.token_display.setReadOnly(True)
            self.token_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            top_lay.addWidget(self.token_display)

            btn_copy_token = QPushButton("Copy Token")
            btn_copy_token.setObjectName("accentBtn")
            btn_copy_token.setCursor(Qt.PointingHandCursor)
            btn_copy_token.clicked.connect(self._copy_token)
            top_lay.addWidget(btn_copy_token)

        # Password display (host always sees it; others only if share_info enabled)
        show_pw = self._password and (self._is_host or self._share_info)
        if show_pw:
            pw_lbl = QLabel("Password")
            pw_lbl.setObjectName("fieldLabel")
            top_lay.addWidget(pw_lbl)

            self.pw_display = QLineEdit(self._password)
            self.pw_display.setReadOnly(True)
            self.pw_display.setEchoMode(QLineEdit.Password)
            self.pw_display.setFixedWidth(90)
            top_lay.addWidget(self.pw_display)

            btn_copy_pw = QPushButton("Copy")
            btn_copy_pw.setObjectName("accentBtn")
            btn_copy_pw.setCursor(Qt.PointingHandCursor)
            btn_copy_pw.clicked.connect(self._copy_password)
            top_lay.addWidget(btn_copy_pw)

            self._pw_btn = QPushButton("Show")
            self._pw_btn.setObjectName("readyBtn")
            self._pw_btn.setFixedWidth(100)
            self._pw_btn.setFixedHeight(38)
            self._pw_btn.setCursor(Qt.PointingHandCursor)
            self._pw_btn.clicked.connect(self._toggle_password_visibility)
            top_lay.addWidget(self._pw_btn)

        if not show_token:
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            top_lay.addWidget(spacer)

        root.addWidget(top)

        # ── Splitter ──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left panel ──
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 12, 4, 12)
        left_lay.setSpacing(10)

        # Users header row: label + ready status
        users_header = QHBoxLayout()
        users_header.setSpacing(8)
        users_lbl = QLabel("Users")
        users_lbl.setObjectName("sectionLabel")
        users_header.addWidget(users_lbl)
        users_header.addStretch()
        self.status_label = QLabel("0/0 ready")
        self.status_label.setStyleSheet(
            f"color: {styles.GREEN}; font-size: 12px; font-weight: 600;"
        )
        users_header.addWidget(self.status_label)
        left_lay.addLayout(users_header)

        self.user_list = QListWidget()
        self.user_list.setItemDelegate(_UserItemDelegate(self.user_list))
        self.user_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.user_list.customContextMenuRequested.connect(self._user_context_menu)
        self.user_list.setMinimumWidth(230)
        left_lay.addWidget(self.user_list, stretch=1)

        splitter.addWidget(left)

        # ── Right panel (chat) ──
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 12, 12, 12)
        right_lay.setSpacing(10)

        chat_header = QHBoxLayout()
        chat_header.setSpacing(8)
        chat_lbl = QLabel("Chat")
        chat_lbl.setObjectName("sectionLabel")
        chat_header.addWidget(chat_lbl)
        chat_header.addStretch()

        # Host-only buttons (always created but visibility controlled by _is_host)
        self._mute_btn = QPushButton("Mute All")
        self._mute_btn.setObjectName("accentBtn")
        self._mute_btn.setCursor(Qt.PointingHandCursor)
        self._mute_btn.setFixedHeight(28)
        self._mute_btn.setFixedWidth(110)
        self._mute_btn.clicked.connect(self._toggle_mute_chat)
        self._mute_btn.setVisible(self._is_host)
        chat_header.addWidget(self._mute_btn)

        right_lay.addLayout(chat_header)

        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setFont(QFont("Consolas", 10))
        right_lay.addWidget(self.chat_box, stretch=1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message\u2026")
        self.chat_input.returnPressed.connect(self._send_chat)
        input_row.addWidget(self.chat_input)

        btn_send = QPushButton("Send")
        btn_send.setObjectName("accentBtn")
        btn_send.setCursor(Qt.PointingHandCursor)
        btn_send.clicked.connect(self._send_chat)
        btn_send.setFixedWidth(72)
        input_row.addWidget(btn_send)

        right_lay.addLayout(input_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

        # ── Bottom bar ──
        bottom = QFrame()
        bottom.setObjectName("bottomBar")
        bot = QHBoxLayout(bottom)
        bot.setContentsMargins(20, 10, 20, 10)
        bot.setSpacing(14)

        self.file_label = QLabel("No file loaded")
        self.file_label.setObjectName("infoLabel")
        self.file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bot.addWidget(self.file_label)

        btn_load = QPushButton("Load File")
        btn_load.setCursor(Qt.PointingHandCursor)
        btn_load.clicked.connect(self._load_file)
        bot.addWidget(btn_load)

        self.btn_ready = QPushButton("Ready")
        self.btn_ready.setObjectName("readyBtn")
        self.btn_ready.setCursor(Qt.PointingHandCursor)
        self.btn_ready.setMinimumWidth(130)
        self.btn_ready.clicked.connect(self._toggle_ready)
        bot.addWidget(self.btn_ready)

        root.addWidget(bottom)

    # ══════════════════════════════════════════════════════
    #  SIGNAL WIRING
    # ══════════════════════════════════════════════════════

    def _wire_signals(self):
        c = self._client
        c.connected.connect(self._on_connected)
        c.disconnected.connect(self._on_disconnected)
        c.error_received.connect(self._on_error)
        c.welcome_received.connect(self._on_welcome)
        c.user_joined.connect(self._on_user_joined)
        c.user_left.connect(self._on_user_left)
        c.sync_received.connect(self._on_sync)
        c.chat_received.connect(self._on_chat_received)
        c.user_updated.connect(self._on_user_updated)
        c.kicked.connect(self._on_kicked)
        c.permission_updated.connect(self._on_permission_updated)
        c.chat_muted_changed.connect(self._on_chat_muted_changed)
        c.all_ready.connect(self._on_all_ready)
        c.host_transferred.connect(self._on_host_transferred)

        v = self._vlc
        v.state_changed.connect(self._on_vlc_state)
        v.file_changed.connect(self._on_vlc_file_changed)
        v.vlc_closed.connect(self._on_vlc_closed)
        v.vlc_ready.connect(self._on_vlc_ready)
        self._gif_ready.connect(self._on_gif_downloaded)

    # ══════════════════════════════════════════════════════
    #  VLC HANDLERS
    # ══════════════════════════════════════════════════════

    def _on_vlc_ready(self):
        self._sys_msg("VLC is ready.", styles.GREEN)
        pending = getattr(self, "_pending_file", None)
        if pending:
            self._pending_file = None
            self._file_loaded = True
            self._is_ready = False
            self._all_ready = False
            self._refresh_ready_btn()

            name = os.path.basename(pending)
            size = os.path.getsize(pending) if os.path.isfile(pending) else 0
            self._client.send_file_info(name, size, 0.0)
            self._client.send_ready(False)
            self._refresh_file_label()
            self._sys_msg(f"Loaded: {name}")
            self._refresh_osd_state()

    def _on_vlc_closed(self):
        self._sys_msg("VLC was closed.", styles.RED)
        self._file_loaded = False
        self._is_ready = False
        self._refresh_ready_btn()
        self._client.send_file_info("", 0, 0.0)
        self._client.send_ready(False)
        self._refresh_file_label()

    def _on_vlc_state(self, paused: bool, position: float):
        if self._file_loaded:
            self._refresh_file_label()
        # SAFETY: Always enforce pause when not all ready, regardless of syncing
        if not paused and not self._all_ready:
            self._vlc.set_paused(True)
            self._syncing = True
            QTimer.singleShot(1500, self._clear_syncing)
            self._client.send_state(position, False)
            self._refresh_osd_state()
            return
        if self._syncing:
            # If position differs significantly from the last sync,
            # the user manually seeked — clear syncing and propagate
            if abs(position - self._last_sync_position) > 5.0:
                self._syncing = False
            else:
                return
        self._client.send_state(position, paused)

    def _on_vlc_file_changed(self, name: str, size: int, duration: float):
        if self._file_loaded and name == os.path.basename(self._vlc.file_path):
            return
        self._file_loaded = True
        self._is_ready = False
        self._all_ready = False
        self._refresh_ready_btn()
        self._client.send_ready(False)
        self._client.send_file_info(name, size, duration)
        self._refresh_file_label()
        self._sys_msg(f"File changed to: {name}")
        self._vlc.set_paused(True)
        self._refresh_osd_state()

    # ══════════════════════════════════════════════════════
    #  CLIENT HANDLERS
    # ══════════════════════════════════════════════════════

    def _on_connected(self):
        self._sys_msg("Connected to server.", styles.GREEN)
        self._sync_timer.start()
        self._file_label_timer.start()

    def _on_disconnected(self):
        self._sys_msg("Disconnected from server.", styles.RED)
        self._sync_timer.stop()
        self._file_label_timer.stop()
        if self._vlc.connected:
            self._vlc.set_paused(True)
            self._vlc.show_osd("Disconnected from server", 7.0)

    def _on_error(self, msg: str):
        self._sys_msg(f"Error: {msg}", styles.RED)

    def _on_welcome(self, data: dict):
        self._room_name = data.get("room", self._room_name)
        host_from_welcome = data.get("host", "")
        self._host_username = host_from_welcome
        self._host_file_name = data.get("host_file_name", "")
        self._host_file_size = data.get("host_file_size", 0)

        # Update share_info from server for non-host users
        if not self._is_host:
            self._share_info = data.get("share_info", True)
            self._features_enabled = data.get("features_enabled", False)

        # If welcome says we are the host (e.g. from server mode), update our status
        if host_from_welcome and host_from_welcome == self._username and not self._is_host:
            self._is_host = True
            self._host_username = self._username
            self._update_host_buttons_visibility()

        # Update chat muted state
        self._chat_muted = data.get("chat_muted", False)
        self._update_chat_muted_ui()

        for name, udict in data.get("users", {}).items():
            self._users[name] = udict

        self.setWindowTitle(f"SyncWatch \u2014 {self._room_name}")
        self._room_lbl.setText(f"  {self._room_name}")
        self._refresh_user_list()
        self._sys_msg(f'Joined room "{self._room_name}" as {self._username}.', styles.GREEN)

        log.info("WELCOME received: room=%s, users=%s",
                 self._room_name, list(self._users.keys()))

        pos = data.get("position", 0)
        paused = data.get("paused", True)
        if self._vlc.connected:
            self._syncing = True
            self._vlc.seek_to(pos, paused)
            QTimer.singleShot(1500, self._clear_syncing)

    def _on_user_joined(self, data: dict):
        uname = data.get("username", "")
        self._users[uname] = data.get("user", {})
        # Recalculate all_ready — only false if someone isn't ready
        self._all_ready = all(u.get("is_ready") for u in self._users.values())
        self._refresh_user_list()
        self._sys_msg(f"{uname} joined the room.")
        log.info("USER_JOINED: %s, total users: %s", uname, list(self._users.keys()))
        if self._vlc.connected:
            self._vlc.show_osd(f"{uname} joined — waiting for them", 6.0)
            self._refresh_osd_state()

    def _on_user_left(self, username: str):
        self._users.pop(username, None)
        # Recalculate all_ready after removing user
        self._all_ready = bool(self._users) and all(
            u.get("is_ready") for u in self._users.values()
        )
        self._refresh_user_list()
        if self._vlc.connected:
            self._vlc.set_paused(True)
            self._vlc.show_osd(f"{username} left the room -- paused", 7.0)
            self._refresh_osd_state()

    def _on_sync(self, data: dict):
        pos = data.get("position", 0)
        paused = data.get("paused", True)

        self._last_sync_paused = paused
        self._last_sync_position = pos

        if self._vlc.connected and self._file_loaded:
            pos_diff = abs(self._vlc.position - pos)
            if paused:
                # Pause command is critical — always enforce it immediately
                self._syncing = True
                self._vlc.set_paused(True)
                if pos_diff >= 1.0:
                    self._vlc.seek_to(pos, True)
                QTimer.singleShot(1500, self._clear_syncing)
            elif pos_diff < 1.0:
                # Small drift — just fix pause state, no heavy seek needed
                self._syncing = True
                if self._vlc.paused != paused:
                    self._vlc.set_paused(paused)
                QTimer.singleShot(500, self._clear_syncing)
            else:
                # Significant difference — full seek with verification
                self._syncing = True
                self._vlc.seek_to(pos, paused)
                QTimer.singleShot(1500, self._clear_syncing)

    def _on_chat_received(self, username: str, message: str):
        if username == "System":
            self._sys_msg(message)
            if self._vlc.connected and any(
                kw in message for kw in ("paused", "resumed", "seeked", "left the room")
            ):
                self._vlc.show_osd(message, 6.0)
        else:
            gif_match = _GIF_URL_RE.search(message)
            if gif_match:
                gif_url = gif_match.group(1) or gif_match.group(2) or gif_match.group(3) or gif_match.group(4)
                display_msg = message.replace(gif_url, "").strip()
                if display_msg:
                    self._chat_msg(username, display_msg)
                else:
                    # Only show username + timestamp, no text
                    ts = datetime.now().strftime("%H:%M")
                    name_clr = styles.COLOR_HOST if username == self._host_username else styles.TEXT
                    self.chat_box.append(
                        f'<span style="color:{styles.TEXT_DIM};">[{ts}]</span> '
                        f'<span style="color:{name_clr};font-weight:bold;">{username}:</span>'
                    )
                    self.chat_box.moveCursor(QTextCursor.End)
                if self._vlc.connected:
                    self._vlc.show_osd(f"{username}: [GIF]", 8.0)
                Thread(
                    target=self._download_gif,
                    args=(gif_url, username),
                    daemon=True,
                ).start()
            else:
                self._chat_msg(username, message)
                if self._vlc.connected:
                    self._vlc.show_osd(f"{username}: {message}", 8.0)

    def _on_user_updated(self, data: dict):
        uname = data.get("username", "")
        self._users[uname] = data.get("user", {})

        # Sync local ready state if this update is about us
        if uname == self._username:
            server_ready = data.get("user", {}).get("is_ready", False)
            if self._is_ready != server_ready:
                self._is_ready = server_ready
                self._refresh_ready_btn()

            # Check if we became the new host
            is_now_host = data.get("user", {}).get("is_host", False)
            if is_now_host and not self._is_host:
                self._is_host = True
                self._host_username = self._username
                room_token = data.get("room_token", "")
                if room_token:
                    self._public_url = room_token
                    self._update_token_display(room_token)
                self._update_host_buttons_visibility()
                self._sys_msg("You are now the host!", styles.GREEN)
                if self._vlc.connected:
                    self._vlc.show_osd("You're now host!", 5.0)

        hfn = data.get("host_file_name", "")
        hfs = data.get("host_file_size", 0)
        if hfn:
            self._host_file_name = hfn
        if hfs:
            self._host_file_size = hfs

        # If any user is not ready, clear the all-ready flag and pause VLC
        if not all(u.get("is_ready") for u in self._users.values()):
            if self._all_ready:
                # Was all-ready, now someone un-readied — pause locally
                if self._vlc.connected and self._file_loaded:
                    self._vlc.set_paused(True)
            self._all_ready = False

        self._refresh_osd_state()
        self._refresh_user_list()
        self._refresh_status()
        self._update_ready_all_btn()

    def _on_kicked(self, reason: str):
        self._sys_msg(f"You were kicked: {reason}", styles.RED)
        if self._vlc.connected:
            self._vlc.set_paused(True)
            self._vlc.show_osd(f"Kicked: {reason}", 7.0)
        QMessageBox.warning(self, "Kicked", f"You were kicked from the room.\nReason: {reason}")
        self.close()

    def _on_permission_updated(self, data: dict):
        uname = data.get("username", "")
        perm = data.get("permission", "")
        val = data.get("value", True)
        if uname in self._users:
            self._users[uname]["permissions"] = data.get("permissions", {})
        perm_labels = {"chat": "Chat", "kick": "Kick", "make_ready": "Make Ready", "mute_user": "Mute User"}
        perm_label = perm_labels.get(perm, perm)
        state = "enabled" if val else "disabled"
        self._sys_msg(f'{uname}\'s "{perm_label}" permission {state}.')
        self._refresh_user_list()

    def _on_all_ready(self):
        self._all_ready = True
        self._vlc.osd_clear("not_ready")
        self._vlc.osd_clear("diff_file")
        self._sys_msg("All users ready \u2014 playing!", styles.GREEN)
        self._syncing = True
        if self._vlc.connected and self._file_loaded:
            self._vlc.set_paused(False)
            self._vlc.show_osd("All ready! Playing\u2026", 5.0)
        QTimer.singleShot(500, self._clear_syncing)
        self._update_ready_all_btn()

    def _on_host_transferred(self, new_host: str):
        """Handle host transfer when the original host leaves."""
        if new_host:
            self._host_username = new_host
            self._refresh_user_list()

        if new_host == self._username and not self._is_host:
            self._is_host = True
            self._host_username = self._username
            self._update_host_buttons_visibility()
            self._sys_msg("You are now the host!", styles.GREEN)
            if self._vlc.connected:
                self._vlc.show_osd("You're now host!", 5.0)
        elif new_host == self._username and self._is_host:
            # We already became host via user_updated, but ensure UI is up to date
            self._update_host_buttons_visibility()

    # ══════════════════════════════════════════════════════
    #  USER ACTIONS
    # ══════════════════════════════════════════════════════

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Media File", "",
            "Media Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v "
            "*.mpg *.mpeg *.ts *.mp3 *.flac *.ogg *.wav);;All Files (*)",
        )
        if not path:
            return
        if not self._vlc.connected:
            ok = self._vlc.launch(file_path=path)
            if not ok:
                self._sys_msg("Failed to launch VLC. Check Settings.", styles.RED)
                return
            self._pending_file = path
            return
        self._do_load_file(path)

    def _do_load_file(self, path: str):
        ok = self._vlc.load_file(path)
        if ok:
            self._file_loaded = True
            self._is_ready = False
            self._all_ready = False
            self._refresh_ready_btn()

            name = os.path.basename(path)
            size = os.path.getsize(path)
            self._client.send_file_info(name, size, 0.0)
            self._client.send_ready(False)
            self._refresh_file_label()
            self._sys_msg(f"Loaded: {name}")
            self._refresh_osd_state()
        else:
            self._sys_msg("Failed to load file.", styles.RED)

    def _toggle_ready(self):
        if not self._file_loaded:
            self._sys_msg("Load a file first before readying up.", styles.YELLOW)
            return
        self._is_ready = not self._is_ready
        self._client.send_ready(self._is_ready)
        self._refresh_ready_btn()

    def _toggle_ready_all(self):
        """Toggle between Ready All and Unready All based on current state."""
        if not self._is_host:
            return
        if self._all_ready:
            self._client.send_unready_all()
        else:
            self._client.send_ready_all()

    def _update_ready_all_btn(self):
        """Update the Ready All button text and style."""
        if self._is_host and hasattr(self, '_ready_all_btn'):
            if self._all_ready:
                self._ready_all_btn.setText("Unready All")
                self._ready_all_btn.setObjectName("dangerBtn")
            else:
                self._ready_all_btn.setText("Ready All")
                self._ready_all_btn.setObjectName("accentBtn")
            self._ready_all_btn.style().unpolish(self._ready_all_btn)
            self._ready_all_btn.style().polish(self._ready_all_btn)

    def _update_host_buttons_visibility(self):
        """Show/hide host-only buttons."""
        if hasattr(self, '_mute_btn'):
            self._mute_btn.setVisible(self._is_host)
        if hasattr(self, '_ready_all_btn'):
            self._ready_all_btn.setVisible(self._is_host)
        # Update mute UI only if host
        if self._is_host:
            self._update_chat_muted_ui()
        self._update_ready_all_btn()

    def _send_chat(self):
        text = self.chat_input.text().strip()
        if text:
            self._client.send_chat(text)
            self.chat_input.clear()

    def _update_token_display(self, new_token: str):
        """Update the token display when a new host receives the room token."""
        self._public_url = new_token
        if hasattr(self, 'token_display') and self.token_display:
            self.token_display.setText(new_token)
        self._sys_msg("You are now the host! Token updated.", styles.GREEN)
        if self._vlc.connected:
            self._vlc.show_osd("You're now host!", 5.0)

    def _copy_token(self):
        QApplication.clipboard().setText(self._public_url)
        self._sys_msg("Token copied to clipboard.", styles.GREEN)

    def _copy_password(self):
        QApplication.clipboard().setText(self._password)
        self._sys_msg("Password copied to clipboard.", styles.GREEN)

    def _toggle_password_visibility(self):
        if self.pw_display.echoMode() == QLineEdit.Password:
            self.pw_display.setEchoMode(QLineEdit.Normal)
            self._pw_btn.setText("Hide")
            self._pw_btn.setObjectName("dangerBtn")
        else:
            self.pw_display.setEchoMode(QLineEdit.Password)
            self._pw_btn.setText("Show")
            self._pw_btn.setObjectName("readyBtn")
        self._pw_btn.style().unpolish(self._pw_btn)
        self._pw_btn.style().polish(self._pw_btn)

    def _toggle_mute_chat(self):
        self._chat_muted = not self._chat_muted
        self._client.send_mute_chat(self._chat_muted)
        self._update_chat_muted_ui()

    def _on_chat_muted_changed(self, muted: bool):
        self._chat_muted = muted
        self._update_chat_muted_ui()

    def _update_chat_muted_ui(self):
        if self._is_host and hasattr(self, '_mute_btn'):
            if self._chat_muted:
                self._mute_btn.setText("Unmute All")
                self._mute_btn.setObjectName("dangerBtn")
            else:
                self._mute_btn.setText("Mute All")
                self._mute_btn.setObjectName("accentBtn")
            self._mute_btn.style().unpolish(self._mute_btn)
            self._mute_btn.style().polish(self._mute_btn)

        # Disable chat input for non-host users when muted
        if not self._is_host:
            self.chat_input.setEnabled(not self._chat_muted)
            if self._chat_muted:
                self.chat_input.setPlaceholderText("Chat is muted by host")
            else:
                self.chat_input.setPlaceholderText("Type a message\u2026")

    # ══════════════════════════════════════════════════════
    #  USER LIST
    # ══════════════════════════════════════════════════════

    def _refresh_user_list(self):
        self.user_list.clear()
        # Host always first, then others in join order
        sorted_users = sorted(
            self._users.items(),
            key=lambda x: (0 if x[1].get("is_host") else 1),
        )
        for uname, uinfo in sorted_users:
            is_host = uinfo.get("is_host", False)
            is_ready = uinfo.get("is_ready", False)
            file_name = uinfo.get("file_name", "")
            file_size = uinfo.get("file_size", 0)

            if not file_name:
                colour, tag = styles.COLOR_NOT_READY, "No file"
            elif (
                self._host_file_name
                and (file_name != self._host_file_name or file_size != self._host_file_size)
            ):
                colour, tag = styles.COLOR_WRONG_FILE, "Different file"
            elif is_ready:
                colour, tag = styles.COLOR_READY, "Ready"
            else:
                colour, tag = styles.COLOR_NOT_READY, "Not ready"

            prefix = "\u2605" if is_host else "\u25CF"
            is_me = (uname == self._username)
            prefix_color = styles.ORANGE if is_me else styles.TEXT
            label = f"{uname}  [{tag}]"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, uname)
            item.setData(_ROLE_PREFIX, prefix)
            item.setData(_ROLE_PREFIX_COLOR, prefix_color)
            item.setData(_ROLE_NAME_COLOR, colour)
            item.setData(_ROLE_FILE_LINE, file_name if file_name else "")
            if is_host:
                item.setData(Qt.FontRole, True)
            self.user_list.addItem(item)

        self._refresh_status()

    def _user_context_menu(self, pos):
        item = self.user_list.itemAt(pos)
        if not item:
            return
        target = item.data(Qt.UserRole)
        if not target or target == self._username:
            return

        uinfo = self._users.get(target, {})
        target_is_host = uinfo.get("is_host", False)
        target_has_file = bool(uinfo.get("file_name", ""))
        target_is_ready = uinfo.get("is_ready", False)
        perms = uinfo.get("permissions", {"chat": True, "kick": False, "make_ready": False, "mute_user": False})

        menu = QMenu(self)
        menu.setStyleSheet("")  # Use global style

        if self._is_host:
            # -- Host context menu --
            if not target_is_host:
                # Actions
                kick_act = menu.addAction("\u2716  Kick User")
                kick_act.setData(("kick", target))

                if target_has_file:
                    if not target_is_ready:
                        ready_act = menu.addAction("\u25B6  Make Ready")
                        ready_act.setData(("make_ready", target))
                    else:
                        unready_act = menu.addAction("\u25A0  Make Not Ready")
                        unready_act.setData(("make_not_ready", target))

                target_chat = perms.get("chat", True)
                if target_chat:
                    mute_act = menu.addAction("\u2298  Mute User")
                    mute_act.setData(("mute_user", target, True))
                else:
                    unmute_act = menu.addAction("\u2299  Unmute User")
                    unmute_act.setData(("mute_user", target, False))

                menu.addSeparator()

                # Permissions header
                header = menu.addAction("\u2699  Permissions")
                header.setEnabled(False)

                kick_perm = perms.get("kick", False)
                kick_icon = "\u2713" if kick_perm else "\u2717"
                kick_perm_act = menu.addAction(f"    {kick_icon}  Allow Kick")
                kick_perm_act.setData(("perm", target, "kick", not kick_perm))

                mr_perm = perms.get("make_ready", False)
                mr_icon = "\u2713" if mr_perm else "\u2717"
                mr_perm_act = menu.addAction(f"    {mr_icon}  Allow Make Ready")
                mr_perm_act.setData(("perm", target, "make_ready", not mr_perm))

                mu_perm = perms.get("mute_user", False)
                mu_icon = "\u2713" if mu_perm else "\u2717"
                mu_perm_act = menu.addAction(f"    {mu_icon}  Allow Mute User")
                mu_perm_act.setData(("perm", target, "mute_user", not mu_perm))

                chat_perm = perms.get("chat", True)
                chat_icon = "\u2713" if chat_perm else "\u2717"
                chat_perm_act = menu.addAction(f"    {chat_icon}  Allow Chat")
                chat_perm_act.setData(("perm", target, "chat", not chat_perm))

        else:
            # -- Non-host context menu --
            if target_is_host:
                return

            has_actions = False

            my_perms = self._users.get(self._username, {}).get(
                "permissions", {"chat": True, "kick": False, "make_ready": False, "mute_user": False}
            )

            if my_perms.get("kick", False):
                kick_act = menu.addAction("\u2716  Kick User")
                kick_act.setData(("kick", target))
                has_actions = True

            if my_perms.get("make_ready", False) and target_has_file:
                if not target_is_ready:
                    ready_act = menu.addAction("\u25B6  Make Ready")
                    ready_act.setData(("make_ready", target))
                    has_actions = True
                else:
                    unready_act = menu.addAction("\u25A0  Make Not Ready")
                    unready_act.setData(("make_not_ready", target))
                    has_actions = True

            if my_perms.get("mute_user", False):
                target_chat = perms.get("chat", True)
                if target_chat:
                    mute_act = menu.addAction("\u2298  Mute User")
                    mute_act.setData(("mute_user", target, True))
                else:
                    unmute_act = menu.addAction("\u2299  Unmute User")
                    unmute_act.setData(("mute_user", target, False))
                has_actions = True

            if not has_actions:
                return

        chosen = menu.exec(self.user_list.mapToGlobal(pos))
        if not chosen or not chosen.data():
            return
        data = chosen.data()
        if data[0] == "kick":
            self._client.send_kick(data[1], f"Kicked by {self._username}")
        elif data[0] == "make_ready":
            self._client.send_make_ready(data[1])
        elif data[0] == "make_not_ready":
            self._client.send_make_not_ready(data[1])
        elif data[0] == "mute_user":
            self._client.send_mute_user(data[1], data[2])
        elif data[0] == "perm":
            self._client.send_set_permission(data[1], data[2], data[3])

    # ══════════════════════════════════════════════════════
    #  CHAT HELPERS
    # ══════════════════════════════════════════════════════

    def _chat_msg(self, username: str, message: str):
        ts = datetime.now().strftime("%H:%M")
        name_clr = styles.COLOR_HOST if username == self._host_username else styles.TEXT
        html = (
            f'<span style="color:{styles.TEXT_DIM};">[{ts}]</span> '
            f'<span style="color:{name_clr};font-weight:bold;">{username}:</span> '
            f'<span style="color:{styles.TEXT};">{message}</span>'
        )
        self.chat_box.append(html)
        self.chat_box.moveCursor(QTextCursor.End)

    def _sys_msg(self, message: str, colour: str = None):
        if colour is None:
            colour = styles.TEXT_DIM
        ts = datetime.now().strftime("%H:%M")
        html = (
            f'<span style="color:{styles.TEXT_DIM};">[{ts}]</span> '
            f'<span style="color:{colour};font-style:italic;">\u2699 {message}</span>'
        )
        self.chat_box.append(html)
        self.chat_box.moveCursor(QTextCursor.End)

    # ══════════════════════════════════════════════════════
    #  GIF SUPPORT
    # ══════════════════════════════════════════════════════

    def _download_gif(self, gif_url: str, username: str):
        """Download a GIF in a background thread with retries."""
        if not gif_url.startswith(("http://", "https://")):
            return
        resolved = _resolve_gif_url(gif_url)
        filename = md5(resolved.encode()).hexdigest()[:12] + ".gif"
        path = os.path.join(self._gif_dir, filename)

        if os.path.isfile(path):
            self._gif_ready.emit(path, username, gif_url)
            return

        _MAX_RETRIES = 3
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                req = Request(resolved, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })
                with urlopen(req, timeout=15) as resp:
                    data = resp.read(_MAX_GIF_SIZE + 1)
                if len(data) > _MAX_GIF_SIZE:
                    log.debug("GIF too large (%d bytes): %s", len(data), resolved)
                    return
                # Accept GIF, WebP (RIFF), PNG, JPEG
                if (data[:3] not in (b"GIF", b"RIF")
                        and data[:4] != b"\x89PNG"
                        and data[:2] != b"\xff\xd8"):
                    log.warning("Unexpected image format (header: %r): %s", data[:4], resolved)
                    return
                with open(path, "wb") as f:
                    f.write(data)
                self._gif_ready.emit(path, username, gif_url)
                return
            except (URLError, OSError) as e:
                if attempt < _MAX_RETRIES:
                    log.debug("GIF download attempt %d/%d failed (%s), retrying: %s",
                              attempt, _MAX_RETRIES, e, resolved)
                    time.sleep(1.5 * attempt)
                else:
                    log.warning("GIF download failed after %d attempts for %s: %s",
                                _MAX_RETRIES, gif_url, e)
            except Exception as e:
                log.warning("GIF download error for %s: %s", gif_url, e)
                return

    def _on_gif_downloaded(self, local_path: str, username: str, gif_url: str):
        """Display a downloaded GIF/image in the chat (animated if possible)."""
        movie = QMovie(local_path)
        animated = movie.isValid() and movie.frameCount() != 1

        if animated:
            movie.jumpToFrame(0)
            first_frame = movie.currentImage()
            if first_frame.isNull():
                animated = False

        # Fallback to static QImage for WebP/PNG or single-frame GIFs
        if not animated:
            first_frame = QImage(local_path)
            if first_frame.isNull():
                log.warning("Cannot display image: %s", local_path)
                return

        # Scale to fit chat area
        w, h = first_frame.width(), first_frame.height()
        max_w, max_h = 250, 200
        if w > max_w or h > max_h:
            scale = min(max_w / w, max_h / h)
            w, h = int(w * scale), int(h * scale)
            if animated:
                movie.setScaledSize(QSize(w, h))
                movie.jumpToFrame(0)
                first_frame = movie.currentImage()
            else:
                first_frame = first_frame.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Unique resource name
        self._gif_counter += 1
        res_name = f"sw_gif_{self._gif_counter}"
        url = QUrl(res_name)
        doc = self.chat_box.document()
        doc.addResource(QTextDocument.ImageResource, url, first_frame)

        self.chat_box.append(f'<img src="{res_name}" width="{w}" height="{h}">')
        self.chat_box.moveCursor(QTextCursor.End)

        if animated:
            # Animate: update the resource on each frame change
            def _update_frame(_frame_num):
                img = movie.currentImage()
                if not img.isNull():
                    doc.addResource(QTextDocument.ImageResource, url, img)
                    self.chat_box.viewport().update()

            movie.frameChanged.connect(_update_frame)
            movie.start()

            # Evict oldest animation if too many active
            if len(self._gif_movies) >= _MAX_ACTIVE_GIFS:
                oldest_key = next(iter(self._gif_movies))
                self._gif_movies[oldest_key].stop()
                del self._gif_movies[oldest_key]

        self._gif_movies[res_name] = movie

        # Show GIF in VLC video via logo sub-filter (native VLC rendering)
        if self._vlc.connected:
            self._vlc.show_gif_on_video(local_path, 10.0, username)

    # ══════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════

    def _refresh_file_label(self):
        if self._vlc.file_name:
            mb = self._vlc.file_size / (1024 * 1024)
            pos_str = self._fmt_time(self._vlc.position)
            dur_str = self._fmt_time(self._vlc.duration) if self._vlc.duration > 0 else "--:--"
            self.file_label.setText(
                f"{self._vlc.file_name}  ({mb:.1f} MB)  \u2022  {pos_str} / {dur_str}"
            )
        else:
            self.file_label.setText("No file loaded")

    def _refresh_ready_btn(self):
        if not self._file_loaded:
            self.btn_ready.setEnabled(False)
            self.btn_ready.setText("Ready")
            self.btn_ready.setObjectName("readyBtn")
        else:
            self.btn_ready.setEnabled(True)
            name = "readyBtnActive" if self._is_ready else "readyBtn"
            self.btn_ready.setText("\u2713 Ready" if self._is_ready else "Ready")
            self.btn_ready.setObjectName(name)
        self.btn_ready.style().unpolish(self.btn_ready)
        self.btn_ready.style().polish(self.btn_ready)

    def _refresh_status(self):
        total = len(self._users)
        ready = sum(1 for u in self._users.values() if u.get("is_ready"))
        self.status_label.setText(f"{ready}/{total} ready" if total else "No users")

    def _clear_syncing(self):
        self._syncing = False

    def _sync_heartbeat(self):
        """Periodically send playback state to keep everyone in sync."""
        if not self._vlc.connected or not self._file_loaded:
            return
        if self._syncing:
            return
        self._client.send_state(self._vlc.position, self._vlc.paused, heartbeat=True)

    # ══════════════════════════════════════════════════════
    #  OSD STATE
    # ══════════════════════════════════════════════════════

    def _refresh_osd_state(self):
        if not self._vlc.connected:
            return

        if self._users and not all(u.get("is_ready") for u in self._users.values()):
            if self._all_ready:
                self._all_ready = False
                self._vlc.set_paused(True)

        if self._all_ready:
            self._vlc.osd_clear("not_ready")
            self._vlc.osd_clear("diff_file")
            return

        not_ready, wrong_file = [], []
        for uname, uinfo in self._users.items():
            fname = uinfo.get("file_name", "")
            fsize = uinfo.get("file_size", 0)
            if (
                fname and self._host_file_name
                and (fname != self._host_file_name or fsize != self._host_file_size)
            ):
                wrong_file.append(uname)
            if not uinfo.get("is_ready"):
                not_ready.append(uname)

        if wrong_file:
            self._vlc.osd_set("diff_file", "!! Different file: " + ", ".join(wrong_file))
        else:
            self._vlc.osd_clear("diff_file")

        if not_ready:
            self._vlc.osd_set("not_ready", "Not ready: " + ", ".join(not_ready))
        else:
            self._vlc.osd_clear("not_ready")

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = int(seconds)
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"

    def refresh_theme(self):
        """Re-apply inline-styled widgets after theme change."""
        self.setStyleSheet(styles.get_style())
        self._room_lbl.setStyleSheet(f"color: {styles.YELLOW};")
        self.status_label.setStyleSheet(
            f"color: {styles.GREEN}; font-size: 12px; font-weight: 600;"
        )

    # ══════════════════════════════════════════════════════
    #  LIFECYCLE
    # ══════════════════════════════════════════════════════

    def closeEvent(self, event):
        """Fade out the whole window, then close."""
        # If already fading, this is the second call — close for real
        if getattr(self, '_fading_out', False):
            self._sync_timer.stop()
            self._file_label_timer.stop()
            for movie in self._gif_movies.values():
                movie.stop()
            self._gif_movies.clear()
            shutil.rmtree(self._gif_dir, ignore_errors=True)
            self._client.disconnect()
            self._vlc.close()
            self._fading_out = False
            event.accept()
            return

        event.ignore()
        self._fading_out = True

        # Tell MainWindow to start fading in NOW (cross-dissolve)
        self.about_to_close.emit()

        # Fade entire window (including title bar) using windowOpacity
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(200)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuad)

        def _on_fade_done():
            # Hide first — completely removes the window from screen
            self.hide()
            # Clean up resources NOW (no second closeEvent)
            self._sync_timer.stop()
            self._file_label_timer.stop()
            for movie in self._gif_movies.values():
                movie.stop()
            self._gif_movies.clear()
            shutil.rmtree(self._gif_dir, ignore_errors=True)
            self._client.disconnect()
            self._vlc.close()
            self._fading_out = False
            # Tell MainWindow to show itself
            self.closed.emit()
            self.deleteLater()

        self._fade_anim.finished.connect(_on_fade_done)
        self._fade_anim.start()
