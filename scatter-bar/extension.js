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
const BAR_HEIGHT = 76;

// Motion grammar — one easing, one rise, one fall. Every Scatter animation
// that isn't a composed signature (fox-leap, etc.) pulls from here so the
// surface has one heartbeat, Plymouth-weighted.
const MOTION_EASE = Clutter.AnimationMode.EASE_OUT_CUBIC;
const MOTION_IN_MS = 240;
const MOTION_OUT_MS = 180;
const MOTION_RISE_PX = 16;

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
        if (this._desktop) { Main.layoutManager.removeChrome(this._desktop); this._desktop.destroy(); this._desktop = null; }
        if (this._desktopHideTimeout) { GLib.source_remove(this._desktopHideTimeout); this._desktopHideTimeout = 0; }
        this._entry = null;
        this._session = null;
    }

    // ── Bar: the literal bottom panel ────────────────────────────────────

    _buildBar() {
        // One row, full-width. >-< at the left, entry stretching right.
        // No wordmark, no handle, no apps zone. The bar is the still center
        // of the OS; it carries one verb (talk) and wears no decoration.
        this._bar = new St.BoxLayout({
            name: 'scatterBar',
            style_class: 'scatter-bar',
            vertical: false,
            reactive: true,
            track_hover: false,
        });

        this._glyph = new St.Label({
            text: '>-<',
            style_class: 'scatter-bar-glyph',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._bar.add_child(this._glyph);

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

    // Reveal is no longer triggered by hovering the bar — the bar is now a
    // still line that wears no apps. Apps get summoned by a verb typed into
    // the entry, or by the top-left apps button (future). The reveal actor
    // and its animation code remain so that summoning path can reuse them.
    _wireHoverReveal() { /* intentionally empty */ }

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
        const trail = this._formatTrail(meta || {});
        this._desktopTrail.set_text(trail);
        this._desktopTrail.visible = trail.length > 0;
        this._desktop.opacity = 0;
        this._desktop.translation_y = MOTION_RISE_PX;
        this._desktop.visible = true;
        this._place();
        this._desktop.ease({
            opacity: 255,
            translation_y: 0,
            duration: MOTION_IN_MS,
            mode: MOTION_EASE,
        });
        // No auto-fade. The bubble stays until × is clicked or the next
        // reply replaces it. Sovereignty over your own thoughts includes
        // sovereignty over when they disappear.
    }

    _hideResponse() {
        if (!this._overlay || !this._overlay.visible) return;
        this._overlay.ease({
            opacity: 0,
            duration: MOTION_OUT_MS,
            mode: MOTION_EASE,
            onComplete: () => { if (this._overlay) this._overlay.visible = false; },
        });
    }

    _hideDesktop() {
        if (!this._desktop || !this._desktop.visible) return;
        // Falls back into the bar — same rise distance, same easing.
        this._desktop.ease({
            opacity: 0,
            translation_y: MOTION_RISE_PX,
            duration: MOTION_OUT_MS,
            mode: MOTION_EASE,
            onComplete: () => { if (this._desktop) this._desktop.visible = false; },
        });
    }

    // Provenance chip on the desktop bubble. Local replies are the invariant
    // and carry no trail — silence is the success signal. Cloud replies carry
    // a visible 'claude · egress on' mark so data leaves consciously.
    _formatTrail(meta) {
        const route = meta.route || '';
        if (route.startsWith('cloud:')) return 'claude · egress on';
        return '';
    }

    _showResponse(route, text, holdMs = 6000) {
        this._overlayRoute.set_text(route.toUpperCase());
        this._overlayText.set_text(text);
        this._overlay.opacity = 0;
        this._overlay.visible = true;
        this._place();
        this._overlay.ease({
            opacity: 255,
            duration: MOTION_IN_MS,
            mode: MOTION_EASE,
        });
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, holdMs, () => {
            if (this._overlay) {
                this._overlay.ease({
                    opacity: 0,
                    duration: MOTION_OUT_MS,
                    mode: MOTION_EASE,
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
            const tileWidth = 140;
            const tileGap = 16;
            const revealHeight = 120;
            const revealWidth = APPS.length * tileWidth + (APPS.length - 1) * tileGap + 48;
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
            // The bubble rises directly above the bar's >-< glyph — Scatter's
            // mouth opening. Matches the bar's background and hairline so the
            // bubble reads as the bar growing a thought, not a second widget.
            const bubbleWidth = Math.min(560, Math.floor(monitor.width * 0.42));
            this._desktop.set_size(bubbleWidth, -1);
            const [, natHeight] = this._desktop.get_preferred_height(bubbleWidth);
            const height = Math.max(56, natHeight);
            const barTop = monitor.y + monitor.height - BAR_HEIGHT;
            const anchorX = monitor.x + 56;
            this._desktop.set_position(anchorX, barTop - height);
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

    // Action-fired feedback lives in motion, not color. When a verb lands
    // (sleep / open firefox / etc.), the entry clears and — for visible
    // actions — the launched app's own signature carries the story. No
    // extra pulse on the bar's chrome.
    _flashGlyph() { /* no-op; kept for call sites */ }

    _sendToRouter(message) {
        // No routing overlay — the bar entry itself is the signal that a
        // message is in flight. A floating 'ROUTING …' pop-up announces the
        // machinery of conversation; we want silence until there's a reply.
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
