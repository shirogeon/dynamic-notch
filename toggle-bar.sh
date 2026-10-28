#!/usr/bin/env bash
# toggle-bar.sh — Toggle GNOME Top Bar visibility
STATUS=$(dconf read /org/gnome/shell/extensions/just-perfection/panel 2>/dev/null)
if [ "$STATUS" = "false" ]; then
    dconf write /org/gnome/shell/extensions/just-perfection/panel true
    echo "✅ Top bar: SHOWN (Muncul kembali)"
else
    dconf write /org/gnome/shell/extensions/just-perfection/panel false
    echo "🚀 Top bar: HIDDEN (Hilang, Notch leluasa)"
fi
