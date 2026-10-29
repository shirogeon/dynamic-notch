/**
 * Dynamic Notch Cinema Bridge GNOME Shell Extension
 *
 * Emits session D-Bus signals when any window enters or leaves fullscreen
 * on the active workspace/monitor. Dynamic Notch listens to this service to
 * activate CINEMA_SUPPRESSED state and cleanly hide its interface over fullscreen video.
 */

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

const CinemaBridgeIface = `
<node>
  <interface name="org.dynamicnotch.CinemaBridge">
    <method name="GetFullscreen">
      <arg type="b" direction="out" name="is_fullscreen"/>
    </method>
    <signal name="FullscreenChanged">
      <arg type="b" name="is_fullscreen"/>
    </signal>
  </interface>
</node>`;

export default class DynamicNotchCinemaBridge extends Extension {
    enable() {
        this._lastFullscreen = false;
        this._dbusImpl = Gio.DBusExportedObject.wrapJSObject(CinemaBridgeIface, this);
        this._dbusImpl.export(Gio.DBus.session, '/org/dynamicnotch/CinemaBridge');

        this._ownerId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            'org.dynamicnotch.CinemaBridge',
            Gio.BusNameOwnerFlags.NONE,
            null,
            null,
            null
        );

        this._checkFullscreen = () => {
            const workspace = global.workspace_manager ? global.workspace_manager.get_active_workspace() : null;
            if (!workspace) return;
            const windows = workspace.list_windows();
            let isFs = false;
            for (const win of windows) {
                if (win.get_window_type && win.get_window_type() === Meta.WindowType.NORMAL && win.is_fullscreen && win.is_fullscreen()) {
                    isFs = true;
                    break;
                }
            }
            if (this._lastFullscreen !== isFs) {
                this._lastFullscreen = isFs;
                if (this._dbusImpl) {
                    this._dbusImpl.emit_signal('FullscreenChanged', new GLib.Variant('(b)', [isFs]));
                }
            }
        };

        this._signalIds = [];
        if (global.display) {
            this._signalIds.push(global.display.connect('in-fullscreen-changed', this._checkFullscreen));
            this._signalIds.push(global.display.connect('notify::focus-window', this._checkFullscreen));
            this._signalIds.push(global.display.connect('restacked', this._checkFullscreen));
        }
        this._checkFullscreen();
    }

    GetFullscreen() {
        return this._lastFullscreen || false;
    }

    disable() {
        if (global.display && this._signalIds) {
            for (const id of this._signalIds) {
                global.display.disconnect(id);
            }
        }
        this._signalIds = [];
        if (this._ownerId) {
            Gio.bus_unown_name(this._ownerId);
            this._ownerId = null;
        }
        if (this._dbusImpl) {
            this._dbusImpl.unexport();
            this._dbusImpl = null;
        }
    }
}
