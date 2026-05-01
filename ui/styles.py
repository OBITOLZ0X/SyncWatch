"""
SyncWatch - Theme system with Dark and Light modes.
"""

# ── Dark Theme Palette ──────────────────────────────────
_DARK = {
    'BG_DARK': '#0f0f14', 'BG_BASE': '#16161e', 'BG_SURFACE': '#1a1b26',
    'BG_OVERLAY': '#1f2029', 'BG_ELEVATED': '#24253a', 'BG_HOVER': '#2a2b3d',
    'BG_SELECTED': '#2a2f55',
    'BORDER': '#2e2f42', 'BORDER_FOCUS': '#7aa2f7',
    'TEXT': '#c0caf5', 'TEXT_DIM': '#565f89', 'TEXT_MUTED': '#414868',
    'ACCENT': '#7aa2f7', 'GREEN': '#9ece6a', 'RED': '#f7768e',
    'YELLOW': '#e0af68', 'PURPLE': '#bb9af7', 'CYAN': '#7dcfff',
    'ORANGE': '#ff9e64',
    'BTN_TEXT': '#0f0f14',
    'ACCENT_HOVER': '#89b4fa', 'GREEN_HOVER': '#b9e07a', 'RED_HOVER': '#ff9daa',
}

# ── Light Theme Palette ─────────────────────────────────
_LIGHT = {
    'BG_DARK': '#c8c8d8', 'BG_BASE': '#e4e4ee', 'BG_SURFACE': '#ededf4',
    'BG_OVERLAY': '#f8f8fc', 'BG_ELEVATED': '#dcdce8', 'BG_HOVER': '#d0d0e0',
    'BG_SELECTED': '#c8c8dd',
    'BORDER': '#b0b0c8', 'BORDER_FOCUS': '#4a68b8',
    'TEXT': '#1c1c30', 'TEXT_DIM': '#5c5c78', 'TEXT_MUTED': '#8888a4',
    'ACCENT': '#4a68b8', 'GREEN': '#2e7d32', 'RED': '#c62828',
    'YELLOW': '#e65100', 'PURPLE': '#7b1fa2', 'CYAN': '#00838f',
    'ORANGE': '#d84315',
    'BTN_TEXT': '#ffffff',
    'ACCENT_HOVER': '#6080d0', 'GREEN_HOVER': '#43a047', 'RED_HOVER': '#ef5350',
}

# ── Active colors (updated by set_theme) ────────────────
_current_theme = 'dark'

BG_DARK      = _DARK['BG_DARK']
BG_BASE      = _DARK['BG_BASE']
BG_SURFACE   = _DARK['BG_SURFACE']
BG_OVERLAY   = _DARK['BG_OVERLAY']
BG_ELEVATED  = _DARK['BG_ELEVATED']
BG_HOVER     = _DARK['BG_HOVER']
BG_SELECTED  = _DARK['BG_SELECTED']
BORDER       = _DARK['BORDER']
BORDER_FOCUS = _DARK['BORDER_FOCUS']
TEXT         = _DARK['TEXT']
TEXT_DIM     = _DARK['TEXT_DIM']
TEXT_MUTED   = _DARK['TEXT_MUTED']
ACCENT       = _DARK['ACCENT']
GREEN        = _DARK['GREEN']
RED          = _DARK['RED']
YELLOW       = _DARK['YELLOW']
PURPLE       = _DARK['PURPLE']
CYAN         = _DARK['CYAN']
ORANGE       = _DARK['ORANGE']
BTN_TEXT     = _DARK['BTN_TEXT']
ACCENT_HOVER = _DARK['ACCENT_HOVER']
GREEN_HOVER  = _DARK['GREEN_HOVER']
RED_HOVER    = _DARK['RED_HOVER']

COLOR_READY      = GREEN
COLOR_WRONG_FILE = RED
COLOR_NOT_READY  = ACCENT
COLOR_HOST       = YELLOW


def current_theme() -> str:
    return _current_theme


