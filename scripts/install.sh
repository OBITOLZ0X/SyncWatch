#!/usr/bin/env bash
# SyncWatch Linux Installer — curl | bash
# Installs the latest SyncWatch release from GitHub.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.sh | sudo bash  # system-wide
#   bash install.sh --uninstall   # uninstall
#   bash install.sh --help       # help

set -e

REPO="OBITOLZ0X/SyncWatch"
APP="SyncWatch"
BIN_NAME="syncwatch"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
header()  { echo -e "${CYAN}${BOLD}$*${NC}"; }

usage() {
    cat <<EOF
SyncWatch Installer for Linux

Usage:
  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/install.sh | bash
  ./install.sh [OPTIONS]

Options:
  --help, -h        Show this help
  --uninstall       Uninstall SyncWatch
  --prefix DIR      Install prefix (default: auto-detect)
  --version TAG     Install specific version (e.g., v2.0.0)
  --no-desktop      Skip desktop entry creation
  --force           Force reinstall even if already installed

Environment:
  SYNCWATCH_NO_DESKTOP=1   Skip desktop entry

EOF
}

# Parse args
PREFIX=""
VERSION="latest"
NO_DESKTOP=0
FORCE=0
DO_UNINSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --no-desktop) NO_DESKTOP=1; shift ;;
        --force) FORCE=1; shift ;;
        *) warn "Unknown option: $1"; shift ;;
    esac
done

# Allow env var to skip desktop
[[ "${SYNCWATCH_NO_DESKTOP:-0}" == "1" ]] && NO_DESKTOP=1

# Detect install prefix
detect_prefix() {
    if [[ -n "$PREFIX" ]]; then
        echo "$PREFIX"
    elif [[ $EUID -eq 0 ]]; then
        echo "/usr/local"
    elif [[ -w "/usr/local/bin" ]]; then
        echo "/usr/local"
    else
        echo "$HOME/.local"
    fi
}

INSTALL_PREFIX="$(detect_prefix)"
BIN_DIR="$INSTALL_PREFIX/bin"
APP_DIR="$INSTALL_PREFIX/lib/syncwatch"
DESKTOP_DIR=""
if [[ $EUID -eq 0 ]]; then
    DESKTOP_DIR="/usr/share/applications"
else
    DESKTOP_DIR="$HOME/.local/share/applications"
fi

uninstall() {
    header "Uninstalling SyncWatch..."

    # Remove binary
    if [[ -f "$BIN_DIR/$BIN_NAME" ]]; then
        rm -f "$BIN_DIR/$BIN_NAME"
        success "Removed $BIN_DIR/$BIN_NAME"
    fi
    if [[ -f "$HOME/.local/bin/$BIN_NAME" ]]; then
        rm -f "$HOME/.local/bin/$BIN_NAME"
        success "Removed $HOME/.local/bin/$BIN_NAME"
    fi

    # Remove app dir (check both prefixes)
    for dir in "$APP_DIR" "$HOME/.local/lib/syncwatch" "/usr/local/lib/syncwatch"; do
        if [[ -d "$dir" ]]; then
            rm -rf "$dir"
            success "Removed $dir"
        fi
    done

    # Remove desktop entry
    for d in "$HOME/.local/share/applications" "/usr/share/applications"; do
        if [[ -f "$d/syncwatch.desktop" ]]; then
            rm -f "$d/syncwatch.desktop"
            success "Removed $d/syncwatch.desktop"
        fi
    done

    # Remove icon
    for d in "$HOME/.local/share/icons" "/usr/share/icons"; do
        rm -f "$d/syncwatch.png" 2>/dev/null || true
    done

    # Remove uninstaller itself
    rm -f "$BIN_DIR/syncwatch-uninstall" "$HOME/.local/bin/syncwatch-uninstall" 2>/dev/null || true

    success "SyncWatch uninstalled."
    exit 0
}

[[ $DO_UNINSTALL -eq 1 ]] && uninstall

# ── Header ──
echo ""
header "╔══════════════════════════════════════╗"
header "║     SyncWatch — Linux Installer      ║"
header "╚══════════════════════════════════════╝"
echo ""

# ── Checks ──
if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
    error "curl or wget is required. Install one and retry:"
    error "  sudo apt update && sudo apt install curl"
    exit 1
fi

