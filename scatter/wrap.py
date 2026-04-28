#!/usr/bin/env python3
"""
scatter/wrap.py — wrap a Commons app in the Scatter system.

Generates, per app:
  1. Bash launcher at ~/.local/bin/scatter-<slug>
     - Profile gate: learner-profile refuses network-capable apps
     - Journals every launch to ~/.scatter/journal.jsonl
     - Runs the underlying binary through firejail when available
     - Falls back to direct invocation if firejail not installed
  2. Desktop entry at ~/.local/share/applications/scatter-<slug>.desktop
     - Scatter-themed display name ("Scatter Draft" vs "LibreOffice Writer")
     - Original provenance loudly named in Comment + Keywords
     - Categorized under Scatter;Commons;<orig-category>;
  3. Firejail profile at ~/.scatter/firejail-profiles/<slug>.profile
     - Only applied when firejail exists at launch time

Dry-run default. Pass --apply to actually write files.

No sudo needed — all targets are user-owned paths.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


# ---------- Commons registry ----------
# Per-app metadata. Kept small and auditable — grows by explicit addition,
# not by scraping. Each entry names the gift clearly.

COMMONS = {
    "libreoffice-writer": {
        "scatter_name": "Scatter Writer",
        "provenance": "LibreOffice Writer — The Document Foundation",
        "exec": "libreoffice --writer",
        "icon": "libreoffice-writer",
        "needs_net": False,
        "category": "Office",
        "keywords": "write;document;essay;text;letter",
        "comment": "General word processing. Built on LibreOffice Writer. (For playwriting, see Scatter Draft.)",
    },
    "libreoffice-calc": {
        "scatter_name": "Scatter Sheet",
        "provenance": "LibreOffice Calc — The Document Foundation",
        "exec": "libreoffice --calc",
        "icon": "libreoffice-calc",
        "needs_net": False,
        "category": "Office",
        "keywords": "spreadsheet;calculate;table;data",
        "comment": "Work with numbers and tables. Built on LibreOffice Calc.",
    },
    "gimp": {
        "scatter_name": "Scatter Paint",
        "provenance": "GIMP — GNU Image Manipulation Program",
        "exec": "gimp",
        "icon": "gimp",
        "needs_net": False,
        "category": "Graphics",
        "keywords": "paint;image;edit;photo;raster",
        "comment": "Paint and edit images. Built on GIMP.",
    },
    "inkscape": {
        "scatter_name": "Scatter Vector",
        "provenance": "Inkscape — Inkscape Project",
        "exec": "inkscape",
        "icon": "inkscape",
        "needs_net": False,
        "category": "Graphics",
        "keywords": "vector;svg;illustration;draw",
        "comment": "Make vector drawings. Built on Inkscape.",
    },
    "krita": {
        "scatter_name": "Scatter Sketch",
        "provenance": "Krita — The Krita Foundation",
        "exec": "krita",
        "icon": "krita",
        "needs_net": False,
        "category": "Graphics",
        "keywords": "sketch;draw;paint;digital art",
        "comment": "Digital sketching and painting. Built on Krita.",
    },
    "blender": {
        "scatter_name": "Scatter Form",
        "provenance": "Blender — Blender Foundation",
        "exec": "blender",
        "icon": "blender",
        "needs_net": False,
        "category": "Graphics;3DGraphics",
        "keywords": "3d;model;sculpt;animate",
        "comment": "Make 3D things. Built on Blender.",
    },
    "firefox": {
        "scatter_name": "Scatter Browser",
        "provenance": "Firefox — Mozilla",
        "exec": "firefox",
        "icon": "firefox",
        "needs_net": True,
        "category": "Network;WebBrowser",
        "keywords": "browser;web;internet;bubble",
        "comment": "Browse the web in a bubble. Built on Firefox.",
    },
    "thunderbird": {
        "scatter_name": "Scatter Mail",
        "provenance": "Thunderbird — Mozilla",
        "exec": "thunderbird",
        "icon": "thunderbird",
        "needs_net": True,
        "category": "Office;Email",
        "keywords": "mail;email;messages",
        "comment": "Read and write email. Built on Thunderbird.",
    },
    "obs": {
        "scatter_name": "Scatter Studio",
        "provenance": "OBS Studio — OBS Project",
        "exec": "obs",
        "icon": "obs",
        "needs_net": False,
        "category": "AudioVideo;Recorder",
        "keywords": "record;stream;video;screencast",
        "comment": "Record and stream. Built on OBS Studio.",
    },
    "audacity": {
        "scatter_name": "Scatter Sound",
        "provenance": "Audacity — Audacity Team",
        "exec": "audacity",
        "icon": "audacity",
        "needs_net": False,
        "category": "AudioVideo;Audio",
        "keywords": "audio;sound;record;edit",
        "comment": "Record and edit audio. Built on Audacity.",
    },
}


# ---------- prototype registry ----------
# Next.js-era apps in ~/projects/scatter/. These are gifts-from-self: Ryann's
# prototype work preserved intact. Launchers spawn `npm run dev` on an
# assigned port, wait for it, and host it in a native GTK window.
# The directories on disk still carry legacy names for git-history reasons;
# in prose and UI, they are always referred to by their Scatter name.

PROTOTYPES = {
    "draft-prototype": {
        "scatter_name": "Scatter Draft",
        "provenance": "Ryann Murphy — Scatter prototype, early 2026 (playwriting)",
        "source_dir": "projects/scatter/scatter-draft",
        "dev_port": 3101,
        "icon": "accessories-text-editor",
        "needs_net": False,
        "category": "Scatter;Office;WordProcessor",
        "keywords": "write;draft;play;script;screenplay",
        "comment": "Playwriting and scriptwriting environment — prototype.",
    },
    "film-prototype": {
        "scatter_name": "Scatter Film",
        "provenance": "Ryann Murphy — Scatter prototype, early 2026 (script-aware editing)",
        "source_dir": "projects/scatter/scatter-film",
        "dev_port": 3102,
        "icon": "video-x-generic",
        "needs_net": False,
        "category": "Scatter;AudioVideo;Video",
        "keywords": "film;video;edit;shot;timeline",
        "comment": "Screenwriter's editing environment — prototype.",
    },
    "music-prototype": {
        "scatter_name": "Scatter Music",
        "provenance": "Ryann Murphy — Scatter prototype, early 2026 (composition)",
        "source_dir": "projects/scatter/scatter-music",
        "dev_port": 3103,
        "icon": "audio-x-generic",
        "needs_net": False,
        "category": "Scatter;AudioVideo;Audio",
        "keywords": "music;compose;piano;arrange;score",
        "comment": "Composition environment for writers — prototype.",
    },
    "write-prototype": {
        "scatter_name": "Scatter Write",
        "provenance": "Ryann Murphy — Scatter prototype, early 2026 (long-form)",
        "source_dir": "projects/scatter/scatter-write",
        "dev_port": 3104,
        "icon": "accessories-text-editor",
        "needs_net": False,
        "category": "Scatter;Office",
        "keywords": "write;essay;long-form;markdown;distraction-free",
        "comment": "Distraction-free writing environment — prototype.",
    },
}


# ---------- paths ----------

LAUNCHER_DIR = Path.home() / ".local" / "bin"
DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"
FIREJAIL_DIR = Path.home() / ".scatter" / "firejail-profiles"
SCATTER_HOME = Path(__file__).resolve().parent.parent


# ---------- generators ----------

def _launcher_script(slug: str, meta: dict) -> str:
    needs_net = "1" if meta["needs_net"] else "0"
    scatter_core_path = SCATTER_HOME / "scatter_core.py"
    firejail_profile = FIREJAIL_DIR / f"{slug}.profile"
    provenance = meta["provenance"].replace("'", "'\\''")
    return f"""#!/usr/bin/env bash
