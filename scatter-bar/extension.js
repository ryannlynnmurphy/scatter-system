// Scatter Bar — the iconic bottom bar of Scatter OS.
//
// Always-visible input ("talk to scatter…") on the left, peek-reveal apps
// on hover, pinned app in the corner, Apps button as explicit fallback.
//
// Responses dispatch to four modalities (only Action is fully wired here;
// Voice / Artifact / Desktop are staged for future slices):
//   1. Action  — imperative commands ("open firefox") execute silently
//   2. Voice   — router reply spoken via TTS (stub)
//   3. Artifact— durable outputs land in gallery (stub)
//   4. Desktop — conversational replies render on desktop surface (stub)
//
// Talks to the local Scatter router at http://127.0.0.1:8787/chat.

import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup';
import Gio from 'gi://Gio';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const ROUTER_URL = 'http://127.0.0.1:8787/chat';
const BAR_HEIGHT = 96;

// Apps list — peek-reveal. Keep the set tight; the primary verb is the prompt.
const APPS = [
    { label: 'Scatter',      exec: 'xdg-open http://127.0.0.1:8787',               glyph: '>-<' },
    { label: 'Scatter Code', exec: 'gnome-terminal -- bash -lc "cd ~/scatter-system && exec bash"', glyph: '</>' },
    { label: 'Claude Code',  exec: 'gnome-terminal -- bash -lc "claude || bash"',  glyph: '[c]' },
    { label: 'Files',        exec: 'nautilus',                                      glyph: '[ ]' },
    { label: 'Firefox',      exec: 'firefox',                                       glyph: ' @ ' },
    { label: 'Terminal',     exec: 'gnome-terminal',                                glyph: ' _ ' },
];

// Action-modality rules. Client-side first pass — zero-latency and doesn't
// need the router for the common cases. Router handles everything else.
//
// Matcher is intentionally forgiving: natural phrasings like "please open
// firefox", "can you open the browser for me", "open up firefox" should all
// resolve. We scan for any launch verb in the message, then look for any
// known target keyword anywhere after it.
const ACTION_VERBS = /\b(open|launch|start|run|show|fire up|pull up|bring up)\b/i;
const ACTION_MAP = {
    'firefox':      'firefox',
    'browser':      'firefox',
    'web':          'firefox',
    'files':        'nautilus',
    'file manager': 'nautilus',
    'finder':       'nautilus',
    'terminal':     'gnome-terminal',
    'shell':        'gnome-terminal',
    'console':      'gnome-terminal',
    'scatter':      'xdg-open http://127.0.0.1:8787',
    'scatter code': 'gnome-terminal -- bash -lc "cd ~/scatter-system && exec bash"',
    'claude':       'gnome-terminal -- bash -lc "claude || bash"',
    'claude code':  'gnome-terminal -- bash -lc "claude || bash"',
    'code':         'gnome-terminal -- bash -lc "claude || bash"',
};

export default class ScatterBarExtension extends Extension {
    enable() {
        this._session = new Soup.Session();
        this._revealShown = false;

        this._buildBar();
        this._buildRevealLayer();
        this._buildResponseOverlay();
        this._wireHoverReveal();
        this._place();

        this._monitorsChangedId = Main.layoutManager.connect(
            'monitors-changed', () => this._place());
    }