def set_theme(name: str):
    global _current_theme
    global BG_DARK, BG_BASE, BG_SURFACE, BG_OVERLAY, BG_ELEVATED, BG_HOVER, BG_SELECTED
    global BORDER, BORDER_FOCUS
    global TEXT, TEXT_DIM, TEXT_MUTED
    global ACCENT, GREEN, RED, YELLOW, PURPLE, CYAN, ORANGE
    global BTN_TEXT, ACCENT_HOVER, GREEN_HOVER, RED_HOVER
    global COLOR_READY, COLOR_WRONG_FILE, COLOR_NOT_READY, COLOR_HOST

    _current_theme = name
    src = _DARK if name == 'dark' else _LIGHT

    BG_DARK      = src['BG_DARK']
    BG_BASE      = src['BG_BASE']
    BG_SURFACE   = src['BG_SURFACE']
    BG_OVERLAY   = src['BG_OVERLAY']
    BG_ELEVATED  = src['BG_ELEVATED']
    BG_HOVER     = src['BG_HOVER']
    BG_SELECTED  = src['BG_SELECTED']
    BORDER       = src['BORDER']
    BORDER_FOCUS = src['BORDER_FOCUS']
    TEXT         = src['TEXT']
    TEXT_DIM     = src['TEXT_DIM']
    TEXT_MUTED   = src['TEXT_MUTED']
    ACCENT       = src['ACCENT']
    GREEN        = src['GREEN']
    RED          = src['RED']
    YELLOW       = src['YELLOW']
    PURPLE       = src['PURPLE']
    CYAN         = src['CYAN']
    ORANGE       = src['ORANGE']
    BTN_TEXT     = src['BTN_TEXT']
    ACCENT_HOVER = src['ACCENT_HOVER']
    GREEN_HOVER  = src['GREEN_HOVER']
    RED_HOVER    = src['RED_HOVER']

    COLOR_READY      = GREEN
    COLOR_WRONG_FILE = RED
    COLOR_NOT_READY  = ACCENT
    COLOR_HOST       = YELLOW


