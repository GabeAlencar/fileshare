#!/bin/bash
# Adds FileShare to the app launcher (any freedesktop desktop: KDE, GNOME, Hyprland launchers...).
# Run again after moving the folder. Remove with:  ./install-linux.sh --uninstall
set -e
dir="$(cd "$(dirname "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
entry="$apps/fileshare.desktop"

if [ "$1" = "--uninstall" ]; then
    rm -f "$entry"
    echo "Removed $entry"
    exit 0
fi

command -v python3 >/dev/null || echo "Note: python3 not found. On Arch: sudo pacman -S python"
command -v tailscale >/dev/null || echo "Note: tailscale not found. On Arch: sudo pacman -S tailscale && sudo systemctl enable --now tailscaled && sudo tailscale up"

mkdir -p "$apps"
cat > "$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=FileShare
Comment=Send files between your Tailscale devices
Exec=python3 "$dir/fileshare.py" --quit-when-closed
Icon=$dir/icon.svg
Terminal=false
Categories=Network;FileTransfer;
DESKTOP
chmod +x "$entry"
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" 2>/dev/null || true
echo "Installed $entry"

echo "If you haven't yet, allow receiving without sudo (once):  sudo tailscale set --operator=\$USER"
