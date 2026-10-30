#!/usr/bin/env bash
# setup.sh — Conservative installer and launcher/autostart manager for Dynamic Notch
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
LAUNCHER="$APPS_DIR/dynamic-notch.desktop"
AUTOSTART_ENTRY="$AUTOSTART_DIR/dynamic-notch.desktop"
LOCAL_LAUNCHER="$DIR/dynamic-notch.desktop"
TEMPLATE="$DIR/dynamic-notch.desktop.in"

REQUIRED_PACKAGES=(
    gir1.2-gtk-3.0
    python3-gi
    python3-gi-cairo
    python3-dbus
    pipewire
    wireplumber
    libnotify-bin
)

show_help() {
    cat <<EOF
Usage: ./setup.sh [OPTION]

Dynamic Notch installer, desktop launcher generator, and autostart manager.

Options:
  (no option)           Check dependencies and install desktop application launcher
  --enable-autostart    Configure Dynamic Notch to start automatically on login
  --disable-autostart   Disable automatic start on login
  --status              Display installation, launcher, autostart, and process status
  --help, -h            Show this help message

Documentation & Uninstaller:
  README.md             Complete setup, usage, and troubleshooting guide
  ./uninstall.sh        Remove desktop launcher and autostart configuration
EOF
}

generate_launcher() {
    local target="$1"
    local perms="$2"
    if [ ! -f "$TEMPLATE" ]; then
        echo "❌ Error: Template $TEMPLATE not found." >&2
        exit 1
    fi
    mkdir -p "$(dirname "$target")"
    sed -e "s|@EXEC_PATH@|$DIR/run.sh|g" -e "s|@PROJECT_DIR@|$DIR|g" "$TEMPLATE" > "$target"
    chmod "$perms" "$target"
}

enable_autostart() {
    echo "==> Dynamic Notch Autostart Configuration"
    mkdir -p "$AUTOSTART_DIR"
    generate_launcher "$AUTOSTART_ENTRY" 644
    echo "  ✓ Autostart enabled: created $AUTOSTART_ENTRY"
    echo "    Dynamic Notch will start automatically upon desktop login."
}

disable_autostart() {
    echo "==> Dynamic Notch Autostart Configuration"
    if [ -f "$AUTOSTART_ENTRY" ]; then
        if grep -q "Dynamic Notch" "$AUTOSTART_ENTRY" 2>/dev/null; then
            rm -f "$AUTOSTART_ENTRY"
            echo "  ✓ Autostart disabled: removed $AUTOSTART_ENTRY"
            echo "    The desktop application launcher in $APPS_DIR remains installed."
        else
            echo "⚠️  Refusing to remove $AUTOSTART_ENTRY: file content does not match Dynamic Notch." >&2
            exit 1
        fi
    else
        echo "  ℹ️ Autostart is already disabled (no autostart entry found)."
    fi
}

show_status() {
    echo "==> Dynamic Notch Status"
    echo ""
    echo "  Application Launcher:"
    if [ -f "$LAUNCHER" ]; then
        local exec_target
        exec_target=$(grep "^Exec=" "$LAUNCHER" 2>/dev/null | cut -d'=' -f2-)
        if [ -x "$exec_target" ]; then
            echo "    Status:   Installed (✓ points to valid executable: $exec_target)"
        else
            echo "    Status:   Installed (⚠️ points to non-executable or missing path: $exec_target)"
        fi
        echo "    Path:     $LAUNCHER"
    else
        echo "    Status:   Not installed (run './setup.sh' to install)"
        echo "    Path:     $LAUNCHER"
    fi

    echo ""
    echo "  Project Executables:"
    for script in "run.sh" "notch.py" "uninstall.sh"; do
        if [ -x "$DIR/$script" ]; then
            echo "    $script:  $DIR/$script (executable ✓)"
        elif [ -f "$DIR/$script" ]; then
            echo "    $script:  $DIR/$script (present, not executable ⚠️)"
        else
            echo "    $script:  missing ✗"
        fi
    done

    echo ""
    echo "  Autostart on Login:"
    if [ -f "$AUTOSTART_ENTRY" ]; then
        echo "    Status:   Enabled (starts automatically on login ✓)"
        echo "    Path:     $AUTOSTART_ENTRY"
    else
        echo "    Status:   Disabled (run './setup.sh --enable-autostart' to enable)"
        echo "    Path:     $AUTOSTART_ENTRY"
    fi

    echo ""
    echo "  Application Process:"
    local running_pids
    running_pids=$(pgrep -u "$UID" -f "notch\.py" 2>/dev/null | tr '\n' ' ' || true)
    if [ -n "$running_pids" ]; then
        echo "    Status:   Running (PID: $running_pids)✓"
    else
        echo "    Status:   Not running"
    fi
}

# Parse command line options
case "$1" in
    --help|-h)
        show_help
        exit 0
        ;;
    --enable-autostart)
        enable_autostart
        exit 0
        ;;
    --disable-autostart)
        disable_autostart
        exit 0
        ;;
    --status)
        show_status
        exit 0
        ;;
    "")
        # Proceed with normal installation flow
        ;;
    *)
        echo "❌ Unknown option: $1" >&2
        echo "Run './setup.sh --help' for usage." >&2
        exit 1
        ;;