# Scatter wrapper for {meta['scatter_name']}
# Generated by `scatter wrap`. Rerun to regenerate.
# Original: {meta['provenance']}

set -e

SCATTER_CORE="{scatter_core_path}"
NEEDS_NET="{needs_net}"
SLUG="{slug}"

# Learner profile: refuse network-capable apps by construction.
PROFILE=$(python3 "$SCATTER_CORE" profile 2>/dev/null || echo researcher)
if [ "$PROFILE" = "learner" ] && [ "$NEEDS_NET" = "1" ]; then
    echo "Scatter: {meta['scatter_name']} needs the network, and the current"
    echo "  profile is 'learner' — learner stays local."
    echo "  To switch: python3 \\"$SCATTER_CORE\\" profile --set researcher"
    exit 1
fi

# Journal the launch. Never fails the launcher — journaling is nice-to-have.
python3 "$SCATTER_CORE" - <<'PYJOURNAL' 2>/dev/null || true
import scatter_core as sc
sc.journal_append(
    "commons_launch",
    slug="{slug}",
    provenance='{provenance}',
    profile=sc.profile(),
)
PYJOURNAL

# Launch via firejail when available.
if command -v firejail >/dev/null 2>&1; then
    FJ_PROFILE="{firejail_profile}"
    if [ -f "$FJ_PROFILE" ]; then
        exec firejail --profile="$FJ_PROFILE" {meta['exec']} "$@"
    else
        exec firejail {meta['exec']} "$@"
    fi
