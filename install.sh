#!/bin/sh
# Ajoute Manette au menu des applications (dans ~/.local, sans sudo).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPS" "$ICONS" "$HOME/.local/bin"
cp "$DIR/data/local.Manette.svg" "$ICONS/"
ln -sf "$DIR/bin/manette" "$HOME/.local/bin/manette"
sed "s|@EXEC@|$DIR/bin/manette|" "$DIR/data/local.Manette.desktop.in" > "$APPS/local.Manette.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Manette est installée : cherche « Manette » dans tes applications, ou tape « manette »."