# Detect arch
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)  ARCH_LABEL="x86_64" ;;
    aarch64|arm64) ARCH_LABEL="arm64" ;;
    armv7l)        ARCH_LABEL="armv7" ;;
    *)             ARCH_LABEL="$ARCH"; warn "Unknown arch $ARCH, trying x86_64 build..." ; ARCH_LABEL="x86_64" ;;
esac

OS="$(uname -s)"
if [[ "$OS" != "Linux" ]]; then
    error "This installer is for Linux. Detected: $OS"
    error "For Windows, use: irm https://raw.githubusercontent.com/${REPO}/main/scripts/install.ps1 | iex"
    exit 1
fi

info "System: $OS $ARCH_LABEL"
info "Install prefix: $INSTALL_PREFIX"
info "Binary dir: $BIN_DIR"
echo ""

# ── Fetch latest release info ──
fetch_url() {
    local url="$1"
    if command -v curl &>/dev/null; then
        curl -fsSL "$url"
    else
        wget -qO- "$url"
    fi
}

if [[ "$VERSION" == "latest" ]]; then
    info "Fetching latest release..."
    RELEASE_JSON="$(fetch_url "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || echo "")"
    if [[ -z "$RELEASE_JSON" ]] || echo "$RELEASE_JSON" | grep -q '"message": "Not Found"'; then
        warn "No releases found via API, trying direct download from main..."
        # Fallback: check if there's a release asset URL pattern
        TAG="latest"
        DOWNLOAD_URL=""
    else
        TAG="$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
        info "Latest version: $TAG"

        # Try to find Linux asset URL
        DOWNLOAD_URL="$(echo "$RELEASE_JSON" | grep '"browser_download_url"' | grep -i 'linux' | head -1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')"
        if [[ -z "$DOWNLOAD_URL" ]]; then
            # Fallback to any tar.gz or zip
            DOWNLOAD_URL="$(echo "$RELEASE_JSON" | grep '"browser_download_url"' | grep -E '\.tar\.gz|\.zip' | head -1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')"
        fi
    fi
else
    TAG="$VERSION"
    RELEASE_JSON="$(fetch_url "https://api.github.com/repos/${REPO}/releases/tags/${TAG}" 2>/dev/null || echo "")"
    DOWNLOAD_URL="$(echo "$RELEASE_JSON" | grep '"browser_download_url"' | grep -i 'linux' | head -1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')"
    if [[ -z "$DOWNLOAD_URL" ]]; then
        DOWNLOAD_URL="$(echo "$RELEASE_JSON" | grep '"browser_download_url"' | grep -E '\.tar\.gz|\.zip' | head -1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')"
    fi
fi

# If no release assets found, try building from source warning
if [[ -z "$DOWNLOAD_URL" ]]; then
    echo ""
    warn "No pre-built Linux release found for $TAG."
    warn "You can either:"
    warn "  1. Wait for the next release (builds run on every tag)"
    warn "  2. Install from source:"
    echo ""
    echo "     git clone https://github.com/${REPO}.git"
    echo "     cd SyncWatch && pip install -r requirements.txt && python main.py"
    echo ""
    warn "Or build a portable binary locally:"
    echo "     pip install pyinstaller && python build.py"
    echo ""
    if [[ "$FORCE" != "1" ]]; then
        error "Aborting. Use --force to try legacy download URL, or install from source."
        exit 1
    fi
    # Force: try predictable URL
    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${TAG}/SyncWatch-Linux.tar.gz"
    info "Trying forced URL: $DOWNLOAD_URL"
fi

info "Download URL: $DOWNLOAD_URL"
echo ""

# ── Download ──
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

ARCHIVE="$TMPDIR/syncwatch.tar.gz"
if [[ "$DOWNLOAD_URL" == *.zip ]]; then
    ARCHIVE="$TMPDIR/syncwatch.zip"
fi

info "Downloading..."
if command -v curl &>/dev/null; then
    if ! curl -fL --progress-bar -o "$ARCHIVE" "$DOWNLOAD_URL"; then
        error "Download failed. URL may be invalid or release has no Linux build yet."
        error "Check: https://github.com/${REPO}/releases"
        exit 1
    fi
else
    if ! wget --show-progress -O "$ARCHIVE" "$DOWNLOAD_URL"; then
        error "Download failed."
        exit 1
    fi
fi