# ── Stylesheet Generator ───────────────────────────────
def get_style() -> str:
    return f"""
/* ── Base ── */
QWidget {{
    background-color: {BG_BASE};
    color: {TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 18px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_FOCUS};
}}
QPushButton:pressed {{
    background-color: {BG_SURFACE};
}}
QPushButton:disabled {{
    background-color: {BG_SURFACE};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QPushButton#accentBtn {{
    background-color: {ACCENT};
    color: {BTN_TEXT};
    border: none;
    font-weight: 700;
}}
QPushButton#accentBtn:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#accentBtn:disabled {{
    background-color: {BG_ELEVATED};
    color: {TEXT_MUTED};
}}

QPushButton#greenBtn {{
    background-color: {GREEN};
    color: {BTN_TEXT};
    border: none;
    font-weight: 700;
}}
QPushButton#greenBtn:hover {{
    background-color: {GREEN_HOVER};
}}

QPushButton#dangerBtn {{
    background-color: {RED};
    color: {BTN_TEXT};
    border: none;
    font-weight: 700;
}}
QPushButton#dangerBtn:hover {{
    background-color: {RED_HOVER};
}}

QPushButton#readyBtn {{
    background-color: {BG_ELEVATED};
    color: {ACCENT};
    border: 2px solid {ACCENT};
    border-radius: 10px;
    font-size: 14px;
    font-weight: 700;
    padding: 10px 28px;
}}
QPushButton#readyBtn:hover {{
    background-color: {BG_HOVER};
}}

QPushButton#readyBtnActive {{
    background-color: {GREEN};
    color: {BTN_TEXT};
    border: 2px solid {GREEN};
    border-radius: 10px;
    font-size: 14px;
    font-weight: 700;
    padding: 10px 28px;
}}

/* ── Nav Tab Buttons ── */
QPushButton#navBtn {{
    background-color: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    padding: 10px 20px;
    color: {TEXT_DIM};
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#navBtn:hover {{
    color: {TEXT};
    background-color: {BG_OVERLAY};
}}
QPushButton#navBtnActive {{
    background-color: transparent;
    border: none;
    border-bottom: 3px solid {ACCENT};
    border-radius: 0;
    padding: 10px 20px;
    color: {ACCENT};
    font-size: 13px;
    font-weight: 700;
}}

/* ── Inputs ── */
QLineEdit, QSpinBox {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {BTN_TEXT};
}}
QLineEdit:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled {{
    background-color: {BG_DARK};
    color: {TEXT_MUTED};
}}

/* ── Text Edit ── */
QTextEdit {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {BTN_TEXT};
}}
QTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ── List Widget ── */
QListWidget {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 8px;
    border-radius: 6px;
    margin: 2px 2px;
}}
QListWidget::item:selected {{
    background-color: {BG_ELEVATED};
}}
QListWidget::item:hover {{
    background-color: {BG_HOVER};
}}

/* ── Labels ── */
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel#titleLabel {{
    font-size: 36px;
    font-weight: 800;
    color: {ACCENT};
    letter-spacing: 1px;
}}
QLabel#subtitleLabel {{
    font-size: 13px;
    color: {TEXT_DIM};
}}
QLabel#sectionLabel {{
    font-size: 15px;
    font-weight: 700;
    color: {PURPLE};
}}
QLabel#infoLabel {{
    font-size: 12px;
    color: {TEXT_DIM};
}}
QLabel#fieldLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {TEXT_DIM};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ── Scroll Bars ── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    border-radius: 3px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BG_ELEVATED};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BORDER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    border-radius: 3px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BG_ELEVATED};
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {BORDER};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Context Menu ── */
QMenu {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 8px 24px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {BG_ELEVATED};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ── Frames ── */
QFrame#separator {{
    background-color: {BORDER};
    max-height: 1px;
}}
QFrame#card {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 14px;
}}
QFrame#miniCard {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QFrame#topBar {{
    background-color: {BG_SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QFrame#bottomBar {{
    background-color: {BG_SURFACE};
    border-top: 1px solid {BORDER};
}}
QFrame#serverListPage {{
    background: transparent;
    border: none;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {BORDER};
}}

/* ── Table Widget (server list) ── */
QTableWidget {{
    background-color: {BG_OVERLAY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {BG_ELEVATED};
    outline: none;
    font-size: 12px;
    alternate-background-color: {BG_HOVER};
}}
QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
}}
QTableWidget::item:hover {{
    background-color: {BG_HOVER};
}}
QHeaderView::section {{
    background-color: {BG_SURFACE};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
}}
QHeaderView::section:hover {{
    color: {TEXT};
}}
QTableWidget::indicator {{
    width: 0;
    height: 0;
}}

/* ── CheckBox ── */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {BORDER};
    background: {BG_OVERLAY};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}

/* ── Toggle Buttons ── */
QPushButton#toggleOff {{
    background-color: {BG_OVERLAY};
    border: 2px solid {BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    color: {TEXT_DIM};
    font-weight: 600;
    font-size: 12px;
}}
QPushButton#toggleOff:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}
QPushButton#toggleOn {{
    background-color: {ACCENT};
    border: 2px solid {ACCENT};
    border-radius: 8px;
    padding: 7px 16px;
    color: {BTN_TEXT};
    font-weight: 700;
    font-size: 12px;
}}
QPushButton#toggleOn:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

/* ── Mode Selector Buttons (Self Host / Server) ── */
QPushButton#modeBtn {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 18px;
    color: {TEXT_DIM};
    font-weight: 600;
    font-size: 12px;
}}
QPushButton#modeBtn:hover {{
    background-color: {BG_HOVER};
    color: {TEXT};
    border-color: {ACCENT};
}}
QPushButton#modeBtnActive {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 6px;
    padding: 7px 18px;
    color: {BTN_TEXT};
    font-weight: 700;
    font-size: 12px;
}}
QPushButton#modeBtnActive:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
"""


DARK_STYLE = get_style()
