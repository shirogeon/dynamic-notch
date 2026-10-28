#!/usr/bin/env python3
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
import json
import re
import glob
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
CANVAS_H = 250              # Fixed transparent window canvas height

IDLE_W = 180                # Resting camera notch cover
IDLE_H = 30

MINI_W = 320                # Two-line mini pill: title+badge / live lyric
MINI_H = 42

FULL_W = 400                # Expanded music player
FULL_H = 210

NOTIF_W = 300               # Transient notification pill
NOTIF_H = 36

MARGIN_TOP_SCREEN = 0       # Flush with screen top when top panel is hidden
MARGIN_TOP_PANEL = 0        # Flush with bottom edge of top panel when present

ANIM_DURATION_MS = 220      # Snappy 220ms macOS-like spring transition
ANIM_INTERVAL_MS = 16       # 60 FPS tick
COLLAPSE_DELAY_MS = 550     # Collapse grace period after mouse leaves
UPDATE_INTERVAL_MS = 1000   # Polling interval for battery/media stats
LYRIC_TICK_MS = 150         # 150ms lyric sync polling
ART_SIZE = 46               # Album art dimensions (px)

WATER_REMINDER_INTERVAL_MIN = 30   # Background water reminder interval

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
    color: rgba(255, 255, 255, 0.50);
    font-size: 10px;
    font-weight: 500;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    letter-spacing: 0.2px;
}

/* ── MINI STATE (Resting Music Pill) ── */
.mini-box {
    padding: 4px 18px 5px 18px;
}
.mini-icon {
    color: #1ed760;
    margin-right: 2px;
}
.mini-title {
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    letter-spacing: -0.15px;
}
.mini-sep {
    color: rgba(255, 255, 255, 0.25);
    font-size: 9px;
    margin: 0 4px;
}
.mini-badge {
    color: rgba(255, 255, 255, 0.75);
    font-size: 9.5px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Mono", monospace;
}
.mini-lyric {
    color: rgba(255, 255, 255, 0.60);
    font-size: 9.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    font-style: italic;
    letter-spacing: -0.1px;
}

