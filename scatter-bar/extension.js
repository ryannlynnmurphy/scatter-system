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
import Pango from 'gi://Pango';
import Soup from 'gi://Soup';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// ── Window discovery (single-room enforcement) ─────────────────────────
//
// Scatter apps boot with `--class=Scatter-<Slug>` (see ~/.local/bin/scatter-app).
// Before spawning anything, we ask the compositor whether a window with that
// class already exists; if so, raise/focus it instead of creating a duplicate.
// Stacking is structurally impossible if the gatekeeper actually gates.
const SCATTER_WM_PREFIX = 'Scatter-';

function _findScatterWindowsByPrefix(prefix) {
    const out = [];
    const actors = global.get_window_actors() || [];
    for (const actor of actors) {
        const win = actor.meta_window;
        if (!win) continue;
        const wmClass = win.get_wm_class && win.get_wm_class();
        if (!wmClass) continue;
        if (wmClass.toLowerCase().startsWith(prefix.toLowerCase())) {
            out.push(win);
        }
    }
    return out;
}

function _findScatterWindow(brand) {
    // brand is "music" / "film" / "write" / etc. — wm_class is "Scatter-Music".
    const target = (SCATTER_WM_PREFIX + brand).toLowerCase();
    const actors = global.get_window_actors() || [];
    for (const actor of actors) {
        const win = actor.meta_window;
        if (!win) continue;
        const wmClass = (win.get_wm_class && win.get_wm_class()) || '';
        if (wmClass.toLowerCase() === target) return win;
    }
    return null;
}

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
// Pixel-art logos live alongside the extension. One PNG per app, generated
// by generate_icons.py — the same grammar as the plymouth (◉.◉) face. Owning
// our own marks means every app reads as Scatter, not eight vendors.
const ICONS_DIR = GLib.build_filenamev([
    GLib.get_home_dir(), 'scatter-system', 'scatter-bar', 'icons',
]);
const _icon = (name) => GLib.build_filenamev([ICONS_DIR, `${name}.png`]);

// User-pinned apps live at ~/.config/scatter/pinned-apps.json. Each entry:
//   { label, exec, desktop_id?, icon_path? }
// Pinned apps slot into the column between the eight defaults and All Apps,
// so the column reads (top→bottom): All Apps, pins…, defaults…, bowtie.
const PINS_FILE = GLib.build_filenamev([
    GLib.get_user_config_dir(), 'scatter', 'pinned-apps.json',
]);

function _readPins() {
    try {
        const file = Gio.File.new_for_path(PINS_FILE);
        if (!file.query_exists(null)) return [];
        const [ok, contents] = file.load_contents(null);
        if (!ok) return [];
        const text = new TextDecoder().decode(contents);
        const parsed = JSON.parse(text);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        log(`scatter-bar: pinned-apps read failed: ${e.message || e}`);
        return [];
    }
}

function _writePins(pins) {
    try {
        const dir = GLib.path_get_dirname(PINS_FILE);
        GLib.mkdir_with_parents(dir, 0o755);
        const text = JSON.stringify(pins, null, 2);
        const file = Gio.File.new_for_path(PINS_FILE);
        const enc = new TextEncoder().encode(text);
        file.replace_contents(enc, null, false, Gio.FileCreateFlags.NONE, null);
    } catch (e) {
        log(`scatter-bar: pinned-apps write failed: ${e.message || e}`);
    }
}

// Scatter suite — native surfaces + Home as forward dashboard.
// Everything else (system tools, FOSS, etc.) also reaches Catalog behind ⊕.
//
// Each entry's exec resolves a .desktop in ~/.local/share/applications/
// via gtk-launch — keeps args/icons/wm-class in one source of truth.
const SUITE_APPS = [
    { label: 'Home', story: 'forward laptop surface — your suite grid.', exec: 'gtk-launch scatter-home.desktop', glyph: '⌂', brand: 'home', icon_path: _icon('home') },
    { label: 'Schools', story: 'adaptive lessons, voiced by Scatter.',           exec: 'gtk-launch scatter-schools.desktop', glyph: '>-<', brand: 'schools', icon_path: _icon('schools') },
    { label: 'Studio',  story: 'build things by talking. the brain.',            exec: 'gtk-launch scatter-studio.desktop',  glyph: '>-<', brand: 'studio',  icon_path: _icon('studio') },
    { label: 'Music',   story: 'a daw built for writers, not producers.',        exec: 'gtk-launch scatter-music.desktop',   glyph: '>-<', brand: 'music',   icon_path: _icon('music') },
    { label: 'Write',   story: 'a distraction-free writing environment.',        exec: 'gtk-launch scatter-write.desktop',   glyph: '>-<', brand: 'write',   icon_path: _icon('write') },
    { label: 'Draft',   story: 'playwriting and scriptwriting, by a playwright.', exec: 'gtk-launch scatter-draft.desktop',   glyph: '>-<', brand: 'draft',   icon_path: _icon('draft') },
    { label: 'Film',    story: 'screenwriter\'s editing — script to cut.',       exec: 'gtk-launch scatter-film.desktop',    glyph: '>-<', brand: 'film',    icon_path: _icon('film') },
    { label: 'Stream',  story: 'streaming for creative work, not gaming.',       exec: 'gtk-launch scatter-stream.desktop',  glyph: '>-<', brand: 'stream',  icon_path: _icon('stream') },
];

// Slug → display metadata, used by the recents reader to render a tile
// for each entry in ~/.config/scatter/recents.jsonl.
const SUITE_BY_SLUG = Object.fromEntries(SUITE_APPS.map(a => [a.label.toLowerCase(), a]));

// Control tiles — the corner column. Persistent affordances independent
// of which apps Ryann has used recently.
const HOME_TILE     = { label: 'Home',     story: 'Scatter Home — suite grid, one tap.', exec: 'gtk-launch scatter-home.desktop', glyph: '⌂', brand: 'home', icon_path: _icon('home') };
const CHAT_TILE     = { label: 'Chat',     story: 'past conversations with scatter.', exec: '__history',  glyph: '···', brand: 'history',  icon_path: _icon('history') };
const SETTINGS_TILE = { label: 'Settings', story: 'system settings.',                 exec: '__settings', glyph: '@',   brand: 'settings', icon_path: _icon('gear') };
const CATALOG_TILE  = { label: 'More',     story: 'every app: yours, scatter\'s, and the open-source world.', exec: '__catalog',  glyph: '+',   brand: 'catalog',  icon_path: _icon('all-apps') };

// Recents log — appended by ~/.local/bin/scatter-app on every launch.
// Format: one JSON line per launch, { app: <slug>, ts: <unix> }. Bar
// reads on reveal-show and surfaces the last 5 unique apps.
const RECENTS_FILE = GLib.build_filenamev([
    GLib.get_user_config_dir(), 'scatter', 'recents.jsonl',
]);

