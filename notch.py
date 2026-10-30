#!/usr/bin/env python3
# Copyright (c) 2026 Shiroge (Leon)
# SPDX-License-Identifier: MIT
"""
Custom Dynamic Island Desktop Companion for Linux
Platform: Linux / Wayland (via XWayland backend)
Framework: GTK 3 (PyGObject) + Cairo

Features:
- Fixed-canvas transparent architecture (no window-resize stutter / flicker)
- Premium black-glass macOS / Nusa aesthetic with satin highlight sheen
- Robust multi-stage LRCLIB synced lyrics (no stale data, no album name fallbacks)
- Spotify MPRIS player: album art, seekbar, playback controls, volume
- Battery & TWS headphone status in mini pill
- Auto background water reminder (notify-send, no UI dashboard)
- Seamless cubic ease-out 60 FPS transitions
"""

import os
import sys
import time
import math
import struct
import shutil
import ctypes
from ctypes import c_int, c_ulong, POINTER, byref
import json
import re
import glob
import fcntl
import tempfile
import urllib.request
import urllib.parse
import threading
import subprocess
from datetime import date

# Force X11 backend under Wayland for proper floating top-dock positioning
os.environ["GDK_BACKEND"] = "x11"

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango
import cairo
import dbus
import dbus.mainloop.glib

# ─────────────────────────────────────────────────────────────
#  LAYOUT & TIMING CONSTANTS
# ─────────────────────────────────────────────────────────────
CANVAS_W = 440              # Fixed transparent window canvas width
CANVAS_H = 220              # Fixed transparent window canvas height

IDLE_W = 180                # Resting camera notch cover (no media)
IDLE_H = 30

COMPACT_W = 280             # Compact playing/paused capsule (270-300 px target)
COMPACT_H = 44              # (44-48 px target)

EXPANDED_W = 400            # Expanded music player (390-420 px target)
EXPANDED_H = 178            # (155-185 px target, with 2-line lyric area)
EXPANDED_H_NOLYRIC = 146    # (145-175 px target, without lyric line)

EMPTY_EXPANDED_W = 240      # When expanded with no media playing
EMPTY_EXPANDED_H = 48

NOTIF_W = 280               # Transient notification pill
NOTIF_H = 40

MARGIN_TOP_SCREEN = 0       # Flush with screen top when top panel is hidden
MARGIN_TOP_PANEL = 0        # Flush with bottom edge of top panel when present

ANIM_EXPAND_MS = 300        # 300ms organic fluid expansion (280-320 ms target)
ANIM_COLLAPSE_MS = 250      # 250ms responsive cushioned collapse (230-270 ms target)
ANIM_DURATION_MS = ANIM_EXPAND_MS  # Backward-compatible duration alias
ANIM_INTERVAL_MS = 16       # 60 FPS fallback tick interval
COLLAPSE_DELAY_MS = 500     # Collapse grace period after mouse leaves
UPDATE_INTERVAL_MS = 1000   # Polling interval for battery/media stats
LYRIC_TICK_MS = 150         # 150ms lyric sync polling
ACTIVITY_TICK_MS = 33       # ~30 FPS equalizer wave tick
CINEMA_POLL_MS = 200        # Cinema mode fullscreen poll interval
ART_SIZE_COMPACT = 28       # Compact album art thumbnail (px)
ART_SIZE_EXPANDED = 44      # Expanded album art dimensions (px)

WATER_REMINDER_INTERVAL_MIN = 5   # Background water reminder interval

CONFIG_DIR = os.path.expanduser("~/.config/dynamic-notch")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# ─────────────────────────────────────────────────────────────
#  GTK 3 CSS STYLESHEET
# ─────────────────────────────────────────────────────────────
CSS = """
/* Transparent Root Canvas */
window, .canvas-root {
    background-color: transparent;
    background: transparent;
    border: none;
    box-shadow: none;
}

/* ── IDLE STATE (Camera Notch Cover) ── */
.idle-box {
    padding: 5px 16px;
}
.camera-dot {
    background-color: #34d058;
    border-radius: 50%;
    min-width: 6px;
    min-height: 6px;
}
.idle-text {
    color: #73737B;
    font-size: 10.5px;
    font-weight: 500;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    letter-spacing: 0.1px;
}

/* ── EMPTY EXPANDED STATE (Hovered with no media) ── */
.empty-box {
    padding: 12px 20px;
}
.empty-text {
    color: #73737B;
    font-size: 11px;
    font-weight: 500;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}

/* ── COMPACT MEDIA STATE (280x44) ── */
.compact-box {
    padding: 4px 14px 4px 12px;
}
.compact-art {
    border-radius: 6px;
}
.compact-art-placeholder {
    background: #101012;
    border-radius: 6px;
    min-width: 28px;
    min-height: 28px;
}
.compact-title {
    color: #F5F5F7;
    font-size: 12px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    letter-spacing: -0.15px;
}
.compact-artist {
    color: #A1A1A8;
    font-size: 10.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}

/* ── TRANSIENT NOTIFICATION OVERLAY ── */
.notif-box {
    padding: 6px 16px;
}
.notif-icon {
    color: #EEEEF0;
    font-size: 12px;
    margin-right: 6px;
}
.notif-title {
    color: #F5F5F7;
    font-size: 11px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
.notif-sub {
    color: #A1A1A8;
    font-size: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Mono", monospace;
    margin-left: 6px;
}

/* ── EXPANDED MUSIC PLAYER VIEW (400x178 / 400x146) ── */
.full-box {
    padding: 14px 20px 12px 20px;
}

/* Row 1: Header */
.album-art {
    border-radius: 8px;
}
.art-placeholder {
    background: #101012;
    border-radius: 8px;
    min-width: 44px;
    min-height: 44px;
}
.art-click-area {
    border-radius: 8px;
}
.full-title {
    color: #F5F5F7;
    font-size: 13.5px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", sans-serif;
    letter-spacing: -0.2px;
}
.full-artist {
    color: #A1A1A8;
    font-size: 11.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}

/* Row 2: Subdued Lyric Preview */
.lyric-row {
    padding: 0;
}
.full-lyric {
    color: #A1A1A8;
    font-size: 11.5px;
    font-weight: 400;
    font-style: italic;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    letter-spacing: -0.1px;
}

/* Row 3: Seekbar & Timestamps */
.time-label {
    color: #73737B;
    font-size: 9.5px;
    font-weight: 500;
    font-family: -apple-system, BlinkMacSystemFont, "SF Mono", "JetBrains Mono", monospace;
    letter-spacing: 0.2px;
}
scale {
    padding: 0;
    margin: 0;
}
scale trough {
    background-color: #343438;
    border-radius: 2px;
    min-height: 3px;
    border: none;
}
scale slider {
    background-color: #D8D8DC;
    border-radius: 50%;
    min-width: 8px;
    min-height: 8px;
    border: none;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
}
.seek-slider highlight {
    background-color: #D8D8DC;
    border-radius: 2px;
    min-height: 3px;
    border: none;
}

/* Row 4: Playback Controls (AC-05: Minimal glyphs, no discs, no borders) */
button.ctrl-btn,
button.ctrl-btn:backdrop,
button.ctrl-btn:disabled,
button.ctrl-btn-play,
button.ctrl-btn-play:backdrop,
button.ctrl-btn-play:disabled {
    background: transparent;
    background-color: transparent;
    background-image: none;
    border: none;
    border-color: transparent;
    border-radius: 50%;
    box-shadow: none;
    outline: none;
    padding: 0;
    color: #EEEEF0;
    -gtk-icon-shadow: none;
}
button.ctrl-btn:disabled,
button.ctrl-btn-play:disabled {
    color: #5B5B61;
}
button.ctrl-btn {
    min-width: 34px;
    min-height: 34px;
    transition: background-color 120ms ease;
}
button.ctrl-btn:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: #FFFFFF;
}
button.ctrl-btn-play {
    min-width: 36px;
    min-height: 36px;
    transition: background-color 120ms ease;
}
button.ctrl-btn-play:hover {
    background-color: rgba(255, 255, 255, 0.12);
    color: #FFFFFF;
}

/* Persistent Bluetooth Headset UI */
.full-bt-box {
    margin-right: 6px;
}
.full-bt-name {
    color: #F5F5F7;
    font-size: 11px;
    font-weight: 500;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
.full-bt-battery {
    color: #A1A1A8;
    font-size: 9.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
.empty-bt-label {
    color: #A1A1A8;
    font-size: 10.5px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    margin-left: 8px;
}
"""

# ─────────────────────────────────────────────────────────────
#  CAIRO PIXBUF ROUNDING HELPER
# ─────────────────────────────────────────────────────────────
def round_corners_pixbuf(pixbuf, radius=8):
    w, h = pixbuf.get_width(), pixbuf.get_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    r = float(radius)
    cr.new_sub_path()
    cr.arc(w - r, r, r, -1.5707963, 0)
    cr.arc(w - r, h - r, r, 0, 1.5707963)
    cr.arc(r, h - r, r, 1.5707963, 3.1415926)
    cr.arc(r, r, r, 3.1415926, 4.7123889)
    cr.close_path()
    cr.clip()
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.paint()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, w, h)