esac

echo "==> Dynamic Notch Setup"
echo "==> Checking required system dependencies..."

MISSING_PACKAGES=()
DEPS_CHECKED=false

if command -v dpkg-query >/dev/null 2>&1; then
    DEPS_CHECKED=true
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            echo "  ✓ $pkg is installed"
        else
            echo "  ✗ $pkg is missing"
            MISSING_PACKAGES+=("$pkg")
        fi
    done
else
    echo "⚠️  Package manager 'dpkg-query' (Debian/Ubuntu) not found."
    echo "    Could not verify installed packages automatically."
    echo "    Please verify that the required dependencies are installed using your distribution's package manager:"
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        echo "    - $pkg"
    done
    echo ""
    echo "    See README.md for Fedora (dnf) and Arch Linux (pacman) installation instructions."
fi

if [ "$DEPS_CHECKED" = true ]; then
    if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
        echo ""
        echo "==> Missing dependencies detected: ${MISSING_PACKAGES[*]}"
        echo "    These packages are required for GTK UI, D-Bus media sync, PipeWire audio, and desktop notifications."

        if command -v apt-get >/dev/null 2>&1; then
            echo ""
            echo "==> Analyzing package changes (dry-run simulation)..."
            # Execute simulation without swallowing errors
            set +e
            SIM_OUTPUT=$(apt-get -s install --no-upgrade "${MISSING_PACKAGES[@]}" 2>&1)
            SIM_STATUS=$?
            set -e

            if [ $SIM_STATUS -ne 0 ]; then
                echo "⚠️  apt-get dry-run simulation failed (exit code $SIM_STATUS):"
                echo "$SIM_OUTPUT" | sed 's/^/    /'
                echo ""
                echo "Automatic installation cannot proceed safely. To install manually, run:"
                echo "   sudo apt-get install --no-upgrade ${MISSING_PACKAGES[*]}"
            else
                if echo "$SIM_OUTPUT" | grep -E -q '^[0-9]+ upgraded'; then
                    UPGRADED_COUNT=$(echo "$SIM_OUTPUT" | grep -E -o '^[0-9]+ upgraded' | cut -d' ' -f1)
                    if [ "$UPGRADED_COUNT" -gt 0 ]; then
                        echo "⚠️  Note: Resolving dependencies may also upgrade $UPGRADED_COUNT existing package(s):"
                        echo "$SIM_OUTPUT" | awk '/The following packages will be upgraded:/{flag=1; next} /^[0-9]+ upgraded/{flag=0} flag {print "     " $0}'
                    else
                        echo "  ✓ No existing packages will be upgraded."
                    fi
                fi

                echo ""
                echo "Safety policy: setup.sh never upgrades existing software silently or runs a full system upgrade."
                PROCEED="n"
                if [ -t 0 ]; then
                    read -r -p "Install missing packages (${MISSING_PACKAGES[*]}) via 'sudo apt-get install --no-upgrade'? [y/N]: " PROCEED
                elif read -r -t 1 PROCEED; then
                    :
                else
                    echo "Non-interactive shell with no input detected; skipping automatic installation."
                    PROCEED="n"
                fi

                case "$PROCEED" in
                    [yY]|[yY][eE][sS])
                        echo "==> Installing missing packages..."
                        sudo apt-get install --no-upgrade -y "${MISSING_PACKAGES[@]}"
                        ;;
                    *)
                        echo ""
                        echo "Package installation skipped."
                        echo "To install missing dependencies manually without upgrading existing packages, run:"
                        echo "   sudo apt-get install --no-upgrade ${MISSING_PACKAGES[*]}"
                        echo ""
                        ;;
                esac
            fi
        else
            echo ""
            echo "Please install missing packages using your distribution's package manager:"
            echo "   ${MISSING_PACKAGES[*]}"
            echo ""
        fi
    else
        echo ""
        echo "==> All required system dependencies are verified as installed. No package changes needed."
    fi
fi

echo ""
echo "==> Configuring portable desktop launcher..."
generate_launcher "$LAUNCHER" 644
generate_launcher "$LOCAL_LAUNCHER" 755
chmod +x "$DIR/run.sh" "$DIR/notch.py"

if [ -f "$DIR/uninstall.sh" ]; then
    chmod +x "$DIR/uninstall.sh"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo "    Installed desktop launcher to $LAUNCHER"
echo "    Generated local launcher at $LOCAL_LAUNCHER"
echo ""
echo "✅ Setup complete! Dynamic Notch is now installed as a desktop application."
echo ""
echo "🚀 How to launch:"
echo "   • Open your desktop Application Menu / GNOME App Grid and launch 'Dynamic Notch'"
echo "   • Or launch from terminal: $DIR/run.sh"
echo ""
echo "⚙️  Optional autostart on login (disabled by default):"
echo "   • Enable:  ./setup.sh --enable-autostart"
echo "   • Disable: ./setup.sh --disable-autostart"
echo "   • Status:  ./setup.sh --status"
echo ""
echo "🗑️  Uninstallation:"
echo "   • Run:     ./uninstall.sh"