function _readRecents(maxUnique = 5) {
    try {
        const file = Gio.File.new_for_path(RECENTS_FILE);
        if (!file.query_exists(null)) return [];
        const [ok, contents] = file.load_contents(null);
        if (!ok) return [];
        const text = new TextDecoder().decode(contents);
        const lines = text.split('\n').filter(l => l.trim().length > 0);
        // Walk newest-first, deduping by slug. Keep the most recent N.
        const seen = new Set();
        const out = [];
        for (let i = lines.length - 1; i >= 0 && out.length < maxUnique; i--) {
            try {
                const e = JSON.parse(lines[i]);
                const slug = (e.app || '').toLowerCase();
                if (!slug || seen.has(slug)) continue;
                const meta = SUITE_BY_SLUG[slug];
                if (!meta) continue;        // Unknown app — skip.
                seen.add(slug);
                out.push({
                    ...meta,
                    label: meta.label,
                    story: meta.story,
                    brand: `recent-${meta.brand}`, // distinct CSS class for tinting
                });
            } catch (_) { /* skip malformed line */ }
        }
        return out;
    } catch (e) {
        log(`scatter-bar: recents read failed: ${e.message || e}`);
        return [];
    }
}

// Chat history persistence. Append-only NDJSON at ~/.config/scatter/chats.jsonl.
// Each line: { ts: ISO8601, prompt, reply, route }. The journal is the truth;
// the history modal is a view over it.
const CHATS_FILE = GLib.build_filenamev([
    GLib.get_user_config_dir(), 'scatter', 'chats.jsonl',
]);

function _appendChat(entry) {
    try {
        const dir = GLib.path_get_dirname(CHATS_FILE);
        GLib.mkdir_with_parents(dir, 0o755);
        const line = JSON.stringify(entry) + '\n';
        const file = Gio.File.new_for_path(CHATS_FILE);
        const stream = file.append_to(Gio.FileCreateFlags.NONE, null);
        stream.write_all(new TextEncoder().encode(line), null);
        stream.close(null);
    } catch (e) {
        log(`scatter-bar: chat append failed: ${e.message || e}`);
    }
}

function _readChats() {
    try {
        const file = Gio.File.new_for_path(CHATS_FILE);
        if (!file.query_exists(null)) return [];
        const [ok, contents] = file.load_contents(null);
        if (!ok) return [];
        const text = new TextDecoder().decode(contents);
        const lines = text.split('\n').filter(l => l.trim().length > 0);
        const out = [];
        for (const l of lines) {
            try { out.push(JSON.parse(l)); } catch (_) { /* skip malformed */ }
        }
        return out;
    } catch (e) {
        log(`scatter-bar: chat read failed: ${e.message || e}`);
        return [];
    }
}

// Compose reveal sections. Three columns, each rendered bottom-up:
//   recents : last 5 unique apps launched via ~/.local/bin/scatter-app
//   suite   : (reserved — empty; suite lives in Catalog + Home surface)
//   controls: home, chat, settings, more (catalog)
// Pins are kept (back-compat with anyone who already added pins) and
// joined into the suite column so they don't disappear.
function _buildApps() {
    const recents = _readRecents(5);
    const pins = _readPins().map(p => ({
        label: p.label || 'pinned',
        story: 'pinned by you.',
        exec: p.exec || '',
        desktop_id: p.desktop_id,
        icon_path: p.icon_path,
        glyph: '·',
        brand: 'pinned',
        pinned: true,
    }));
    // Reveal layout: last 5 unique apps Ryann actually used + the three
    // control tiles (chat / settings / more-apps). The full Scatter suite
    // is reachable via the More tile's catalog — the bar itself is a
    // recents-aware shortcut, not a directory of every surface.
    return {
        recents:  [...recents, ...pins],
        suite:    [],
        controls: [HOME_TILE, CHAT_TILE, SETTINGS_TILE, CATALOG_TILE],
    };
}

let APPS = _buildApps();
// Flat view for places that still want a single iterable (e.g. tooltip
// lookup). Rebuilt whenever _buildApps runs.
function _flatApps(sections) {
    return [...sections.recents, ...sections.suite, ...sections.controls];
}

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
    // Scatter-native surfaces — longer phrases first.
    'scatter home':        'gtk-launch scatter-home.desktop',
    'scatter catalog':     'gtk-launch scatter-catalog.desktop',
    'catalog':             'gtk-launch scatter-catalog.desktop',
    'suite':               'gtk-launch scatter-catalog.desktop',
    'future':              'gtk-launch scatter-home.desktop',
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

// Pin verbs: `pin <name>` / `unpin <name>` add/remove apps in the column.
// Resolves <name> against the system app list (case-insensitive substring).
const PIN_VERB = /^(pin|unpin)\s+(.+)$/i;

export default class ScatterBarExtension extends Extension {
    enable() {
        const VERSION_MARKER = `SCATTER-BAR-LOADED-${Date.now()}`;
        try {
            const f = Gio.File.new_for_path('/tmp/scatter-bubble-trace.log');
            const stream = f.append_to(Gio.FileCreateFlags.NONE, null);
            stream.write_all(new TextEncoder().encode(`${new Date().toISOString()} ENABLE ${VERSION_MARKER}\n`), null);
            stream.close(null);
        } catch (_) {}
        Main.notify('SCATTER bar enable', VERSION_MARKER);
        this._session = new Soup.Session();
        this._revealShown = false;
        this._libraryShown = false;

        // Build order = chrome z-order. The bowtie is the only thing the user
        // must always be able to click (to dismiss the reveal), so add it LAST
        // so it sits on top of the reveal grid and entry capsule.
        this._buildEntry();
        this._buildRevealLayer();
        this._buildResponseOverlay();
        this._buildDesktopSurface();
        this._buildLibrary();
        this._buildBar();
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
        if (this._entryFloat) { Main.layoutManager.removeChrome(this._entryFloat); this._entryFloat.destroy(); this._entryFloat = null; }
        if (this._reveal) { Main.layoutManager.removeChrome(this._reveal); this._reveal.destroy(); this._reveal = null; }
        if (this._tooltip) { Main.layoutManager.removeChrome(this._tooltip); this._tooltip.destroy(); this._tooltip = null; }
        if (this._overlay) { Main.layoutManager.removeChrome(this._overlay); this._overlay.destroy(); this._overlay = null; }
        if (this._desktop) { Main.layoutManager.removeChrome(this._desktop); this._desktop.destroy(); this._desktop = null; }
        if (this._library) { Main.layoutManager.removeChrome(this._library); this._library.destroy(); this._library = null; }
        if (this._history) { Main.layoutManager.removeChrome(this._history); this._history.destroy(); this._history = null; }
        if (this._desktopHideTimeout) { GLib.source_remove(this._desktopHideTimeout); this._desktopHideTimeout = 0; }
        this._entry = null;
        this._session = null;
    }

    // ── Bar: the literal bottom panel ────────────────────────────────────