else
    echo "Scatter: firejail not installed; running without sandbox."
    echo "  Install with: sudo apt install firejail"
    exec {meta['exec']} "$@"
fi
"""


def _desktop_entry(slug: str, meta: dict, launcher_path: Path) -> str:
    categories = f"Scatter;Commons;{meta['category']};"
    return f"""[Desktop Entry]
Type=Application
Name={meta['scatter_name']}
GenericName={meta['provenance']}
Comment={meta['comment']}
Exec={launcher_path} %U
Icon={meta['icon']}
Terminal=false
Categories={categories}
Keywords={meta['keywords']};scatter;commons;gift
StartupWMClass={meta['scatter_name']}
"""


def _prototype_launcher_script(slug: str, meta: dict) -> str:
    """Launcher for Next.js dev-server-style prototype apps.

    Starts `npm run dev` on a fixed port, waits for the server to respond,
    opens a chromeless GTK window via scatter/ui_window.py pointing at the
    dev server, and kills the server when the window closes.
    """
    scatter_core_path = SCATTER_HOME / "scatter_core.py"
    ui_window_path = SCATTER_HOME / "scatter" / "ui_window.py"
    source_dir = Path.home() / meta["source_dir"]
    port = meta["dev_port"]
    provenance = meta["provenance"].replace("'", "'\\''")
    return f"""#!/usr/bin/env bash
# Scatter wrapper for {meta['scatter_name']} (prototype)
# Generated by `scatter wrap`. Rerun to regenerate.
# {meta['provenance']}

set -u

SCATTER_CORE="{scatter_core_path}"
UI_WINDOW="{ui_window_path}"
SOURCE_DIR="{source_dir}"
PORT="{port}"
SLUG="{slug}"
LOG="/tmp/scatter-{slug}.log"

# Prototype apps are researcher-only: they need node, local dev tooling,
# and consume resources. A child on the learner profile does not run them.
PROFILE=$(python3 "$SCATTER_CORE" profile 2>/dev/null || echo researcher)
if [ "$PROFILE" = "learner" ]; then
    echo "Scatter: {meta['scatter_name']} (prototype) is a researcher-profile tool."
    echo "  To switch: python3 \\"$SCATTER_CORE\\" profile --set researcher"
    exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Scatter: prototype source directory not found: $SOURCE_DIR"
    exit 1
fi

if [ ! -d "$SOURCE_DIR/node_modules" ]; then
    echo "Scatter: node_modules missing for {meta['scatter_name']}."
    echo "  Run once: cd \\"$SOURCE_DIR\\" && npm install"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "Scatter: npm not installed. Install node.js first."
    exit 1
