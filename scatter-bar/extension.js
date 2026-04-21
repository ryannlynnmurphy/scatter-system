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
const SPEAK_URL = 'http://127.0.0.1:8787/speak';
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
const ACTION_VERBS = /\b(open|launch|start|run|show|fire up|pull up|bring up|go to)\b/i;
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

// Session verbs. Only the reversible ones live in chat — worst case you
// wake the laptop. log out / restart / shutdown wait until there's a
// non-language path (physical button story), per antithesis.
const SESSION_VERBS = /\b(sleep|suspend|go to sleep|nap)\b/i;
const SESSION_CMD = 'systemctl suspend';

export default class ScatterBarExtension extends Extension {
    enable() {
        this._session = new Soup.Session();
        this._revealShown = false;

        this._buildBar();
        this._buildRevealLayer();
        this._buildResponseOverlay();
        this._buildDesktopSurface();
        this._wireHoverReveal();
        this._place();
        this._refreshHistoryHandle();

        this._monitorsChangedId = Main.layoutManager.connect(
            'monitors-changed', () => this._place());

        // Boot greet: once per shell session, Scatter names the state of
        // the machine so sovereignty is legible before the first prompt.
        // Deferred ~1.2s so the shell settles and the bubble doesn't
        // flash during extension re-enable cycles.
        this._greetTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1200, () => {
            this._greetTimeout = 0;
            this._bootGreet();
            return GLib.SOURCE_REMOVE;
        });
    }

    disable() {
        if (this._greetTimeout) {
            GLib.source_remove(this._greetTimeout);
            this._greetTimeout = 0;
        }
        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = 0;
        }
        if (this._statusTimeout) {
            GLib.source_remove(this._statusTimeout);
            this._statusTimeout = 0;
        }
        if (this._hideRevealTimeout) {
            GLib.source_remove(this._hideRevealTimeout);
            this._hideRevealTimeout = 0;
        }
        if (this._bar) { Main.layoutManager.removeChrome(this._bar); this._bar.destroy(); this._bar = null; }
        if (this._reveal) { Main.layoutManager.removeChrome(this._reveal); this._reveal.destroy(); this._reveal = null; }
        if (this._overlay) { Main.layoutManager.removeChrome(this._overlay); this._overlay.destroy(); this._overlay = null; }
        if (this._desktop) { Main.layoutManager.removeChrome(this._desktop); this._desktop.destroy(); this._desktop = null; }
        if (this._desktopHideTimeout) { GLib.source_remove(this._desktopHideTimeout); this._desktopHideTimeout = 0; }
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

        // Far left: the artifacts handle — a small typographic mark that
        // becomes visible only when artifacts exist. Clicking opens the
        // gallery so the forgetful user doesn't have to remember a verb.
        this._historyHandle = new St.Button({
            style_class: 'scatter-bar-history',
            label: '≡',
            can_focus: true,
            track_hover: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._historyHandle.visible = false;
        this._historyHandle.connect('clicked', () => this._openJournal());
        this._bar.add_child(this._historyHandle);

        // Left column — vertical stack: SCATTER wordmark above the
        // prompt input. The face/wordmark is the speaker; the input is
        // what you say back. One voice, two lines of register.
        this._leftColumn = new St.BoxLayout({
            vertical: true,
            style_class: 'scatter-bar-speaker',
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._face = new St.Label({
            text: 'Scatter',
            style_class: 'scatter-bar-wordmark',
        });
        this._leftColumn.add_child(this._face);

        this._entry = new St.Entry({
            hint_text: 'talk to scatter…',
            can_focus: true,
            track_hover: true,
            style_class: 'scatter-bar-entry',
        });
        this._entry.clutter_text.connect('activate', () => this._submit());
        this._entry.clutter_text.connect('key-focus-in', () => {
            this._face.add_style_class_name('listening');
        });
        this._entry.clutter_text.connect('key-focus-out', () => {
            this._face.remove_style_class_name('listening');
        });
        this._leftColumn.add_child(this._entry);

        this._bar.add_child(this._leftColumn);

        // Right side: empty breathing space. Apps reveal as tiles above
        // this region when the mouse drags across it — progressive dock.
        // No status strip (clock/battery/net live in the GNOME top panel).
        this._appsZone = new St.Widget({
            style_class: 'scatter-bar-apps-zone',
            x_expand: true,
            reactive: true,
            track_hover: true,
        });
        this._bar.add_child(this._appsZone);

        Main.layoutManager.addChrome(this._bar, {
            affectsStruts: true,
            trackFullscreen: true,
            affectsInputRegion: true,
        });
    }

    // ── Reveal layer: apps slide up above the bar, one by one ──────────

    _buildRevealLayer() {
        // Progressive dock: tiles live above the bar in the apps zone,
        // hidden below the screen edge at rest. As the cursor drags across
        // the bar from left to right, each tile rises up in turn. Hover
        // magnifies. Click triggers the per-app signature animation.
        this._reveal = new St.BoxLayout({
            name: 'scatterReveal',
            style_class: 'scatter-reveal',
            vertical: false,
            reactive: false,
        });
        this._reveal.visible = true;  // container always present; items animate in
        this._reveal.opacity = 255;

        this._revealItems = [];
        APPS.forEach((app, i) => {
            const item = new St.Button({
                style_class: 'scatter-reveal-item',
                can_focus: true,
                track_hover: true,
                reactive: true,
            });
            const inner = new St.BoxLayout({ vertical: true });
            const glyph = new St.Label({ text: app.glyph, style_class: 'scatter-reveal-glyph' });
            const label = new St.Label({ text: app.label, style_class: 'scatter-reveal-label' });
            inner.add_child(glyph);
            inner.add_child(label);
            item.set_child(inner);

            // Initial state: below its final position, invisible.
            item.set_pivot_point(0.5, 1.0);
            item.translation_y = 120;
            item.opacity = 0;
            item._armed = false;  // has the cursor passed its column yet

            item.connect('clicked', () => {
                this._launchFromTile(item, app);
            });
            item.connect('enter-event', () => this._magnifyTile(item));
            item.connect('leave-event', () => this._settleTile(item));

            this._reveal.add_child(item);
            this._revealItems.push(item);
        });

        Main.layoutManager.addChrome(this._reveal, {
            affectsInputRegion: true,
        });
    }

    _wireHoverReveal() {
        // Mouse at the bottom of the screen = apps pull up, one by one,
        // in the order the cursor crosses their columns. Mac-dock progressive
        // reveal, authored for the Scatter register.
        this._bar.connect('motion-event', (actor, event) => {
            const [x] = event.get_coords();
            this._revealByCursorX(x);
        });
        this._bar.connect('leave-event', () => this._scheduleHide());
        this._reveal.connect('leave-event', () => this._scheduleHide());
        // Per-tile hover handled by enter/leave on the individual tiles.
    }

    _revealByCursorX(cursorX) {
        this._cancelHideTimer();
        this._revealShown = true;
        // For each tile: if the cursor has passed its left edge, arm it
        // (animate into position). Tiles behind the cursor stay up; tiles
        // ahead of the cursor stay down.
        this._revealItems.forEach((item, i) => {
            const [tx] = item.get_transformed_position();
            const leftEdge = tx;
            if (cursorX >= leftEdge - 8 && !item._armed) {
                item._armed = true;
                // Tiny stagger so even a fast drag feels like a cascade.
                const delay = i * 18;
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
                    if (!item._armed) return GLib.SOURCE_REMOVE;
                    item.ease({
                        opacity: 255,
                        translation_y: 0,
                        duration: 360,
                        mode: Clutter.AnimationMode.EASE_OUT_BACK,
                    });
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
    }

    _magnifyTile(item) {
        // Mac-dock magnify — the tile the cursor is over grows and lifts.
        item.ease({
            scale_x: 1.18,
            scale_y: 1.18,
            translation_y: -10,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _settleTile(item) {
        // Return to armed-but-unhovered state. Keep translation_y at 0
        // (still raised to its dock position, just no extra lift).
        if (!item._armed) return;
        item.ease({
            scale_x: 1.0,
            scale_y: 1.0,
            translation_y: 0,
            duration: 160,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _showReveal() {
        // Retained for back-compat (toggle path). Arms all tiles at once.
        this._cancelHideTimer();
        this._revealShown = true;
        this._revealItems.forEach((item, i) => {
            if (item._armed) return;
            item._armed = true;
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, i * 28, () => {
                item.ease({
                    opacity: 255,
                    translation_y: 0,
                    duration: 360,
                    mode: Clutter.AnimationMode.EASE_OUT_BACK,
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
        // Drop each tile back below the bar in reverse order — the last
        // tile leaves first so the retreat reads as deliberate, not a
        // collapse.
        const items = [...this._revealItems].reverse();
        items.forEach((item, i) => {
            item._armed = false;
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, i * 14, () => {
                item.ease({
                    opacity: 0,
                    translation_y: 120,
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: 260,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                });
                return GLib.SOURCE_REMOVE;
            });
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

    // ── Desktop modality: prose replies render as a durable chat bubble
    // on the wallpaper. Dismissed by × or by the next reply — never by a
    // timer. The machine does not decide when her thought disappears.

    _buildDesktopSurface() {
        this._desktop = new St.BoxLayout({
            name: 'scatterDesktop',
            style_class: 'scatter-desktop-bubble',
            vertical: true,
            reactive: true,
        });

        // Top row: text (flex) + close glyph.
        const topRow = new St.BoxLayout({
            style_class: 'scatter-desktop-row',
            vertical: false,
        });
        this._desktopText = new St.Label({
            style_class: 'scatter-desktop-text',
            text: '',
            x_expand: true,
            y_align: Clutter.ActorAlign.START,
        });
        this._desktopText.clutter_text.line_wrap = true;
        this._desktopText.clutter_text.line_wrap_mode = 2;

        this._desktopClose = new St.Button({
            style_class: 'scatter-desktop-close',
            label: '×',
            can_focus: true,
            track_hover: true,
            reactive: true,
        });
        this._desktopClose.connect('clicked', () => this._hideDesktop());

        topRow.add_child(this._desktopText);
        topRow.add_child(this._desktopClose);
        this._desktop.add_child(topRow);

        // Teach-trail footer: provenance of the reply. Dim, editorial.
        this._desktopTrail = new St.Label({
            style_class: 'scatter-desktop-trail',
            text: '',
        });
        this._desktop.add_child(this._desktopTrail);

        this._desktop.opacity = 0;
        this._desktop.visible = false;
        Main.layoutManager.addChrome(this._desktop, {
            affectsInputRegion: true,
        });
    }

    _showDesktop(text, meta) {
        if (this._desktopHideTimeout) {
            GLib.source_remove(this._desktopHideTimeout);
            this._desktopHideTimeout = 0;
        }
        this._desktopText.set_text(text);
        this._desktopTrail.set_text(this._formatTrail(meta || {}));
        this._desktop.visible = true;
        this._place();
        this._desktop.ease({
            opacity: 255,
            duration: 320,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        // No auto-fade. The bubble stays until × is clicked or the next
        // reply replaces it. Sovereignty over your own thoughts includes
        // sovereignty over when they disappear.
    }

    // Boot greet — named state of the machine at first paint. Runs once
    // per shell session via the timeout scheduled in enable().
    _bootGreet() {
        const parts = [
            "I'm awake.",
            "Cloud is off.",
            "Voice is off.",
            "Running locally.",
        ];
        this._showDesktop(parts.join(' '), {
            route: 'local:greet',
            model: 'scatter',
        });
    }

    _openJournal() {
        // Spawns the webkit Journal inspector. It's a stepping-stone until
        // history lands natively on the canvas — the handle lets users
        // reach their chats without remembering the recall verb.
        try {
            GLib.spawn_command_line_async(
                'python3 /home/ryannlynnmurphy/scatter-system/scatter/launcher.py',
            );
        } catch (e) {
            this._showResponse('error', `could not open journal: ${e.message || e}`, 4000);
        }
    }

    // Check if a chat log exists on disk; show/hide the history handle
    // accordingly. Called on enable and after each reply.
    _refreshHistoryHandle() {
        if (!this._historyHandle) return;
        try {
            const logFile = Gio.File.new_for_path(
                GLib.get_home_dir() + '/.scatter/chats.jsonl',
            );
            const [exists, size] = (() => {
                try {
                    const info = logFile.query_info('standard::size', 0, null);
                    return [true, info.get_size()];
                } catch (_) {
                    return [false, 0];
                }
            })();
            this._historyHandle.visible = exists && size > 0;
        } catch (_) {
            this._historyHandle.visible = false;
        }
    }

    _hideResponse() {
        if (!this._overlay || !this._overlay.visible) return;
        this._overlay.ease({
            opacity: 0,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._overlay) this._overlay.visible = false; },
        });
    }

    _hideDesktop() {
        if (!this._desktop || !this._desktop.visible) return;
        this._desktop.ease({
            opacity: 0,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._desktop) this._desktop.visible = false; },
        });
    }

    // Teach-trail: 'local · llama · 0.4s' or 'cloud · sonnet · egress on'.
    // Makes provenance visible on every reply — the patent claim, rendered.
    _formatTrail(meta) {
        const parts = [];
        const route = meta.route || '';
        if (route.startsWith('cloud:')) {
            parts.push('cloud');
            const model = route.split(':')[1];
            if (model) parts.push(model);
            parts.push('egress on');
        } else if (route.startsWith('local:')) {
            parts.push('local');
            const m = meta.model || route.split(':')[1];
            if (m) parts.push(String(m).split(':')[0]);
        } else if (route) {
            parts.push(route);
        }
        if (meta.ms !== undefined) {
            const s = Math.max(0, meta.ms / 1000);
            parts.push(s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`);
        }
        return parts.join(' · ');
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

    // ── Status strip: glanceable system state in the bar's right column.
    // Reads /sys for battery, /proc/net/route for network presence, and the
    // shell clock for time. Updated on a 15s tick — rendered as one tight
    // monospace line in Scatter's register. No icons, no tray bloat.

    _startStatusClock() {
        this._refreshStatus();
        this._statusTimeout = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, 15, () => {
                this._refreshStatus();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _refreshStatus() {
        if (!this._status) return;
        const now = GLib.DateTime.new_now_local();
        const time = now.format('%H:%M');
        const battery = this._readBattery();
        const net = this._hasNetwork() ? 'net' : 'offline';
        const parts = [net, battery, time].filter(Boolean);
        this._status.set_text(parts.join('  ·  '));
    }

    _readBattery() {
        try {
            const dir = Gio.File.new_for_path('/sys/class/power_supply');
            const iter = dir.enumerate_children('standard::name',
                Gio.FileQueryInfoFlags.NONE, null);
            let info;
            while ((info = iter.next_file(null)) !== null) {
                const name = info.get_name();
                if (!name.startsWith('BAT')) continue;
                const cap = Gio.File.new_for_path(
                    `/sys/class/power_supply/${name}/capacity`);
                const [ok, bytes] = cap.load_contents(null);
                if (!ok) continue;
                const pct = parseInt(new TextDecoder().decode(bytes).trim(), 10);
                if (!Number.isFinite(pct)) continue;
                return `${pct}%`;
            }
        } catch (_) {}
        return '';
    }

    _hasNetwork() {
        // /proc/net/route has a header line plus one entry per route. More
        // than one line → at least one route exists → online-ish.
        try {
            const file = Gio.File.new_for_path('/proc/net/route');
            const [ok, bytes] = file.load_contents(null);
            if (!ok) return false;
            const lines = new TextDecoder().decode(bytes).split('\n')
                .filter(l => l.trim().length > 0);
            return lines.length > 1;
        } catch (_) {
            return false;
        }
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
            // Reveal sits directly above the bar, spanning the apps zone on
            // the right side. Tiles live here but start 120px below their
            // resting spot — they rise as the cursor crosses their columns.
            const tileWidth = 140;
            const tileGap = 16;
            const revealHeight = 120;
            const revealWidth = APPS.length * tileWidth + (APPS.length - 1) * tileGap + 48;
            // Anchor near the right of the bar, leaving breathing space.
            const rightMargin = 56;
            this._reveal.set_size(revealWidth, revealHeight);
            this._reveal.set_position(
                monitor.x + monitor.width - revealWidth - rightMargin,
                monitor.y + monitor.height - BAR_HEIGHT - revealHeight + 12,
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
        if (this._desktop) {
            // Speech bubble above Scatter's face in the bar's left column.
            // One reply at a time, dismissed by ×. Anchored so it reads as
            // speech from the character, not a broadcast over the desktop.
            const bubbleWidth = Math.min(520, Math.floor(monitor.width * 0.38));
            this._desktop.set_size(bubbleWidth, -1);
            const [, natHeight] = this._desktop.get_preferred_height(bubbleWidth);
            const height = Math.max(64, natHeight);
            const barTop = monitor.y + monitor.height - BAR_HEIGHT;
            // Left-anchored to where the wordmark lives, with a gap above.
            const anchorX = monitor.x + 56;
            this._desktop.set_position(anchorX, barTop - height - 18);
        }
    }

    // ── Submit: classify → dispatch ──────────────────────────────────────

    _submit() {
        const text = this._entry.get_text().trim();
        if (!text) return;
        this._entry.set_text('');

        // Session verbs (sleep) — no launch-verb required since "sleep"
        // is itself the verb.
        if (SESSION_VERBS.test(text)) {
            this._launch(SESSION_CMD);
            this._flashGlyph();
            return;
        }

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

    // Tile scale-up: the animation lives on the tile, not on the window.
    // The tile tells the "app is expanding onto the desktop" story; GNOME's
    // compositor opens the window with its own animation. One animation,
    // no compositor race, no brittle window-created matching.
    _launchFromTile(tile, app) {
        // Dispatch to the app's signature animation. Each app has its own
        // entrance — Firefox leaps, Terminal cuts, etc. The signature is a
        // function that drives the tile (and any satellite actors) with
        // Clutter easing, then resolves when the launch should commit.
        // Back-compat: accept a plain exec string for callers not yet
        // migrated.
        const appSpec = (typeof app === 'object' && app !== null)
            ? app
            : { exec: app, signature: null };
        const signature = this._signatureFor(appSpec);
        const launchFn = () => this._launch(appSpec.exec);

        // Safety net: whatever the signature does, it can't block a launch
        // beyond 1200ms and it can't leave the tile in a broken state.
        let launched = false;
        const launchOnce = () => {
            if (launched) return;
            launched = true;
            launchFn();
        };
        const resetTile = () => {
            tile.set_scale(1.0, 1.0);
            tile.opacity = 255;
            tile.translation_x = 0;
            tile.translation_y = 0;
            tile.rotation_angle_z = 0;
            tile._armed = false;
        };
        const deadline = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1200, () => {
            launchOnce();
            return GLib.SOURCE_REMOVE;
        });

        try {
            signature(tile, launchOnce, () => {
                GLib.source_remove(deadline);
                resetTile();
                this._hideReveal();
            });
        } catch (e) {
            log(`scatter-bar[${appSpec.label || 'app'}]: signature error ${e.message || e}`);
            launchOnce();
            resetTile();
            this._hideReveal();
        }
    }

    // Returns the signature function for a given app. Looks up by label;
    // falls back to the generic scale-up. New apps drop in by adding a
    // method named _signatureFooBar and wiring it here.
    _signatureFor(appSpec) {
        const label = (appSpec.label || '').toLowerCase();
        if (label === 'firefox') return (t, launch, done) => this._signatureFirefox(t, launch, done);
        return (t, launch, done) => this._signatureDefault(t, launch, done);
    }

    // Generic signature — scale-up + fade. Calls launch at 100ms into the
    // arc so the window can open while the tile is still dissolving.
    _signatureDefault(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);
        tile.ease({
            scale_x: 1.6,
            scale_y: 1.6,
            opacity: 0,
            duration: 260,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => done(),
        });
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            launch();
            return GLib.SOURCE_REMOVE;
        });
    }

    // Firefox — The Fox: anticipation crouch → coiled spring → arc leap
    // across the canvas with amber trail → impact ring → dissolve.
    // Pure Clutter — no sprite sheets. Built from transforms, satellite
    // ember actors, and a scaled ring on impact.
    _signatureFirefox(tile, launch, done) {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor) { return this._signatureDefault(tile, launch, done); }

        const [tileX, tileY] = tile.get_transformed_position();
        const [tileW, tileH] = [tile.width, tile.height];
        const targetX = monitor.x + monitor.width / 2 - tileW / 2;
        const targetY = monitor.y + monitor.height / 3 - tileH / 2;
        const dx = targetX - tileX;
        const dy = targetY - tileY;

        tile.set_pivot_point(0.5, 1.0);  // bottom-center pivot for squash

        // Spawn satellite embers — six small amber widgets trailing the arc.
        const embers = [];
        for (let i = 0; i < 6; i++) {
            const e = new St.Widget({
                style_class: 'scatter-ember',
                width: 8,
                height: 8,
                opacity: 0,
                reactive: false,
            });
            e.set_position(
                tileX + tileW / 2 - 4,
                tileY + tileH / 2 - 4,
            );
            Main.layoutManager.addChrome(e, { affectsInputRegion: false });
            embers.push(e);
        }

        // Shockwave ring — spawned on impact, scales up and fades.
        const ring = new St.Widget({
            style_class: 'scatter-shockwave',
            width: 24,
            height: 24,
            opacity: 0,
            reactive: false,
        });
        ring.set_pivot_point(0.5, 0.5);
        ring.set_position(targetX + tileW / 2 - 12, targetY + tileH / 2 - 12);
        Main.layoutManager.addChrome(ring, { affectsInputRegion: false });

        // Beat 1 — ANTICIPATION (0-180ms): squash low, pull slightly back.
        tile.ease({
            scale_x: 1.15, scale_y: 0.72,
            translation_x: -18, translation_y: 8,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — COIL (180-320ms): deeper crouch, hold.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            tile.ease({
                scale_x: 1.2, scale_y: 0.6,
                translation_x: -26,
                duration: 140,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — LEAP (320-720ms): arc across the canvas, stretched mid-flight.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 320, () => {
            tile.ease({
                translation_x: dx,
                translation_y: dy,
                scale_x: 0.9, scale_y: 1.35,
                rotation_angle_z: 12,
                duration: 420,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            // Embers spawn along the arc at staggered delays.
            embers.forEach((e, i) => {
                const t = i / (embers.length - 1);
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.floor(t * 320), () => {
                    const arcX = tileX + tileW / 2 - 4 + dx * t;
                    const arcY = tileY + tileH / 2 - 4 + dy * t - 40 * Math.sin(Math.PI * t);
                    e.set_position(arcX, arcY);
                    e.opacity = 255;
                    e.ease({
                        opacity: 0,
                        translation_y: 24,
                        duration: 520,
                        mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    });
                    return GLib.SOURCE_REMOVE;
                });
            });
            // Fire the actual app launch mid-arc so the window opens
            // as the fox is landing — no dead air.
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 4 — IMPACT (720-900ms): squash on land, shockwave ring.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 720, () => {
            tile.ease({
                scale_x: 1.25, scale_y: 0.78,
                rotation_angle_z: 0,
                duration: 160,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            ring.opacity = 255;
            ring.ease({
                scale_x: 6.0, scale_y: 6.0,
                opacity: 0,
                duration: 620,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            return GLib.SOURCE_REMOVE;
        });

        // Beat 5 — DISSOLVE (900-1100ms): fade the fox, clean up actors.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 900, () => {
            tile.ease({
                opacity: 0,
                duration: 180,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    embers.forEach(e => { try { e.destroy(); } catch (_) {} });
                    try { ring.destroy(); } catch (_) {}
                    done();
                },
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    _flashGlyph() {
        // Brief amber pulse on the wordmark to confirm an action fired.
        if (!this._face) return;
        const orig = this._face.get_style();
        this._face.set_style('color: #ffb800;');
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 420, () => {
            if (this._face) this._face.set_style(orig);
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
                    // Dispatch modality by route:
                    //   launch / system_query → small chrome overlay (confirmation)
                    //   prose replies          → Desktop (wallpaper as stage) + Voice
                    if (route === 'local:launch' || route === 'local:shell') {
                        this._showResponse(route, reply, 8000);
                    } else {
                        // Reply goes to the durable desktop bubble — dismiss
                        // the transient ROUTING overlay first so they don't
                        // both sit on screen.
                        this._hideResponse();
                        this._showDesktop(reply, {
                            route,
                            model: data.model,
                            ms: data.ms,
                        });
                        this._speak(reply);
                        this._refreshHistoryHandle();
                    }
                } catch (e) {
                    this._showResponse('error', `${e.message || e}`, 4000);
                }
            },
        );
    }

    // ── Voice: POST reply to /speak, pipe audio/mpeg to a temp file, play it.
    // Kept simple — file handoff to ffplay avoids pulling Gst into the shell
    // process. Previous playback is killed when a new one starts so replies
    // don't stack.
    _speak(text) {
        const body = JSON.stringify({ text });
        const msg = Soup.Message.new('POST', SPEAK_URL);
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
                    if (!bytes) return;
                    const ctype = msg.response_headers.get_one('Content-Type') || '';
                    if (!ctype.startsWith('audio/')) return;  // error JSON — skip
                    const raw = bytes.get_data();
                    const path = GLib.build_filenamev([
                        GLib.get_tmp_dir(),
                        `scatter-voice-${GLib.get_monotonic_time()}.mp3`,
                    ]);
                    const file = Gio.File.new_for_path(path);
                    const stream = file.replace(null, false,
                        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
                    stream.write_all(raw, null);
                    stream.close(null);
                    this._playAudio(path);
                } catch (e) {
                    // Voice failing must not break the text reply.
                    log(`scatter-bar: speak failed: ${e.message || e}`);
                }
            },
        );
    }

    _playAudio(path) {
        try {
            if (this._audioProc) {
                try { this._audioProc.force_exit(); } catch (_) {}
                this._audioProc = null;
            }
            this._audioProc = Gio.Subprocess.new(
                ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', path],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            );
            this._audioProc.wait_async(null, (proc, res) => {
                try { proc.wait_finish(res); } catch (_) {}
                GLib.unlink(path);
                if (this._audioProc === proc) this._audioProc = null;
            });
        } catch (e) {
            log(`scatter-bar: play failed: ${e.message || e}`);
        }
    }
}
