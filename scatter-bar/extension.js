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
        this._startStatusClock();

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
        // Focus-brighten: when the prompt takes focus, the glyph brightens.
        // Binary "I hear you" — no pulse, no loop, no AI-listening novelty.
        this._entry.clutter_text.connect('key-focus-in', () => {
            this._glyph.add_style_class_name('listening');
        });
        this._entry.clutter_text.connect('key-focus-out', () => {
            this._glyph.remove_style_class_name('listening');
        });
        this._bar.add_child(this._entry);

        // Right: glanceable status strip. Replaces what used to live in
        // GNOME's top panel — time, battery, network — rendered in Scatter's
        // register so there's exactly one chrome surface, not two.
        this._status = new St.Label({
            text: '',
            style_class: 'scatter-bar-status',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._bar.add_child(this._status);

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
                this._launchFromTile(item, app.exec);
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
        // Synthesis: the bar itself is the reveal trigger. Whole-bar target
        // (96px tall) is Fitts-safe — no edge-strip hunting, no accidental
        // summon from fullscreen video resting the mouse at screen bottom.
        this._bar.connect('enter-event', () => this._showReveal());
        this._bar.connect('leave-event', () => this._scheduleHide());
        this._reveal.connect('enter-event', () => this._cancelHideTimer());
        this._reveal.connect('leave-event', () => this._scheduleHide());
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
        // Rigid plate: whole row appears as one surface. No stagger cascade,
        // no per-item choreography. 120ms linear-ease — System 7, not dock.
        this._revealItems.forEach(item => { item.opacity = 255; });
        this._reveal.ease({
            opacity: 255,
            duration: 120,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
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
            duration: 120,
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
        if (this._desktop) {
            // Bubble: upper-center, max ~56% width so long replies wrap
            // without feeling like a billboard. Height auto.
            const desktopWidth = Math.min(1040, Math.floor(monitor.width * 0.56));
            const verticalInset = Math.floor((monitor.height - BAR_HEIGHT) * 0.22);
            this._desktop.set_size(desktopWidth, -1);
            this._desktop.set_position(
                monitor.x + Math.floor((monitor.width - desktopWidth) / 2),
                monitor.y + verticalInset,
            );
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
    _launchFromTile(tile, cmd) {
        tile.set_pivot_point(0.5, 0.5);
        tile.ease({
            scale_x: 1.6,
            scale_y: 1.6,
            opacity: 0,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                tile.set_scale(1.0, 1.0);
                tile.opacity = 255;
            },
        });
        this._launch(cmd);
        // Hide the reveal after the tile has visibly committed. Grace is
        // short enough to feel rigid, long enough to let the eye track.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 160, () => {
            this._hideReveal();
            return GLib.SOURCE_REMOVE;
        });
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