fi

# Journal the launch.
python3 "$SCATTER_CORE" - <<'PYJOURNAL' 2>/dev/null || true
import scatter_core as sc
sc.journal_append(
    "prototype_launch",
    slug="{slug}",
    scatter_name="{meta['scatter_name']}",
    provenance='{provenance}',
)
PYJOURNAL

# Start the Next.js dev server in a fresh process group so we can kill
# the whole tree when the window closes.
cd "$SOURCE_DIR"
setsid env PORT="$PORT" npm run dev > "$LOG" 2>&1 &
SERVER_PGID=$!

cleanup() {{
    kill -TERM -"$SERVER_PGID" 2>/dev/null || true
    sleep 0.5
    kill -KILL -"$SERVER_PGID" 2>/dev/null || true
}}
trap cleanup EXIT INT TERM

# Wait for the dev server to start responding.
for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    echo "Scatter: {meta['scatter_name']} dev server failed to start. Log at $LOG."
    cleanup
    exit 1
fi

# Open the native window. When the user closes it, ui_window.py kills
# the server pgid for us.
exec python3 "$UI_WINDOW" \\
    --url "http://127.0.0.1:$PORT/" \\
    --title "{meta['scatter_name']}" \\
    --kill-pgid "$SERVER_PGID"
"""


def _firejail_profile(slug: str, meta: dict) -> str:
    """Minimal Scatter firejail profile. Inherits upstream firejail preset for the app."""
    include_line = f"include {slug}.profile" if meta.get("firejail_preset") else "# no upstream firejail preset defined"
    net_line = "net none" if not meta["needs_net"] else "# network allowed (researcher profile only)"
    return f"""# Scatter firejail profile for {meta['scatter_name']}
# Generated by `scatter wrap`. Rerun to regenerate.
# Original: {meta['provenance']}

# Inherit Scatter's common defaults plus the upstream preset if any.
{include_line}

# Sovereignty-aligned defaults
private-tmp
private-dev
noroot
seccomp
caps.drop all
nosound
novideo
noprinters
no3d

# Network stance
{net_line}