if [[ ! -s "$ARCHIVE" ]]; then
    error "Downloaded file is empty. No Linux build available for $TAG."
    error "See releases: https://github.com/${REPO}/releases"
    exit 1
fi

ARCHIVE_SIZE="$(du -h "$ARCHIVE" | cut -f1)"
success "Downloaded ($ARCHIVE_SIZE)"

# ── Extract ──
info "Extracting..."
EXTRACT_DIR="$TMPDIR/extract"
mkdir -p "$EXTRACT_DIR"

if [[ "$ARCHIVE" == *.zip ]]; then
    if command -v unzip &>/dev/null; then
        unzip -q "$ARCHIVE" -d "$EXTRACT_DIR"
    else
        python3 -m zipfile -e "$ARCHIVE" "$EXTRACT_DIR" 2>/dev/null || {
            error "unzip not found. Install it: sudo apt install unzip"
            exit 1
        }
    fi
else
    tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
fi

# Find the binary (SyncWatch or SyncWatchLz/SyncWatch or SyncWatch-Linux/SyncWatch)
BINARY=""
for candidate in \
    "$EXTRACT_DIR/SyncWatch" \
    "$EXTRACT_DIR/SyncWatch-Linux/SyncWatch" \
    "$EXTRACT_DIR/SyncWatchLz/SyncWatch" \
    "$EXTRACT_DIR"/*/SyncWatch \
    "$EXTRACT_DIR"/*/SyncWatch/SyncWatch; do
    if [[ -f "$candidate" && -x "$candidate" ]] || [[ -f "$candidate" ]]; then
        # Check if it's actually the binary (not a directory)
        if [[ -f "$candidate" ]]; then
            BINARY="$candidate"
            # If parent is SyncWatch-Linux or similar, use that as source dir
            break
        fi
    fi
done

# More robust: find any file named SyncWatch that is executable or large
if [[ -z "$BINARY" || ! -f "$BINARY" ]]; then
    BINARY="$(find "$EXTRACT_DIR" -name "SyncWatch" -type f 2>/dev/null | head -1)"
fi
if [[ -z "$BINARY" || ! -f "$BINARY" ]]; then
    BINARY="$(find "$EXTRACT_DIR" -name "SyncWatch.exe" -type f 2>/dev/null | head -1)"
fi

if [[ -z "$BINARY" ]]; then
    error "Could not find SyncWatch binary in archive. Contents:"
    find "$EXTRACT_DIR" -type f | head -20 >&2
    exit 1
fi

# Source dir is the folder containing the binary
SRC_DIR="$(dirname "$BINARY")"
# If binary is in _internal's parent, SRC_DIR is correct
# If archive had a top-level folder, use it
if [[ "$(basename "$SRC_DIR")" == "_internal" ]]; then
    SRC_DIR="$(dirname "$SRC_DIR")"
fi

info "Found binary: $BINARY"
info "Source dir: $SRC_DIR"
echo ""

# ── Install ──
info "Installing to $INSTALL_PREFIX..."

# Create dirs
mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"

