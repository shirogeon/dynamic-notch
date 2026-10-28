#!/usr/bin/env bash
# run.sh — Run Dynamic Notch
DIR="$(cd "$(dirname "$0")" && pwd)"
export GDK_BACKEND=x11
exec python3 -u "$DIR/notch.py" "$@"
