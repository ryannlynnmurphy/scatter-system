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
// Scatter herself is not in this list — the bowtie IS the face. Putting `>-<`
// in the reveal would duplicate her, and the duplicate would compete with
// the real one for "which is Scatter."
//
// Each tile is an orb (circle), branded per-app. `desktop_id` resolves a real
// system icon when available; `glyph` is the fallback for in-house apps that
// don't have a .desktop file. `brand` keys into per-app CSS tint.
//
// Order: tiles render bottom-up (column rises out of the bowtie), so the
// first entry sits closest to the face.
// Phase 1 tool ring. Bottom-up = closest to the bowtie first; the column
// rises out of Scatter's face. Order is intent-frequency ascending: web
// nearest the hand, system tools furthest. Eight visible orbs — the cap
// before the column overruns 1080p screens. Phase 2 tools (Excalidraw,
// VLC, Blanket, Stirling-PDF, etc.) are reachable via prompt verbs even
// without a visible orb (see ACTION_MAP).
const APPS = [
    { label: 'Scatter',      exec: 'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',                            desktop_id: 'scatter-browser.desktop',         glyph: '>-<', brand: 'scatter-browser' },
    { label: 'AppFlowy',     exec: 'flatpak run io.appflowy.AppFlowy',                                                       desktop_id: 'io.appflowy.AppFlowy.desktop',    glyph: '[]',  brand: 'appflowy' },
    { label: 'OnlyOffice',   exec: 'flatpak run org.onlyoffice.desktopeditors',                                              desktop_id: 'org.onlyoffice.desktopeditors.desktop', glyph: '|=|', brand: 'onlyoffice' },
    { label: 'Zotero',       exec: 'flatpak run org.zotero.Zotero',                                                          desktop_id: 'org.zotero.Zotero.desktop',       glyph: '{ }', brand: 'zotero' },
    { label: 'Files',        exec: 'nautilus',                                                                               desktop_id: 'org.gnome.Nautilus.desktop',      glyph: '[ ]', brand: 'files' },
    { label: 'Scatter Code', exec: 'gnome-terminal -- bash -lc "cd ~/scatter-system && exec bash"',                          glyph: '</>', brand: 'scatter-code' },
    { label: 'Claude Code',  exec: 'gnome-terminal -- bash -lc "claude || bash"',                                            glyph: '[c]', brand: 'claude-code' },
    { label: 'Terminal',     exec: 'gnome-terminal',                                                                         desktop_id: 'org.gnome.Terminal.desktop',      glyph: ' _ ', brand: 'terminal' },
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
    'scatter browser': 'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',
    'browser':         'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',
    'web':             'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',
    'librewolf':       'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',
    'firefox':         'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh"',
    'files':        'nautilus',
    'file manager': 'nautilus',
    'finder':       'nautilus',
    'terminal':     'gnome-terminal',
    'shell':        'gnome-terminal',
    'console':      'gnome-terminal',
    // Phase 1 tool-ring intents — verbs first so the prompt feels like
    // language not a launcher. Climate-hacker register: low chrome, high
    // intent. Each verb resolves to a flatpak run if installed, else a
    // friendly fallback (TBD via the router on miss).
    'note':         'flatpak run io.appflowy.AppFlowy',
    'notes':        'flatpak run io.appflowy.AppFlowy',
    'appflowy':     'flatpak run io.appflowy.AppFlowy',
    'write':        'flatpak run org.onlyoffice.desktopeditors',
    'document':     'flatpak run org.onlyoffice.desktopeditors',
    'spreadsheet':  'flatpak run org.onlyoffice.desktopeditors',
    'slides':       'flatpak run org.onlyoffice.desktopeditors',
    'onlyoffice':   'flatpak run org.onlyoffice.desktopeditors',
    'research':     'flatpak run org.zotero.Zotero',
    'cite':         'flatpak run org.zotero.Zotero',
    'zotero':       'flatpak run org.zotero.Zotero',
    'paper':        'flatpak run org.zotero.Zotero',
    'draw':         'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh --new-window https://excalidraw.com"',
    'sketch':       'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh --new-window https://excalidraw.com"',
    'whiteboard':   'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh --new-window https://excalidraw.com"',
    'flowchart':    'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh --new-window https://excalidraw.com"',
    'excalidraw':   'bash -lc "$HOME/scatter-system/scatter-browser/launcher.sh --new-window https://excalidraw.com"',
    'play':         'flatpak run org.videolan.VLC',
    'video':        'flatpak run org.videolan.VLC',
    'movie':        'flatpak run org.videolan.VLC',
    'vlc':          'flatpak run org.videolan.VLC',
    'focus':        'flatpak run com.rafaelmardojai.Blanket',
    'rain':         'flatpak run com.rafaelmardojai.Blanket',
    'ambient':      'flatpak run com.rafaelmardojai.Blanket',
    'blanket':      'flatpak run com.rafaelmardojai.Blanket',
    // Scatter-native + dev — kept last so longer matches above win first.
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

        // The bowtie. Scatter's face — and the apps trigger. Clicking it
        // summons the reveal layer; clicking again dismisses it. Hover and
        // press are felt in motion, not color. Plain `>-<` text — the
        // mascot.png stack was being eaten by the theme; the glyph IS
        // Scatter's face on its own. Stylesheet kills liga/calt so the
        // dash doesn't ligature into an arrow.
        const bowtieLabel = new St.Label({
            text: '>-<',
            style_class: 'scatter-bar-bowtie',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._glyph = new St.Button({
            style_class: 'scatter-bar-glyph',
            y_align: Clutter.ActorAlign.CENTER,
            can_focus: true,
            track_hover: true,
            reactive: true,
            child: bowtieLabel,
        });
        this._glyph.set_pivot_point(0.5, 0.5);
        this._glyph.connect('clicked', () => this._toggleReveal());
        this._glyph.connect('enter-event', () => {
            this._glyph.ease({
                scale_x: 1.06, scale_y: 1.06,
                duration: 140,
                mode: MOTION_EASE,
            });
        });
        this._glyph.connect('leave-event', () => {
            this._glyph.ease({
                scale_x: 1.0, scale_y: 1.0,
                duration: 160,
                mode: MOTION_EASE,
            });
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
        // Vertical column rising out of the bowtie. Each tile is a circular
        // orb branded per-app — real system icon when one exists, glyph fallback
        // for in-house apps. Click triggers that app's signature animation,
        // which is what carries the "orb morphs into the app" story.
        this._reveal = new St.BoxLayout({
            name: 'scatterReveal',
            style_class: 'scatter-reveal',
            vertical: true,
            reactive: false,
        });
        // Hidden by default — clicking the bowtie summons it, clicking again
        // dismisses it. Was previously visible-but-empty, which let half-armed
        // orbs leak onto the canvas as stuck pills.
        this._reveal.visible = false;
        this._reveal.opacity = 0;

        this._revealItems = [];
        APPS.forEach((app, i) => {
            const item = new St.Button({
                style_class: 'scatter-reveal-item',
                can_focus: true,
                track_hover: true,
                reactive: true,
            });
            // Force the orb size via JS — CSS width/height alone gets eaten
            // by the inherited shell theme, which is what made these render
            // as narrow stadium pills instead of 96px circles.
            item.set_size(96, 96);
            // Brand tint — one CSS class per app, per stylesheet.
            if (app.brand) item.add_style_class_name(`scatter-orb-${app.brand}`);

            // Pull the real desktop icon when available; otherwise fall back
            // to the glyph. The orb is the holder; what's inside is the
            // app's identity.
            let iconChild = null;
            if (app.desktop_id) {
                try {
                    const info = Gio.DesktopAppInfo.new(app.desktop_id);
                    if (info) {
                        const gicon = info.get_icon();
                        if (gicon) {
                            iconChild = new St.Icon({
                                gicon,
                                icon_size: 48,
                                style_class: 'scatter-orb-icon',
                            });
                        }
                    }
                } catch (_) { /* fall through to glyph */ }
            }
            if (!iconChild) {
                iconChild = new St.Label({
                    text: app.glyph,
                    style_class: 'scatter-reveal-glyph',
                });
            }

            const inner = new St.Bin({
                style_class: 'scatter-orb-inner',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
                child: iconChild,
            });
            item.set_child(inner);

            // Initial state: collapsed at the bowtie's position, invisible.
            // Animation will rise each orb up the column with a stagger so the
            // bottom-most (closest to bowtie) emerges first.
            item.set_pivot_point(0.5, 1.0);
            item.translation_y = 80;
            item.opacity = 0;
            item._armed = false;

            item.connect('clicked', () => {
                this._launchFromTile(item, app);
            });
            item.connect('enter-event', () => this._magnifyTile(item));
            item.connect('leave-event', () => this._settleTile(item));

            this._revealItems.push(item);
        });

        // Add to the box in REVERSE so source-order index 0 sits at the bottom
        // of the column (closest to the bowtie). Stagger by source index then
        // gives "rises out of the face" — the bottom-most orb emerges first.
        [...this._revealItems].reverse().forEach(item => this._reveal.add_child(item));

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
        // Bowtie click → arm all tiles. Container becomes visible (it's
        // hidden at rest), then each orb rises with a small stagger.
        this._cancelHideTimer();
        this._revealShown = true;
        if (this._reveal) {
            this._reveal.visible = true;
            this._reveal.opacity = 255;
        }
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

    // Bowtie click — face opens, face closes. The press pulse on the bowtie
    // gives the click a felt response without needing a color flash.
    _toggleReveal() {
        if (this._glyph) {
            this._glyph.ease({
                scale_x: 0.92, scale_y: 0.92,
                duration: 90,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    this._glyph.ease({
                        scale_x: 1.0, scale_y: 1.0,
                        duration: 160,
                        mode: Clutter.AnimationMode.EASE_OUT_BACK,
                    });
                },
            });
        }
        if (this._revealShown) this._hideReveal();
        else this._showReveal();
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
        // collapse. Once every tile has finished falling, the container
        // itself goes invisible so nothing can leak through.
        const items = [...this._revealItems].reverse();
        const totalMs = items.length * 14 + 280;
        items.forEach((item, i) => {
            item._armed = false;
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, i * 14, () => {
                item.ease({
                    opacity: 0,
                    translation_y: 80,
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: 260,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                });
                return GLib.SOURCE_REMOVE;
            });
        });
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, totalMs, () => {
            if (this._reveal && !this._revealShown) {
                this._reveal.visible = false;
                this._reveal.opacity = 0;
            }
            return GLib.SOURCE_REMOVE;
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
            // Vertical column anchored above the bowtie — the column rises
            // out of the face. Bar's left padding is 56px and the bowtie has
            // min-width 64px, so its center sits at ~88px from monitor.x.
            const orbSize = 96;       // diameter, must match stylesheet
            const orbGap = 18;
            const padding = 16;
            const revealWidth = orbSize + padding * 2;
            const revealHeight = APPS.length * orbSize + (APPS.length - 1) * orbGap + padding * 2;
            const bowtieCenterX = monitor.x + 56 + 32;  // bar padding + half bowtie width
            const anchorX = Math.max(monitor.x + 8, bowtieCenterX - revealWidth / 2);
            this._reveal.set_size(revealWidth, revealHeight);
            this._reveal.set_position(
                anchorX,
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
        // 'Scatter' (the browser, brand=scatter-browser) gets the wolf
        // signature — stalk + sprint + sink-into-shadow. Distinct from the
        // bowtie's bloom by way of the brand key.
        if ((appSpec.brand || '') === 'scatter-browser')
                                      return (t, l, d) => this._signatureScatterBrowser(t, l, d);
        if (label === 'scatter')      return (t, l, d) => this._signatureScatter(t, l, d);
        if (label === 'scatter code') return (t, l, d) => this._signatureScatterCode(t, l, d);
        if (label === 'claude code')  return (t, l, d) => this._signatureClaudeCode(t, l, d);
        if (label === 'files')        return (t, l, d) => this._signatureFiles(t, l, d);
        if (label === 'terminal')     return (t, l, d) => this._signatureTerminal(t, l, d);
        return (t, l, d) => this._signatureDefault(t, l, d);
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

    // Scatter Browser — The Wolf: stalk → lock-on → straight-line sprint →
    // sink into shadow. Where the fox leapt in an arc with embers, the wolf
    // moves low and direct. No bounce, no curve. The trail is a charcoal
    // shadow that absorbs the orb at the end. Same Clutter primitives,
    // different physicality.
    _signatureScatterBrowser(tile, launch, done) {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor) { return this._signatureDefault(tile, launch, done); }

        const [tileX, tileY] = tile.get_transformed_position();
        const [tileW, tileH] = [tile.width, tile.height];
        const targetX = monitor.x + monitor.width / 2 - tileW / 2;
        const targetY = monitor.y + monitor.height / 3 - tileH / 2;
        const dx = targetX - tileX;
        const dy = targetY - tileY;

        tile.set_pivot_point(0.5, 0.5);

        // Shadow-trail: a single elongated charcoal mark drawn behind the
        // wolf as it sprints. Stretched, low-opacity, no glow. The wolf
        // doesn't burn the canvas; it leaves a streak of weight.
        const shadow = new St.Widget({
            width: 10,
            height: 10,
            opacity: 0,
            reactive: false,
        });
        shadow.set_position(tileX + tileW / 2 - 5, tileY + tileH / 2 - 5);
        shadow.set_style('background-color: #0a0a0a; border-radius: 999px;');
        Main.layoutManager.addChrome(shadow, { affectsInputRegion: false });

        // Beat 1 — STALK (0-220ms): drop low and forward, body lengthening.
        // Wolves don't squash for a leap; they flatten to track. No backwards
        // pull — the wolf is already pointed at the prey.
        tile.ease({
            scale_x: 1.10, scale_y: 0.86,
            translation_y: 4,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — LOCK (220-360ms): hold. The pause is the threat. Eyes on.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 220, () => {
            tile.ease({
                scale_x: 1.06, scale_y: 0.92,
                duration: 140,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — SPRINT (360-720ms): straight line, no arc, no rotation,
        // body stretched horizontally in the direction of travel. The shadow
        // trail extends behind it. Linear easing — wolves don't decelerate
        // mid-run.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 360, () => {
            tile.ease({
                translation_x: dx,
                translation_y: dy,
                scale_x: 1.35, scale_y: 0.78,
                duration: 360,
                mode: Clutter.AnimationMode.LINEAR,
            });
            // Shadow grows along the path — single streak, not embers.
            shadow.opacity = 110;
            shadow.set_pivot_point(0.5, 0.5);
            shadow.ease({
                translation_x: dx,
                translation_y: dy,
                scale_x: 14.0, scale_y: 0.4,
                opacity: 0,
                duration: 480,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            // Window opens mid-sprint — the wolf carries it in.
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 4 — ABSORB (720-1020ms): no impact bounce. The wolf sinks
        // into a charcoal pool — opacity drops, scale collapses. The window
        // is already on screen by now.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 720, () => {
            tile.ease({
                scale_x: 1.0, scale_y: 0.2,
                opacity: 0,
                duration: 300,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    try { shadow.destroy(); } catch (_) {}
                    done();
                },
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Scatter — "bloom": the bowtie expands as a concentric ring while
    // the tile dissolves outward. Scatter opening into herself.
    _signatureScatter(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);

        const [tx, ty] = tile.get_transformed_position();
        const ring = new St.Widget({
            style_class: 'scatter-shockwave',
            width: 28, height: 28,
            opacity: 0,
            reactive: false,
        });
        ring.set_pivot_point(0.5, 0.5);
        ring.set_position(tx + tile.width / 2 - 14, ty + tile.height / 2 - 14);
        Main.layoutManager.addChrome(ring, { affectsInputRegion: false });

        // Beat 1 — INHALE (0-140ms): small pull-in, the face gathering itself.
        tile.ease({
            scale_x: 0.92, scale_y: 0.92,
            duration: 140,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — BLOOM (140-460ms): expand fast, ring rides out with it.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 140, () => {
            tile.ease({
                scale_x: 2.2, scale_y: 2.2,
                opacity: 0,
                duration: 320,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            ring.opacity = 230;
            ring.ease({
                scale_x: 5.5, scale_y: 5.5,
                opacity: 0,
                duration: 520,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — RESOLVE (460-620ms): clean up satellite actor, finish.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 620, () => {
            try { ring.destroy(); } catch (_) {}
            done();
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Scatter Code — "Pollock": the one Pollock signature in Scatter.
    // The orb winds up, whips, and a composed splatter of streaks draws
    // itself outward from the center. Each streak is a thin elongated mark
    // — a Pollock drip in motion, not a particle blob. Restrained palette
    // (cream / charcoal / amber / scatter-green); chaotic energy inside a
    // composed gesture. Pollock × 1, never repeated elsewhere.
    _signatureScatterCode(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);
        const [tileX, tileY] = tile.get_transformed_position();
        const cx = tileX + tile.width / 2;
        const cy = tileY + tile.height / 2;

        // The whole drip palette — four colors, as Pollock often used. No
        // rainbow, no slop. Each streak picks one.
        const palette = ['#f5f2ea', '#1a1a1a', '#ffb800', '#4ade80'];

        // 14 streaks spread across a ¾-circle below and beside the orb (no
        // streaks shooting straight up — gravity reads better when the
        // splatter favors lateral and downward angles).
        const STREAKS = 14;
        const streaks = [];
        for (let i = 0; i < STREAKS; i++) {
            const angle = -Math.PI * 0.15 + (Math.PI * 1.30) * (i / (STREAKS - 1)) + (Math.random() - 0.5) * 0.18;
            const length = 56 + Math.random() * 88;
            const thickness = 2 + Math.floor(Math.random() * 3);
            const color = palette[i % palette.length];
            const s = new St.Widget({
                width: thickness,
                height: 1,
                opacity: 0,
                reactive: false,
            });
            s.set_pivot_point(0.5, 0.0);  // grow downward from origin
            s.rotation_angle_z = (angle * 180 / Math.PI) + 90;  // 0° points down
            s.set_position(cx - thickness / 2, cy);
            s.set_style(`background-color: ${color}; border-radius: ${thickness}px; box-shadow: 0 0 6px ${color}55;`);
            Main.layoutManager.addChrome(s, { affectsInputRegion: false });
            streaks.push({ actor: s, length });
        }

        // Beat 1 — WIND-UP (0-120ms): tilt back, pull in. The wrist coils.
        tile.ease({
            scale_x: 0.92, scale_y: 0.92,
            rotation_angle_z: -8,
            duration: 120,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — WHIP (120-260ms): snap forward, streaks draw themselves
        // outward from the orb center. This is the gesture itself.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 120, () => {
            tile.ease({
                scale_x: 1.18, scale_y: 1.18,
                rotation_angle_z: 14,
                duration: 140,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            streaks.forEach((streakObj, i) => {
                const { actor, length } = streakObj;
                // Stagger the strokes slightly — a real wrist-whip lands
                // marks across a few frames, not in one instant.
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, i * 6, () => {
                    actor.opacity = 255;
                    actor.height = length;
                    actor.ease({
                        opacity: 0,
                        duration: 480 + Math.floor(Math.random() * 160),
                        mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    });
                    return GLib.SOURCE_REMOVE;
                });
            });
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — DISSOLVE (260-560ms): the orb fades into the splatter
        // it just made. No bounce; Pollock doesn't bounce.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 260, () => {
            tile.ease({
                scale_x: 1.6, scale_y: 1.6,
                opacity: 0,
                rotation_angle_z: 0,
                duration: 300,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => done(),
            });
            return GLib.SOURCE_REMOVE;
        });

        // Cleanup — destroy streaks once they've fully faded.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 800, () => {
            streaks.forEach(({ actor }) => { try { actor.destroy(); } catch (_) {} });
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Claude Code — "cipher": tile rises, rotates a half turn while
    // expanding, then dissolves upward like steam. The cipher unlocking.
    _signatureClaudeCode(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);

        // Beat 1 — LIFT (0-160ms): rise + small scale up.
        tile.ease({
            translation_y: -10,
            scale_x: 1.08, scale_y: 1.08,
            duration: 160,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — ROTATE (160-460ms): half-turn while widening.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 160, () => {
            tile.ease({
                rotation_angle_z: 180,
                scale_x: 1.35, scale_y: 1.35,
                duration: 300,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — STEAM (460-720ms): drift up + fade.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 460, () => {
            tile.ease({
                translation_y: -56,
                opacity: 0,
                rotation_angle_z: 360,
                duration: 260,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => done(),
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Files — "Monet": Water Lilies dissolution. The orb softens, then
    // breaks into a small set of soft color dabs that drift outward and
    // upward like reflections on water. Atmospheric, not crisp. Composed,
    // not random — a fixed lily-pad palette, a slow EASE_OUT_SINE drift,
    // dabs fading into the canvas as the file manager opens.
    _signatureFiles(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);
        const [tileX, tileY] = tile.get_transformed_position();
        const cx = tileX + tile.width / 2;
        const cy = tileY + tile.height / 2;

        // Lily-pad palette — sage / lavender / blush / periwinkle / cream.
        // Five colors, each a low-saturation pastel, the way Monet built
        // light from broken color rather than mixed pigment.
        const palette = ['#7a9e7e', '#a294b8', '#d4a5a5', '#8da3c7', '#e8d4a5'];

        // 12 dabs, evenly spaced around the orb with slight angular jitter.
        // Each dab is a soft circle, low opacity, slightly varied size.
        const DABS = 12;
        const dabs = [];
        for (let i = 0; i < DABS; i++) {
            const baseAngle = (Math.PI * 2) * (i / DABS);
            const angle = baseAngle + (Math.random() - 0.5) * 0.22;
            const distance = 90 + Math.random() * 80;
            const dx = Math.cos(angle) * distance;
            const dy = Math.sin(angle) * distance - 24;  // slight drift upward
            const size = 14 + Math.floor(Math.random() * 10);
            const color = palette[i % palette.length];
            const d = new St.Widget({
                width: size,
                height: size,
                opacity: 0,
                reactive: false,
            });
            d.set_pivot_point(0.5, 0.5);
            d.set_position(cx - size / 2, cy - size / 2);
            d.set_style(
                `background-color: ${color}; ` +
                `border-radius: ${size}px; ` +
                `box-shadow: 0 0 ${Math.floor(size * 0.6)}px ${color}66;`
            );
            Main.layoutManager.addChrome(d, { affectsInputRegion: false });
            dabs.push({ actor: d, dx, dy });
        }

        // Beat 1 — HUSH (0-180ms): orb breathes, very slight expansion.
        // Monet doesn't snap — he settles.
        tile.ease({
            scale_x: 1.04, scale_y: 1.04,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_SINE,
        });

        // Beat 2 — EMISSION (180-260ms): dabs fade in at the orb's edge,
        // then begin their drift. The fade-in masks their spawn — they
        // appear to bloom from the orb itself.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            dabs.forEach(({ actor, dx, dy }, i) => {
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, i * 8, () => {
                    actor.opacity = Math.floor(140 + Math.random() * 70);
                    actor.ease({
                        translation_x: dx,
                        translation_y: dy,
                        scale_x: 1.4,
                        scale_y: 1.4,
                        opacity: 0,
                        duration: 720 + Math.floor(Math.random() * 200),
                        mode: Clutter.AnimationMode.EASE_OUT_SINE,
                    });
                    return GLib.SOURCE_REMOVE;
                });
            });
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — DISSOLVE (260-740ms): orb softens away into the dabs
        // it just released. Slow expansion, slow fade. No bounce.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 260, () => {
            tile.ease({
                scale_x: 1.35, scale_y: 1.35,
                opacity: 0,
                duration: 480,
                mode: Clutter.AnimationMode.EASE_OUT_SINE,
                onComplete: () => done(),
            });
            return GLib.SOURCE_REMOVE;
        });

        // Cleanup — destroy dabs once they've drifted away.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1100, () => {
            dabs.forEach(({ actor }) => { try { actor.destroy(); } catch (_) {} });
            return GLib.SOURCE_REMOVE;
        });
    }

    // ── Terminal — "prompt extend": underscore stretches across the
    // tile, blinks once, then dissolves. The cursor declaring itself.
    _signatureTerminal(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);

        // Beat 1 — STRETCH (0-180ms): horizontal extension, slight drop.
        tile.ease({
            scale_x: 1.7, scale_y: 0.85,
            translation_y: 4,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });

        // Beat 2 — BLINK (180-360ms): brief opacity dip, then back.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            tile.ease({
                opacity: 90,
                duration: 90,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    tile.ease({
                        opacity: 255,
                        duration: 90,
                        mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    });
                },
            });
            launch();
            return GLib.SOURCE_REMOVE;
        });

        // Beat 3 — DISSOLVE (380-640ms): scale + fade.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 380, () => {
            tile.ease({
                scale_x: 2.2, scale_y: 1.0,
                opacity: 0,
                duration: 260,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => done(),
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
