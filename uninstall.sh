#!/usr/bin/env bash
# uninstall.sh — Safe desktop launcher and autostart uninstaller for Dynamic Notch
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
LAUNCHER="$APPS_DIR/dynamic-notch.desktop"
AUTOSTART_ENTRY="$AUTOSTART_DIR/dynamic-notch.desktop"
LOCAL_LAUNCHER="$DIR/dynamic-notch.desktop"

echo "==> Dynamic Notch Uninstaller"
echo ""

# 1. Remove application launcher from desktop menu
if [ -f "$LAUNCHER" ]; then
    if grep -q "Dynamic Notch" "$LAUNCHER" 2>/dev/null; then
        rm -f "$LAUNCHER"
        echo "  ✓ Removed desktop application launcher: $LAUNCHER"
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$APPS_DIR" 2>/dev/null || true
        fi
    else
        echo "  ⚠️  Skipping $LAUNCHER: content does not match Dynamic Notch."
    fi
else
    echo "  ℹ️ Desktop launcher was not found in $APPS_DIR."
fi

# 2. Remove autostart entry if present
if [ -f "$AUTOSTART_ENTRY" ]; then
    if grep -q "Dynamic Notch" "$AUTOSTART_ENTRY" 2>/dev/null; then
        rm -f "$AUTOSTART_ENTRY"
        echo "  ✓ Removed autostart entry: $AUTOSTART_ENTRY"
    else
        echo "  ⚠️  Skipping $AUTOSTART_ENTRY: content does not match Dynamic Notch."
    fi
else
    echo "  ℹ️ Autostart was not configured."
fi

# 3. Clean up local generated launcher in project directory
if [ -f "$LOCAL_LAUNCHER" ]; then
    rm -f "$LOCAL_LAUNCHER"
    echo "  ✓ Removed local launcher file: $LOCAL_LAUNCHER"
fi

echo ""
echo "==> Uninstallation summary:"
echo "  ✓ Application launcher removed from desktop menu (GNOME App Grid)."
echo "  ✓ Autostart entry removed (if previously enabled)."
echo "  ✓ System dependencies and packages remain untouched."
echo "  ✓ Project source code and local files in $DIR are preserved."
echo ""
echo "To completely delete the Dynamic Notch repository and source files:"
echo "   rm -rf \"$DIR\""
