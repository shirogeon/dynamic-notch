# Dynamic Notch Cinema Bridge (GNOME Shell Companion Extension)

This minimal GNOME Shell companion extension provides session D-Bus notifications when another window on the active workspace enters or leaves fullscreen.

## Purpose
Wayland protocol isolation prevents standard client applications from enumerating arbitrary native Wayland windows or monitoring global window state. This companion bridge observes the `Meta.Display` fullscreen events within GNOME Shell and publishes a boolean signal (`FullscreenChanged(b)`) on session D-Bus (`org.dynamicnotch.CinemaBridge`).

Dynamic Notch consumes this signal (in addition to its built-in XWayland fullscreen detector) to immediately enter the `CINEMA_SUPPRESSED` state, completely hiding the island and pausing visual rendering while you watch movies or videos.

## Installation (Optional for Native Wayland Fullscreen Detection)

> Note: Dynamic Notch includes an automatic built-in XWayland fullscreen detector that automatically suppresses the notch for all XWayland fullscreen players (such as VLC, Chrome/Electron on XWayland, MPV, etc.) without needing this extension. Installing this extension enables detection for native Wayland windows as well.

To install:
```bash
mkdir -p ~/.local/share/gnome-shell/extensions/cinema-bridge@dynamic-notch
cp -r gnome-extension/* ~/.local/share/gnome-shell/extensions/cinema-bridge@dynamic-notch/
gnome-extensions enable cinema-bridge@dynamic-notch
```

## D-Bus Interface

- **Bus**: Session Bus
- **Service**: `org.dynamicnotch.CinemaBridge`
- **Object Path**: `/org/dynamicnotch/CinemaBridge`
- **Interface**: `org.dynamicnotch.CinemaBridge`
  - Method: `GetFullscreen() -> (b is_fullscreen)`
  - Signal: `FullscreenChanged(b is_fullscreen)`
