# Changelog

All notable changes to Dynamic Notch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Desktop Application Integration & Autostart Management**:
  - Full desktop menu integration: `setup.sh` generates and installs `dynamic-notch.desktop` into `${XDG_DATA_HOME:-~/.local/share}/applications/` with `update-desktop-database` trigger for instant GNOME App Grid and desktop menu indexing.
  - Command-line flags for autostart lifecycle: `./setup.sh --enable-autostart`, `./setup.sh --disable-autostart`, and `./setup.sh --status`.
  - Default autostart disabled: Autostart remains disabled by default until explicitly enabled by the user.
  - Dedicated uninstaller script (`uninstall.sh`) providing clean removal of the desktop application launcher and autostart configuration while preserving source code, system packages, and user data.
  - Single-instance locking via kernel advisory file locking (`fcntl.flock`) and process table scanning, preventing accidental duplicate instances when clicking the application menu launcher while Dynamic Notch is already running.
  - Automated installer test suite (`tests/test_installer.py`) with 8 tests validating launcher generation, autostart lifecycle, repeated operation idempotence, unrelated file protection, status reporting, uninstaller safety, and single-instance locking.
- **Audio Visualizer Signal Accuracy & Synchronization Test Suite**:
  - Added 10 deterministic synthetic audio validation tests in `TestAudioVisualizerSignalAccuracy` within `tests/test_reliability.py` verifying resting silence decay, discrete tone discrimination (160 Hz bass, 800 Hz mid, 2400 Hz treble), composite harmonic chords, low/high frequency sweeps, ambient noise rejection, full-scale signal clipping stability, and sample boundary buffer continuity.
- **Persistent Bluetooth Headset & TWS UI**:
  - Persistent headset status in the expanded player header displaying full device name (`🎧 {Name}`) and battery status (`Battery {percent}%`, multi-component breakdown, or `Battery unavailable`) without crowding or resizing the window.
  - Preserved original 280x44 compact layout without consuming horizontal pill space or distorting music metadata and equalizer balance.
  - Persistent status indicator in the empty-expanded view (`_empty_box`) for continuous visibility when media playback is stopped.
  - Independent application-level state tracking (`_persistent_bt_device`) that persists across state transitions and survives transient notification dismissal.
  - Immediate UI label and canvas updates on battery percentage change events without modal interruptions.
  - Deterministic primary headset latching across polling cycles and D-Bus events when multiple audio devices are connected.
  - 14 automated unit tests in `TestPersistentBluetoothUI` covering compact space preservation, expanded presentation, notification survival, multi-component formatting, and BlueZ lifecycle.
- **Real-Time Bluetooth & BlueZ D-Bus Core Integration**:
  - System BlueZ D-Bus (`org.bluez`) integration for automatic audio headset and TWS detection.
  - Preferred display name resolution prioritizing `org.bluez.Device1.Alias` before falling back to `Name`, suppressing raw MAC addresses and eliminating artificial string truncation.
  - Audio device classification checking Bluetooth Class of Device (Audio/Video service and major device classes) and standard Bluetooth audio UUIDs (A2DP, HFP, HSP).
  - Headset battery level extraction via `org.bluez.Battery1`, supporting aggregate percentages and multi-component TWS battery identifiers (`left`, `right`, `case`) when exposed by BlueZ.
  - Event-driven D-Bus signal listeners (`PropertiesChanged`, `InterfacesAdded`, `InterfacesRemoved`, `NameOwnerChanged`) for immediate connect, disconnect, and low-battery (<= 20%) alerts without aggressive polling.
  - Startup detection for audio headsets connected prior to launching Dynamic Notch.
  - Decoupled laptop battery monitoring from Bluetooth queries so laptop charger plug/unplug events function while wearing headphones.
- **Organic Fluid Animation Engine**:
  - Display frame-clock synchronization via GTK's `add_tick_callback()`, eliminating timer jitter and frame drops.
  - Monotonic and frame-clock timestamp calculations ensuring exact elapsed time tracking.
  - Organic critically damped spring curve (`_anim_curve`) with smooth takeoff, zero overshoot, and distinct easing profiles for expansion (~300ms) and collapse (~250ms).
  - Synchronized opacity transitions for incoming and outgoing views aligned with geometry expansion and contraction.
- **Lyric Presentation & Typography**:
  - Two-line synchronized lyric wrapping with word-char wrap mode (`Pango.WrapMode.WORD_CHAR`) and 36px reserved height row (`EXPANDED_H = 178`), eliminating single-line ellipsis truncation.
- **Installer Safety & Distribution Portability**:
  - Conservative dependency detection in `setup.sh` that checks for missing packages without performing invasive system upgrades or updating package lists without consent.
  - Explicit user confirmation prompt before invoking `sudo` or modifying system packages.
  - Distro-aware messaging providing package names and manual instructions for Fedora, Arch, and non-Debian distributions.
  - Portable desktop entry template (`dynamic-notch.desktop.in`) dynamically expanded by `setup.sh` to use the user's actual project directory.