def format_time(microseconds: int) -> str:
    s = max(0, microseconds // 1_000_000)
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"

def _anim_curve(progress: float, is_expanding: bool = True) -> float:
    """Organic critically damped spring curve with zero overshoot and smooth takeoff.

    - Expanding: omega = 6.5 (soft organic fluid bloom over ~300 ms).
    - Collapsing: omega = 7.5 (snappy, cushioned retraction over ~250 ms).
    Guaranteed boundary conditions: f(0.0) == 0.0, f(1.0) == 1.0, strictly monotonic.
    """
    if progress <= 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    omega = 6.5 if is_expanding else 7.5
    raw = 1.0 - (1.0 + omega * progress) * math.exp(-omega * progress)
    norm = 1.0 - (1.0 + omega) * math.exp(-omega)
    return raw / norm

# ─────────────────────────────────────────────────────────────
#  PIPEWIRE AUDIO LEVEL MONITOR (Audio-Reactive Equalizer)
# ─────────────────────────────────────────────────────────────
class BiquadBandpass:
    """Second-order IIR Biquad Bandpass filter with constant 0 dB peak gain.
    Provides wide, musical frequency-region energy integration around anchor frequencies.
    """
    def __init__(self, f0: float, Q: float = 1.2, fs: float = 8000.0):
        self.f0 = f0
        self.Q = Q
        self.fs = fs
        w0 = 2.0 * math.pi * f0 / fs
        alpha = math.sin(w0) / (2.0 * Q)
        b0 = math.sin(w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * math.cos(w0)
        a2 = 1.0 - alpha
        self.b0 = b0 / a0
        self.b2 = -b0 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0
        self.reset()

    def reset(self):
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def process(self, samples) -> float:
        """Processes samples through the filter and returns mean squared energy."""
        if not samples:
            return 0.0
        energy = 0.0
        b0, b2, a1, a2 = self.b0, self.b2, self.a1, self.a2
        x1, x2, y1, y2 = self.x1, self.x2, self.y1, self.y2
        for x in samples:
            y = b0 * (x - x2) - a1 * y1 - a2 * y2
            x2, x1 = x1, x
            y2, y1 = y1, y
            energy += y * y
        self.x1, self.x2, self.y1, self.y2 = x1, x2, y1, y2
        return energy / max(1, len(samples))


class AudioLevelMonitor:
    """Captures real-time audio from default PipeWire audio sink monitor stream.
    Computes 3-band energy (Bass ~160Hz, Mid ~800Hz, Treble ~2400Hz) using 2nd-order
    IIR Biquad bandpass filter bank with perceptual loudness mapping and peak tracking.
    Thread-safe, non-blocking, follows default sink changes (speakers <-> Bluetooth TWS),
    with graceful fallback.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._bp_bass = BiquadBandpass(160.0, Q=1.2, fs=8000.0)
        self._bp_mid = BiquadBandpass(800.0, Q=1.2, fs=8000.0)
        self._bp_treble = BiquadBandpass(2400.0, Q=1.2, fs=8000.0)
        self._peak = 1200.0
        self._levels = [0.25, 0.25, 0.25]
        self._is_playing = False
        self._running = True
        self._proc = None
        self._source_name = "Initializing..."
        self._current_sink_name = None
        self._restart_requested = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def set_playing(self, playing: bool):
        with self._lock:
            self._is_playing = playing

    def get_levels(self) -> list:
        with self._lock:
            return list(self._levels)

    def get_source_name(self) -> str:
        with self._lock:
            return self._source_name

    def reset_filters(self):
        """Resets filter memories, peak tracker, and resting levels."""
        with self._lock:
            if hasattr(self, "_bp_bass") and self._bp_bass is not None:
                self._bp_bass.reset()
            if hasattr(self, "_bp_mid") and self._bp_mid is not None:
                self._bp_mid.reset()
            if hasattr(self, "_bp_treble") and self._bp_treble is not None:
                self._bp_treble.reset()
            self._peak = 1200.0
            self._levels = [0.25, 0.25, 0.25]

    def stop(self):
        self._running = False
        self._stop_recorder()
        if hasattr(self, "_thread") and self._thread.is_alive() and threading.current_thread() != self._thread:
            try:
                self._thread.join(timeout=0.5)
            except Exception:
                pass

    def _stop_recorder(self):
        with self._lock:
            self._restart_requested = True
            proc = self._proc
            self._proc = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=0.2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
        self.reset_filters()

    def restart_recorder(self):
        """Signals worker to cleanly terminate and restart recorder on active sink."""
        self._stop_recorder()

    @staticmethod
    def compute_goertzel(samples, target_freq: float, sample_rate: float = 8000.0) -> float:
        """Goertzel algorithm to compute single-frequency DFT power with O(N) complexity."""
        N = len(samples)
        if N == 0:
            return 0.0
        k = int(0.5 + (N * target_freq) / sample_rate)
        omega = (2.0 * math.pi * k) / N
        coeff = 2.0 * math.cos(omega)
        s_prev = 0.0
        s_prev2 = 0.0
        for x in samples:
            s = x + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        return max(0.0, s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2)

    def process_samples(self, samples, is_playing: bool = True) -> list:
        """Processes a 256-sample PCM chunk and returns updated [bass, mid, treble] levels in [0.0, 1.0]."""
        with self._lock:
            cur_levels = list(self._levels)
            peak = self._peak

        if not is_playing or not samples:
            for j in range(3):
                cur_levels[j] = cur_levels[j] * 0.82 + 0.25 * 0.18
            with self._lock:
                self._levels = list(cur_levels)
            return list(cur_levels)

        rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
        if rms < 35.0:  # Silence or near noise floor
            for j in range(3):
                cur_levels[j] = cur_levels[j] * 0.82 + 0.25 * 0.18
            with self._lock:
                self._levels = list(cur_levels)
            return list(cur_levels)

        e_b = self._bp_bass.process(samples)
        e_m = self._bp_mid.process(samples)
        e_t = self._bp_treble.process(samples)

        # Treble pink noise tilt compensation
        amps = [
            math.sqrt(max(0.0, e_b)),
            math.sqrt(max(0.0, e_m)),
            math.sqrt(max(0.0, e_t)) * 1.15,
        ]

        # Shared peak follower preserves inter-band spectral balance
        peak = max(1200.0, max(peak * 0.993, max(amps)))
        noise_floor = 20.0
        denom = max(1.0, peak - noise_floor)

        for j in range(3):
            usable = max(0.0, amps[j] - noise_floor)
            ratio = min(1.0, usable / denom)
            comp = ratio ** 0.65  # Perceptual dynamic compression
            target = 0.20 + 0.75 * comp

            # Asymmetric attack/release smoothing
            if target > cur_levels[j]:
                cur_levels[j] = cur_levels[j] * 0.35 + target * 0.65
            else:
                cur_levels[j] = cur_levels[j] * 0.82 + target * 0.18

        with self._lock:
            self._peak = peak
            self._levels = list(cur_levels)

        return list(cur_levels)

    def get_default_sink_info(self):
        """Queries WirePlumber for active default audio sink name and description."""
        try:
            out = subprocess.check_output(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                stderr=subprocess.DEVNULL,
                timeout=1.0
            ).decode("utf-8")
            node_name = None
            node_desc = None
            for line in out.splitlines():
                line = line.strip()
                if "node.name =" in line:
                    node_name = line.split("=")[1].strip().strip('"')
                elif "node.description =" in line:
                    node_desc = line.split("=")[1].strip().strip('"')
            return node_name, node_desc
        except Exception:
            return None, None

    def get_recorder_sources(self):
        """Inspects actual PipeWire links feeding pw-record input ports."""
        try:
            out = subprocess.check_output(
                ["pw-link", "-l"],
                stderr=subprocess.DEVNULL,
                timeout=1.0
            ).decode("utf-8")
            sources = set()
            current_dest = None
            for line in out.splitlines():
                line_s = line.strip()
                if line_s.startswith("|<- "):
                    src = line_s[4:].strip()
                    if current_dest and "pw-record" in current_dest:
                        sources.add(src)
                elif not line.startswith(" "):
                    current_dest = line.strip()
            return sources
        except Exception:
            return set()

    def check_default_sink(self):
        """Checks if current capture is attached to active default sink monitor."""
        if not self._running:
            return

        sink_name, sink_desc = self.get_default_sink_info()
        if not sink_name:
            return

        with self._lock:
            proc = self._proc

        if not proc or proc.poll() is not None:
            self.restart_recorder()
            return

        sources = self.get_recorder_sources()
        if not sources:
            return

        is_correct = True
        has_mic = False
        for s in sources:
            if ":" in s:
                node, port = s.rsplit(":", 1)
                if "capture" in port.lower():
                    has_mic = True
                if node != sink_name:
                    is_correct = False

        if has_mic or not is_correct:
            self.restart_recorder()
        else:
            with self._lock:
                self._current_sink_name = sink_name
                self._source_name = f"PipeWire ({sink_desc or sink_name})"

    def _worker(self):
        pw_path = shutil.which("pw-record")
        if not pw_path:
            with self._lock:
                self._source_name = "Pseudo-reactive fallback (pw-record not installed)"
            self._fallback_loop()
            return

        while self._running:
            with self._lock:
                self._restart_requested = False

            sink_name, sink_desc = self.get_default_sink_info()
            sink_label = sink_desc or sink_name or "@DEFAULT_AUDIO_SINK@"

            cmd = [
                pw_path,
                "--media-category=Monitor",
                "-P", '{ stream.capture.sink: true }',
                "--target", "@DEFAULT_AUDIO_SINK@",
                "--latency", "32ms",
                "--rate", "8000",
                "--channels", "1",
                "--format", "s16",
                "--raw", "-"
            ]

            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=1024
                )
                with self._lock:
                    self._proc = proc
                    self._current_sink_name = sink_name
                    self._source_name = f"PipeWire ({sink_label})"
            except Exception as e:
                with self._lock:
                    self._source_name = f"Fallback ({e})"
                self._run_fallback_ticks(duration_sec=0.5)
                continue

            chunk_bytes = 512  # 256 samples of 16-bit PCM = 32ms at 8000 Hz mono
            buf = bytearray()
            chunk_count = 0

            try:
                while self._running:
                    with self._lock:
                        if self._restart_requested:
                            break

                    needed = chunk_bytes - len(buf)
                    try:
                        raw = proc.stdout.read(needed)
                    except Exception:
                        break

                    if not raw:
                        if proc.poll() is not None:
                            break  # Subprocess exited or audio sink disconnected
                        time.sleep(0.01)
                        continue

                    buf.extend(raw)
                    if len(buf) < chunk_bytes:
                        continue

                    chunk = bytes(buf[:chunk_bytes])
                    del buf[:chunk_bytes]

                    chunk_count += 1
                    if chunk_count % 30 == 0:
                        self.check_default_sink()
                        with self._lock:
                            if self._restart_requested:
                                break

                    samples = struct.unpack("<256h", chunk)
                    with self._lock:
                        is_play = self._is_playing

                    self.process_samples(samples, is_playing=is_play)

            except Exception:
                time.sleep(0.05)
            finally:
                if proc:
                    try:
                        proc.terminate()
                        proc.wait(timeout=0.2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        if proc.stdout:
                            proc.stdout.close()
                    except Exception:
                        pass
                with self._lock:
                    if self._proc == proc:
                        self._proc = None

            if self._running:
                self._run_fallback_ticks(duration_sec=0.2)

    def _run_fallback_ticks(self, duration_sec: float = 0.5):
        """Smoothly decays or animates levels during transitions or when audio stream reconnects."""
        end_time = time.time() + duration_sec
        cur_levels = [0.25, 0.25, 0.25]
        while self._running and time.time() < end_time:
            time.sleep(0.033)
            with self._lock:
                is_play = self._is_playing
            if not is_play:
                for j in range(3):
                    cur_levels[j] = cur_levels[j] * 0.88 + 0.25 * 0.12
            else:
                t = time.time()
                targets = [
                    0.25 + 0.65 * (math.sin(t * 8.0) ** 2),
                    0.20 + 0.75 * (math.sin(t * 12.0 + 1.2) ** 2),
                    0.25 + 0.60 * (math.sin(t * 16.0 + 2.5) ** 2),
                ]
                for j in range(3):
                    cur_levels[j] = cur_levels[j] * 0.4 + targets[j] * 0.6
            with self._lock:
                self._levels = list(cur_levels)

    def _fallback_loop(self):
        """Permanent fallback loop when pw-record binary is completely unavailable."""
        while self._running:
            self._run_fallback_ticks(duration_sec=1.0)

# ─────────────────────────────────────────────────────────────
#  MEDIA ACTIVITY EQUALIZER INDICATOR (Apple Music-style Wave)
# ─────────────────────────────────────────────────────────────
class MediaActivityIndicator(Gtk.DrawingArea):
    def __init__(self, size=16, monitor: AudioLevelMonitor = None):
        super().__init__()
        self.set_size_request(size, size)
        self._size = size
        self._playing = False
        self._bars = [0.25, 0.25, 0.25]
        self._monitor = monitor
        self.connect("draw", self._on_draw)

    def set_monitor(self, monitor: AudioLevelMonitor):
        self._monitor = monitor

    def set_playing(self, is_playing: bool):
        self._playing = is_playing
        if not is_playing:
            self._bars = [0.25, 0.25, 0.25]
        self.queue_draw()

    def tick(self):
        if self._monitor:
            targets = self._monitor.get_levels()
            changed = False
            for i in range(3):
                new_bar = self._bars[i] * 0.65 + targets[i] * 0.35
                if abs(new_bar - self._bars[i]) > 0.001:
                    changed = True
                self._bars[i] = new_bar
            if changed:
                self.queue_draw()

    def _on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        # AC-07: Silver-white equalizer bars (#EEEEF0)
        cr.set_source_rgba(238/255.0, 238/255.0, 240/255.0, 0.95)
        bar_w = 2.0
        gap = 2.0
        total_w = 3 * bar_w + 2 * gap
        start_x = (w - total_w) / 2.0
        max_bar_h = h * 0.75

        for i, frac in enumerate(self._bars):
            bx = start_x + i * (bar_w + gap)
            bh = max(2.5, frac * max_bar_h)
            by = (h - bh) / 2.0
            r = bar_w / 2.0
            cr.new_sub_path()
            cr.arc(bx + r, by + r, r, math.pi, 0)
            cr.arc(bx + r, by + bh - r, r, 0, math.pi)
            cr.close_path()
            cr.fill()
        return False

# ─────────────────────────────────────────────────────────────
#  MEDIA CONTROLLER (MPRIS / SPOTIFY + D-BUS SIGNALS)
# ─────────────────────────────────────────────────────────────
class MediaController:
    def __init__(self, on_change_callback=None):
        self._bus = dbus.SessionBus()
        self._player = None
        self._props = None
        self._name = None
        self._cached_art_url = None
        self._cached_pixbuf_expanded = None
        self._cached_pixbuf_compact = None
        self._on_change_callback = on_change_callback
        self._scan()

        self._bus.add_signal_receiver(
            self._on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus"
        )
        self._bus.add_signal_receiver(
            self._on_props_changed,
            signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties",
            path="/org/mpris/MediaPlayer2"
        )

    def _on_props_changed(self, iface, changed, invalidated):
        if self._on_change_callback and ("Metadata" in changed or "PlaybackStatus" in changed):
            GLib.idle_add(self._on_change_callback)

    def _on_name_owner_changed(self, name, old_owner, new_owner):
        if name.startswith("org.mpris.MediaPlayer2."):
            if new_owner:
                self._connect(name)
            elif name == self._name:
                self._player = None
                self._props = None
                self._name = None
                self._cached_art_url = None
                self._cached_pixbuf_expanded = None
                self._cached_pixbuf_compact = None
                self._scan()
            if self._on_change_callback:
                GLib.idle_add(self._on_change_callback)

    def _scan(self):
        try:
            names = [n for n in self._bus.list_names() if n.startswith("org.mpris.MediaPlayer2.")]
            if not names:
                return
            spotify = [n for n in names if "spotify" in n.lower()]
            target = spotify[0] if spotify else names[0]
            self._connect(target)
        except Exception:
            pass

    def _connect(self, name):
        try:
            obj = self._bus.get_object(name, "/org/mpris/MediaPlayer2")
            self._player = dbus.Interface(obj, "org.mpris.MediaPlayer2.Player")
            self._props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            self._name = name
        except Exception:
            self._player = None
            self._props = None
            self._name = None

    def is_available(self):
        if not self._props:
            self._scan()
        return self._props is not None

    def get_position_us(self) -> int:
        """Fast D-Bus position query (<1ms) for high-frequency lyric sync."""
        if not self._props:
            return 0
        try:
            return int(self._props.Get("org.mpris.MediaPlayer2.Player", "Position"))
        except Exception:
            return 0

    def get_info(self):
        default = {
            "title": None,
            "artist": None,
            "album": None,
            "length_us": 0,
            "position_us": 0,
            "status": "Stopped",
            "track_id": "/",
            "art_url": None,
            "pixbuf": None,
            "pixbuf_compact": None,
        }
        if not self.is_available():
            self._cached_art_url = None
            self._cached_pixbuf_expanded = None
            self._cached_pixbuf_compact = None
            return default
        try:
            p = self._props.GetAll("org.mpris.MediaPlayer2.Player")
            meta = p.get("Metadata", {})
            title = str(meta.get("xesam:title", "")) or None
            artists = meta.get("xesam:artist", [])
            artist = str(artists[0]) if artists else None
            album = str(meta.get("xesam:album", "")) or None
            length_us = int(meta.get("mpris:length", 0))
            position_us = int(p.get("Position", 0))
            status = str(p.get("PlaybackStatus", "Stopped"))
            track_id = str(meta.get("mpris:trackid", "/"))
            art_url = str(meta.get("mpris:artUrl", "")) or None

            if art_url:
                if art_url != self._cached_art_url:
                    self._cached_art_url = art_url
                    threading.Thread(target=self._fetch_art, args=(art_url,), daemon=True).start()
            else:
                self._cached_art_url = None
                self._cached_pixbuf_expanded = None
                self._cached_pixbuf_compact = None

            return {
                "title": title,
                "artist": artist,
                "album": album,
                "length_us": length_us,
                "position_us": position_us,
                "status": status,
                "track_id": track_id,
                "art_url": art_url,
                "pixbuf": self._cached_pixbuf_expanded,
                "pixbuf_compact": self._cached_pixbuf_compact,
            }
        except Exception:
            self._player = None
            self._props = None
            self._name = None
            self._cached_art_url = None
            self._cached_pixbuf_expanded = None
            self._cached_pixbuf_compact = None
            return default

    def _fetch_art(self, url):
        cache_file = "/tmp/dynamic_notch_art.jpg"
        try:
            urllib.request.urlretrieve(url, cache_file)
            pb_exp = GdkPixbuf.Pixbuf.new_from_file_at_scale(cache_file, ART_SIZE_EXPANDED, ART_SIZE_EXPANDED, True)
            exp = round_corners_pixbuf(pb_exp, radius=8)
            pb_comp = GdkPixbuf.Pixbuf.new_from_file_at_scale(cache_file, ART_SIZE_COMPACT, ART_SIZE_COMPACT, True)
            comp = round_corners_pixbuf(pb_comp, radius=6)
            if self._cached_art_url == url:
                self._cached_pixbuf_expanded = exp
                self._cached_pixbuf_compact = comp
                if self._on_change_callback:
                    GLib.idle_add(self._on_change_callback)
        except Exception:
            if self._cached_art_url == url:
                self._cached_pixbuf_expanded = None
                self._cached_pixbuf_compact = None

    def play_pause(self):
        if self.is_available():
            try:
                self._player.PlayPause()
            except Exception:
                pass

    def next(self):
        if self.is_available():
            try:
                self._player.Next()
            except Exception:
                pass

    def prev(self):
        if self.is_available():
            try:
                self._player.Previous()
            except Exception:
                pass

    def seek_to(self, position_us, track_id):
        if self.is_available():
            try:
                self._player.SetPosition(dbus.ObjectPath(track_id), dbus.Int64(position_us))
            except Exception:
                pass

    def open_app(self):
        for cmd in (["spotify"], ["xdg-open", "spotify:"]):
            try:
                subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return
            except Exception:
                continue

# ─────────────────────────────────────────────────────────────
#  VOLUME CONTROLLER (PIPEWIRE / WIREPLUMBER)
# ─────────────────────────────────────────────────────────────
class VolumeController:
    def get(self) -> float:
        try:
            out = subprocess.check_output(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                stderr=subprocess.DEVNULL,
                text=True
            )
            m = re.search(r"Volume:\s*([\d.]+)", out)
            if m:
                return float(m.group(1))
        except Exception:
            pass
        return 0.5

    def set(self, fraction: float):
        v = max(0.0, min(1.5, float(fraction)))
        try:
            subprocess.Popen(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{v:.2f}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────
#  BLUETOOTH TWS & LAPTOP BATTERY
# ─────────────────────────────────────────────────────────────
class BluetoothBattery:
    """Monitors connected Bluetooth audio headsets/TWS devices via BlueZ D-Bus and laptop battery.

    Features:
    - Queries BlueZ D-Bus (org.bluez) for connected audio devices.
    - Retrieves device Alias (preferred) or Name (fallback), suppressing raw MAC addresses.
    - Reads org.bluez.Battery1 Percentage and Source.
    - Supports multiple battery components (left, right, case) via Identifier property when exposed.
    - Dispatches live updates on connection, disconnection, and battery percentage changes.
    - Idempotent cleanup of D-Bus signal matches on shutdown.
    - Laptop battery fallback via /sys/class/power_supply.
    """
    AUDIO_SHORT_UUIDS = ("110b", "110a", "111e", "1108", "110c", "110e")
    AUDIO_ICONS = {"audio-headphones", "audio-headset", "audio-card"}

    def __init__(self, on_change_callback=None):
        self._on_change_callback = on_change_callback
        self._bus = None
        self._signal_matches = []
        self._connected_headsets = {}  # dev_path -> dict
        self._primary_headset_path = None
        self._notified_low_batteries = set()

        try:
            self._bus = dbus.SystemBus()
            self._setup_signals()
            self._refresh_headsets()
        except Exception:
            self._bus = None

    def _setup_signals(self):
        if not self._bus:
            return
        try:
            # Monitor property changes (Connected, Percentage, Alias)
            m1 = self._bus.add_signal_receiver(
                self._on_properties_changed,
                signal_name="PropertiesChanged",
                dbus_interface="org.freedesktop.DBus.Properties",
                path_keyword="path"
            )
            self._signal_matches.append(m1)

            # Monitor interface additions (e.g. Battery1 appearing after connection)
            m2 = self._bus.add_signal_receiver(
                self._on_interfaces_added,
                signal_name="InterfacesAdded",
                dbus_interface="org.freedesktop.DBus.ObjectManager",
                path_keyword="signal_path"
            )
            self._signal_matches.append(m2)

            # Monitor interface removals (e.g. device disconnected)
            m3 = self._bus.add_signal_receiver(
                self._on_interfaces_removed,
                signal_name="InterfacesRemoved",
                dbus_interface="org.freedesktop.DBus.ObjectManager",
                path_keyword="signal_path"
            )
            self._signal_matches.append(m3)

            # Monitor BlueZ service lifecycle
            m4 = self._bus.add_signal_receiver(
                self._on_name_owner_changed,
                signal_name="NameOwnerChanged",
                dbus_interface="org.freedesktop.DBus"
            )
            self._signal_matches.append(m4)
        except Exception:
            pass

    def _on_name_owner_changed(self, name, old_owner, new_owner):
        if name == "org.bluez":
            if not new_owner:
                self._connected_headsets.clear()
                self._primary_headset_path = None
                if self._on_change_callback:
                    self._on_change_callback("disconnected", {"name": "Bluetooth Headset"})
            else:
                refreshed = self._refresh_headsets()
                if refreshed is not None:
                    self._connected_headsets = refreshed
                primary = self.get_headset_info()
                if primary and self._on_change_callback:
                    self._on_change_callback("connected", primary)

    def _is_mac_address(self, s: str) -> bool:
        if not s:
            return False
        clean = s.replace("_", ":").replace("-", ":")
        parts = clean.split(":")
        if len(parts) == 6 and all(len(p) == 2 and all(c in "0123456789abcdefABCDEF" for c in p) for p in parts):
            return True
        return s.lower().startswith("dev_")

    def _get_device_display_name(self, dev: dict) -> str:
        alias = dev.get("Alias")
        if alias:
            name = str(alias).strip()
            if name and not self._is_mac_address(name):
                return name
        name_prop = dev.get("Name")
        if name_prop:
            name = str(name_prop).strip()
            if name and not self._is_mac_address(name):
                return name
        return "Bluetooth Headset"

    def _is_audio_device(self, dev: dict) -> bool:
        icon = str(dev.get("Icon", "")).lower()
        if icon in self.AUDIO_ICONS or icon.startswith("audio-"):
            return True
        try:
            cod = int(dev.get("Class", 0))
            if (cod & 0x1F00) == 0x0400 or (cod & 0x200000) != 0:
                return True
        except Exception:
            pass
        uuids = [str(u).lower() for u in dev.get("UUIDs", [])]
        for u in uuids:
            for s in self.AUDIO_SHORT_UUIDS:
                if s in u:
                    return True
        return False

    def _extract_battery(self, dev_path: str, all_objects: dict) -> tuple[int | None, str, dict]:
        """Extracts battery percentage, readable string, and components for a device path."""
        components = {}
        aggregate_pct = None
        aggregate_source = None

        for path, ifaces in all_objects.items():
            if path == dev_path or str(path).startswith(str(dev_path) + "/"):
                if "org.bluez.Battery1" in ifaces:
                    bat = ifaces["org.bluez.Battery1"]
                    ident = str(bat.get("Identifier", "")).lower().strip()
                    pct = None
                    if "Percentage" in bat:
                        try:
                            raw_pct = int(bat["Percentage"])
                            if 0 <= raw_pct <= 100:
                                pct = raw_pct
                        except Exception:
                            pct = None
                    source = str(bat.get("Source", "")) if "Source" in bat else None

                    if ident:
                        components[ident] = {
                            "percent": pct,
                            "source": source
                        }
                    else:
                        if pct is not None:
                            aggregate_pct = pct
                        if source:
                            aggregate_source = source

        comp_parts = []
        for key, label in [("left", "L"), ("right", "R"), ("case", "Case")]:
            if key in components and components[key]["percent"] is not None:
                comp_parts.append(f"{label}: {components[key]['percent']}%")
        for key, val in components.items():
            if key not in ("left", "right", "case") and val["percent"] is not None:
                comp_parts.append(f"{key.capitalize()}: {val['percent']}%")

        if comp_parts:
            battery_text = " · ".join(comp_parts)
            primary_pct = aggregate_pct
            if primary_pct is None:
                valid_pcts = [v["percent"] for v in components.values() if v["percent"] is not None]
                primary_pct = valid_pcts[0] if valid_pcts else None
            return primary_pct, battery_text, components

        if aggregate_pct is not None:
            return aggregate_pct, f"{aggregate_pct}%", components

        return None, "Battery unavailable", components

    def _refresh_headsets(self):
        if not self._bus:
            return {}
        try:
            mgr = dbus.Interface(
                self._bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            objs = mgr.GetManagedObjects()
        except Exception:
            return {}

        return self._refresh_headsets_from_objects(objs)

    def _refresh_headsets_from_objects(self, objs: dict) -> dict:
        new_headsets = {}
        for path, ifaces in objs.items():
            if "org.bluez.Device1" in ifaces:
                dev = ifaces["org.bluez.Device1"]
                if dev.get("Connected") and self._is_audio_device(dev):
                    name = self._get_device_display_name(dev)
                    pct, bat_text, comps = self._extract_battery(path, objs)
                    new_headsets[path] = {
                        "name": name,
                        "percent": pct,
                        "battery_text": bat_text,
                        "components": comps,
                        "is_laptop": False,
                        "connected": True,
                        "charging": False,
                        "path": path,
                    }

        self._connected_headsets = new_headsets
        return new_headsets

    def _on_properties_changed(self, iface, changed, invalidated, path=None, signal_path=None):
        target_path = signal_path if signal_path is not None else path
        if iface == "org.bluez.Device1":
            if "Connected" in changed:
                connected = bool(changed["Connected"])
                if connected:
                    refreshed = self._refresh_headsets()
                    if target_path in refreshed:
                        info = refreshed[target_path]
                        if self._on_change_callback:
                            self._on_change_callback("connected", info)
                else:
                    if target_path in self._connected_headsets:
                        info = self._connected_headsets.pop(target_path)
                        self._notified_low_batteries.discard(target_path)
                        if self._primary_headset_path == target_path:
                            self._primary_headset_path = None
                        if self._on_change_callback:
                            self._on_change_callback("disconnected", info)
            elif "Alias" in changed or "Name" in changed:
                if target_path in self._connected_headsets:
                    new_name = self._get_device_display_name(changed)
                    self._connected_headsets[target_path]["name"] = new_name

        elif iface == "org.bluez.Battery1":
            target_dev = None
            for dev_path in self._connected_headsets:
                if target_path == dev_path or (target_path and str(target_path).startswith(str(dev_path) + "/")):
                    target_dev = dev_path
                    break

            if target_dev:
                refreshed = self._refresh_headsets()
                if target_dev in refreshed:
                    info = refreshed[target_dev]
                    if self._on_change_callback:
                        self._on_change_callback("battery_changed", info)

                    pct = info.get("percent")
                    if pct is not None and pct <= 20:
                        if target_dev not in self._notified_low_batteries:
                            self._notified_low_batteries.add(target_dev)
                            if self._on_change_callback:
                                self._on_change_callback("low_battery", info)
                    elif pct is not None and pct > 20:
                        self._notified_low_batteries.discard(target_dev)

    def _on_interfaces_added(self, object_path, interfaces, signal_path=None):
        if "org.bluez.Battery1" in interfaces or "org.bluez.Device1" in interfaces:
            was_known = object_path in self._connected_headsets
            refreshed = self._refresh_headsets()
            for dev_path, info in refreshed.items():
                if object_path == dev_path or str(object_path).startswith(str(dev_path) + "/"):
                    if self._on_change_callback:
                        event_type = "connected" if (not was_known and object_path == dev_path) else "battery_changed"
                        self._on_change_callback(event_type, info)
                    break

    def _on_interfaces_removed(self, object_path, interfaces, signal_path=None):
        if "org.bluez.Device1" in interfaces and object_path in self._connected_headsets:
            info = self._connected_headsets.pop(object_path)
            self._notified_low_batteries.discard(object_path)
            if self._primary_headset_path == object_path:
                self._primary_headset_path = None
            if self._on_change_callback:
                self._on_change_callback("disconnected", info)
        elif "org.bluez.Battery1" in interfaces:
            target_dev = None
            for dev_path in self._connected_headsets:
                if object_path == dev_path or str(object_path).startswith(str(dev_path) + "/"):
                    target_dev = dev_path
                    break
            if target_dev:
                refreshed = self._refresh_headsets()
                if target_dev in refreshed and self._on_change_callback:
                    self._on_change_callback("battery_changed", refreshed[target_dev])

    def get_headset_info(self):
        """Returns info for the primary connected headset, or None."""
        if not self._connected_headsets:
            self._refresh_headsets()
        if not self._connected_headsets:
            self._primary_headset_path = None
            return None
        if self._primary_headset_path not in self._connected_headsets:
            self._primary_headset_path = sorted(self._connected_headsets.keys())[0]
        return self._connected_headsets[self._primary_headset_path]

    def get_laptop_battery(self):
        """Returns laptop battery info, or None."""
        try:
            caps = glob.glob("/sys/class/power_supply/BAT*/capacity")
            if caps:
                with open(caps[0], "r") as f:
                    cap = int(f.read().strip())
                status = "Discharging"
                stats = glob.glob("/sys/class/power_supply/BAT*/status")
                if stats:
                    with open(stats[0], "r") as f:
                        status = f.read().strip()
                charging = (status == "Charging")
                return {
                    "name": "Laptop",
                    "percent": cap,
                    "battery_text": f"{cap}%",
                    "components": {},
                    "is_laptop": True,
                    "connected": False,
                    "charging": charging,
                }
        except Exception:
            pass
        return None

    def get_info(self):
        """Returns connected headset info if available, otherwise laptop battery."""
        headset = self.get_headset_info()
        if headset:
            return headset
        return self.get_laptop_battery()

    def close(self):
        for match in self._signal_matches:
            try:
                match.remove()
            except Exception:
                pass
        self._signal_matches.clear()
        self._connected_headsets.clear()
        self._primary_headset_path = None
        self._notified_low_batteries.clear()

# ─────────────────────────────────────────────────────────────
#  ROBUST MULTI-STAGE SYNCED LYRICS CONTROLLER (LRCLIB)
# ─────────────────────────────────────────────────────────────
class LyricsController:
    """
    Fetches synchronized timed lyrics from LRCLIB.
    Guarantees:
    - Never fabricates metadata or substitutes album names for lyrics
    - Automatic title sanitization & multi-stage lookup (exact -> clean -> search)
    - Thread token lifecycle to eliminate race conditions on track skip
    """
    LRCLIB_GET = "https://lrclib.net/api/get"
    LRCLIB_SEARCH = "https://lrclib.net/api/search"

    STATUS_IDLE = "idle"
    STATUS_LOADING = "loading"
    STATUS_SYNCED = "synced"
    STATUS_INSTRUMENTAL = "instrumental"
    STATUS_UNAVAILABLE = "unavailable"

    def __init__(self):
        self._cache = {}  # key -> (status, lines)
        self._current_key = None
        self._token = 0
        self._status = self.STATUS_IDLE
        self._lines = []  # list of (ts_ms, text)

    @staticmethod
    def clean_title(title: str) -> str:
        if not title:
            return ""
        t = re.sub(r'[\(\[](?:feat|with|remaster|radio edit|deluxe|bonus|live|version|from).*?[\)\]]', '', title, flags=re.IGNORECASE)
        t = re.sub(r' - .*(?:remaster|edit|version|live|deluxe).*$', '', t, flags=re.IGNORECASE)
        return t.strip()

    def _make_key(self, title: str, artist: str) -> str:
        return f"{artist.lower().strip()}|{title.lower().strip()}"

    def update_track(self, title: str | None, artist: str | None, album: str | None = None, duration_s: int = 0):
        if not title or not artist:
            self._current_key = None
            self._status = self.STATUS_IDLE
            self._lines = []
            return

        key = self._make_key(title, artist)
        if key == self._current_key:
            return

        self._current_key = key
        self._token += 1
        curr_token = self._token

        if key in self._cache:
            self._status, self._lines = self._cache[key]
            return

        self._status = self.STATUS_LOADING
        self._lines = []

        threading.Thread(
            target=self._fetch_lyrics,
            args=(curr_token, key, title, artist, album, duration_s),
            daemon=True
        ).start()

    @staticmethod
    def _score_candidate(cand: dict, title: str, artist: str, duration_s: int) -> int:
        cand_title = cand.get("trackName") or ""
        cand_artist = cand.get("artistName") or ""
        cand_dur = float(cand.get("duration") or 0)
        has_synced = bool(cand.get("syncedLyrics"))
        is_inst = bool(cand.get("instrumental"))

        # Must provide synchronized lyrics or be marked instrumental
        if not has_synced and not is_inst:
            return -1

        clean_t = LyricsController.clean_title(title).lower()
        clean_ct = LyricsController.clean_title(cand_title).lower()

        # Title compatibility check
        if clean_t == clean_ct:
            title_score = 40
        elif clean_t in clean_ct or clean_ct in clean_t:
            title_score = 25
        else:
            return -1  # Reject candidate with incompatible title

        # Artist compatibility check
        a_low = artist.lower()
        ca_low = cand_artist.lower()
        if a_low == ca_low:
            artist_score = 30
        elif a_low in ca_low or ca_low in a_low:
            artist_score = 20
        else:
            a_words = set(re.findall(r"\w+", a_low))
            ca_words = set(re.findall(r"\w+", ca_low))
            if a_words & ca_words:
                artist_score = 15
            else:
                return -1  # Reject candidate with incompatible artist

        # Duration validation (~4s tolerance initial criterion)
        dur_score = 0
        if duration_s > 0 and cand_dur > 0:
            diff = abs(cand_dur - duration_s)
            if diff <= 2.0:
                dur_score = 30
            elif diff <= 4.5:
                dur_score = 20
            elif diff <= 8.0:
                dur_score = 5
            else:
                return -1  # Reject candidate with obviously different duration (> 8s)

        synced_score = 50 if has_synced else 30
        return synced_score + title_score + artist_score + dur_score

    def _fetch_lyrics(self, token: int, key: str, title: str, artist: str, album: str | None, duration_s: int):
        status = self.STATUS_UNAVAILABLE
        lines = []

        cleaned_title = self.clean_title(title)
        data = None

        # Stage 1A: Exact GET with album (if provided) and duration
        if album:
            params = {"track_name": title, "artist_name": artist}
            if duration_s > 0:
                params["duration"] = duration_s
            params["album_name"] = album
            data = self._http_get(self.LRCLIB_GET, params)

        # Stage 1B: Exact GET without album (fixes Spotify album-edition mismatches)
        if not data:
            params = {"track_name": title, "artist_name": artist}
            if duration_s > 0:
                params["duration"] = duration_s
            data = self._http_get(self.LRCLIB_GET, params)

        # Stage 2: Cleaned title GET with duration
        if not data and cleaned_title and cleaned_title != title:
            params_clean = {"track_name": cleaned_title, "artist_name": artist}
            if duration_s > 0:
                params_clean["duration"] = duration_s
            data = self._http_get(self.LRCLIB_GET, params_clean)

        # Stage 3: Cleaned title GET without duration
        if not data and duration_s > 0:
            params_nodur = {"track_name": cleaned_title if cleaned_title else title, "artist_name": artist}
            data = self._http_get(self.LRCLIB_GET, params_nodur)

        # Stage 4: Search endpoint fallback with candidate scoring & validation
        if not data:
            q_title = cleaned_title if cleaned_title else title
            search_params = {"track_name": q_title, "artist_name": artist}
            search_results = self._http_get_json(self.LRCLIB_SEARCH, search_params)

            if not isinstance(search_results, list) or not search_results:
                search_results = self._http_get_json(self.LRCLIB_SEARCH, {"q": f"{artist} {q_title}"})

            if isinstance(search_results, list) and search_results:
                best_cand = None
                best_score = -1
                for candidate in search_results:
                    score = self._score_candidate(candidate, title, artist, duration_s)
                    if score > best_score:
                        best_score = score
                        best_cand = candidate
                if best_cand and best_score >= 100:
                    data = best_cand

        if data:
            if data.get("instrumental"):
                status = self.STATUS_INSTRUMENTAL
            elif data.get("syncedLyrics"):
                lines = self._parse_lrc(data["syncedLyrics"])
                if lines:
                    status = self.STATUS_SYNCED
                else:
                    status = self.STATUS_UNAVAILABLE
            else:
                status = self.STATUS_UNAVAILABLE

        self._cache[key] = (status, lines)

        if token == self._token:
            GLib.idle_add(self._apply_result, token, status, lines)

    def _apply_result(self, token: int, status: str, lines: list):
        if token == self._token:
            self._status = status
            self._lines = lines
        return False

    def _http_get(self, base_url: str, params: dict):
        res = self._http_get_json(base_url, params)
        return res if isinstance(res, dict) else None

    def _http_get_json(self, base_url: str, params: dict):
        try:
            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "DynamicNotch/2.0 (linux; https://github.com/local)"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _parse_lrc(self, lrc_text: str) -> list:
        pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
        result = []
        for line in lrc_text.splitlines():
            m = pattern.match(line.strip())
            if m:
                minutes = int(m.group(1))
                seconds = float(m.group(2))
                text = m.group(3).strip()
                ms = int((minutes * 60 + seconds) * 1000)
                result.append((ms, text))
        result.sort(key=lambda x: x[0])
        return result

    def get_state(self, position_us: int) -> dict:
        pos_ms = max(0, position_us // 1000)
        state = {
            "status": self._status,
            "current_line": "",
            "next_line": "",
            "is_intro": False,
        }

        if self._status != self.STATUS_SYNCED or not self._lines:
            return state

        # Check if before first lyric
        if pos_ms < self._lines[0][0]:
            state["is_intro"] = True
            state["next_line"] = self._lines[0][1]
            return state

        # Binary search for current timestamp
        low, high = 0, len(self._lines) - 1
        curr_idx = 0
        while low <= high:
            mid = (low + high) // 2
            if self._lines[mid][0] <= pos_ms:
                curr_idx = mid
                low = mid + 1
            else:
                high = mid - 1

        state["current_line"] = self._lines[curr_idx][1]
        if curr_idx + 1 < len(self._lines):
            state["next_line"] = self._lines[curr_idx + 1][1]

        return state

# ─────────────────────────────────────────────────────────────
#  CINEMA MODE CONTROLLER (Fullscreen Suppression)
# ─────────────────────────────────────────────────────────────
class CinemaModeController:
    """Monitors whether another window is fullscreen on the current monitor.
    Uses dual detection mechanisms:
    1. GNOME Shell Cinema Bridge extension via session D-Bus (org.dynamicnotch.CinemaBridge)
    2. Built-in low-latency XWayland/X11 detector querying _NET_ACTIVE_WINDOW & _NET_CLIENT_LIST
    3. Manual override file (/tmp/dynamic_notch_cinema_override)
    """
    OVERRIDE_FILE = "/tmp/dynamic_notch_cinema_override"

    def __init__(self, on_change_callback=None):
        self._on_change_callback = on_change_callback
        self._is_fullscreen = False
        self._bridge_available = False
        self._dbus_fs = False
        self._lock = threading.Lock()
        self._display = None
        self._root = None

        # 1. Setup D-Bus listener for GNOME Shell Cinema Bridge
        try:
            self._bus = dbus.SessionBus()
            self._bus.add_signal_receiver(
                self._on_bridge_signal,
                signal_name="FullscreenChanged",
                dbus_interface="org.dynamicnotch.CinemaBridge"
            )
            # Check initial state if service is already present
            if "org.dynamicnotch.CinemaBridge" in self._bus.list_names():
                bridge = self._bus.get_object("org.dynamicnotch.CinemaBridge", "/org/dynamicnotch/CinemaBridge")
                iface = dbus.Interface(bridge, "org.dynamicnotch.CinemaBridge")
                self._dbus_fs = bool(iface.GetFullscreen())
                self._bridge_available = True
        except Exception:
            self._bus = None

        # 2. Setup X11/XWayland detector via libX11.so.6
        self._init_x11()

    def _init_x11(self):
        try:
            self._x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            self._x11.XOpenDisplay.restype = ctypes.c_void_p
            self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self._x11.XInternAtom.restype = ctypes.c_ulong
            self._display = self._x11.XOpenDisplay(None)
            if self._display:
                self._root = self._x11.XDefaultRootWindow(self._display)
                self._atom_active = self._x11.XInternAtom(self._display, b"_NET_ACTIVE_WINDOW", False)
                self._atom_clients = self._x11.XInternAtom(self._display, b"_NET_CLIENT_LIST", False)
                self._atom_state = self._x11.XInternAtom(self._display, b"_NET_WM_STATE", False)
                self._atom_fs = self._x11.XInternAtom(self._display, b"_NET_WM_STATE_FULLSCREEN", False)
                self._atom_window = self._x11.XInternAtom(self._display, b"WINDOW", False)
                self._atom_atom = self._x11.XInternAtom(self._display, b"ATOM", False)
            else:
                self._root = None
        except Exception:
            self._display = None
            self._root = None

    def _on_bridge_signal(self, is_fs):
        with self._lock:
            self._bridge_available = True
            self._dbus_fs = bool(is_fs)
        if self._on_change_callback:
            GLib.idle_add(self._on_change_callback)

    def check_fullscreen(self) -> bool:
        # Check manual file override first
        override_path = getattr(self, "_override_file", self.OVERRIDE_FILE)
        if os.path.exists(override_path):
            return True

        # Check D-Bus bridge state
        with self._lock:
            if self._bridge_available and self._dbus_fs:
                return True

        # Check X11 / XWayland root properties
        return self._check_x11_fullscreen()

    def _check_x11_fullscreen(self) -> bool:
        if not self._display or not self._root:
            return False
        try:
            # 1. Check active focused window
            act_win = self._x11_get_active_window()
            if act_win and self._x11_is_fullscreen(act_win):
                return True

            # 2. Check client list
            return self._x11_check_clients_fullscreen()
        except Exception:
            return False

    def _x11_get_active_window(self):
        actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
        nitems, bytes_after = ctypes.c_ulong(), ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ulong)()
        status = self._x11.XGetWindowProperty(
            self._display, self._root, self._atom_active, 0, 1, False, self._atom_window,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop)
        )
        if status == 0 and prop and nitems.value > 0:
            win = prop[0]
            self._x11.XFree(prop)
            return win
        return None

    def _x11_is_fullscreen(self, win):
        actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
        nitems, bytes_after = ctypes.c_ulong(), ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ulong)()
        status = self._x11.XGetWindowProperty(
            self._display, win, self._atom_state, 0, 64, False, self._atom_atom,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop)
        )
        if status == 0 and prop:
            for i in range(nitems.value):
                if prop[i] == self._atom_fs:
                    self._x11.XFree(prop)
                    return True
            self._x11.XFree(prop)
        return False

    def _x11_check_clients_fullscreen(self):
        actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
        nitems, bytes_after = ctypes.c_ulong(), ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ulong)()
        status = self._x11.XGetWindowProperty(
            self._display, self._root, self._atom_clients, 0, 1024, False, self._atom_window,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop)
        )
        if status == 0 and prop:
            for i in range(nitems.value):
                win = prop[i]
                if self._x11_is_fullscreen(win):
                    self._x11.XFree(prop)
                    return True
            self._x11.XFree(prop)
        return False

    def close(self):
        if self._display:
            try:
                self._x11.XCloseDisplay(self._display)
            except Exception:
                pass
            self._display = None

# ─────────────────────────────────────────────────────────────
#  MAIN DYNAMIC ISLAND WINDOW (FIXED CANVAS ARCHITECTURE)
# ─────────────────────────────────────────────────────────────
class DynamicIslandWindow(Gtk.Window):
    STATE_IDLE = 0
    STATE_COMPACT = 1
    STATE_FULL = 2
    STATE_NOTIF = 3
    STATE_EMPTY = 4
    STATE_CINEMA_SUPPRESSED = 5

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        self.media = MediaController(on_change_callback=self._on_tick)
        self.vol = VolumeController()
        self.bt = BluetoothBattery(on_change_callback=self._on_bt_event)
        self.lyrics = LyricsController()

        self._state = self.STATE_IDLE
        self._target_state = self.STATE_IDLE

        # Fixed Canvas Animated Size Interpolation
        self._current_w = float(IDLE_W)
        self._current_h = float(IDLE_H)
        self._start_w = float(IDLE_W)
        self._start_h = float(IDLE_H)
        self._anim_target_w = float(IDLE_W)
        self._anim_target_h = float(IDLE_H)
        self._anim_start_time = 0.0
        self._anim_running = False
        self._anim_is_expanding = True
        self._anim_duration_ms = float(ANIM_EXPAND_MS)
        self._anim_tick_id = None

        self._tick_timer = None
        self._lyric_timer = None
        self._activity_timer = None
        self._cinema_timer = None
        self._anim_timer = None
        self._collapse_timer = None
        self._notif_timer = None
        self._water_reminder_timer = None
        self._seeking = False
        self._last_info = {}
        self._last_battery_state = None
        self._low_battery_notified = False
        self._persistent_bt_device = None

        self._seek_blocked = False

        self._current_track_key = None
        self._last_lyric_line = ""
        self._has_lyrics = False

        # Dynamic positioning state
        self._current_pos_x = None
        self._current_pos_y = None

        # Real PipeWire Audio-Reactive Equalizer Monitor
        self._audio_monitor = AudioLevelMonitor()

        # Cinema Mode Controller (Fullscreen Suppression)
        self._cinema = CinemaModeController(on_change_callback=self._on_cinema_state_changed)
        self._is_cinema_suppressed = False
        self._cinema_debounce_counter = 0

        self._setup_window()
        self._build_ui()
        self._apply_css()

        self.show_all()
        self._full_box.set_visible(False)
        self._compact_box.set_visible(False)
        self._empty_box.set_visible(False)
        self._notif_box.set_visible(False)
        self._idle_box.set_visible(True)
        self._update_input_shape(IDLE_W, IDLE_H)
        self._update_persistent_bt(self.bt.get_headset_info())

        if self._cinema.check_fullscreen():
            self._enter_cinema_suppression()
        else:
            self._on_tick()

        self._tick_timer = GLib.timeout_add(UPDATE_INTERVAL_MS, self._on_tick)
        self._lyric_timer = GLib.timeout_add(LYRIC_TICK_MS, self._on_lyric_tick)
        self._activity_timer = GLib.timeout_add(ACTIVITY_TICK_MS, self._on_activity_tick)
        self._cinema_timer = GLib.timeout_add(CINEMA_POLL_MS, self._check_cinema_mode)

        self._start_water_reminder()

        # Check initial connected headset status shortly after launch
        GLib.timeout_add(1000, self._check_initial_headset)

        self.connect("delete-event", self._on_delete)

    def _cancel_timer(self, attr_name: str):
        if attr_name == "_anim_timer":
            self._anim_running = False
            tick_id = getattr(self, "_anim_tick_id", None)
            if tick_id is not None:
                try:
                    if hasattr(self, "remove_tick_callback"):
                        self.remove_tick_callback(tick_id)
                except Exception:
                    pass
                self._anim_tick_id = None
        timer_id = getattr(self, attr_name, None)
        if timer_id is not None:
            try:
                GLib.source_remove(timer_id)
            except Exception:
                pass
            setattr(self, attr_name, None)

    def _on_cinema_state_changed(self):
        GLib.idle_add(self._check_cinema_mode)

    def _check_cinema_mode(self):
        fs = self._cinema.check_fullscreen()
        if fs:
            self._cinema_debounce_counter = min(3, self._cinema_debounce_counter + 1)
        else:
            self._cinema_debounce_counter = max(0, self._cinema_debounce_counter - 1)

        if fs and not self._is_cinema_suppressed:
            self._enter_cinema_suppression()
        elif not fs and self._is_cinema_suppressed and self._cinema_debounce_counter == 0:
            self._exit_cinema_suppression()

        return True

    def _enter_cinema_suppression(self):
        self._is_cinema_suppressed = True
        self._state = self.STATE_CINEMA_SUPPRESSED
        if self._anim_running:
            self._anim_running = False
        self._cancel_timer("_anim_timer")
        self._cancel_timer("_collapse_timer")
        self._cancel_timer("_notif_timer")

        self._full_box.set_visible(False)
        self._compact_box.set_visible(False)
        self._empty_box.set_visible(False)
        self._idle_box.set_visible(False)
        self._notif_box.set_visible(False)

        self._update_input_shape(0, 0)
        self.hide()

    def _exit_cinema_suppression(self):
        self._is_cinema_suppressed = False

        self._last_info = self.media.get_info()
        self._on_lyric_tick()

        self.show()

        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        target = self.STATE_COMPACT if has_music else self.STATE_IDLE

        self._start_w = float(IDLE_W)
        self._start_h = float(IDLE_H)
        self._current_w = float(IDLE_W)
        self._current_h = float(IDLE_H)
        self._idle_box.set_visible(True)
        self._idle_box.set_opacity(1.0)
        self._update_input_shape(IDLE_W, IDLE_H)
        self.queue_draw()

        self._state = self.STATE_IDLE
        self._target_state = self.STATE_IDLE
        if target != self.STATE_IDLE:
            self._animate_to(target)

    def _on_activity_tick(self):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return True
        if self._state == self.STATE_COMPACT and hasattr(self, "compact_activity"):
            self.compact_activity.tick()
        elif self._state == self.STATE_FULL and hasattr(self, "full_activity"):
            self.full_activity.tick()
        return True

    def _update_persistent_bt(self, headset_info: dict | None):
        if headset_info and headset_info.get("connected"):
            self._persistent_bt_device = dict(headset_info)
        else:
            self._persistent_bt_device = None
        self._refresh_bt_ui()
        self.queue_draw()

    def _refresh_bt_ui(self):
        dev = self._persistent_bt_device
        if dev and dev.get("connected"):
            name = dev.get("name") or "Headset"
            pct = dev.get("percent")
            comps = dev.get("components") or {}

            # Expanded battery formatting:
            # Component levels if genuinely exposed, else "Battery X%", else "Battery unavailable"
            if comps:
                comp_parts = []
                for key, label in [("left", "L"), ("right", "R"), ("case", "Case")]:
                    if key in comps and comps[key].get("percent") is not None:
                        comp_parts.append(f"{label}: {comps[key]['percent']}%")
                bat_text = " · ".join(comp_parts) if comp_parts else ("Battery unavailable" if pct is None else f"Battery {pct}%")
            elif pct is not None:
                bat_text = f"Battery {pct}%"
            else:
                bat_text = "Battery unavailable"

            if hasattr(self, "full_bt_name") and hasattr(self, "full_bt_battery"):
                self.full_bt_name.set_text(f"🎧 {name}")
                self.full_bt_battery.set_text(bat_text)
                self.full_bt_box.set_visible(True)
                if hasattr(self, "full_title"):
                    self.full_title.set_max_width_chars(15)
                if hasattr(self, "full_artist"):
                    self.full_artist.set_max_width_chars(18)

            if hasattr(self, "empty_bt_label"):
                self.empty_bt_label.set_text(f"🎧 {name} · {bat_text}")
                self.empty_bt_label.set_visible(True)
        else:
            if hasattr(self, "full_bt_name") and hasattr(self, "full_bt_battery"):
                self.full_bt_name.set_text("")
                self.full_bt_battery.set_text("")
                self.full_bt_box.set_visible(False)
                if hasattr(self, "full_title"):
                    self.full_title.set_max_width_chars(26)
                if hasattr(self, "full_artist"):
                    self.full_artist.set_max_width_chars(30)

            if hasattr(self, "empty_bt_label"):
                self.empty_bt_label.set_text("")
                self.empty_bt_label.set_visible(False)

    def _on_bt_event(self, event_type: str, info: dict):
        # 1. Update persistent state independently of notification state
        if event_type in ("connected", "battery_changed"):
            self._update_persistent_bt(info)
            if event_type == "connected" and hasattr(self, "_audio_monitor") and self._audio_monitor:
                self._audio_monitor.check_default_sink()
        elif event_type == "disconnected":
            self._update_persistent_bt(None)
            if hasattr(self, "_audio_monitor") and self._audio_monitor:
                self._audio_monitor.check_default_sink()

        # 2. Transient notifications (suppressed in Cinema Mode or Expanded panel)
        if self._is_cinema_suppressed or self._state in (self.STATE_CINEMA_SUPPRESSED, self.STATE_FULL):
            return

        name = info.get("name", "Headset")
        pct = info.get("percent")
        bat_text = info.get("battery_text", "")

        if event_type == "connected":
            sub = f"{bat_text} battery" if (pct is not None or info.get("components")) else "Connected · Battery unavailable"
            self.show_notification("🎧", name, sub, duration_s=2.5)
        elif event_type == "disconnected":
            self.show_notification("🎧", name, "Disconnected", duration_s=2.0)
        elif event_type == "low_battery":
            sub = f"{pct}% remaining" if pct is not None else "Low battery"
            self.show_notification("🪫", f"Low Battery: {name}", sub, duration_s=2.5)

    def _check_initial_headset(self):
        headset = self.bt.get_headset_info()
        if headset and headset.get("connected"):
            self._update_persistent_bt(headset)
            if not (self._is_cinema_suppressed or self._state in (self.STATE_CINEMA_SUPPRESSED, self.STATE_FULL)):
                name = headset.get("name", "Headset")
                pct = headset.get("percent")
                bat_text = headset.get("battery_text", "")
                sub = f"{bat_text} battery" if (pct is not None or headset.get("components")) else "Connected · Battery unavailable"
                self.show_notification("🎧", name, sub, duration_s=2.0)
        else:
            self._update_persistent_bt(None)
        return False

    def _on_delete(self, *_):
        self._cancel_timer("_tick_timer")
        self._cancel_timer("_lyric_timer")
        self._cancel_timer("_activity_timer")
        self._cancel_timer("_cinema_timer")
        self._cancel_timer("_anim_timer")
        self._cancel_timer("_collapse_timer")
        self._cancel_timer("_notif_timer")
        self._cancel_timer("_water_reminder_timer")
        if hasattr(self, "bt") and self.bt:
            self.bt.close()
        if hasattr(self, "_cinema") and self._cinema:
            self._cinema.close()
        if hasattr(self, "_audio_monitor") and self._audio_monitor:
            self._audio_monitor.stop()
        if Gtk.main_level() > 0:
            Gtk.main_quit()
        return False

    # ─────────────────────────────────────────────────────────
    #  BACKGROUND WATER REMINDER
    # ─────────────────────────────────────────────────────────
    def _start_water_reminder(self):
        if self._water_reminder_timer:
            return
        interval_ms = WATER_REMINDER_INTERVAL_MIN * 60 * 1000
        self._water_reminder_timer = GLib.timeout_add(interval_ms, self._water_reminder_tick)

    def _water_reminder_tick(self):
        """Send a desktop notification reminding the user to drink water."""
        try:
            subprocess.Popen(
                ["notify-send", "--expire-time=6000", "--urgency=low",
                 "💧 Hydration Reminder", "Time to drink some water! Stay hydrated."],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        return True

    def _setup_window(self):
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.connect("draw", self._on_draw)

        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.SCROLL_MASK
        )
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("scroll-event", self._on_scroll)
        self.connect("map-event", self._on_map_event)

        # Fixed canvas size
        self.resize(CANVAS_W, CANVAS_H)

        # Dynamic workarea positioning & signal binding
        self._update_geometry_and_position()
        self._bind_monitor_signals()

    def _on_map_event(self, widget, event):
        # Force window repositioning after compositor maps the window
        self._update_geometry_and_position(force=True)
        return False

    def _update_geometry_and_position(self, force: bool = False):
        display = Gdk.Display.get_default()
        if not display:
            return

        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if not monitor:
            return

        geom = monitor.get_geometry()
        work = monitor.get_workarea()

        # Dynamic top alignment:
        # If a desktop panel is present, work.y > geom.y (e.g. 28px on GNOME Shell).
        # We align to work.y so the island sits directly below the panel.
        has_top_panel = (work.y > geom.y)
        target_y = (work.y + MARGIN_TOP_PANEL) if has_top_panel else (geom.y + MARGIN_TOP_SCREEN)

        # Horizontally center relative to monitor's workarea
        target_x = work.x + int((work.width - CANVAS_W) / 2)

        needs_move = force
        if not needs_move:
            gdk_win = self.get_window()
            if gdk_win:
                cur_x, cur_y = self.get_position()
                if (cur_x, cur_y) != (target_x, target_y):
                    needs_move = True
            elif (target_x, target_y) != (self._current_pos_x, self._current_pos_y):
                needs_move = True

        if needs_move:
            self._current_pos_x = target_x
            self._current_pos_y = target_y
            self.move(target_x, target_y)

    def _bind_monitor_signals(self):
        display = Gdk.Display.get_default()
        if not display:
            return

        try:
            display.connect("monitor-added", lambda *_: self._update_geometry_and_position(force=True))
            display.connect("monitor-removed", lambda *_: self._update_geometry_and_position(force=True))
        except Exception:
            pass

        try:
            screen = self.get_screen()
            if screen:
                screen.connect("size-changed", lambda *_: self._update_geometry_and_position(force=True))
        except Exception:
            pass

        try:
            n = display.get_n_monitors()
            for i in range(n):
                mon = display.get_monitor(i)
                if mon:
                    mon.connect("notify::workarea", lambda *_: self._update_geometry_and_position(force=True))
                    mon.connect("notify::geometry", lambda *_: self._update_geometry_and_position(force=True))
                    mon.connect("notify::scale-factor", lambda *_: self._update_geometry_and_position(force=True))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    #  PURE 60 FPS CAIRO SQUIRCLE RENDERING (macOS Satin Glass)
    # ─────────────────────────────────────────────────────────
    def _on_draw(self, widget, cr):
        # 1. Clear entire canvas with 100% transparency
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.restore()

        # 2. Draw animated black capsule pill centered horizontally
        w = float(self._current_w)
        h = float(self._current_h)
        px = (CANVAS_W - w) / 2.0
        py = 0.0

        if h <= float(COMPACT_H):
            r = h / 2.0
        else:
            prog = (h - float(COMPACT_H)) / float(EXPANDED_H - COMPACT_H)
            prog = max(0.0, min(1.0, prog))
            t_smooth = prog * prog * (3.0 - 2.0 * prog)
            r = (float(COMPACT_H) / 2.0) + (28.0 - (float(COMPACT_H) / 2.0)) * t_smooth

        cr.new_sub_path()
        cr.arc(px + w - r, py + r, r, -math.pi / 2, 0)
        cr.arc(px + w - r, py + h - r, r, 0, math.pi / 2)
        cr.arc(px + r, py + h - r, r, math.pi / 2, math.pi)
        cr.arc(px + r, py + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        # OLED Deep Black Base Fill (#050506, 1.0 alpha - completely opaque inside squircle)
        cr.set_source_rgba(5/255.0, 5/255.0, 6/255.0, 1.0)
        cr.fill_preserve()

        # Specular satin sheen on top rim
        cr.save()
        cr.clip_preserve()
        sheen_h = min(h, 40.0)
        sheen = cairo.LinearGradient(px, py, px, py + sheen_h)
        sheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.04)
        sheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
        cr.set_source(sheen)
        cr.paint()
        cr.restore()

        # Subtle macOS dark glass rim highlight (#29292D)
        rim = cairo.LinearGradient(px, py, px, py + h)
        rim.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.14)
        rim.add_color_stop_rgba(0.25, 41/255.0, 41/255.0, 45/255.0, 0.90)
        rim.add_color_stop_rgba(1.0, 41/255.0, 41/255.0, 45/255.0, 0.40)
        cr.set_source(rim)
        cr.set_line_width(1.0)
        cr.stroke()

        return False

    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ─────────────────────────────────────────────────────────
    #  BUILD UI COMPONENTS
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self._overlay = Gtk.Overlay()
        self._overlay.get_style_context().add_class("canvas-root")
        self.add(self._overlay)

        # ── 1. IDLE VIEW (Camera Notch Cover: 180x30) ──
        self._idle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._idle_box.get_style_context().add_class("idle-box")
        self._idle_box.set_halign(Gtk.Align.CENTER)
        self._idle_box.set_valign(Gtk.Align.START)
        self._idle_box.set_size_request(IDLE_W, IDLE_H)

        cam_dot = Gtk.Box()
        cam_dot.get_style_context().add_class("camera-dot")
        cam_dot.set_valign(Gtk.Align.CENTER)
        self._idle_box.pack_start(cam_dot, False, False, 0)

        self._idle_label = Gtk.Label(label="Dynamic Notch")
        self._idle_label.get_style_context().add_class("idle-text")
        self._idle_label.set_valign(Gtk.Align.CENTER)
        self._idle_box.pack_start(self._idle_label, False, False, 0)
        self._overlay.add_overlay(self._idle_box)

        # ── 2. EMPTY EXPANDED VIEW (Hovered with no media: 220x50) ──
        self._empty_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._empty_box.get_style_context().add_class("empty-box")
        self._empty_box.set_halign(Gtk.Align.CENTER)
        self._empty_box.set_valign(Gtk.Align.CENTER)
        self._empty_box.set_size_request(EMPTY_EXPANDED_W, EMPTY_EXPANDED_H)

        empty_label = Gtk.Label(label="No media playing")
        empty_label.get_style_context().add_class("empty-text")
        empty_label.set_valign(Gtk.Align.CENTER)
        self._empty_box.pack_start(empty_label, True, True, 0)

        self.empty_bt_label = Gtk.Label(label="")
        self.empty_bt_label.get_style_context().add_class("empty-bt-label")
        self.empty_bt_label.set_valign(Gtk.Align.CENTER)
        self.empty_bt_label.set_visible(False)
        self._empty_box.pack_end(self.empty_bt_label, False, False, 0)
        self._overlay.add_overlay(self._empty_box)

        # ── 3. COMPACT PLAYING / PAUSED VIEW (240x40) ──
        self._compact_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._compact_box.get_style_context().add_class("compact-box")
        self._compact_box.set_halign(Gtk.Align.CENTER)
        self._compact_box.set_valign(Gtk.Align.START)
        self._compact_box.set_size_request(COMPACT_W, COMPACT_H)

        # 22x22 album art container
        self.compact_art_image = Gtk.Image()
        self.compact_art_image.get_style_context().add_class("compact-art")
        self.compact_art_image.set_size_request(ART_SIZE_COMPACT, ART_SIZE_COMPACT)

        self.compact_art_placeholder = Gtk.Box()
        self.compact_art_placeholder.get_style_context().add_class("compact-art-placeholder")
        self.compact_art_placeholder.set_size_request(ART_SIZE_COMPACT, ART_SIZE_COMPACT)

        self.compact_art_container = Gtk.Overlay()
        self.compact_art_container.set_size_request(ART_SIZE_COMPACT, ART_SIZE_COMPACT)
        self.compact_art_container.add(self.compact_art_placeholder)
        self.compact_art_container.add_overlay(self.compact_art_image)
        self.compact_art_container.set_valign(Gtk.Align.CENTER)
        self._compact_box.pack_start(self.compact_art_container, False, False, 0)

        # Track metadata column (title + artist)
        compact_info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        compact_info_col.set_valign(Gtk.Align.CENTER)
        compact_info_col.set_hexpand(True)
        self._compact_box.pack_start(compact_info_col, True, True, 0)

        self.compact_title = Gtk.Label(label="")
        self.compact_title.get_style_context().add_class("compact-title")
        self.compact_title.set_single_line_mode(True)
        self.compact_title.set_line_wrap(False)
        self.compact_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.compact_title.set_halign(Gtk.Align.FILL)
        self.compact_title.set_xalign(0.0)
        self.compact_title.set_hexpand(True)
        self.compact_title.set_max_width_chars(20)
        compact_info_col.pack_start(self.compact_title, False, False, 0)

        self.compact_artist = Gtk.Label(label="")
        self.compact_artist.get_style_context().add_class("compact-artist")
        self.compact_artist.set_single_line_mode(True)
        self.compact_artist.set_line_wrap(False)
        self.compact_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.compact_artist.set_halign(Gtk.Align.FILL)
        self.compact_artist.set_xalign(0.0)
        self.compact_artist.set_hexpand(True)
        self.compact_artist.set_max_width_chars(22)
        compact_info_col.pack_start(self.compact_artist, False, False, 0)

        # 3-bar media activity equalizer wave
        self.compact_activity = MediaActivityIndicator(size=14, monitor=self._audio_monitor)
        self.compact_activity.set_valign(Gtk.Align.CENTER)
        self._compact_box.pack_end(self.compact_activity, False, False, 0)
        self._overlay.add_overlay(self._compact_box)

        # ── 4. TRANSIENT NOTIFICATION OVERLAY (260x36) ──
        self._notif_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._notif_box.get_style_context().add_class("notif-box")
        self._notif_box.set_halign(Gtk.Align.CENTER)
        self._notif_box.set_valign(Gtk.Align.START)
        self._notif_box.set_size_request(NOTIF_W, NOTIF_H)

        self._notif_icon = Gtk.Label(label="⚡")
        self._notif_icon.get_style_context().add_class("notif-icon")
        self._notif_box.pack_start(self._notif_icon, False, False, 0)

        self._notif_title = Gtk.Label(label="Notification")
        self._notif_title.get_style_context().add_class("notif-title")
        self._notif_box.pack_start(self._notif_title, False, False, 0)

        self._notif_sub = Gtk.Label(label="")
        self._notif_sub.get_style_context().add_class("notif-sub")
        self._notif_box.pack_start(self._notif_sub, False, False, 0)
        self._overlay.add_overlay(self._notif_box)

        # ── 5. EXPANDED MUSIC PLAYER VIEW (380x162 / 380x142) ──
        self._full_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._full_box.get_style_context().add_class("full-box")
        self._full_box.set_halign(Gtk.Align.CENTER)
        self._full_box.set_valign(Gtk.Align.START)
        self._full_box.set_size_request(EXPANDED_W, EXPANDED_H)
        self._overlay.add_overlay(self._full_box)

        self._build_music_panel()

    # ── Music Player Panel ──
    def _build_music_panel(self):
        # Row 1: Header (Album Art + Track Metadata + Activity Wave)
        row_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._full_box.pack_start(row_hdr, False, False, 0)

        # 42x42 album art
        self.art_image = Gtk.Image()
        self.art_image.get_style_context().add_class("album-art")
        self.art_image.set_size_request(ART_SIZE_EXPANDED, ART_SIZE_EXPANDED)
        self.art_placeholder = Gtk.Box()
        self.art_placeholder.get_style_context().add_class("art-placeholder")
        self.art_placeholder.set_size_request(ART_SIZE_EXPANDED, ART_SIZE_EXPANDED)
        self.art_container = Gtk.Overlay()
        self.art_container.set_size_request(ART_SIZE_EXPANDED, ART_SIZE_EXPANDED)
        self.art_container.get_style_context().add_class("art-click-area")
        self.art_container.add(self.art_placeholder)
        self.art_container.add_overlay(self.art_image)
        self.art_container.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.art_container.connect("button-press-event", lambda *_: self.media.open_app())
        row_hdr.pack_start(self.art_container, False, False, 0)

        # Track info column
        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_col.set_valign(Gtk.Align.CENTER)
        row_hdr.pack_start(info_col, True, True, 0)

        self.full_title = Gtk.Label(label="Not Playing")
        self.full_title.get_style_context().add_class("full-title")
        self.full_title.set_single_line_mode(True)
        self.full_title.set_line_wrap(False)
        self.full_title.set_halign(Gtk.Align.START)
        self.full_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_title.set_max_width_chars(26)
        info_col.pack_start(self.full_title, False, False, 0)

        self.full_artist = Gtk.Label(label="Open Spotify to play")
        self.full_artist.get_style_context().add_class("full-artist")
        self.full_artist.set_single_line_mode(True)
        self.full_artist.set_line_wrap(False)
        self.full_artist.set_halign(Gtk.Align.START)
        self.full_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_artist.set_max_width_chars(30)
        info_col.pack_start(self.full_artist, False, False, 0)

        # Full activity wave indicator (right side of header)
        self.full_activity = MediaActivityIndicator(size=18, monitor=self._audio_monitor)
        self.full_activity.set_valign(Gtk.Align.CENTER)
        row_hdr.pack_end(self.full_activity, False, False, 0)

        # Persistent Headset / TWS Status (top-right of header)
        self.full_bt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.full_bt_box.get_style_context().add_class("full-bt-box")
        self.full_bt_box.set_valign(Gtk.Align.CENTER)
        self.full_bt_box.set_halign(Gtk.Align.END)
        self.full_bt_box.set_visible(False)

        self.full_bt_name = Gtk.Label(label="")
        self.full_bt_name.get_style_context().add_class("full-bt-name")
        self.full_bt_name.set_halign(Gtk.Align.END)
        self.full_bt_name.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_bt_name.set_max_width_chars(18)
        self.full_bt_box.pack_start(self.full_bt_name, False, False, 0)

        self.full_bt_battery = Gtk.Label(label="")
        self.full_bt_battery.get_style_context().add_class("full-bt-battery")
        self.full_bt_battery.set_halign(Gtk.Align.END)
        self.full_bt_battery.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_bt_battery.set_max_width_chars(22)
        self.full_bt_box.pack_start(self.full_bt_battery, False, False, 0)

        row_hdr.pack_end(self.full_bt_box, False, False, 0)

        # Row 2: Subdued Lyric Preview (hidden when no lyrics, 2-line reserved area)
        self._lyric_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._lyric_row.get_style_context().add_class("lyric-row")
        self._lyric_row.set_size_request(-1, 36)
        self._full_box.pack_start(self._lyric_row, False, False, 0)

        self._full_lyric_label = Gtk.Label(label="")
        self._full_lyric_label.get_style_context().add_class("full-lyric")
        self._full_lyric_label.set_line_wrap(True)
        self._full_lyric_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._full_lyric_label.set_lines(2)
        self._full_lyric_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._full_lyric_label.set_halign(Gtk.Align.FILL)
        self._full_lyric_label.set_hexpand(True)
        self._full_lyric_label.set_xalign(0.0)
        self._full_lyric_label.set_valign(Gtk.Align.CENTER)
        self._full_lyric_label.set_max_width_chars(42)
        self._lyric_row.pack_start(self._full_lyric_label, True, True, 0)

        # Row 3: Seekbar & Timestamps
        row_seek = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._full_box.pack_start(row_seek, False, False, 0)

        self.lbl_cur_time = Gtk.Label(label="0:00")
        self.lbl_cur_time.get_style_context().add_class("time-label")
        row_seek.pack_start(self.lbl_cur_time, False, False, 0)

        self.seek_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.002)
        self.seek_scale.get_style_context().add_class("seek-slider")
        self.seek_scale.set_draw_value(False)
        self.seek_scale.connect("button-press-event", self._on_seek_press)
        self.seek_scale.connect("button-release-event", self._on_seek_release)
        self.seek_scale.connect("value-changed", self._on_seek_changed)
        row_seek.pack_start(self.seek_scale, True, True, 0)

        self.lbl_tot_time = Gtk.Label(label="-0:00")
        self.lbl_tot_time.get_style_context().add_class("time-label")
        row_seek.pack_end(self.lbl_tot_time, False, False, 0)

        # Row 4: Centered Playback Controls (AC-05: Minimal glyphs, no discs, no borders)
        row_ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        row_ctrl.set_halign(Gtk.Align.CENTER)
        self._full_box.pack_start(row_ctrl, False, False, 0)

        btn_prev = Gtk.Button()
        btn_prev.set_relief(Gtk.ReliefStyle.NONE)
        btn_prev.set_focus_on_click(False)
        btn_prev.get_style_context().add_class("ctrl-btn")
        img_prev = Gtk.Image.new_from_icon_name("media-skip-backward-symbolic", Gtk.IconSize.BUTTON)
        img_prev.set_pixel_size(18)
        btn_prev.set_image(img_prev)
        btn_prev.connect("clicked", lambda *_: self.media.prev())
        row_ctrl.pack_start(btn_prev, False, False, 0)

        self.btn_play = Gtk.Button()
        self.btn_play.set_relief(Gtk.ReliefStyle.NONE)
        self.btn_play.set_focus_on_click(False)
        self.btn_play.get_style_context().add_class("ctrl-btn-play")
        self.play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.play_icon.set_pixel_size(20)
        self.btn_play.set_image(self.play_icon)
        self.btn_play.connect("clicked", lambda *_: self.media.play_pause())
        row_ctrl.pack_start(self.btn_play, False, False, 0)

        btn_next = Gtk.Button()
        btn_next.set_relief(Gtk.ReliefStyle.NONE)
        btn_next.set_focus_on_click(False)
        btn_next.get_style_context().add_class("ctrl-btn")
        img_next = Gtk.Image.new_from_icon_name("media-skip-forward-symbolic", Gtk.IconSize.BUTTON)
        img_next.set_pixel_size(18)
        btn_next.set_image(img_next)
        btn_next.connect("clicked", lambda *_: self.media.next())
        row_ctrl.pack_start(btn_next, False, False, 0)

    # ─────────────────────────────────────────────────────────
    #  TRANSIENT NOTIFICATIONS
    # ─────────────────────────────────────────────────────────
    def show_notification(self, icon: str, title: str, subtitle: str = "", duration_s: float = 1.2):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return  # Suppress all in-island notifications over fullscreen video

        self._notif_icon.set_text(icon)
        self._notif_title.set_text(title)
        self._notif_sub.set_text(subtitle)

        if self._state == self.STATE_FULL:
            return  # Don't hijack expanded panel

        self._cancel_timer("_notif_timer")
        self._animate_to(self.STATE_NOTIF)
        self._notif_timer = GLib.timeout_add(int(duration_s * 1000), self._dismiss_notification)

    def _dismiss_notification(self):
        self._notif_timer = None
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        self._animate_to(self.STATE_COMPACT if has_music else self.STATE_IDLE)
        return False

    # ─────────────────────────────────────────────────────────
    #  DYNAMIC INPUT SHAPE (PASS-THROUGH ON EMPTY REGION)
    # ─────────────────────────────────────────────────────────
    def _update_input_shape(self, w, h):
        gdk_win = self.get_window()
        if gdk_win:
            if w <= 0 or h <= 0:
                reg = cairo.Region()
                gdk_win.input_shape_combine_region(reg, 0, 0)
                return
            px = int((CANVAS_W - w) / 2)
            rect = cairo.RectangleInt(px, 0, int(w), int(h))
            reg = cairo.Region(rect)
            gdk_win.input_shape_combine_region(reg, 0, 0)

    # ─────────────────────────────────────────────────────────
    #  60 FPS SMOOTH ANIMATION ENGINE (FRAME-CLOCK DRIVEN DAMPED SPRING)
    # ─────────────────────────────────────────────────────────
    def _animate_to(self, target_state):
        if self._is_cinema_suppressed:
            return  # Never start animation while cinema-suppressed

        if self._target_state == target_state and self._anim_running:
            return  # Transition already actively in progress toward this target

        if self._state == target_state and not self._anim_running:
            if target_state != self.STATE_FULL:
                return
            expected_h = float(EXPANDED_H if self._has_lyrics else EXPANDED_H_NOLYRIC)
            if self._current_h == expected_h:
                return

        self._target_state = target_state

        if target_state == self.STATE_IDLE:
            target_w, target_h = float(IDLE_W), float(IDLE_H)
        elif target_state == self.STATE_COMPACT:
            target_w, target_h = float(COMPACT_W), float(COMPACT_H)
            self._update_compact_ui()
        elif target_state == self.STATE_NOTIF:
            target_w, target_h = float(NOTIF_W), float(NOTIF_H)
        elif target_state == self.STATE_EMPTY:
            target_w, target_h = float(EMPTY_EXPANDED_W), float(EMPTY_EXPANDED_H)
        else:
            target_h = float(EXPANDED_H if self._has_lyrics else EXPANDED_H_NOLYRIC)
            target_w = float(EXPANDED_W)
            self._update_full_ui()

        self._start_w = float(self._current_w)
        self._start_h = float(self._current_h)
        self._anim_target_w = target_w
        self._anim_target_h = target_h
        self._anim_start_time = 0.0  # Latch on first tick so pre-timer work does not consume animation budget

        # Separate expand vs collapse durations
        is_expanding = (target_w * target_h) >= (self._start_w * self._start_h)
        self._anim_is_expanding = is_expanding
        self._anim_duration_ms = float(ANIM_EXPAND_MS if is_expanding else ANIM_COLLAPSE_MS)

        active_boxes = {
            self.STATE_IDLE: self._idle_box,
            self.STATE_COMPACT: self._compact_box,
            self.STATE_NOTIF: self._notif_box,
            self.STATE_EMPTY: self._empty_box,
            self.STATE_FULL: self._full_box,
        }

        # Snapshot start opacities for continuous cross-fading (even on mid-flight reversal)
        self._start_opacities = {box: box.get_opacity() for box in active_boxes.values()}

        target_box = active_boxes.get(target_state)
        if target_box:
            # If changing to a different state, incoming box must not pop in before ease-out
            if self._state != target_state and not target_box.get_visible():
                target_box.set_opacity(0.0)
                self._start_opacities[target_box] = 0.0
            target_box.set_visible(True)

        if target_state == self.STATE_FULL:
            self._update_input_shape(EXPANDED_W, target_h)
        elif target_state == self.STATE_EMPTY:
            self._update_input_shape(EMPTY_EXPANDED_W, EMPTY_EXPANDED_H)

        self._cancel_timer("_anim_timer")
        self._anim_running = True

        # Synchronize with display frame clock via add_tick_callback
        if hasattr(self, "add_tick_callback"):
            try:
                self._anim_tick_id = self.add_tick_callback(self._on_anim_tick)
            except Exception:
                self._anim_tick_id = None
                self._anim_timer = GLib.timeout_add(ANIM_INTERVAL_MS, self._anim_step)
        else:
            self._anim_timer = GLib.timeout_add(ANIM_INTERVAL_MS, self._anim_step)

    def _on_anim_tick(self, widget, frame_clock):
        if not self._anim_running:
            self._anim_tick_id = None
            return False
        now_ms = (frame_clock.get_frame_time() / 1000.0) if frame_clock else (time.monotonic() * 1000.0)
        cont = self._anim_step(now_ms=now_ms)
        if not cont:
            self._anim_tick_id = None
            return False
        return True

    def _anim_step(self, now_ms=None):
        if not self._anim_running:
            return False

        if now_ms is None:
            now_ms = time.monotonic() * 1000.0

        if self._anim_start_time <= 0.0:
            self._anim_start_time = now_ms
            elapsed = 0.0
            progress = 0.0
            factor = 0.0
        else:
            elapsed = max(0.0, now_ms - self._anim_start_time)
            duration = getattr(self, "_anim_duration_ms", float(ANIM_EXPAND_MS))
            progress = min(1.0, elapsed / duration)
            is_expanding = getattr(self, "_anim_is_expanding", True)
            factor = _anim_curve(progress, is_expanding=is_expanding)

        self._current_w = self._start_w + (self._anim_target_w - self._start_w) * factor
        self._current_h = self._start_h + (self._anim_target_h - self._start_h) * factor

        active_boxes = {
            self.STATE_IDLE: self._idle_box,
            self.STATE_COMPACT: self._compact_box,
            self.STATE_NOTIF: self._notif_box,
            self.STATE_EMPTY: self._empty_box,
            self.STATE_FULL: self._full_box,
        }

        target_box = active_boxes.get(self._target_state)
        start_opacities = getattr(self, "_start_opacities", {})

        for s, box in active_boxes.items():
            if box == target_box:
                if self._state == self._target_state and self._state == self.STATE_FULL:
                    # In-place height adjustment (e.g. lyrics arrival/departure)
                    box.set_opacity(1.0)
                else:
                    target_start_op = start_opacities.get(box, 0.0)
                    # Synchronize incoming opacity with geometry expansion
                    in_factor = max(0.0, min(1.0, (factor - 0.25) / 0.75))
                    new_op = target_start_op + (1.0 - target_start_op) * in_factor
                    curr_op = box.get_opacity()
                    if not isinstance(curr_op, (int, float)) or abs(curr_op - new_op) > 0.005 or progress >= 1.0:
                        box.set_opacity(new_op)
            else:
                out_start_op = start_opacities.get(box, 1.0)
                if out_start_op > 0.0:
                    # Synchronize outgoing opacity with geometry contraction
                    out_factor = max(0.0, 1.0 - factor * 2.2)
                    new_op = out_start_op * out_factor
                    curr_op = box.get_opacity()
                    if not isinstance(curr_op, (int, float)) or abs(curr_op - new_op) > 0.005 or progress >= 1.0:
                        box.set_opacity(new_op)

        self.queue_draw()

        if progress >= 1.0:
            self._anim_running = False
            self._anim_timer = None
            self._anim_tick_id = None
            self._state = self._target_state
            self._current_w = self._anim_target_w
            self._current_h = self._anim_target_h

            for s, box in active_boxes.items():
                if s == self._state:
                    box.set_visible(True)
                    box.set_opacity(1.0)
                else:
                    box.set_visible(False)
                    box.set_opacity(0.0)

            dim_map = {
                self.STATE_IDLE: (IDLE_W, IDLE_H),
                self.STATE_COMPACT: (COMPACT_W, COMPACT_H),
                self.STATE_NOTIF: (NOTIF_W, NOTIF_H),
                self.STATE_EMPTY: (EMPTY_EXPANDED_W, EMPTY_EXPANDED_H),
                self.STATE_FULL: (EXPANDED_W, EXPANDED_H if self._has_lyrics else EXPANDED_H_NOLYRIC),
            }
            if self._state in dim_map:
                w, h = dim_map[self._state]
                self._update_input_shape(w, h)
            return False

        return True

    # ─────────────────────────────────────────────────────────
    #  HOVER, MOTION & SCROLL HANDLERS
    # ─────────────────────────────────────────────────────────
    def _on_scroll(self, widget, event):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        curr = self.vol.get()
        if event.direction == Gdk.ScrollDirection.UP:
            new_v = min(1.5, curr + 0.05)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            new_v = max(0.0, curr - 0.05)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            new_v = max(0.0, min(1.5, curr - dy * 0.05))
        else:
            return False

        self.vol.set(new_v)
        pct = int(round(new_v * 100))
        self.show_notification("🔊", "Volume", f"{pct}%", duration_s=1.2)
        return True

    def _on_enter(self, widget, event):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self._cancel_timer("_collapse_timer")
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        target = self.STATE_FULL if has_music else self.STATE_EMPTY
        if self._target_state != target or (self._state != target and not self._anim_running):
            self._animate_to(target)
        return False

    def _on_motion(self, widget, event):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        self._cancel_timer("_collapse_timer")
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        target = self.STATE_FULL if has_music else self.STATE_EMPTY
        if self._target_state != target or (self._state != target and not self._anim_running):
            self._animate_to(target)
        return False

    def _on_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self._seeking or self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        self._cancel_timer("_collapse_timer")
        self._collapse_timer = GLib.timeout_add(COLLAPSE_DELAY_MS, self._do_collapse)
        return False

    def _do_collapse(self):
        self._collapse_timer = None
        if self._seeking or self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return False
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        target = self.STATE_COMPACT if has_music else self.STATE_IDLE
        if self._target_state != target or (self._state != target and not self._anim_running):
            self._animate_to(target)
        return False

    # ─────────────────────────────────────────────────────────
    #  REAL-TIME SYNCED LYRIC POLLING (150ms)
    # ─────────────────────────────────────────────────────────
    def _on_lyric_tick(self):
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return True
        if not self._last_info:
            return True

        status = self._last_info.get("status", "Stopped")
        title = self._last_info.get("title")

        if not title or status == "Stopped":
            if self._has_lyrics:
                self._has_lyrics = False
                self._lyric_row.set_visible(False)
            self._last_lyric_line = ""
            self._full_lyric_label.set_text("")
            return True

        pos_us = self.media.get_position_us()
        l_state = self.lyrics.get_state(pos_us)
        curr_lyric = l_state["current_line"]
        l_status = l_state["status"]

        has_synced = (l_status == LyricsController.STATUS_SYNCED and bool(curr_lyric or l_state.get("is_intro")))
        is_instrumental = (l_status == LyricsController.STATUS_INSTRUMENTAL)

        should_show = has_synced or is_instrumental
        if should_show != self._has_lyrics:
            self._has_lyrics = should_show
            self._lyric_row.set_visible(should_show)
            if self._state == self.STATE_FULL and not self._anim_running:
                self._animate_to(self.STATE_FULL)
                self.queue_draw()

        if has_synced:
            if l_state.get("is_intro"):
                lyric_text = "• • •"
            elif curr_lyric:
                # Sanitize multiple newlines: allow at most one natural line break; subsequent breaks collapse to spaces
                parts = curr_lyric.replace("\r", "").split("\n")
                if len(parts) > 2:
                    curr_lyric = parts[0] + "\n" + " ".join(parts[1:])
                lyric_text = f"“{curr_lyric}”"
            else:
                lyric_text = "• • •"
        elif is_instrumental:
            lyric_text = "Instrumental"
        else:
            lyric_text = ""

        if lyric_text != self._last_lyric_line:
            self._last_lyric_line = lyric_text
            self._full_lyric_label.set_text(lyric_text)

        return True

    # ─────────────────────────────────────────────────────────
    #  PERIODIC TICK (SPOTIFY METADATA + BATTERY NOTIFICATIONS)
    # ─────────────────────────────────────────────────────────
    def _on_tick(self):
        info = self.media.get_info()
        tws = self.bt.get_info()
        self._last_info = info

        # Continuous background media & audio tracking
        has_music = bool(info.get("title") and info.get("status") != "Stopped")
        is_playing = (info.get("status") == "Playing")
        if hasattr(self, "_audio_monitor") and self._audio_monitor:
            self._audio_monitor.set_playing(is_playing)

        title = info.get("title")
        artist = info.get("artist") or ""
        track_id = info.get("track_id") or "/"
        current_track_key = f"{track_id}|{artist}|{title}" if has_music else None

        if current_track_key != self._current_track_key:
            self._current_track_key = current_track_key
            self._last_lyric_line = ""
            if hasattr(self, "_full_lyric_label"):
                self._full_lyric_label.set_text("")

        dur_s = info.get("length_us", 0) // 1_000_000
        self.lyrics.update_track(info.get("title"), info.get("artist"), info.get("album"), dur_s)

        # In Cinema Mode, keep window hidden and suppress on-screen notifications/draws
        if self._is_cinema_suppressed or self._state == self.STATE_CINEMA_SUPPRESSED:
            return True

        # Verify geometry & monitor workarea on each tick
        self._update_geometry_and_position()

        # Battery power state transitions & low battery notifications for laptop
        laptop_bat = self.bt.get_laptop_battery()
        if laptop_bat:
            curr_charging = laptop_bat.get("charging")
            pct = laptop_bat.get("percent", 0)
            if self._last_battery_state is not None and curr_charging != self._last_battery_state:
                if curr_charging:
                    self.show_notification("⚡", "Charger Connected", f"{pct}% battery")
                else:
                    self.show_notification("🔋", "On Battery Power", f"{pct}% remaining")
            elif not curr_charging and pct <= 20 and not self._low_battery_notified:
                self._low_battery_notified = True
                self.show_notification("⚠️", "Low Battery", f"{pct}% remaining")
            elif pct > 20:
                self._low_battery_notified = False
            self._last_battery_state = curr_charging

        # Auto-state transition when not hovered, not in notification, and not cinema-suppressed
        if not self._anim_running and self._state not in (self.STATE_FULL, self.STATE_EMPTY, self.STATE_NOTIF):
            if has_music and self._state == self.STATE_IDLE:
                self._animate_to(self.STATE_COMPACT)
            elif not has_music and self._state == self.STATE_COMPACT:
                self._animate_to(self.STATE_IDLE)

        # Update UI according to active state
        if self._state == self.STATE_COMPACT:
            self._update_compact_ui()
        elif self._state == self.STATE_FULL:
            self._update_full_ui()

        return True

    def _update_compact_ui(self):
        info = self._last_info
        if not info:
            return

        is_playing = (info.get("status") == "Playing")
        self.compact_activity.set_playing(is_playing)

        title = (info.get("title") or "Music").replace("\r", "").replace("\n", " ")
        artist = (info.get("artist") or "").replace("\r", "").replace("\n", " ")

        self.compact_title.set_text(title)
        self.compact_artist.set_text(artist)

        pb = info.get("pixbuf_compact")
        if pb:
            self.compact_art_image.set_from_pixbuf(pb)
            self.compact_art_image.set_visible(True)
        else:
            self.compact_art_image.set_visible(False)

        self._refresh_bt_ui()

    def _update_full_ui(self):
        info = self._last_info
        if not info:
            return

        is_playing = (info.get("status") == "Playing")
        self.full_activity.set_playing(is_playing)
        self._refresh_bt_ui()

        # Track metadata
        title = (info.get("title") or "Not Playing").replace("\r", "").replace("\n", " ")
        artist = (info.get("artist") or "Open Spotify to play").replace("\r", "").replace("\n", " ")
        self.full_title.set_text(title)
        self.full_artist.set_text(artist)

        # Play/pause icon
        icon_name = "media-playback-pause-symbolic" if is_playing else "media-playback-start-symbolic"
        self.play_icon.set_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        self.play_icon.set_pixel_size(20)

        # Album art (42x42)
        pb = info.get("pixbuf")
        if pb:
            self.art_image.set_from_pixbuf(pb)
            self.art_image.set_visible(True)
        else:
            self.art_image.set_visible(False)

        # Seekbar & Remaining Time
        l_us = info.get("length_us", 0)
        p_us = info.get("position_us", 0)
        if l_us > 0 and not self._seeking:
            frac = min(1.0, max(0.0, p_us / float(l_us)))
            self._set_scale_val(self.seek_scale, frac, "_seek_blocked")
            self.lbl_cur_time.set_text(format_time(p_us))
            rem_us = max(0, l_us - p_us)
            self.lbl_tot_time.set_text(f"-{format_time(rem_us)}")
            self.seek_scale.set_sensitive(True)
        elif not self._seeking:
            self._set_scale_val(self.seek_scale, 0, "_seek_blocked")
            self.lbl_cur_time.set_text("0:00")
            self.lbl_tot_time.set_text("-0:00")
            self.seek_scale.set_sensitive(False)

        return True

    # ─────────────────────────────────────────────────────────
    #  SLIDER & SEEK CALLBACKS
    # ─────────────────────────────────────────────────────────
    def _set_scale_val(self, scale, val, block_attr):
        setattr(self, block_attr, True)
        scale.set_value(val)
        setattr(self, block_attr, False)

    def _on_seek_press(self, scale, event):
        self._seeking = True

    def _on_seek_release(self, scale, event):
        self._seeking = False
        frac = scale.get_value()
        length_us = self._last_info.get("length_us", 0)
        track_id = self._last_info.get("track_id", "/")
        if length_us > 0:
            pos = int(frac * length_us)
            self.media.seek_to(pos, track_id)

    def _on_seek_changed(self, scale):
        if self._seeking and not self._seek_blocked:
            length_us = self._last_info.get("length_us", 0)
            if length_us > 0:
                pos = int(scale.get_value() * length_us)
                self.lbl_cur_time.set_text(format_time(pos))
                rem_us = max(0, length_us - pos)
                self.lbl_tot_time.set_text(f"-{format_time(rem_us)}")

# ─────────────────────────────────────────────────────────────
#  ENTRY POINT & SINGLE-INSTANCE MANAGEMENT
# ─────────────────────────────────────────────────────────────
def acquire_single_instance_lock():
    """Acquires a single-instance advisory lock.
    Returns (lock_fd, existing_pid). If another instance is running, returns (None, existing_pid).
    """
    my_pid = os.getpid()

    # 1. Check proc table for existing running notch.py instances
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            pid = int(p.split("/")[2])
            if pid == my_pid:
                continue
            with open(p, "rb") as f:
                cmdline = f.read().decode("utf-8", errors="ignore").replace("\0", " ")
                if "notch.py" in cmdline and "test" not in cmdline and "grep" not in cmdline:
                    return None, pid
        except (IOError, OSError, ValueError):
            continue

    # 2. Kernel-enforced file lock using fcntl.flock
    lock_path = os.path.join(tempfile.gettempdir(), f"dynamic_notch_{os.getuid()}.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(lock_fd, 0)
        os.write(lock_fd, f"{my_pid}\n".encode("utf-8"))
        os.lseek(lock_fd, 0, os.SEEK_SET)
        return lock_fd, None
    except (BlockingIOError, IOError):
        existing_pid = None
        try:
            with open(lock_path, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    existing_pid = int(content)
        except Exception:
            pass
        return None, existing_pid


def main():
    if "--cinema-toggle" in sys.argv:
        override = "/tmp/dynamic_notch_cinema_override"
        if os.path.exists(override):
            os.remove(override)
            print("🎬 Cinema Mode override toggled OFF (Dynamic Island restored).")
        else:
            with open(override, "w") as f:
                f.write("1\n")
            print("🎬 Cinema Mode override toggled ON (Dynamic Island suppressed).")
        sys.exit(0)

    # Prevent accidental duplicate instances if already running
    lock_fd, existing_pid = acquire_single_instance_lock()
    if lock_fd is None:
        pid_msg = f" (PID {existing_pid})" if existing_pid else ""
        print(f"ℹ️  Dynamic Notch is already running{pid_msg}. Preventing duplicate instance.")
        return 0

    print("🚀 Dynamic Notch is running!")
    print("   📍 Position: Centered top notch on Wayland desktop (XWayland).")
    print("   💡 Hover over the notch to expand the music player.")
    print(f"   💧 Background water reminders every {WATER_REMINDER_INTERVAL_MIN} minutes via notify-send.")
    print("   🎬 Cinema Mode: Automatically hides over fullscreen video (VLC/Browser/etc).")
    print("   🛑 Press Ctrl+C to terminate.\n")
    win = DynamicIslandWindow()
    try:
        Gtk.main()
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                pass

if __name__ == "__main__":
    main()
