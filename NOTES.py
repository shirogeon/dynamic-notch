#!/usr/bin/env python3
"""
Dynamic Notch - GTK4 signal blocking utility
GTK4 Gtk.Scale doesn't have block_signal by name directly.
This patch file fixes the approach.
"""
# Patch: use handler_block_by_func instead
# Applied inline in notch.py via _seek_dragging/_vol_dragging flags