- **Project Documentation & Licensing**:
  - Standard root-level MIT License attributed to Shiroge (Leon).
  - Comprehensive `README.md` with feature guides, installation steps, screenshots, and architecture details.

### Changed
- **Audio Visualizer Frequency Analysis & Dynamic Response**:
  - Upgraded 3-band spectral analysis from narrow single-bin Goertzel point-meters to a 2nd-order IIR Biquad Bandpass filter bank ($Q=1.2$, $f_s=8000\text{ Hz}$) centered at 160 Hz (Bass), 800 Hz (Mid), and 2400 Hz (Treble).
  - Expanded bass capture bandwidth to seamlessly track kick drums and 808 basslines across 60–250 Hz, and treble bandwidth across 1800–3400 Hz for hi-hats and cymbals.
  - Implemented shared peak-envelope follower with slow logarithmic decay ($0.993$) to maintain inter-band relative dynamics and prevent quiet bleed frequencies from over-inflating visualizer bars.
  - Added perceptual loudness curve ($ratio^{0.65}$) with noise floor gate ($20.0$), ensuring silence/ambient noise decays to resting height ($0.25$) while transient musical beats reach full scale ($0.95$).
  - Refined asymmetric attack and release temporal smoothing (attack coefficient $0.65$, release coefficient $0.18$) for punchy beat synchronization and organic decay.
- **Compact Player Long Song Title & Artist Layout**:
  - Constrained `compact_title` and `compact_artist` GTK labels in the compact pill (`STATE_COMPACT`, 280×44) with single-line enforcement (`single_line_mode=True`, `line_wrap=False`) and end-ellipsization (`Pango.EllipsizeMode.END`).
  - Enabled dynamic horizontal allocation via `set_hexpand(True)`, `set_halign(Gtk.Align.FILL)`, and `set_xalign(0.0)`, allowing song titles and artists to utilize the full 196px available in `compact_info_col` without artificial premature clipping.
  - Capped preferred natural width request via `set_max_width_chars()` to prevent lengthy song titles from forcing container geometry expansion beyond the 280px pill boundary.
  - Refined `.compact-box` CSS padding (`padding: 4px 14px 4px 12px;`) ensuring tall Unicode/CJK and emoji glyphs maintain exact 44px container height without vertical stretching.
  - Sanitized newline and carriage-return characters from media metadata in `_update_compact_ui()`, preserving vertical height constraints.
  - Retained independent unconstrained title presentation in expanded mode (`STATE_FULL`, 400×178).

### Fixed
- Fixed expanded synchronized lyrics horizontal overflow and clipping in `_full_lyric_label` by configuring bounded natural width request (`set_max_width_chars(42)`), full row allocation fill (`set_halign(Gtk.Align.FILL)`, `set_hexpand(True)`), left alignment (`set_xalign(0.0)`), 2-line word wrapping with character fallback (`Pango.WrapMode.WORD_CHAR`, `set_lines(2)`), and end-ellipsization (`Pango.EllipsizeMode.END`), preventing long lyrics from forcing `_full_box` natural width past `EXPANDED_W = 400` onto the transparent canvas.
- Fixed expanded player header metadata and lyric row height stability by adjusting `.lyric-row` padding (`padding: 0;`) so 2-line CJK and Latin lyrics strictly fit within the reserved 36px lyric row, adding single-line constraints and end-ellipsization to `full_title` and `full_artist`, and adding dynamic natural width bounding when persistent Bluetooth headset header is active, ensuring `_full_box` never expands past 400×178 with lyrics or 400×146 without lyrics.
- Fixed audio buffer boundary fragmentation in `AudioLevelMonitor._worker()` by implementing an exact 512-byte chunk accumulator, eliminating discarded partial reads and preserving 16-bit little-endian PCM sample alignment across PipeWire read cycles.
- Fixed filter memory initialization in `AudioLevelMonitor.reset_filters()` to safely handle partially initialized test mocks without attribute errors.
- Fixed PipeWire equalizer visualizer audio capture on Bluetooth output devices by specifying `-P '{ stream.capture.sink: true }'` and `--media-category=Monitor` in `pw-record`, preventing PipeWire from mistakenly capturing the TWS microphone node.
- Added dynamic default output sink tracking in `AudioLevelMonitor` to follow audio device switches between laptop speakers and Bluetooth A2DP headphones without activating HFP/Hands-Free profiles or degrading audio quality.
- Fixed `AudioLevelMonitor` process lifecycle to cleanly restart the recorder upon sink detachment or device disconnection instead of permanently stalling in fallback mode.
- Fixed a `TypeError` parameter-name collision (`got multiple values for argument 'path'`) in `BluetoothBattery._on_interfaces_added()` and `_on_interfaces_removed()` by using unambiguous positional `object_path` for signal payloads and keyword `signal_path` for D-Bus sender path injection.
- Fixed Bluetooth headset detection where connected headsets were ignored and never shown in the UI due to laptop battery check filtering.
- Fixed battery reporting to display "Battery unavailable" with `None` instead of assuming or displaying `0%` when battery interfaces are missing or unsupported by hardware.
- Fixed resource management to cleanly unsubscribe and release all D-Bus signal receivers upon application exit.
- Fixed `_on_delete()` shutdown to safely guard `Gtk.main_quit()` with `Gtk.main_level() > 0`, avoiding GTK critical assertions during headless test execution.

