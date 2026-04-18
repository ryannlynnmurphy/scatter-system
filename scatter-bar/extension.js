// Scatter Bar — top-bar input that talks to the local Scatter router.
//
// Click the panel button to open. Type a message. Enter to send. Response
// appears inline with the route badge (cloud:sonnet, local:qwen, local:shell).
//
// Talks to http://127.0.0.1:8787/chat via Soup 3.

import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const ROUTER_URL = 'http://127.0.0.1:8787/chat';

export default class ScatterBarExtension extends Extension {
    enable() {
        this._session = new Soup.Session();
        this._indicator = new PanelMenu.Button(0.0, 'scatter-bar', false);

        this._triggerLabel = new St.Label({
            text: 'scatter',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'scatter-bar-trigger',
        });
        this._indicator.add_child(this._triggerLabel);

        // Build popup content.
        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
            style_class: 'scatter-bar-item',
        });

        const container = new St.BoxLayout({
            vertical: true,
            style_class: 'scatter-bar-container',
            x_expand: true,
        });

        this._entry = new St.Entry({
            hint_text: 'talk to scatter — launch, edit, ask, teach',
            can_focus: true,
            track_hover: true,
            style_class: 'scatter-bar-entry',
            x_expand: true,
        });
        this._entry.clutter_text.connect('activate', () => this._send());

        this._routeLabel = new St.Label({
            text: '',
            style_class: 'scatter-bar-route',
        });

        this._response = new St.Label({
            text: '',
            style_class: 'scatter-bar-response',
            x_expand: true,
        });
        this._response.clutter_text.line_wrap = true;
        this._response.clutter_text.line_wrap_mode = 2; // WORD_CHAR

        container.add_child(this._entry);
        container.add_child(this._routeLabel);
        container.add_child(this._response);
        item.add_child(container);

        this._indicator.menu.addMenuItem(item);

        // Focus the input when the menu opens.
        this._indicator.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                global.stage.set_key_focus(this._entry.clutter_text);
            }
        });

        Main.panel.addToStatusArea(this.uuid, this._indicator, 1, 'right');
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        this._session = null;
        this._entry = null;
        this._routeLabel = null;
        this._response = null;
    }

    _send() {
        const message = this._entry.get_text().trim();
        if (!message) return;

        this._routeLabel.set_text('routing…');
        this._response.set_text('');
        this._entry.set_text('');

        const body = JSON.stringify({ message, prefer_local: false });
        const msg = Soup.Message.new('POST', ROUTER_URL);
        msg.request_headers.append('Content-Type', 'application/json');
        msg.set_request_body_from_bytes(
            'application/json',
            new GLib.Bytes(new TextEncoder().encode(body))
        );

        this._session.send_and_read_async(
            msg,
            GLib.PRIORITY_DEFAULT,
            null,
            (session, result) => {
                try {
                    const bytes = session.send_and_read_finish(result);
                    if (!bytes) {
                        this._routeLabel.set_text('error');
                        this._response.set_text('no response from router');
                        return;
                    }
                    const text = new TextDecoder().decode(bytes.get_data());
                    const data = JSON.parse(text);
                    const route = data.route || 'unknown';
                    const tokens = data.tokens ?? 0;
                    const ms = data.ms ?? 0;
                    this._routeLabel.set_text(`${route} · ${tokens} tokens · ${ms}ms`);
                    this._response.set_text(data.response || '(no response)');
                } catch (e) {
                    this._routeLabel.set_text('error');
                    this._response.set_text(`${e.message || e}`);
                }
            }
        );
    }
}
