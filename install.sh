#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin/kde-zed-tint.py"
SERVICE_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "==> Installing kde-zed-tint"

# 1. Copy script
mkdir -p "$HOME/.local/bin"
cp "$SCRIPT_DIR/kde-zed-tint.py" "$BIN"
chmod +x "$BIN"
echo "    Script → $BIN"

# 2. Run once immediately to generate the theme
echo "    Generating initial theme…"
"$BIN"

# 3a. If systemd --user is available, use it (preferred)
if systemctl --user status > /dev/null 2>&1; then
    mkdir -p "$SERVICE_DIR"
    cp "$SCRIPT_DIR/kde-zed-tint.service" "$SERVICE_DIR/"
    systemctl --user daemon-reload
    systemctl --user enable --now kde-zed-tint.service
    echo "    Systemd service enabled: kde-zed-tint.service"
else
    # 3b. Fall back to KDE autostart
    mkdir -p "$AUTOSTART_DIR"
    cp "$SCRIPT_DIR/kde-zed-tint-autostart.desktop" "$AUTOSTART_DIR/"
    echo "    KDE autostart entry installed → $AUTOSTART_DIR"
fi

echo ""
echo "Done! Next steps in Zed:"
echo "  1. Open Command Palette → 'theme selector'"
echo "  2. Select 'KDE Tint Dark'"
echo ""
echo "The theme will auto-update whenever your KDE accent color changes."
echo "Requires inotify-tools for instant updates (sudo pacman -S inotify-tools)"
echo "or falls back to 2-second polling."