---

## Animation and Reliability — 2026-10-29

### Added
- Automated unit test suite (`tests/test_reliability.py`) verifying GLib timer lifecycle, cubic ease-out curves, frequency discrimination, and media controller state.

### Fixed
- Restored visible expand and collapse transitions following reliability refactoring regressions.
- Fixed mid-flight animation reversal so changing hover state mid-transition smoothly reverses from current in-flight width and height.
- Hardened GLib timer cancellation (`_cancel_timer()`), preventing dangling callbacks, timer leaks, and animation state race conditions.

---

## Water Reminder Configuration — 2026-10-29

### Changed
- Configured the background desktop hydration reminder interval to 5 minutes (`WATER_REMINDER_INTERVAL_MIN = 5`), delivered via desktop notification (`notify-send`).

---

## Cinema Mode Fullscreen Suppression — 2026-10-29

### Added
- `CinemaModeController` providing dual fullscreen detection: low-latency XWayland active window property checks (`_NET_ACTIVE_WINDOW`, `_NET_CLIENT_LIST`) and GNOME Shell D-Bus companion bridge (`gnome-extension/`).
- `STATE_CINEMA_SUPPRESSED` state: completely hides the GTK window, clears input shape pass-through, pauses the visualizer draw queue, and suppresses in-island notifications during fullscreen video or presentation playback.
- Debounced hysteresis restoration (requiring 3 consecutive non-fullscreen ticks) before restoring compact state with refreshed track metadata and lyrics.
- Manual `--cinema-toggle` CLI flag and temporary override toggle support.
- Minimal GNOME Shell companion extension in `gnome-extension/` for native Wayland window state detection.

### Changed
- Fine-tuned Dynamic Island design tokens: primary text `#F5F5F7`, progress track `#343438`, slider fill `#D8D8DC`, disabled text `#5B5B61`.
- Reduced `pw-record` audio capture buffer latency to 32ms and smoothed equalizer bar rendering interpolation.

---

## MacBook Pro Dynamic Island Experience — 2026-10-29

### Added
- Real audio-reactive 3-band equalizer driven by PipeWire monitor streams (`pw-record`) and Goertzel discrete Fourier transform frequency discrimination.
- 100% opaque `#050506` squircle Cairo fill with sub-pixel anti-aliasing and true transparent canvas root, eliminating background desktop bleed-through.

### Changed
- Replaced bulky circular button discs with minimal `#EEEEF0` button glyphs and subtle hover highlights.
- Refined geometry tokens matching MacBook Pro Dynamic Island proportions: Compact state 280x44, Expanded state 400x168 (with lyrics) / 400x146 (without lyrics), 28px album art.

---

## Apple Music Dynamic Island Design & Interaction — 2026-10-29

### Added
- Apple Music Dynamic Island design and interaction model for Linux.
- Hover-triggered expansion with configurable grace period (`COLLAPSE_DELAY_MS = 500`) preventing accidental collapse during mouse transit.
- Dynamic input shape pass-through via `input_shape_combine_region`, allowing transparent canvas areas to pass mouse clicks directly to underlying desktop applications.

### Changed
- Restructured layout hierarchy into dedicated view containers: Idle, Compact, Expanded, and Notification overlays.

---

## Synchronized Lyrics Matching & Placement — 2026-10-28

### Added
- Multi-stage LRCLIB synchronized lyric lookup heuristics: exact match, title cleaning (stripping feat., parentheticals, and remasters), and candidate scoring with duration tolerance.
- Thread token lifecycle to eliminate stale lyric rendering during rapid track skipping.

### Fixed
- Fixed window positioning and monitor workarea alignment after window mapping on XWayland.
- Prevented stale lyric text caching across track transitions.

---

## Initial Implementation — 2026-10-28

### Added
- Initial Dynamic Notch implementation created by Shiroge (Leon), inspired by Nusa and Apple's Dynamic Island for Linux laptops.
- GTK 3 (PyGObject) and Cairo floating dock architecture running under XWayland on Wayland desktops.
- Fixed-canvas transparent architecture (440x250) preventing window-resize stutter and flickering.
- Spotify and MPRIS media player integration: playback controls (Previous, Play/Pause, Next), album artwork extraction, track metadata, and seekbar with interactive scrubbing.
- Synchronized lyric parser (`.lrc` format) powered by LRCLIB API.
- Laptop battery and initial Bluetooth pill notification display.
- Background hydration reminders via system notifications.
- Helper scripts: `run.sh` launcher, `setup.sh` installer, and `toggle-bar.sh` GNOME top bar toggle.
