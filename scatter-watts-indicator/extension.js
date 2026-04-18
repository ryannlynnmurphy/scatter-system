// Scatter Watts — GNOME Shell extension (shell-version 45+).
//
// Shows the cumulative joules-this-session number from ~/.scatter/watts.jsonl
// in the top bar. Click: opens Scatter so you can see the full audit +
// forget UI. Refreshes every 10 seconds.
//
// ES module format. Import GLib via import { Extension } ... pattern.

import GLib from 'gi://GLib';
import St from 'gi://St';
import Gio from 'gi://Gio';
import Clutter from 'gi://Clutter';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const REFRESH_INTERVAL_SECONDS = 10;

export default class ScatterWattsExtension extends Extension {
    enable() {
        this._indicator = new PanelMenu.Button(0.0, 'scatter-watts', false);

        this._label = new St.Label({
            text: 'scatter · —',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'scatter-watts-label',
        });
        this._indicator.add_child(this._label);

        // Click opens Scatter.
        this._indicator.connect('button-press-event', () => {
            try {
                GLib.spawn_command_line_async('scatter');
            } catch (e) {
                // scatter not in PATH; ignore rather than crash the shell
                log(`[scatter-watts] could not launch scatter: ${e}`);
            }
        });

        Main.panel.addToStatusArea(this.uuid, this._indicator, 1, 'right');

        // First update + periodic refresh.
        this._update();
        this._timeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            REFRESH_INTERVAL_SECONDS,
            () => {
                this._update();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    disable() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = null;
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        this._label = null;
    }

    _update() {
        try {
            const wattsPath = GLib.get_home_dir() + '/.scatter/watts.jsonl';
            const file = Gio.File.new_for_path(wattsPath);
            if (!file.query_exists(null)) {
                this._label.set_text('scatter · 0.0 J');
                return GLib.SOURCE_CONTINUE;
            }
            const [ok, contents] = file.load_contents(null);
            if (!ok) {
                this._label.set_text('scatter · ?');
                return GLib.SOURCE_CONTINUE;
            }
            const text = new TextDecoder('utf-8').decode(contents);
            let total = 0;
            for (const line of text.split('\n')) {
                if (!line.trim()) continue;
                try {
                    const entry = JSON.parse(line);
                    if (typeof entry.joules === 'number') {
                        total += entry.joules;
                    }
                } catch (e) {
                    // skip malformed line
                }
            }
            const shown = total < 1000 ? `${total.toFixed(1)} J`
                                       : `${(total / 1000).toFixed(2)} kJ`;
            this._label.set_text(`scatter · ${shown}`);
        } catch (e) {
            log(`[scatter-watts] update failed: ${e}`);
            this._label.set_text('scatter · ?');
        }
        return GLib.SOURCE_CONTINUE;
    }
}