    _buildBar() {
        // The floating face. Just the bowtie, anchored bottom-left. No strip,
        // no entry, no gear — those are summoned. The bowtie is the only
        // permanent chrome Scatter keeps on screen.
        this._bar = new St.BoxLayout({
            name: 'scatterBar',
            style_class: 'scatter-bar',
            vertical: false,
            reactive: true,
            track_hover: false,
        });

        const bowtieLabel = new St.Label({
            text: '>-<',
            style_class: 'scatter-bar-bowtie',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        // St.Label defaults to ellipsize=END. At certain DPIs the `<` got
        // chopped to `...`, breaking the iconic glyph. Force NONE so the
        // bowtie always renders as three discrete characters.
        bowtieLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;

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
        // Right-click on the bowtie = "go home" — minimize every Scatter
        // window so the user is never trapped in a fullscreen app with no
        // chrome. Doesn't kill processes; their work is intact, just out of
        // the way. (Esc inside any Scatter app remains the per-window close.)
        this._glyph.connect('button-press-event', (_actor, event) => {
            if (event.get_button() === 3) {
                this._goHome();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
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

        Main.layoutManager.addChrome(this._bar, {
            affectsStruts: false,
            trackFullscreen: true,
            affectsInputRegion: true,
        });
    }

    // ── Entry capsule: summoned by bowtie, slides out to the right ─────
    _buildEntry() {
        // Floating talk-to-scatter entry. The bowtie's `-<` arm points at
        // it; it extends rightward from the right side of the bowtie when
        // the face opens, retracts when the face closes.
        this._entryFloat = new St.BoxLayout({
            name: 'scatterEntryFloat',
            style_class: 'scatter-entry-float',
            vertical: false,
            reactive: true,
            visible: false,
            opacity: 0,
        });

        this._entry = new St.Entry({
            hint_text: 'talk to scatter…',
            can_focus: true,
            track_hover: true,
            style_class: 'scatter-bar-entry',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._entry.clutter_text.connect('activate', () => this._submit());
        this._entry.clutter_text.connect('key-press-event', (_a, ev) => {
            if (ev.get_key_symbol() === Clutter.KEY_Escape) {
                this._hideReveal();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this._entryFloat.add_child(this._entry);

        Main.layoutManager.addChrome(this._entryFloat, {
            affectsStruts: false,
            trackFullscreen: true,
            affectsInputRegion: true,
        });
    }

    // ── Reveal layer: apps slide up above the bar, one by one ──────────

    // Build one orb tile from an app spec. Used by _buildRevealLayer to
    // populate each section column. Wires hover (magnify + tooltip),
    // click (launch + signature animation), and the initial slide-up
    // state (40px below, invisible — _showReveal animates them up).
    _makeRevealTile(app) {
        const item = new St.Button({
            style_class: 'scatter-reveal-item',
            can_focus: true,
            track_hover: true,
            reactive: true,
        });
        item.set_size(72, 72);
        if (app.brand) item.add_style_class_name(`scatter-orb-${app.brand}`);

        let iconChild = null;
        if (app.pinned) {
            iconChild = this._makeScatterGlyphIcon(app.label, 36);
        }
        if (!iconChild && app.desktop_id) {
            try {
                const info = Gio.DesktopAppInfo.new(app.desktop_id);
                if (info) {
                    const gicon = info.get_icon();
                    if (gicon) {
                        iconChild = new St.Icon({
                            gicon,
                            icon_size: 36,
                            style_class: 'scatter-orb-icon',
                        });
                    }
                }
            } catch (_) { /* fall through */ }
        }
        if (!iconChild && app.icon_path) {
            try {
                const file = Gio.File.new_for_path(app.icon_path);
                if (file.query_exists(null)) {
                    iconChild = new St.Icon({
                        gicon: new Gio.FileIcon({ file }),
                        icon_size: 40,
                        style_class: 'scatter-orb-icon',
                    });
                }
            } catch (_) { /* fall through to glyph */ }
        }
        if (!iconChild) {
            iconChild = new St.Label({
                text: app.glyph || '·',
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

        item.set_pivot_point(0.5, 1.0);
        item.translation_y = 40;
        item.opacity = 0;
        item._armed = false;

        item.connect('clicked', () => {
            this._launchFromTile(item, app);
        });
        item.connect('enter-event', () => {
            this._magnifyTile(item);
            this._showTooltip(item, app.label, app.story);
        });
        item.connect('leave-event', () => {
            this._settleTile(item);
            this._hideTooltip();
        });

        return item;
    }

    _buildRevealLayer() {
        // Apps reveal — a 2-column grid that grows UP-AND-TO-THE-RIGHT from
        // just above the bowtie. Was a single vertical column; that column
        // grew tall enough on a 1080p display to bleed into the upper-left,
        // colliding with GNOME's Activities corner. The grid stays anchored
        // in the bottom-left quadrant no matter how many apps get pinned.
        this._reveal = new St.BoxLayout({
            name: 'scatterReveal',
            style_class: 'scatter-reveal',
            vertical: false,
            reactive: false,
        });
        // Hidden by default — clicking the bowtie summons it, clicking again
        // dismisses it. Was previously visible-but-empty, which let half-armed
        // orbs leak onto the canvas as stuck pills.
        this._reveal.visible = false;
        this._reveal.opacity = 0;

        this._revealItems = [];

        // Three columns growing right from the bowtie:
        //   recents → suite → controls
        // Each column reads bottom-up (closest-to-bowtie tile first), so
        // the user's most recent app sits at the base of the leftmost
        // column and the catalog/⊕ tile sits at the base of the rightmost.
        // Columns with zero items (e.g. no recents on first run) collapse
        // out so the reveal stays anchored low-left.
        const sections = [
            { key: 'recents',  items: APPS.recents },
            { key: 'suite',    items: APPS.suite },
            { key: 'controls', items: APPS.controls },
        ];

        sections.forEach(section => {
            if (!section.items.length) return;
            const col = new St.BoxLayout({
                style_class: `scatter-reveal-col scatter-reveal-col-${section.key}`,
                vertical: true,
                reactive: false,
            });
            // Bottom-up: build the items array in display order (top → bottom),
            // then add to the BoxLayout in reverse so the first item lands at
            // the bottom of the column (closest to the bowtie).
            const tiles = section.items.map(app => this._makeRevealTile(app));
            this._revealItems.push(...tiles);
            [...tiles].reverse().forEach(t => col.add_child(t));
            this._reveal.add_child(col);
        });

        // Tooltip is created once (not recreated on rebuild) — see _ensureTooltip.
        this._ensureTooltip();

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

    // ── History modal: chats grouped by date ─────────────────────────────
    // Reads ~/.config/scatter/chats.jsonl, groups by Today / Yesterday /
    // This Week / Older, renders in Scatter grammar. Click an entry to
    // expand the full prompt + reply.

    _showHistory() {
        if (!this._history) this._buildHistory();
        const monitor = Main.layoutManager.primaryMonitor;
        if (monitor) {
            this._history.set_position(monitor.x, monitor.y);
            this._history.set_size(monitor.width, monitor.height);
        }
        this._renderHistory();
        this._history.visible = true;
        this._history.ease({
            opacity: 255,
            duration: 280,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _hideHistory() {
        if (!this._history || !this._history.visible) return;
        this._history.ease({
            opacity: 0,
            duration: 200,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._history) this._history.visible = false; },
        });
    }

    _buildHistory() {
        this._history = new St.BoxLayout({
            name: 'scatterHistory',
            style_class: 'scatter-library', // share library scrim styling
            vertical: true,
            reactive: true,
        });
        this._history.visible = false;
        this._history.opacity = 0;
        this._history.connect('button-press-event', (actor, event) => {
            if (event.get_source() === this._history) {
                this._hideHistory();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        const header = new St.BoxLayout({
            style_class: 'scatter-library-header',
            vertical: true,
        });
        const title = new St.Label({
            text: 'history',
            style_class: 'scatter-library-title',
        });
        header.add_child(title);
        this._history.add_child(header);

        const scroll = new St.ScrollView({
            style_class: 'scatter-library-scroll',
            x_expand: true,
            y_expand: true,
        });
        scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._historyList = new St.BoxLayout({
            vertical: true,
            x_expand: true,
            style_class: 'scatter-history-list',
        });
        scroll.set_child(this._historyList);
        this._history.add_child(scroll);

        Main.layoutManager.addChrome(this._history, {
            affectsInputRegion: true,
        });
    }

    _renderHistory() {
        if (!this._historyList) return;
        this._historyList.destroy_all_children();
        const chats = _readChats();
        if (chats.length === 0) {
            this._historyList.add_child(new St.Label({
                text: 'no chats yet — talk to scatter and your history shows up here.',
                style_class: 'scatter-library-empty',
            }));
            return;
        }
        // Newest first, then group.
        chats.reverse();
        const now = new Date();
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
        const startOfYesterday = startOfToday - 86400_000;
        const startOfThisWeek = startOfToday - 7 * 86400_000;
        const groups = { today: [], yesterday: [], thisWeek: [], older: [] };
        for (const c of chats) {
            const ts = Date.parse(c.ts || '');
            if (isNaN(ts)) { groups.older.push(c); continue; }
            if (ts >= startOfToday) groups.today.push(c);
            else if (ts >= startOfYesterday) groups.yesterday.push(c);
            else if (ts >= startOfThisWeek) groups.thisWeek.push(c);
            else groups.older.push(c);
        }
        const sections = [
            ['today', groups.today],
            ['yesterday', groups.yesterday],
            ['this week', groups.thisWeek],
            ['older', groups.older],
        ];
        for (const [label, items] of sections) {
            if (items.length === 0) continue;
            const heading = new St.Label({
                text: label,
                style_class: 'scatter-history-heading',
            });
            this._historyList.add_child(heading);
            for (const c of items) this._historyList.add_child(this._buildHistoryItem(c));
        }
    }

    _buildHistoryItem(chat) {
        const tile = new St.Button({
            style_class: 'scatter-history-item',
            x_expand: true,
            can_focus: true,
            track_hover: true,
            reactive: true,
        });
        const inner = new St.BoxLayout({ vertical: true, x_expand: true });
        const time = new Date(chat.ts);
        const hh = String(time.getHours()).padStart(2, '0');
        const mm = String(time.getMinutes()).padStart(2, '0');
        const meta = new St.Label({
            text: `${hh}:${mm}` + (chat.route && chat.route.startsWith('cloud') ? '  ↗ claude' : ''),
            style_class: 'scatter-history-meta',
        });
        const promptLabel = new St.Label({
            text: chat.prompt || '(no prompt)',
            style_class: 'scatter-history-prompt',
        });
        promptLabel.clutter_text.line_wrap = true;
        promptLabel.clutter_text.set_ellipsize(0);
        const replyLabel = new St.Label({
            text: chat.reply || '',
            style_class: 'scatter-history-reply',
            visible: false,
        });
        replyLabel.clutter_text.line_wrap = true;
        replyLabel.clutter_text.set_ellipsize(0);
        inner.add_child(meta);
        inner.add_child(promptLabel);
        inner.add_child(replyLabel);
        tile.set_child(inner);
        // Click toggles full reply.
        tile.connect('clicked', () => {
            replyLabel.visible = !replyLabel.visible;
        });
        return tile;
    }

    // Generic Scatter app-glyph: dark tile, green initial letter, JB Mono.
    // Used for any app that isn't one of the eight hand-crafted defaults.
    // Library + pinned bar tiles share this exact treatment so the bar reads
    // continuous with the library. ALL open-source apps wear Scatter grammar.
    _makeScatterGlyphIcon(label, size) {
        const cleaned = (label || '?').trim();
        // First letter of the first word that starts with [A-Za-z0-9].
        let ch = '?';
        for (const part of cleaned.split(/\s+/)) {
            const m = part.match(/[A-Za-z0-9]/);
            if (m) { ch = m[0].toUpperCase(); break; }
        }
        const tile = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            style_class: 'scatter-app-glyph-tile',
            width: size,
            height: size,
        });
        const glyph = new St.Label({
            text: ch,
            style_class: 'scatter-app-glyph',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        tile.add_child(glyph);
        return tile;
    }

    _ensureTooltip() {
        if (this._tooltip) return;
        // Tooltip is a two-line placard floating to the right of the hovered
        // tile: app name on top (paper-white), story line under it (dim).
        // The story is the WHY of each app — what it does, why it earns its
        // pixel on the bar — so the reveal grid reads as a guided tour.
        this._tooltip = new St.BoxLayout({
            style_class: 'scatter-reveal-tooltip',
            vertical: true,
            opacity: 0,
            visible: false,
        });
        this._tooltipTitle = new St.Label({
            text: '',
            style_class: 'scatter-reveal-tooltip-title',
        });
        this._tooltipStory = new St.Label({
            text: '',
            style_class: 'scatter-reveal-tooltip-story',
        });
        this._tooltip.add_child(this._tooltipTitle);
        this._tooltip.add_child(this._tooltipStory);
        Main.layoutManager.addChrome(this._tooltip, {
            affectsInputRegion: false,
        });
    }

    _showTooltip(tile, label, story) {
        this._ensureTooltip();
        if (!this._tooltip) return;
        this._tooltipTitle.set_text(label || '');
        this._tooltipStory.set_text(story || '');
        this._tooltipStory.visible = !!(story && story.length);
        const [tx, ty] = tile.get_transformed_position();
        const [tw, th] = [tile.width, tile.height];
        this._tooltip.visible = true;
        // Raise above the reveal layer. Reveal is re-added to chrome on every
        // recents change, which pushes it above the (older) tooltip in the
        // chrome stack — without this, tile names render behind the next
        // column's orbs and Settings/Chats blur into the rest of the grid.
        const tParent = this._tooltip.get_parent();
        if (tParent) tParent.set_child_above_sibling(this._tooltip, null);
        // Force a layout pass so we know the tooltip's natural width.
        const [, natWidth] = this._tooltip.get_preferred_width(-1);
        const [, natHeight] = this._tooltip.get_preferred_height(natWidth);
        // Default placement is to the right of the tile. If that runs the
        // tooltip past the right edge of the monitor, flip it to the left
        // so the label always lands fully on-screen and in front.
        const monitor = Main.layoutManager.primaryMonitor;
        let tipX = tx + tw + 16;
        if (monitor && tipX + natWidth > monitor.x + monitor.width - 12) {
            tipX = Math.max(monitor.x + 12, tx - natWidth - 16);
        }
        this._tooltip.set_position(
            tipX,
            ty + Math.floor((th - natHeight) / 2),
        );
        this._tooltip.ease({
            opacity: 255,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _hideTooltip() {
        if (!this._tooltip) return;
        this._tooltip.ease({
            opacity: 0,
            duration: 160,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._tooltip) this._tooltip.visible = false; },
        });
    }

    _showReveal() {
        // Bowtie click → face opens. Apps rise on the left in a staggered
        // column; the entry capsule slides out to the right and takes
        // focus so the user can speak immediately.
        //
        // Refresh APPS first so the recents column reflects whatever has
        // been launched since the bar last built. Cheap (one file read,
        // last-N parse) and keeps the bar honest about "last 5 used."
        const newApps = _buildApps();
        const recentsChanged = JSON.stringify(newApps.recents.map(r => r.label))
            !== JSON.stringify(APPS.recents.map(r => r.label));
        APPS = newApps;
        if (recentsChanged) this._rebuildRevealLayer();
        this._cancelHideTimer();
        this._revealShown = true;
        if (this._reveal) {
            this._reveal.visible = true;
            this._reveal.opacity = 255;
        }
        if (this._entryFloat) {
            this._entryFloat.visible = true;
            this._entryFloat.translation_y = 0;
            this._entryFloat.translation_x = -16;
            this._entryFloat.ease({
                opacity: 255,
                translation_x: 0,
                duration: 280,
                mode: Clutter.AnimationMode.EASE_OUT_BACK,
            });
            if (this._entry) {
                this._entry.grab_key_focus();
            }
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
                    translation_y: 40,
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: 260,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                });
                return GLib.SOURCE_REMOVE;
            });
        });
        if (this._entryFloat) {
            if (this._entry) {
                this._entry.set_text('');
                if (global.stage) global.stage.set_key_focus(null);
            }
            this._entryFloat.ease({
                opacity: 0,
                translation_x: -16,
                duration: 220,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    if (this._entryFloat && !this._revealShown) {
                        this._entryFloat.visible = false;
                    }
                },
            });
        }
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
        this._desktopText.clutter_text.set_ellipsize(0); // Pango.EllipsizeMode.NONE

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
        // Diagnostic: write to /tmp so we can verify the path is hit even when
        // console output isn't reaching the journal.
        try {
            const f = Gio.File.new_for_path('/tmp/scatter-bubble-trace.log');
            const stream = f.append_to(Gio.FileCreateFlags.NONE, null);
            const line = `${new Date().toISOString()} len=${text ? text.length : 'NULL'} text="${(text||'').slice(0,80)}"\n`;
            stream.write_all(new TextEncoder().encode(line), null);
            stream.close(null);
        } catch (_) { /* swallow */ }
        // Clean rewrite: ask Pango directly how big the wrapped text is.
        // No Clutter measurement-cache games. Sequence:
        //   1. set_text on the label
        //   2. configure clutter_text: ellipsize NONE, line_wrap ON, set_width = MAX_INNER
        //   3. ask Pango layout for actual pixel extents of the wrapped text
        //   4. resize clutter_text and bubble to those exact dimensions
        //   5. position above bar at bowtie, animate scale-from-zero
        if (this._desktopHideTimeout) {
            GLib.source_remove(this._desktopHideTimeout);
            this._desktopHideTimeout = 0;
        }
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor) return;

        const PADDING_X = 40;        // CSS horizontal padding (20×2)
        const PADDING_CLOSE = 30;    // × button + row spacing
        const MAX_W = Math.min(440, Math.floor(monitor.width * 0.40));
        const MAX_INNER = MAX_W - PADDING_X - PADDING_CLOSE;

        const trail = this._formatTrail(meta || {});
        this._desktopTrail.set_text(trail);
        this._desktopTrail.visible = trail.length > 0;

        // Step 1+2: set text and wrap configuration.
        this._desktopText.set_text(text);
        const ct = this._desktopText.clutter_text;
        ct.set_ellipsize(0);
        ct.line_wrap = true;
        ct.line_wrap_mode = 2;
        ct.set_width(MAX_INNER);

        // Step 3: Pango layout's actual rendered size after wrap. This is
        // the source of truth — never lies, never caches stale.
        const layout = ct.get_layout();
        const [, logical] = layout.get_pixel_extents();
        const wrappedTextW = Math.min(MAX_INNER, logical.width);
        const wrappedTextH = logical.height;

        // Step 4: shrink clutter_text to actual width so the actor doesn't
        // claim wasted horizontal space for short messages.
        ct.set_width(wrappedTextW + 2); // +2 px to avoid edge clipping
        this._desktopText.set_width(wrappedTextW + 2);

        // Bubble outer width = wrapped text + close button + padding.
        const bubbleWidth = Math.max(120, wrappedTextW + PADDING_X + PADDING_CLOSE);
        this._desktop.set_size(bubbleWidth, -1);

        // Step 5: position. Bubble emerges from the dash of `>-<`. Bottom-left
        // anchored at the dash so it grows up-and-right; dash sits at the
        // center of the face. Vertical gap keeps the bubble clear of the face.
        const [, bubbleHeight] = this._desktop.get_preferred_height(bubbleWidth);
        const FACE_W = 124;
        const FACE_H = 64;
        const CORNER_PAD = 40;        // matches face placement (_place)
        const FACE_GAP = 14;          // breathing room above the bowtie
        const faceX = monitor.x + CORNER_PAD;
        const faceTop = monitor.y + monitor.height - FACE_H - CORNER_PAD;
        const dashX = faceX + Math.round(FACE_W / 2);
        this._desktop.set_position(dashX - 8, faceTop - bubbleHeight - FACE_GAP);
        this._desktop.set_pivot_point(0.0, 1.0);

        const dbg = `scatter-bar:bubble len=${text.length} pango.w=${logical.width}`
            + ` pango.h=${logical.height} bubble=${bubbleWidth}x${bubbleHeight}`;
        log(dbg);
        console.log(dbg);
        console.error(dbg);

        // Animate emergence — scale from a near-zero dot at the bowtie pivot.
        this._desktop.opacity = 0;
        this._desktop.scale_x = 0.05;
        this._desktop.scale_y = 0.05;
        this._desktop.translation_y = 0;
        this._desktop.visible = true;
        this._desktop.ease({
            opacity: 255,
            scale_x: 1.0,
            scale_y: 1.0,
            duration: 320,
            mode: Clutter.AnimationMode.EASE_OUT_BACK,
        });
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
        // Collapses back into the bowtie — scales down to the same point
        // it emerged from, so dismissal mirrors emergence.
        this._desktop.ease({
            opacity: 0,
            scale_x: 0.05,
            scale_y: 0.05,
            duration: 220,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._desktop) this._desktop.visible = false; },
        });
    }

    // Provenance chip. Local replies are silent (the invariant). Cloud replies
    // wear a plain-language mark so the user sees that data left this machine.
    // No "egress" jargon. Per Data-Leaves-Consciously: the toggle is visible.
    _formatTrail(meta) {
        const route = meta.route || '';
        if (route.startsWith('cloud:')) return '↗ claude · over the internet';
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

        // Floating face geometry: the bowtie sits in the bottom-left
        // corner with a margin off both edges. Apps ascend from its left;
        // the entry capsule extends from its right.
        // FACE_W = 124 holds `>-<` at 28px JB Mono without subpixel-clipping
        // the right `<` (88px clipped on certain DPI configs).
        const FACE_W = 124;
        const FACE_H = 64;
        const CORNER_PAD = 40;
        const faceX = monitor.x + CORNER_PAD;
        const faceY = monitor.y + monitor.height - FACE_H - CORNER_PAD;
        const faceCenterY = faceY + FACE_H / 2;

        if (this._bar) {
            this._bar.set_position(faceX, faceY);
            this._bar.set_size(FACE_W, FACE_H);
        }
        if (this._entryFloat) {
            // Entry capsule shares the bowtie's row and extends to its right.
            // Sits at the bottom of the screen, vertically centered against
            // the face. Width fills the rest of the bottom edge minus a
            // generous right margin.
            const ENTRY_H = 56;
            const ENTRY_GAP = 132;
            const RIGHT_PAD = CORNER_PAD;
            const entryX = faceX + FACE_W + ENTRY_GAP;
            const entryW = Math.max(
                360,
                Math.min(720, monitor.x + monitor.width - RIGHT_PAD - entryX),
            );
            const entryY = faceY + Math.round((FACE_H - ENTRY_H) / 2);
            this._entryFloat.set_position(entryX, entryY);
            this._entryFloat.set_size(entryW, ENTRY_H);
        }
        if (this._reveal) {
            // Apps ascend from the bowtie — column anchored to the face's
            // left edge, rising straight up. Bottom of the column sits one
            // gap above the top of the face so the cascade reads as pouring
            // out of the side of Scatter's face.
            //
            // Legibility-within-bounds rule: the column MUST fit between
            // monitor top and the face. If the natural 72px orb size would
            // overflow (10 apps on 1080p was clipping the bottom orb against
            // the face), scale orb size + gap down proportionally so every
            // tile is fully on-screen and intact.
            const padding = 18;
            const TOP_MARGIN = 24;
            // Runway between the top of the bowtie face and the bottom orb.
            // PREFERRED is what we want at 1080p+ so the cascade reads as
            // separate from the face. MIN is the legacy 56 — we collapse
            // toward it on shorter monitors so MIN_ORB orbs still fit.
            const APPS_GAP_PREFERRED = 140;
            const APPS_GAP_MIN = 56;
            // N drives column-sizing — we size for the tallest column so
            // every section fits within available height.
            const N = Math.max(
                APPS.recents.length,
                APPS.suite.length,
                APPS.controls.length,
            ) || 1;
            const NATURAL_ORB = 72;
            const NATURAL_GAP = 24;
            const MIN_ORB = 44;
            const MIN_ORB_GAP = 8;
            const totalRoom = faceY - (monitor.y + TOP_MARGIN);
            const minColumnH = N * MIN_ORB + (N - 1) * MIN_ORB_GAP + padding * 2;
            const APPS_GAP = Math.max(
                APPS_GAP_MIN,
                Math.min(APPS_GAP_PREFERRED, totalRoom - minColumnH),
            );

            const available = faceY - APPS_GAP - (monitor.y + TOP_MARGIN);
            const naturalH = N * NATURAL_ORB + (N - 1) * NATURAL_GAP + padding * 2;

            let orbSize = NATURAL_ORB;
            let orbGap = NATURAL_GAP;
            if (N > 1 && naturalH > available) {
                // Hold gap-to-orb ratio at 1:3 so spacing reads consistent.
                const room = available - padding * 2;
                const ratio = NATURAL_GAP / NATURAL_ORB;  // 1/3
                const calc = Math.floor(room / (N + (N - 1) * ratio));
                orbSize = Math.max(MIN_ORB, Math.min(NATURAL_ORB, calc));
                orbGap = Math.max(8, Math.floor(orbSize * ratio));
            }

            // Apply size inline. CSS no longer carries `!important` on width,
            // but we still mark these `!important` so any inherited shell
            // theme can't reintroduce a pin. Without this, set_size loses to
            // CSS in the layout phase and bottom orbs get pushed off-screen.
            const itemStyle =
                `width: ${orbSize}px !important; height: ${orbSize}px !important;` +
                ` min-width: 0 !important; min-height: 0 !important;`;
            this._revealItems.forEach(item => {
                item.set_size(orbSize, orbSize);
                item.set_style(itemStyle);
                const inner = item.get_child();
                if (inner) inner.set_style(itemStyle);
            });
            // Each column is a vertical BoxLayout — update its spacing too,
            // otherwise the CSS-defined 24px gap stays even when orbs shrink.
            const colStyle = `spacing: ${orbGap}px;`;
            this._reveal.get_children().forEach(col => col.set_style(colStyle));

            const revealWidth = orbSize + padding * 2;
            const revealHeight = N * orbSize + (N - 1) * orbGap + padding * 2;
            this._reveal.set_size(revealWidth, revealHeight);
            const revealX = faceX + Math.round((FACE_W - revealWidth) / 2);
            const revealY = Math.max(monitor.y + TOP_MARGIN, faceY - APPS_GAP - revealHeight);
            this._reveal.set_position(revealX, revealY);
        }
        if (this._overlay) {
            const overlayWidth = Math.min(720, monitor.width - 96);
            this._overlay.set_size(overlayWidth, -1);
            this._overlay.set_position(
                monitor.x + (monitor.width - overlayWidth) / 2,
                faceY - 120,
            );
        }
        // Desktop bubble sizing/positioning lives entirely in _showDesktop —
        // _place only handles bar/reveal/overlay. Desktop is recomputed every
        // time text changes, so doing it here would just race the show path.
    }

    // ── Submit: classify → dispatch ──────────────────────────────────────

    _submit() {
        const _entryText = this._entry.get_text();
        // Use a spawned shell command — we know shell can write to disk.
        // If THIS doesn't work, _submit isn't being called at all.
        try {
            GLib.spawn_command_line_async(
                `/bin/sh -c 'echo "$(date -Iseconds) _submit text=${JSON.stringify(_entryText)}" >> /tmp/scatter-bubble-trace.log'`
            );
        } catch (_) {}
        Main.notify('SCATTER BAR submit', `text="${_entryText}"`);
        const text = _entryText.trim();
        if (!text) return;
        this._entry.set_text('');

        // Pin / unpin — match before action verbs so "pin firefox" doesn't
        // get caught by "open firefox"-style routing.
        const pinMatch = text.match(PIN_VERB);
        if (pinMatch) {
            const verb = pinMatch[1].toLowerCase();
            const name = pinMatch[2].trim();
            if (verb === 'pin') this._pinApp(name);
            else this._unpinApp(name);
            this._flashGlyph();
            return;
        }

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
        this._lastPrompt = text;
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

    // Pin: resolve <name> against system apps, write to pins file, rebuild
    // the column. The column shows the new tile immediately.
    _pinApp(name) {
        const lower = name.toLowerCase();
        const all = Gio.AppInfo.get_all();
        const target = all.find(a => {
            if (!a.should_show()) return false;
            return (a.get_display_name() || '').toLowerCase().includes(lower)
                || (a.get_id() || '').toLowerCase().includes(lower);
        });
        if (!target) {
            this._showResponse('error',
                `no system app matches "${name}". Flatpak apps need a session restart to be pinnable.`);
            return;
        }
        const desktop_id = target.get_id();
        const exec = target.get_commandline() || '';
        const pins = _readPins();
        if (pins.some(p => p.desktop_id === desktop_id)) {
            this._showResponse('info', `${target.get_display_name()} is already pinned.`);
            return;
        }
        pins.push({
            label: target.get_display_name(),
            exec,
            desktop_id,
        });
        _writePins(pins);
        APPS = _buildApps();
        this._rebuildRevealLayer();
        this._showResponse('ok', `pinned ${target.get_display_name()}`);
    }

    _unpinApp(name) {
        const lower = name.toLowerCase();
        const pins = _readPins();
        const idx = pins.findIndex(p =>
            (p.label || '').toLowerCase().includes(lower)
            || (p.desktop_id || '').toLowerCase().includes(lower));
        if (idx < 0) {
            this._showResponse('error', `no pinned app matches "${name}".`);
            return;
        }
        const removed = pins.splice(idx, 1)[0];
        _writePins(pins);
        APPS = _buildApps();
        this._rebuildRevealLayer();
        this._showResponse('ok', `unpinned ${removed.label}`);
    }

    _rebuildRevealLayer() {
        const wasShown = this._revealShown;
        if (this._reveal) {
            Main.layoutManager.removeChrome(this._reveal);
            this._reveal.destroy();
            this._reveal = null;
        }
        this._revealItems = [];
        this._revealShown = false;
        this._buildRevealLayer();
        this._place();
        if (wasShown) this._showReveal();
    }

    // ── Scatter App Library ──────────────────────────────────────────────
    // Full-screen modal listing every installed app in Scatter grammar.
    // Replaces GNOME's Activities apps view, which carries Ubuntu's palette
    // and breaks the "one canvas" thesis. Search at top, grid below, click
    // to launch, right-click to pin.

    _buildLibrary() {
        // Outer scrim — black blur over the whole screen, click outside grid
        // to dismiss. Tapping anywhere except a tile or the search field hides.
        this._library = new St.BoxLayout({
            name: 'scatterLibrary',
            style_class: 'scatter-library',
            vertical: true,
            reactive: true,
        });
        this._library.visible = false;
        this._library.opacity = 0;
        this._library.connect('button-press-event', (actor, event) => {
            // Dismiss only when the press lands on the scrim itself, not on
            // the grid or the search.
            if (event.get_source() === this._library) {
                this._hideLibrary();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        // Header: editorial wordmark + count + search.
        const header = new St.BoxLayout({
            style_class: 'scatter-library-header',
            vertical: true,
        });
        this._libraryTitle = new St.Label({
            text: 'all your software',
            style_class: 'scatter-library-title',
        });
        this._librarySearch = new St.Entry({
            hint_text: 'filter…',
            can_focus: true,
            track_hover: true,
            style_class: 'scatter-library-search',
        });
        this._librarySearch.clutter_text.connect('text-changed', () => {
            this._renderLibraryGrid();
        });
        this._librarySearch.clutter_text.connect('key-press-event', (actor, event) => {
            const sym = event.get_key_symbol();
            if (sym === Clutter.KEY_Escape) {
                this._hideLibrary();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        header.add_child(this._libraryTitle);
        header.add_child(this._librarySearch);
        this._library.add_child(header);

        // Grid container — populated on show.
        this._libraryGrid = new St.Widget({
            style_class: 'scatter-library-grid',
            layout_manager: new Clutter.GridLayout({
                column_homogeneous: true,
                row_homogeneous: false,
                column_spacing: 18,
                row_spacing: 18,
            }),
        });
        const scroll = new St.ScrollView({
            style_class: 'scatter-library-scroll',
            x_expand: true,
            y_expand: true,
        });
        scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        const scrollChild = new St.BoxLayout({
            vertical: true,
            x_expand: true,
        });
        scrollChild.add_child(this._libraryGrid);
        scroll.set_child(scrollChild);
        this._library.add_child(scroll);

        Main.layoutManager.addChrome(this._library, {
            affectsInputRegion: true,
        });
    }

    _showLibrary() {
        if (!this._library) return;
        this._libraryShown = true;
        this._librarySearch.set_text('');
        this._renderLibraryGrid();
        const monitor = Main.layoutManager.primaryMonitor;
        if (monitor) {
            this._library.set_position(monitor.x, monitor.y);
            this._library.set_size(monitor.width, monitor.height);
        }
        this._library.visible = true;
        this._library.ease({
            opacity: 255,
            duration: 280,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        // Hand focus to search so the user can just type.
        global.stage.set_key_focus(this._librarySearch.clutter_text);
    }

    _hideLibrary() {
        if (!this._library || !this._libraryShown) return;
        this._libraryShown = false;
        this._library.ease({
            opacity: 0,
            duration: 200,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._library) this._library.visible = false; },
        });
    }

    _renderLibraryGrid() {
        if (!this._libraryGrid) return;
        this._libraryGrid.destroy_all_children();
        const filter = (this._librarySearch.get_text() || '').toLowerCase().trim();
        const apps = Gio.AppInfo.get_all()
            .filter(a => a.should_show())
            .filter(a => {
                if (!filter) return true;
                const name = (a.get_display_name() || '').toLowerCase();
                const id = (a.get_id() || '').toLowerCase();
                return name.includes(filter) || id.includes(filter);
            })
            .sort((a, b) =>
                (a.get_display_name() || '').localeCompare(b.get_display_name() || ''));

        const COLS = 6;
        const layout = this._libraryGrid.layout_manager;
        apps.forEach((info, i) => {
            const row = Math.floor(i / COLS);
            const col = i % COLS;
            layout.attach(this._buildLibraryTile(info), col, row, 1, 1);
        });
        // Empty-state when nothing matches.
        if (apps.length === 0) {
            const empty = new St.Label({
                text: filter ? `nothing matches "${filter}"` : 'no apps found',
                style_class: 'scatter-library-empty',
            });
            layout.attach(empty, 0, 0, COLS, 1);
        }
    }

    _buildLibraryTile(info) {
        const tile = new St.Button({
            style_class: 'scatter-library-tile',
            can_focus: true,
            track_hover: true,
            reactive: true,
        });
        const inner = new St.BoxLayout({
            vertical: true,
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });

        // Every app in the library wears Scatter grammar — vendor icons are
        // dropped entirely. One register across the whole library: black tile,
        // green letter, JB Mono. No 100 different brand colors competing.
        const iconChild = this._makeScatterGlyphIcon(info.get_display_name() || info.get_id() || '?', 48);
        inner.add_child(iconChild);

        const label = new St.Label({
            text: info.get_display_name() || info.get_id() || 'unknown',
            style_class: 'scatter-library-tile-label',
        });
        label.clutter_text.set_line_wrap(true);
        label.clutter_text.set_ellipsize(3);
        inner.add_child(label);

        tile.set_child(inner);

        tile.connect('clicked', () => {
            try {
                info.launch([], null);
            } catch (e) {
                this._showResponse('error', `could not launch: ${e.message || e}`);
            }
            this._hideLibrary();
        });
        // Right-click → pin to bar.
        tile.connect('button-press-event', (actor, event) => {
            if (event.get_button() !== 3) return Clutter.EVENT_PROPAGATE;
            const desktop_id = info.get_id();
            const exec = info.get_commandline() || '';
            const pins = _readPins();
            if (pins.some(p => p.desktop_id === desktop_id)) {
                this._showResponse('info', `${info.get_display_name()} is already pinned.`);
            } else {
                pins.push({
                    label: info.get_display_name(),
                    exec,
                    desktop_id,
                });
                _writePins(pins);
                APPS = _buildApps();
                this._rebuildRevealLayer();
                this._showResponse('ok', `pinned ${info.get_display_name()}`);
            }
            return Clutter.EVENT_STOP;
        });

        return tile;
    }

    // ── Go home ────────────────────────────────────────────────────────
    //
    // The user's "show me the desktop" gesture. Right-click the bowtie and
    // every Scatter window minimizes, leaving processes alive and work
    // intact. This is the second arm of the escape contract: Esc kills the
    // focused window, the bowtie minimizes the whole suite. Together they
    // mean the user is never trapped in a fullscreen app — there is always a
    // way out that isn't "turn off the computer."
    _goHome() {
        const wins = _findScatterWindowsByPrefix(SCATTER_WM_PREFIX);
        let count = 0;
        for (const win of wins) {
            try {
                win.minimize();
                count += 1;
            } catch (e) {
                log(`scatter-bar: minimize failed for ${win.get_wm_class && win.get_wm_class()}: ${e.message || e}`);
            }
        }
        if (this._revealShown) this._hideReveal();
        if (count > 0) {
            log(`scatter-bar: go-home minimized ${count} Scatter window(s)`);
        }
    }

    _launch(cmd) {
        if (cmd === '__overview_apps') {
            // Sentinel: open the Scatter-native app library instead of GNOME's.
            this._showLibrary();
            return;
        }
        if (cmd === '__history') {
            this._showHistory();
            return;
        }
        if (cmd === '__settings') {
            // Gear → system settings. gnome-control-center is the obvious
            // first stop; Scatter's own settings surface (when it exists)
            // can override this sentinel later.
            try {
                GLib.spawn_command_line_async('gnome-control-center');
            } catch (e) {
                this._showResponse('error', `could not open settings: ${e.message || e}`);
            }
            return;
        }
        if (cmd === '__catalog') {
            // ⊕ → Scatter Catalog. Phase 2 ships this surface as a real app
            // with Suite/Mine/World tabs. Until its .desktop lands, fall
            // back to the legacy library view so the click is never a dead
            // end. Probe by file existence — cheaper than spawning.
            const xdgData = GLib.get_user_data_dir();
            const desktopPath = GLib.build_filenamev([
                xdgData, 'applications', 'scatter-catalog.desktop',
            ]);
            const desktopFile = Gio.File.new_for_path(desktopPath);
            if (desktopFile.query_exists(null)) {
                try { GLib.spawn_command_line_async('gtk-launch scatter-catalog.desktop'); }
                catch (e) { this._showResponse('error', `could not open catalog: ${e.message || e}`); }
            } else {
                this._showLibrary();
            }
            return;
        }
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

        // Single-room enforcement: if this is a known Scatter app and a window
        // already exists with its WM class, raise it instead of spawning.
        // Apps no longer pile up; clicking Music while Music is open focuses
        // the existing window. Stacking is structurally impossible.
        if (appSpec.brand) {
            const existing = _findScatterWindow(appSpec.brand);
            if (existing) {
                try {
                    existing.activate(global.get_current_time());
                    if (this._revealShown) this._hideReveal();
                    return;
                } catch (e) {
                    log(`scatter-bar: activate failed for ${appSpec.brand}: ${e.message || e}`);
                    // fall through to normal spawn path
                }
            }
        }

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

        // The reveal column persists across launches — orbs are residents,
        // not torpedoes. Signature finishes, tile resets, column stays open
        // until the bowtie is clicked again.
        try {
            signature(tile, launchOnce, () => {
                GLib.source_remove(deadline);
                resetTile();
            });
        } catch (e) {
            log(`scatter-bar[${appSpec.label || 'app'}]: signature error ${e.message || e}`);
            launchOnce();
            resetTile();
        }
    }

    // Returns the signature function for a given app. Looks up by label;
    // falls back to the generic scale-up. New apps drop in by adding a
    // method named _signatureFooBar and wiring it here.
    _signatureFor(appSpec) {
        // Phase 1: every app uses the persistent press-pulse so orbs stay
        // residents of the column. Per-app dramatic signatures (wolf sprint,
        // Claude smile, terminal cut) come back as satellite clones that
        // fly while the original tile stays put — Phase 2.
        return (t, l, d) => this._signatureDefault(t, l, d);
    }

    // Generic signature — press-and-release. Tile breathes in, kicks the
    // app on the inhale, then settles back. Stays visible the whole time.
    _signatureDefault(tile, launch, done) {
        tile.set_pivot_point(0.5, 0.5);
        tile.ease({
            scale_x: 1.18,
            scale_y: 1.18,
            duration: 160,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                tile.ease({
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: 240,
                    mode: Clutter.AnimationMode.EASE_OUT_BACK,
                    onComplete: () => done(),
                });
            },
        });
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 90, () => {
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
                    try {
                        const f = Gio.File.new_for_path('/tmp/scatter-bubble-trace.log');
                        const s = f.append_to(Gio.FileCreateFlags.NONE, null);
                        s.write_all(new TextEncoder().encode(
                            `${new Date().toISOString()} reply route=${route} len=${reply.length}\n`
                        ), null);
                        s.close(null);
                    } catch (_) {}
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
                    // Persist every prose chat so the History view has a record.
                    // Launch/shell routes are silent ops, not conversation.
                    if (!route.startsWith('local:launch') && !route.startsWith('local:shell')) {
                        _appendChat({
                            ts: new Date().toISOString(),
                            prompt: this._lastPrompt || '',
                            reply,
                            route,
                        });
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
