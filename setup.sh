#!/usr/bin/env bash
# setup.sh — Dependencies for Dynamic Notch
set -e

echo "==> Installing required system packages..."
sudo apt-get update -y
sudo apt-get install -y \
    gir1.2-gtk-3.0 \
    python3-gi-cairo \
    python3-dbus \
    pipewire \
    wireplumber

echo ""
echo "✅ All packages ready!"
echo ""
echo "🚀 Run Dynamic Notch:"
echo "   ~/Documents/code/notch-test/run.sh"
echo ""
echo "⚙️ Auto-start on login (optional):"
echo "   cp ~/Documents/code/notch-test/dynamic-notch.desktop ~/.config/autostart/"