/* ── TRANSIENT NOTIFICATION OVERLAY ── */
.notif-box {
    padding: 6px 18px;
}
.notif-icon {
    font-size: 12px;
    margin-right: 8px;
}
.notif-title {
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
.notif-sub {
    color: rgba(255, 255, 255, 0.60);
    font-size: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Mono", monospace;
    margin-left: 6px;
}

/* ── EXPANDED MUSIC PLAYER VIEW ── */
.full-box {
    padding: 10px 16px 10px 16px;
}

/* Album Art */
.album-art {
    border-radius: 8px;
}
.art-placeholder {
    background: linear-gradient(135deg, #1c1c1e, #2c2c2e);
    border-radius: 8px;
    min-width: 46px;
    min-height: 46px;
}
.art-click-area {
    border-radius: 8px;
}

/* Track Info */
.full-title {
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", sans-serif;
    letter-spacing: -0.2px;
}
.full-artist {
    color: rgba(255, 255, 255, 0.50);
    font-size: 10.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
.tws-chip {
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    padding: 2px 7px;
    color: rgba(255, 255, 255, 0.75);
    font-size: 9.5px;
    font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, "SF Mono", monospace;
}

/* Synced Lyric Capsule */
.lyric-capsule {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 6px;
    padding: 4px 10px;
}
.full-lyric-icon {
    color: #1ed760;
    font-size: 9px;
    margin-right: 4px;
}
.full-lyric {
    color: rgba(255, 255, 255, 0.88);
    font-size: 10.5px;
    font-weight: 400;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    font-style: italic;
    letter-spacing: -0.1px;
}

/* Seekbar & Timestamps */
.time-label {
    color: rgba(255, 255, 255, 0.38);
    font-size: 9px;
    font-weight: 500;
    font-family: "SF Mono", "JetBrains Mono", monospace;
    letter-spacing: 0.2px;
}

/* Playback Controls */
.ctrl-btn {
    background: transparent;
    border: none;
    border-radius: 50%;
    min-width: 28px;
    min-height: 28px;
    color: rgba(255, 255, 255, 0.72);
    padding: 0;
    transition: all 120ms ease;
}
.ctrl-btn:hover {
    background-color: rgba(255, 255, 255, 0.12);
    color: #ffffff;
}
.ctrl-btn-play {
    background-color: rgba(255, 255, 255, 0.16);
    border: none;
    border-radius: 50%;
    min-width: 34px;
    min-height: 34px;
    color: #ffffff;
    padding: 0;
    transition: all 120ms ease;
}
.ctrl-btn-play:hover {
    background-color: rgba(255, 255, 255, 0.28);
}

/* Volume Slider */
scale {
    padding: 0;
    margin: 0;
}
scale trough {
    background-color: rgba(255, 255, 255, 0.10);
    border-radius: 2px;
    min-height: 3px;
    border: none;
}
scale slider {
    background-color: #ffffff;
    border-radius: 50%;
    min-width: 9px;
    min-height: 9px;
    border: none;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
}
.seek-slider highlight {
    background-color: rgba(255, 255, 255, 0.82);
    border-radius: 2px;
    min-height: 3px;
    border: none;
}
.vol-slider highlight {
    background-color: rgba(255, 255, 255, 0.48);
    border-radius: 2px;
    min-height: 3px;
    border: none;
}
.slider-icon {
    color: rgba(255, 255, 255, 0.38);
    padding: 0 2px;
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
        self._cached_pixbuf = None
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
            "pixbuf": self._cached_pixbuf,
        }
        if not self.is_available():
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

            if art_url and art_url != self._cached_art_url:
                self._cached_art_url = art_url
                threading.Thread(target=self._fetch_art, args=(art_url,), daemon=True).start()

            return {
                "title": title,
                "artist": artist,
                "album": album,
                "length_us": length_us,
                "position_us": position_us,
                "status": status,
                "track_id": track_id,
                "art_url": art_url,
                "pixbuf": self._cached_pixbuf,
            }
        except Exception:
            self._player = None
            self._props = None
            return default

    def _fetch_art(self, url):
        cache_file = "/tmp/dynamic_notch_art.jpg"
        try:
            urllib.request.urlretrieve(url, cache_file)
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(cache_file, ART_SIZE, ART_SIZE, True)
            self._cached_pixbuf = round_corners_pixbuf(pb, radius=8)
        except Exception:
            self._cached_pixbuf = None

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
    _AUDIO_ICONS = {"audio-headphones", "audio-headset", "audio-card"}

    def get_info(self):
        # 1. Bluetooth Headphones / TWS check
        try:
            bus = dbus.SystemBus()
            mgr = dbus.Interface(
                bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            for path, ifaces in mgr.GetManagedObjects().items():
                if "org.bluez.Battery1" in ifaces:
                    pct = int(ifaces["org.bluez.Battery1"].get("Percentage", 0))
                    dev = ifaces.get("org.bluez.Device1", {})
                    name = str(dev.get("Name", "TWS"))[:12] if dev else "TWS"
                    return {"name": name, "percent": pct, "is_laptop": False, "charging": False}
                if "org.bluez.Device1" in ifaces:
                    dev = ifaces["org.bluez.Device1"]
                    if dev.get("Connected") and str(dev.get("Icon", "")) in self._AUDIO_ICONS:
                        name = str(dev.get("Name", "TWS"))[:12]
                        return {"name": name, "percent": -1, "is_laptop": False, "charging": False}
        except Exception:
            pass

        # 2. Laptop Battery fallback
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
                return {"name": "Laptop", "percent": cap, "is_laptop": True, "charging": charging}
        except Exception:
            pass
        return None

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
#  MAIN DYNAMIC ISLAND WINDOW (FIXED CANVAS ARCHITECTURE)
# ─────────────────────────────────────────────────────────────
class DynamicIslandWindow(Gtk.Window):
    STATE_IDLE = 0
    STATE_MINI = 1
    STATE_FULL = 2
    STATE_NOTIF = 3

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        self.media = MediaController(on_change_callback=self._on_tick)
        self.vol = VolumeController()
        self.bt = BluetoothBattery()
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

        self._collapse_timer = None
        self._notif_timer = None
        self._water_reminder_timer = None
        self._seeking = False
        self._vol_dragging = False
        self._last_info = {}
        self._last_battery_state = None

        self._vol_blocked = False
        self._seek_blocked = False

        self._current_track_key = None
        self._last_lyric_line = None
        self._last_mini_lyric = None
        self._lyric_fade_progress = 1.0

        # Dynamic positioning state
        self._current_pos_x = None
        self._current_pos_y = None

        self._setup_window()
        self._build_ui()
        self._apply_css()

        self.show_all()
        self._full_box.set_visible(False)
        self._mini_box.set_visible(False)
        self._notif_box.set_visible(False)
        self._idle_box.set_visible(True)
        self._update_input_shape(IDLE_W, IDLE_H)

        GLib.timeout_add(UPDATE_INTERVAL_MS, self._on_tick)
        GLib.timeout_add(LYRIC_TICK_MS, self._on_lyric_tick)
        self._on_tick()

        # Start background water reminder
        self._start_water_reminder()

        self.connect("delete-event", self._on_delete)

    def _on_delete(self, *_):
        if self._water_reminder_timer:
            GLib.source_remove(self._water_reminder_timer)
            self._water_reminder_timer = None
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
        # Reschedule for next interval (return False to cancel current, re-add manually)
        interval_ms = WATER_REMINDER_INTERVAL_MIN * 60 * 1000
        self._water_reminder_timer = GLib.timeout_add(interval_ms, self._water_reminder_tick)
        return False  # Cancel the current GLib source; we re-added above

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

        if h <= float(MINI_H):
            r = h / 2.0
        else:
            prog = (h - float(MINI_H)) / float(FULL_H - MINI_H)
            prog = max(0.0, min(1.0, prog))
            t_smooth = prog * prog * (3.0 - 2.0 * prog)
            r = (float(MINI_H) / 2.0) + (26.0 - (float(MINI_H) / 2.0)) * t_smooth

        cr.new_sub_path()
        cr.arc(px + w - r, py + r, r, -math.pi / 2, 0)
        cr.arc(px + w - r, py + h - r, r, 0, math.pi / 2)
        cr.arc(px + r, py + h - r, r, math.pi / 2, math.pi)
        cr.arc(px + r, py + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        # OLED Deep Black Base Fill
        cr.set_source_rgba(0.04, 0.04, 0.05, 0.98)
        cr.fill_preserve()

        # Specular satin sheen on top rim
        cr.save()
        cr.clip_preserve()
        sheen_h = min(h, 45.0)
        sheen = cairo.LinearGradient(px, py, px, py + sheen_h)
        sheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.04)
        sheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
        cr.set_source(sheen)
        cr.paint()
        cr.restore()

        # 3-stop macOS glass rim highlight
        rim = cairo.LinearGradient(px, py, px, py + h)
        rim.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.20)
        rim.add_color_stop_rgba(0.4, 1.0, 1.0, 1.0, 0.09)
        rim.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.04)
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

        # ── 1. IDLE VIEW (Camera Notch Cover) ──
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

        # ── 2. MINI COLLAPSED VIEW ──
        self._mini_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._mini_box.get_style_context().add_class("mini-box")
        self._mini_box.set_halign(Gtk.Align.CENTER)
        self._mini_box.set_valign(Gtk.Align.START)
        self._mini_box.set_size_request(MINI_W, MINI_H)

        mini_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        mini_top.set_halign(Gtk.Align.CENTER)
        self._mini_box.pack_start(mini_top, False, False, 0)

        self._mini_icon_img = Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.MENU)
        self._mini_icon_img.get_style_context().add_class("mini-icon")
        mini_top.pack_start(self._mini_icon_img, False, False, 0)

        self._mini_title = Gtk.Label(label="")
        self._mini_title.get_style_context().add_class("mini-title")
        self._mini_title.set_ellipsize(Pango.EllipsizeMode.END)
        self._mini_title.set_max_width_chars(20)
        mini_top.pack_start(self._mini_title, False, False, 0)

        self._mini_sep = Gtk.Label(label="·")
        self._mini_sep.get_style_context().add_class("mini-sep")
        mini_top.pack_start(self._mini_sep, False, False, 0)

        self._mini_badge = Gtk.Label(label="")
        self._mini_badge.get_style_context().add_class("mini-badge")
        mini_top.pack_start(self._mini_badge, False, False, 0)

        # Single synced lyric line in mini view
        self._mini_lyric = Gtk.Label(label="")
        self._mini_lyric.get_style_context().add_class("mini-lyric")
        self._mini_lyric.set_ellipsize(Pango.EllipsizeMode.END)
        self._mini_lyric.set_max_width_chars(38)
        self._mini_lyric.set_halign(Gtk.Align.CENTER)
        self._mini_box.pack_start(self._mini_lyric, False, False, 0)
        self._overlay.add_overlay(self._mini_box)

        # ── 3. TRANSIENT NOTIFICATION OVERLAY ──
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

        # ── 4. EXPANDED MUSIC PLAYER VIEW (no tabs) ──
        self._full_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self._full_box.get_style_context().add_class("full-box")
        self._full_box.set_halign(Gtk.Align.CENTER)
        self._full_box.set_valign(Gtk.Align.START)
        self._full_box.set_size_request(FULL_W, FULL_H)
        self._overlay.add_overlay(self._full_box)

        self._build_music_panel()

    # ── Music Player Panel ──
    def _build_music_panel(self):
        # Header row: Album Art + Track Info + Battery chip
        row_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._full_box.pack_start(row_hdr, False, False, 0)

        # Album art
        self.art_image = Gtk.Image()
        self.art_image.get_style_context().add_class("album-art")
        self.art_placeholder = Gtk.Box()
        self.art_placeholder.get_style_context().add_class("art-placeholder")
        self.art_container = Gtk.Overlay()
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
        self.full_title.set_halign(Gtk.Align.START)
        self.full_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_title.set_max_width_chars(24)
        info_col.pack_start(self.full_title, False, False, 0)

        self.full_artist = Gtk.Label(label="Open Spotify to play")
        self.full_artist.get_style_context().add_class("full-artist")
        self.full_artist.set_halign(Gtk.Align.START)
        self.full_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.full_artist.set_max_width_chars(28)
        info_col.pack_start(self.full_artist, False, False, 0)

        # Battery / TWS chip (top-right)
        self.full_tws = Gtk.Label(label="")
        self.full_tws.get_style_context().add_class("tws-chip")
        self.full_tws.set_valign(Gtk.Align.CENTER)
        row_hdr.pack_end(self.full_tws, False, False, 0)

        # Synced Lyric Capsule (single line, no click-to-expand)
        self._lyric_capsule = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._lyric_capsule.get_style_context().add_class("lyric-capsule")
        self._full_box.pack_start(self._lyric_capsule, False, False, 0)

        self._lyric_icon = Gtk.Label(label="♫")
        self._lyric_icon.get_style_context().add_class("full-lyric-icon")
        self._lyric_capsule.pack_start(self._lyric_icon, False, False, 0)

        self._full_lyric_label = Gtk.Label(label="Listening to music...")
        self._full_lyric_label.get_style_context().add_class("full-lyric")
        self._full_lyric_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._full_lyric_label.set_max_width_chars(44)
        self._full_lyric_label.set_halign(Gtk.Align.START)
        self._lyric_capsule.pack_start(self._full_lyric_label, True, True, 0)

        # Seekbar row
        row_seek = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
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

        self.lbl_tot_time = Gtk.Label(label="0:00")
        self.lbl_tot_time.get_style_context().add_class("time-label")
        row_seek.pack_start(self.lbl_tot_time, False, False, 0)

        # Playback Controls row
        row_ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row_ctrl.set_halign(Gtk.Align.CENTER)
        self._full_box.pack_start(row_ctrl, False, False, 0)

        btn_prev = Gtk.Button()
        btn_prev.get_style_context().add_class("ctrl-btn")
        btn_prev.set_image(Gtk.Image.new_from_icon_name("media-skip-backward-symbolic", Gtk.IconSize.BUTTON))
        btn_prev.connect("clicked", lambda *_: self.media.prev())
        row_ctrl.pack_start(btn_prev, False, False, 0)

        self.btn_play = Gtk.Button()
        self.btn_play.get_style_context().add_class("ctrl-btn-play")
        self.play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.btn_play.set_image(self.play_icon)
        self.btn_play.connect("clicked", lambda *_: self.media.play_pause())
        row_ctrl.pack_start(self.btn_play, False, False, 0)

        btn_next = Gtk.Button()
        btn_next.get_style_context().add_class("ctrl-btn")
        btn_next.set_image(Gtk.Image.new_from_icon_name("media-skip-forward-symbolic", Gtk.IconSize.BUTTON))
        btn_next.connect("clicked", lambda *_: self.media.next())
        row_ctrl.pack_start(btn_next, False, False, 0)

        # Volume slider row
        row_vol = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._full_box.pack_start(row_vol, False, False, 0)

        vol_icon_lo = Gtk.Image.new_from_icon_name("audio-volume-low-symbolic", Gtk.IconSize.MENU)
        vol_icon_lo.get_style_context().add_class("slider-icon")
        row_vol.pack_start(vol_icon_lo, False, False, 0)

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1.5, 0.01)
        self.vol_scale.get_style_context().add_class("vol-slider")
        self.vol_scale.set_draw_value(False)
        self.vol_scale.connect("button-press-event", lambda *_: setattr(self, "_vol_dragging", True))
        self.vol_scale.connect("button-release-event", lambda *_: setattr(self, "_vol_dragging", False))
        self.vol_scale.connect("value-changed", self._on_vol_changed)
        row_vol.pack_start(self.vol_scale, True, True, 0)

        vol_icon_hi = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic", Gtk.IconSize.MENU)
        vol_icon_hi.get_style_context().add_class("slider-icon")
        row_vol.pack_start(vol_icon_hi, False, False, 0)

    # ─────────────────────────────────────────────────────────
    #  TRANSIENT NOTIFICATIONS
    # ─────────────────────────────────────────────────────────
    def show_notification(self, icon: str, title: str, subtitle: str = "", duration_s: float = 2.5):
        self._notif_icon.set_text(icon)
        self._notif_title.set_text(title)
        self._notif_sub.set_text(subtitle)

        if self._state == self.STATE_FULL:
            return  # Don't hijack expanded panel

        if self._notif_timer:
            GLib.source_remove(self._notif_timer)

        self._animate_to(self.STATE_NOTIF)
        self._notif_timer = GLib.timeout_add(int(duration_s * 1000), self._dismiss_notification)

    def _dismiss_notification(self):
        self._notif_timer = None
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        self._animate_to(self.STATE_MINI if has_music else self.STATE_IDLE)
        return False

    # ─────────────────────────────────────────────────────────
    #  DYNAMIC INPUT SHAPE (PASS-THROUGH ON EMPTY REGION)
    # ─────────────────────────────────────────────────────────
    def _update_input_shape(self, w, h):
        gdk_win = self.get_window()
        if gdk_win:
            px = int((CANVAS_W - w) / 2)
            rect = cairo.RectangleInt(px, 0, int(w), int(h))
            reg = cairo.Region(rect)
            gdk_win.input_shape_combine_region(reg, 0, 0)

    # ─────────────────────────────────────────────────────────
    #  60 FPS SMOOTH ANIMATION ENGINE (CUBIC EASE-OUT)
    # ─────────────────────────────────────────────────────────
    def _animate_to(self, target_state):
        if self._state == target_state and not self._anim_running:
            return

        self._target_state = target_state

        if target_state == self.STATE_IDLE:
            target_w, target_h = float(IDLE_W), float(IDLE_H)
        elif target_state == self.STATE_MINI:
            target_w, target_h = float(MINI_W), float(MINI_H)
        elif target_state == self.STATE_NOTIF:
            target_w, target_h = float(NOTIF_W), float(NOTIF_H)
        else:
            target_w, target_h = float(FULL_W), float(FULL_H)
            self._set_scale_val(self.vol_scale, self.vol.get(), "_vol_blocked")
            self._update_full_ui()

        self._start_w = self._current_w
        self._start_h = self._current_h
        self._anim_target_w = target_w
        self._anim_target_h = target_h
        self._anim_start_time = time.time() * 1000.0

        # Pre-activate target widget for seamless cross-fade
        if target_state == self.STATE_FULL:
            self._full_box.set_visible(True)
            self._update_input_shape(FULL_W, FULL_H)
        elif target_state == self.STATE_MINI:
            self._mini_box.set_visible(True)
        elif target_state == self.STATE_NOTIF:
            self._notif_box.set_visible(True)
        else:
            self._idle_box.set_visible(True)

        if not self._anim_running:
            self._anim_running = True
            GLib.timeout_add(ANIM_INTERVAL_MS, self._anim_step)

    def _anim_step(self):
        now = time.time() * 1000.0
        elapsed = now - self._anim_start_time
        progress = min(1.0, elapsed / float(ANIM_DURATION_MS))

        # Smooth cubic ease-out deceleration curve
        factor = 1.0 - (1.0 - progress) ** 3

        self._current_w = self._start_w + (self._anim_target_w - self._start_w) * factor
        self._current_h = self._start_h + (self._anim_target_h - self._start_h) * factor

        # Cross-fade box opacities
        active_boxes = {
            self.STATE_IDLE: self._idle_box,
            self.STATE_MINI: self._mini_box,
            self.STATE_NOTIF: self._notif_box,
            self.STATE_FULL: self._full_box,
        }

        target_box = active_boxes.get(self._target_state)
        in_op = max(0.0, min(1.0, (progress - 0.15) / 0.85))
        out_op = max(0.0, 1.0 - progress * 2.2)

        for s, box in active_boxes.items():
            if box == target_box:
                box.set_opacity(in_op)
            else:
                box.set_opacity(out_op)

        self.queue_draw()

        if progress >= 1.0:
            self._anim_running = False
            self._state = self._target_state
            self._current_w = self._anim_target_w
            self._current_h = self._anim_target_h

            for s, box in active_boxes.items():
                if s == self._state:
                    box.set_visible(True)
                    box.set_opacity(1.0)
                else:
                    box.set_visible(False)

            dim_map = {
                self.STATE_IDLE: (IDLE_W, IDLE_H),
                self.STATE_MINI: (MINI_W, MINI_H),
                self.STATE_NOTIF: (NOTIF_W, NOTIF_H),
                self.STATE_FULL: (FULL_W, FULL_H),
            }
            w, h = dim_map[self._state]
            self._update_input_shape(w, h)
            return False

        return True

    # ─────────────────────────────────────────────────────────
    #  HOVER, MOTION & SCROLL HANDLERS
    # ─────────────────────────────────────────────────────────
    def _on_scroll(self, widget, event):
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
        self._set_scale_val(self.vol_scale, new_v, "_vol_blocked")
        pct = int(new_v * 100)
        self.show_notification("🔊", "Volume", f"{pct}%", duration_s=1.5)
        return True

    def _on_enter(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self._collapse_timer:
            GLib.source_remove(self._collapse_timer)
            self._collapse_timer = None
        if self._state != self.STATE_FULL:
            self._animate_to(self.STATE_FULL)
        return False

    def _on_motion(self, widget, event):
        if self._collapse_timer:
            GLib.source_remove(self._collapse_timer)
            self._collapse_timer = None
        if self._state != self.STATE_FULL and not self._anim_running:
            self._animate_to(self.STATE_FULL)
        return False

    def _on_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self._seeking or self._vol_dragging:
            return False
        if self._collapse_timer:
            GLib.source_remove(self._collapse_timer)
        self._collapse_timer = GLib.timeout_add(COLLAPSE_DELAY_MS, self._do_collapse)
        return False

    def _do_collapse(self):
        self._collapse_timer = None
        if self._seeking or self._vol_dragging:
            return False
        has_music = bool(self._last_info.get("title") and self._last_info.get("status") != "Stopped")
        self._animate_to(self.STATE_MINI if has_music else self.STATE_IDLE)
        return False

    # ─────────────────────────────────────────────────────────
    #  REAL-TIME SYNCED LYRIC POLLING (150ms)
    # ─────────────────────────────────────────────────────────
    def _on_lyric_tick(self):
        if not self._last_info:
            return True

        status = self._last_info.get("status", "Stopped")
        title = self._last_info.get("title")
        artist = self._last_info.get("artist") or ""

        if not title or status == "Stopped":
            if self._last_lyric_line != "":
                self._last_lyric_line = ""
                self._last_mini_lyric = ""
                self._mini_lyric.set_text("")
                self._full_lyric_label.set_text("Open Spotify to play")
            return True

        pos_us = self.media.get_position_us()
        l_state = self.lyrics.get_state(pos_us)
        curr_lyric = l_state["current_line"]
        next_lyric = l_state["next_line"]
        l_status = l_state["status"]

        # Build expanded and mini lyric text (never use artist or album as lyric text)
        if l_status == LyricsController.STATUS_SYNCED:
            if l_state["is_intro"]:
                full_text = "• • •"
                mini_text = "• • •"
            elif curr_lyric:
                full_text = f"\u201c{curr_lyric}\u201d"
                mini_text = f"\u201c{curr_lyric}\u201d"
            else:
                full_text = "• • •"
                mini_text = "• • •"
        elif l_status == LyricsController.STATUS_LOADING:
            full_text = "Searching lyrics..."
            mini_text = "• • •"
        elif l_status == LyricsController.STATUS_INSTRUMENTAL:
            full_text = "Instrumental"
            mini_text = "Instrumental"
        else:
            full_text = "No synced lyrics available"
            mini_text = ""

        if full_text != self._last_lyric_line or mini_text != self._last_mini_lyric:
            self._last_lyric_line = full_text
            self._last_mini_lyric = mini_text
            self._lyric_fade_progress = 0.0
            GLib.timeout_add(16, self._tick_lyric_fade)

            self._mini_lyric.set_text(mini_text)
            self._mini_lyric.set_opacity(0.0)

            self._full_lyric_label.set_text(full_text)
            self._lyric_capsule.set_opacity(0.0)

        return True

    def _tick_lyric_fade(self):
        self._lyric_fade_progress = min(1.0, self._lyric_fade_progress + 0.12)
        self._mini_lyric.set_opacity(self._lyric_fade_progress)
        self._lyric_capsule.set_opacity(self._lyric_fade_progress)
        return self._lyric_fade_progress < 1.0

    # ─────────────────────────────────────────────────────────
    #  PERIODIC TICK (SPOTIFY METADATA + BATTERY NOTIFICATIONS)
    # ─────────────────────────────────────────────────────────
    def _on_tick(self):
        # Verify geometry & monitor workarea on each tick
        self._update_geometry_and_position()

        info = self.media.get_info()
        tws = self.bt.get_info()
        self._last_info = info

        # Battery power state transitions → transient notifications
        if tws and tws.get("is_laptop"):
            curr_charging = tws.get("charging")
            pct = tws.get("percent", 0)
            if self._last_battery_state is not None and curr_charging != self._last_battery_state:
                if curr_charging:
                    self.show_notification("⚡", "Charger Connected", f"{pct}% battery")
                else:
                    self.show_notification("🔋", "On Battery Power", f"{pct}% remaining")
            self._last_battery_state = curr_charging

        has_music = bool(info.get("title") and info.get("status") != "Stopped")

        # Track identity tracking to immediately clear stale lyrics on song change
        title = info.get("title")
        artist = info.get("artist") or ""
        track_id = info.get("track_id") or "/"
        current_track_key = f"{track_id}|{artist}|{title}" if has_music else None

        if current_track_key != self._current_track_key:
            self._current_track_key = current_track_key
            self._last_lyric_line = None
            self._last_mini_lyric = None
            if has_music:
                self._mini_lyric.set_text("• • •")
                self._full_lyric_label.set_text("Searching lyrics...")
            else:
                self._mini_lyric.set_text("")
                self._full_lyric_label.set_text("Open Spotify to play")

        # Update lyrics controller track with duration for exact match
        dur_s = info.get("length_us", 0) // 1_000_000
        self.lyrics.update_track(info.get("title"), info.get("artist"), info.get("album"), dur_s)

        # Auto-state transition when not hovered and not in notification
        if not self._anim_running and self._state not in (self.STATE_FULL, self.STATE_NOTIF):
            if has_music and self._state == self.STATE_IDLE:
                self._animate_to(self.STATE_MINI)
            elif not has_music and self._state == self.STATE_MINI:
                self._animate_to(self.STATE_IDLE)

        # Update Mini UI
        if has_music:
            icon_name = "media-playback-pause-symbolic" if info["status"] == "Playing" else "media-playback-start-symbolic"
            self._mini_icon_img.set_from_icon_name(icon_name, Gtk.IconSize.MENU)
            self._mini_title.set_text(info["title"] or "")
            if tws:
                self._mini_sep.set_visible(True)
                pct = tws["percent"]
                if tws.get("is_laptop"):
                    txt = f"⚡{pct}%" if tws.get("charging") else f"🔋{pct}%"
                else:
                    txt = f"🎧{pct}%" if pct >= 0 else f"🎧{tws['name']}"
                self._mini_badge.set_text(txt)
                self._mini_badge.set_visible(True)
            else:
                self._mini_sep.set_visible(False)
                self._mini_badge.set_visible(False)

        # Update Full UI if expanded
        if self._state == self.STATE_FULL:
            self._update_full_ui()

        return True

    def _update_full_ui(self):
        info = self._last_info
        if not info:
            return
        tws = self.bt.get_info()

        # Track metadata
        self.full_title.set_text(info.get("title") or "Not Playing")

        artist = info.get("artist") or "Open Spotify to play"
        album = info.get("album")
        if album and album != info.get("title") and info.get("title"):
            subtitle = f"{artist} · {album}"
        else:
            subtitle = artist
        self.full_artist.set_text(subtitle)

        # Play/pause icon
        icon_name = "media-playback-pause-symbolic" if info.get("status") == "Playing" else "media-playback-start-symbolic"
        self.play_icon.set_from_icon_name(icon_name, Gtk.IconSize.BUTTON)

        # Album art
        if info.get("pixbuf"):
            self.art_image.set_from_pixbuf(info["pixbuf"])
            self.art_image.set_visible(True)
        else:
            self.art_image.set_visible(False)

        # Battery chip
        if tws:
            pct = tws["percent"]
            if tws.get("is_laptop"):
                txt = f"⚡ {pct}%" if tws.get("charging") else f"🔋 {pct}%"
            else:
                txt = f"🎧 {tws['name']} {pct}%" if pct >= 0 else f"🎧 {tws['name']}"
            self.full_tws.set_text(txt)
            self.full_tws.set_visible(True)
        else:
            self.full_tws.set_visible(False)

        # Seekbar
        l_us = info.get("length_us", 0)
        p_us = info.get("position_us", 0)
        if l_us > 0 and not self._seeking:
            frac = min(1.0, max(0.0, p_us / float(l_us)))
            self._set_scale_val(self.seek_scale, frac, "_seek_blocked")
            self.lbl_cur_time.set_text(format_time(p_us))
            self.lbl_tot_time.set_text(format_time(l_us))
            self.seek_scale.set_sensitive(True)
        elif not self._seeking:
            self._set_scale_val(self.seek_scale, 0, "_seek_blocked")
            self.lbl_cur_time.set_text("0:00")
            self.lbl_tot_time.set_text("0:00")
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

    def _on_vol_changed(self, scale):
        if not self._vol_blocked:
            self.vol.set(scale.get_value())

# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────
def main():
    print("🚀 Dynamic Notch is running!")
    print("   📍 Position: Centered top notch on Wayland desktop (XWayland).")
    print("   💡 Hover over the notch to expand the music player.")
    print("   💧 Background water reminders every 30 minutes via notify-send.")
    print("   🛑 Press Ctrl+C to terminate.\n")
    win = DynamicIslandWindow()
    Gtk.main()

if __name__ == "__main__":
    main()