# Copy all files (portable onedir layout)
if [[ -d "$SRC_DIR/_internal" ]]; then
    # Onedir portable — copy everything
    cp -r "$SRC_DIR"/* "$APP_DIR"/ 2>/dev/null || cp -r "$SRC_DIR"/. "$APP_DIR"/
    # Ensure binary is executable
    chmod +x "$APP_DIR/SyncWatch" 2>/dev/null || true
    chmod +x "$APP_DIR/_internal"/* 2>/dev/null || true
    # Create wrapper in bin
    cat > "$BIN_DIR/$BIN_NAME" << WRAPPER_EOF
#!/usr/bin/env bash
exec "$APP_DIR/SyncWatch" "\$@"
WRAPPER_EOF
    chmod +x "$BIN_DIR/$BIN_NAME"
else
    # Single file — just copy binary
    cp "$BINARY" "$APP_DIR/$BIN_NAME"
    chmod +x "$APP_DIR/$BIN_NAME"
    cat > "$BIN_DIR/$BIN_NAME" << WRAPPER_EOF
#!/usr/bin/env bash
exec "$APP_DIR/$BIN_NAME" "\$@"
WRAPPER_EOF
    chmod +x "$BIN_DIR/$BIN_NAME"
fi

# Handle _internal if exists at top level differently
if [[ -d "$EXTRACT_DIR/_internal" && ! -d "$APP_DIR/_internal" ]]; then
    cp -r "$EXTRACT_DIR/_internal" "$APP_DIR"/
fi

success "Installed to $BIN_DIR/$BIN_NAME"

# ── Desktop entry ──
if [[ $NO_DESKTOP -eq 0 ]]; then
    info "Creating desktop entry..."

    mkdir -p "$DESKTOP_DIR"
    mkdir -p "$HOME/.local/share/icons" 2>/dev/null || true

    # Try to find icon in archive or use embedded
    ICON_SRC=""
    for cand in "$SRC_DIR/_internal/icon.png" "$SRC_DIR/icon.png" "$SRC_DIR/assets/icon.png" "$EXTRACT_DIR"/*/icon.png; do
        if [[ -f "$cand" ]]; then ICON_SRC="$cand"; break; fi
    done

    ICON_DST="$HOME/.local/share/icons/syncwatch.png"
    if [[ $EUID -eq 0 ]]; then
        ICON_DST="/usr/share/icons/syncwatch.png"
    fi

    if [[ -n "$ICON_SRC" && -f "$ICON_SRC" ]]; then
        mkdir -p "$(dirname "$ICON_DST")"
        cp "$ICON_SRC" "$ICON_DST" 2>/dev/null || true
    else
        # Create a minimal placeholder icon path — desktop file will still work without icon
        ICON_DST="video-display"
    fi

    cat > "$DESKTOP_DIR/syncwatch.desktop" << DESKTOP_EOF
[Desktop Entry]
Name=SyncWatch
Comment=Watch Together, Perfectly Synced
Exec=$BIN_DIR/$BIN_NAME
Icon=$ICON_DST
Terminal=false
Type=Application
Categories=AudioVideo;Player;Network;
Keywords=sync;video;watch;vlc;mpv;
StartupWMClass=SyncWatch
DESKTOP_EOF

    # Update desktop database if available
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    success "Desktop entry: $DESKTOP_DIR/syncwatch.desktop"
fi

# ── Uninstaller ──
cat > "$BIN_DIR/syncwatch-uninstall" << 'UNINSTALL_EOF'
#!/usr/bin/env bash
set -e
REPO="OBITOLZ0X/SyncWatch"
echo "Uninstalling SyncWatch..."
for p in "$HOME/.local/bin/syncwatch" "/usr/local/bin/syncwatch" "$HOME/.local/bin/syncwatch-uninstall" "/usr/local/bin/syncwatch-uninstall"; do
    [[ -f "$p" ]] && rm -f "$p" && echo "Removed $p"
done
for d in "$HOME/.local/lib/syncwatch" "/usr/local/lib/syncwatch"; do
    [[ -d "$d" ]] && rm -rf "$d" && echo "Removed $d"
done
for d in "$HOME/.local/share/applications/syncwatch.desktop" "/usr/share/applications/syncwatch.desktop"; do
    [[ -f "$d" ]] && rm -f "$d" && echo "Removed $d"
done
echo "SyncWatch uninstalled."
UNINSTALL_EOF
chmod +x "$BIN_DIR/syncwatch-uninstall"

# ── PATH check ──
echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in your PATH"
    echo ""
    echo "  Add it by running:"
    if [[ "$BIN_DIR" == "$HOME/.local/bin" ]]; then
        echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        echo "    # or for zsh: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    else
        echo "    export PATH=\"$BIN_DIR:\$PATH\""
    fi
    echo ""
else
    success "PATH OK — $BIN_DIR is already in PATH"
fi

# ── Done ──
echo ""
header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
success "SyncWatch installed successfully! 🎉"
header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  Run:        ${BOLD}$BIN_NAME${NC}  or  ${BOLD}$BIN_DIR/$BIN_NAME${NC}"
echo -e "  Uninstall:  ${BOLD}syncwatch-uninstall${NC}  or  ${BOLD}bash <(curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/install.sh) --uninstall${NC}"
echo -e "  Update:     ${BOLD}curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/install.sh | bash${NC}"
echo ""
if command -v "$BIN_DIR/$BIN_NAME" &>/dev/null; then
    info "Testing binary..."
    "$BIN_DIR/$BIN_NAME" --help 2>&1 | head -5 || echo "  (binary test skipped — GUI apps need display)"
fi
echo ""