# Filesystem: restrict writes to a Scatter workspace + standard home subdirs.
whitelist ${{HOME}}/Documents
whitelist ${{HOME}}/Downloads
whitelist ${{HOME}}/Pictures
whitelist ${{HOME}}/Videos
whitelist ${{HOME}}/Music
whitelist ${{HOME}}/.scatter
whitelist ${{HOME}}/.config/libreoffice
whitelist ${{HOME}}/.config/GIMP
whitelist ${{HOME}}/.config/Inkscape
include disable-common.inc
include disable-devel.inc
include disable-passwdmgr.inc
"""


# ---------- writer ----------

def wrap(app_key: str, apply: bool) -> dict:
    # Route to COMMONS (apt/system apps via firejail) or PROTOTYPES
    # (Next.js dev-server apps via ui_window.py).
    if app_key in COMMONS:
        meta = COMMONS[app_key]
        style = "commons"
    elif app_key in PROTOTYPES:
        meta = PROTOTYPES[app_key]
        style = "prototype"
    else:
        raise KeyError(
            f"unknown app: {app_key!r}. known commons: {', '.join(sorted(COMMONS))}. "
            f"known prototypes: {', '.join(sorted(PROTOTYPES))}"
        )
    slug = app_key

    launcher_path = LAUNCHER_DIR / f"scatter-{slug}"
    desktop_path = DESKTOP_DIR / f"scatter-{slug}.desktop"
    firejail_path = FIREJAIL_DIR / f"{slug}.profile"

    if style == "commons":
        launcher_body = _launcher_script(slug, meta)
        firejail_body: Optional[str] = _firejail_profile(slug, meta)
    else:  # prototype
        launcher_body = _prototype_launcher_script(slug, meta)
        firejail_body = None  # dev servers don't play nicely with firejail yet
    desktop_body = _desktop_entry(slug, meta, launcher_path)

    paths = {
        "launcher": str(launcher_path),
        "desktop": str(desktop_path),
    }
    if style == "commons":
        paths["firejail_profile"] = str(firejail_path)
    summary = {
        "slug": slug,
        "scatter_name": meta["scatter_name"],
        "provenance": meta["provenance"],
        "needs_net": meta["needs_net"],
        "style": style,
        "applied": apply,
        "paths": paths,
    }

    if not apply:
        preview = {
            "launcher_first_lines": launcher_body.splitlines()[:8],
            "desktop": desktop_body,
        }
        if firejail_body is not None:
            preview["firejail_first_lines"] = firejail_body.splitlines()[:12]
        summary["preview"] = preview
        summary["style"] = style
        return summary

    # Apply: create parents, write files, mark launcher executable.
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(launcher_body)
    launcher_path.chmod(0o755)
    desktop_path.write_text(desktop_body)
    if firejail_body is not None:
        FIREJAIL_DIR.mkdir(parents=True, exist_ok=True)
        firejail_path.write_text(firejail_body)

    # Journal this wrap.
    sc.journal_append(
        "commons_wrapped",
        slug=slug,
        scatter_name=meta["scatter_name"],
        provenance=meta["provenance"],
        launcher=str(launcher_path),
        desktop=str(desktop_path),
    )

    # Best-effort: update desktop database so the menu sees the new entry.
    update_bin = shutil.which("update-desktop-database")
    if update_bin:
        os.system(f'"{update_bin}" "{DESKTOP_DIR}" >/dev/null 2>&1')

    return summary


# ---------- CLI ----------

def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="scatter wrap",
        description="Wrap a Commons app in the Scatter system.",
    )
    parser.add_argument("app", nargs="?", help="app key (see --list)")
    parser.add_argument("--list", action="store_true", help="list known apps and exit")
    parser.add_argument("--apply", action="store_true", help="actually write files (default: dry-run)")
    parser.add_argument("--all", action="store_true", help="wrap every commons app (prototypes excluded)")
    parser.add_argument("--all-prototypes", action="store_true", help="wrap every prototype app")
    args = parser.parse_args(argv)

    if args.list:
        print("COMMONS (system / apt-installed apps, via firejail):")
        print(f"  {'KEY':<28} {'SCATTER NAME':<22} {'PROVENANCE':<48} NET")
        for key in sorted(COMMONS):
            m = COMMONS[key]
            print(f"  {key:<28} {m['scatter_name']:<22} {m['provenance']:<48} {'yes' if m['needs_net'] else 'no'}")
        print()
        print("PROTOTYPES (Next.js dev-server apps from ~/projects/scatter/):")
        print(f"  {'KEY':<28} {'SCATTER NAME':<22} {'PROVENANCE':<48} PORT")
        for key in sorted(PROTOTYPES):
            m = PROTOTYPES[key]
            print(f"  {key:<28} {m['scatter_name']:<22} {m['provenance']:<48} {m['dev_port']}")
        return 0

    if args.all and args.all_prototypes:
        targets = sorted(COMMONS) + sorted(PROTOTYPES)
    elif args.all:
        targets = sorted(COMMONS)
    elif args.all_prototypes:
        targets = sorted(PROTOTYPES)
    elif args.app:
        targets = [args.app]
    else:
        parser.print_help()
        return 1

    any_err = False
    for key in targets:
        try:
            result = wrap(key, apply=args.apply)
        except KeyError as e:
            print(str(e), file=sys.stderr)
            any_err = True
            continue

        marker = "✓ wrote" if args.apply else "· would write"
        print(f"{marker} {result['scatter_name']} ({key})")
        for label, path in result["paths"].items():
            print(f"    {label}: {path}")
        if not args.apply:
            print(f"    (dry-run — re-run with --apply to write)")

    return 1 if any_err else 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