    disable() {
        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = 0;
        }
        if (this._hideRevealTimeout) {
            GLib.source_remove(this._hideRevealTimeout);
            this._hideRevealTimeout = 0;
        }
        if (this._bar) { Main.layoutManager.removeChrome(this._bar); this._bar.destroy(); this._bar = null; }
        if (this._reveal) { Main.layoutManager.removeChrome(this._reveal); this._reveal.destroy(); this._reveal = null; }
        if (this._overlay) { Main.layoutManager.removeChrome(this._overlay); this._overlay.destroy(); this._overlay = null; }
        this._entry = null;
        this._session = null;
    }

    // ── Bar: the literal bottom panel ────────────────────────────────────

    _buildBar() {
        this._bar = new St.BoxLayout({
            name: 'scatterBar',
            style_class: 'scatter-bar',
            vertical: false,
            reactive: true,
            track_hover: true,
        });

        // Left: the iconic glyph
        this._glyph = new St.Label({
            text: '>-<',
            style_class: 'scatter-bar-glyph',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._bar.add_child(this._glyph);

        // Center: the prompt input — the primary verb of the OS
        this._entry = new St.Entry({
            hint_text: 'talk to scatter…',
            can_focus: true,
            track_hover: true,
            style_class: 'scatter-bar-entry',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._entry.clutter_text.connect('activate', () => this._submit());
        this._bar.add_child(this._entry);

        // Right: Apps — the only thing on the right. Spec is two anchors,
        // glyph+input on the left, Apps on the right. Nothing else.
        this._appsBtn = new St.Button({
            label: 'APPS',
            style_class: 'scatter-bar-apps',
            can_focus: true,
        });
        this._appsBtn.connect('clicked', () => this._toggleReveal());
        this._bar.add_child(this._appsBtn);

        Main.layoutManager.addChrome(this._bar, {
            affectsStruts: true,
            trackFullscreen: true,
            affectsInputRegion: true,
        });
    }

    // ── Reveal layer: apps slide up above the bar, one by one ──────────

    _buildRevealLayer() {
        this._reveal = new St.BoxLayout({
            name: 'scatterReveal',
            style_class: 'scatter-reveal',
            vertical: false,
            reactive: true,
            track_hover: true,
        });
        this._reveal.opacity = 0;
        this._reveal.visible = false;

        this._revealItems = [];
        APPS.forEach((app, i) => {
            const item = new St.Button({
                style_class: 'scatter-reveal-item',
                can_focus: true,
            });
            const inner = new St.BoxLayout({ vertical: true });
            const glyph = new St.Label({ text: app.glyph, style_class: 'scatter-reveal-glyph' });
            const label = new St.Label({ text: app.label, style_class: 'scatter-reveal-label' });
            inner.add_child(glyph);
            inner.add_child(label);
            item.set_child(inner);
            item.connect('clicked', () => {
                this._launch(app.exec);
                this._hideReveal();
            });
            item.opacity = 0;
            this._reveal.add_child(item);
            this._revealItems.push(item);
        });

        Main.layoutManager.addChrome(this._reveal, {
            affectsInputRegion: true,
        });
    }

    _wireHoverReveal() {
        // Hovering the Apps button (or the reveal itself) shows the cascade.
        // Leaving both hides it after a short grace period.
        this._appsBtn.connect('enter-event', () => this._showReveal());
        this._reveal.connect('enter-event', () => this._cancelHideTimer());
        this._reveal.connect('leave-event', () => this._scheduleHide());
        this._appsBtn.connect('leave-event', () => this._scheduleHide());
    }

    _toggleReveal() {
        if (this._revealShown) this._hideReveal();
        else this._showReveal();
    }

    _showReveal() {
        this._cancelHideTimer();
        if (this._revealShown) return;
        this._revealShown = true;
        this._reveal.visible = true;
        this._reveal.ease({
            opacity: 255,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        // Stagger item fade-in: one by one, left to right.
        this._revealItems.forEach((item, i) => {
            item.opacity = 0;
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 40 + i * 60, () => {
                if (!this._revealShown) return GLib.SOURCE_REMOVE;
                item.ease({
                    opacity: 255,
                    duration: 220,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                });
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _scheduleHide() {
        this._cancelHideTimer();
        this._hideRevealTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            this._hideRevealTimeout = 0;
            this._hideReveal();
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelHideTimer() {
        if (this._hideRevealTimeout) {
            GLib.source_remove(this._hideRevealTimeout);
            this._hideRevealTimeout = 0;
        }
    }

    _hideReveal() {
        if (!this._revealShown) return;
        this._revealShown = false;
        this._reveal.ease({
            opacity: 0,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._reveal) this._reveal.visible = false; },
        });
    }

    // ── Response overlay: brief text response above the bar ────────────

    _buildResponseOverlay() {
        this._overlay = new St.BoxLayout({
            name: 'scatterResponse',
            style_class: 'scatter-response',
            vertical: true,
        });
        this._overlay.opacity = 0;
        this._overlay.visible = false;

        this._overlayRoute = new St.Label({
            text: '',
            style_class: 'scatter-response-route',
        });
        this._overlayText = new St.Label({
            text: '',
            style_class: 'scatter-response-text',
        });
        this._overlayText.clutter_text.line_wrap = true;
        this._overlayText.clutter_text.line_wrap_mode = 2;

        this._overlay.add_child(this._overlayRoute);
        this._overlay.add_child(this._overlayText);

        Main.layoutManager.addChrome(this._overlay, {
            affectsInputRegion: false,
        });
    }

    _showResponse(route, text, holdMs = 6000) {
        this._overlayRoute.set_text(route.toUpperCase());
        this._overlayText.set_text(text);
        this._overlay.visible = true;
        this._place();
        this._overlay.ease({
            opacity: 255,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, holdMs, () => {
            if (this._overlay) {
                this._overlay.ease({
                    opacity: 0,
                    duration: 420,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    onComplete: () => { if (this._overlay) this._overlay.visible = false; },
                });
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Placement ─────────────────────────────────────────────────────────

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor) return;

        if (this._bar) {
            this._bar.set_position(monitor.x, monitor.y + monitor.height - BAR_HEIGHT);
            this._bar.set_size(monitor.width, BAR_HEIGHT);
        }
        if (this._reveal) {
            // Reveal sits directly above the bar, flush to the right (where
            // Apps lives).
            const revealHeight = 88;
            const revealWidth = Math.min(monitor.width, APPS.length * 120 + 24);
            this._reveal.set_size(revealWidth, revealHeight);
            this._reveal.set_position(
                monitor.x + monitor.width - revealWidth - 12,
                monitor.y + monitor.height - BAR_HEIGHT - revealHeight - 8,
            );
        }
        if (this._overlay) {
            const overlayWidth = Math.min(720, monitor.width - 96);
            this._overlay.set_size(overlayWidth, -1);
            this._overlay.set_position(
                monitor.x + (monitor.width - overlayWidth) / 2,
                monitor.y + monitor.height - BAR_HEIGHT - 120,
            );
        }
    }

    // ── Submit: classify → dispatch ──────────────────────────────────────

    _submit() {
        const text = this._entry.get_text().trim();
        if (!text) return;
        this._entry.set_text('');

        // Modality 1: Action — try client-side rules first.
        if (this._tryAction(text)) return;

        // Fallback: send to router. Reply comes back as text overlay for
        // now (Voice / Artifact / Desktop modalities staged for later).
        this._sendToRouter(text);
    }

    _tryAction(text) {
        if (!ACTION_VERBS.test(text)) return false;
        const lower = text.toLowerCase();
        // Prefer longer keys so "scatter code" wins over "scatter".
        const keys = Object.keys(ACTION_MAP).sort((a, b) => b.length - a.length);
        for (const key of keys) {
            const re = new RegExp(`\\b${key.replace(/\s+/g, '\\s+')}\\b`);
            if (re.test(lower)) {
                this._launch(ACTION_MAP[key]);
                this._flashGlyph();
                return true;
            }
        }
        return false;
    }

    _launch(cmd) {
        try {
            GLib.spawn_command_line_async(cmd);
        } catch (e) {
            this._showResponse('error', `could not launch: ${e.message || e}`);
        }
    }

    _flashGlyph() {
        // Brief amber pulse on >-< to confirm an action fired silently.
        const orig = this._glyph.get_style();
        this._glyph.set_style('color: #ffb800;');
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 420, () => {
            if (this._glyph) this._glyph.set_style(orig);
            return GLib.SOURCE_REMOVE;
        });
    }

    _sendToRouter(message) {
        this._showResponse('routing', '…', 60000);  // long hold while awaiting
        const body = JSON.stringify({ message, prefer_local: true });
        const msg = Soup.Message.new('POST', ROUTER_URL);
        msg.request_headers.append('Content-Type', 'application/json');
        msg.set_request_body_from_bytes(
            'application/json',
            new GLib.Bytes(new TextEncoder().encode(body)),
        );
        this._session.send_and_read_async(
            msg, GLib.PRIORITY_DEFAULT, null,
            (session, result) => {
                try {
                    const bytes = session.send_and_read_finish(result);
                    if (!bytes) {
                        this._showResponse('error', 'no response from router', 4000);
                        return;
                    }
                    const text = new TextDecoder().decode(bytes.get_data());
                    const data = JSON.parse(text);
                    const route = data.route || 'unknown';
                    const reply = data.response || '(empty reply)';
                    this._showResponse(route, reply, 8000);
                } catch (e) {
                    this._showResponse('error', `${e.message || e}`, 4000);
                }
            },
        );
    }
}
