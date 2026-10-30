#!/usr/bin/env bash
# Устанавливает шрифты презентации: macOS — в ~/Library/Fonts, Linux — в ~/.local/share/fonts.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(uname)" == "Darwin" ]]; then dest="$HOME/Library/Fonts"; else dest="$HOME/.local/share/fonts"; fi
mkdir -p "$dest"
cp "$here"/*.ttf "$dest"/
command -v fc-cache >/dev/null && fc-cache -f "$dest" >/dev/null || true
echo "Шрифты установлены в $dest. Перезапустите PowerPoint или Keynote."
