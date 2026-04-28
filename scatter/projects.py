#!/usr/bin/env python3
"""
scatter/projects.py — one OS-level project format, one creative tool catalog.

Every Scatter discipline (audio, film, 2D, 3D, write, code) opens the same
shape on disk: a folder under ~/scatter-projects/<slug>/ holding a
project.json manifest and per-tool files at conventional names. The Core
HTTP server exposes this so any client (Scatter Music, Scatter Film, the
bar, the desktop) is a thin view on the same store.

stdlib only. No third-party deps. Mirrors the Scatter Method:
- One door (Core HTTP) — clients never own the format.
- Build for actual hardware — tools are runtime-discovered via shutil.which;
  if the binary isn't on PATH, the tool isn't in the catalog.
- Local-first — projects live in $HOME, never leave the device.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


PROJECTS_ROOT = Path.home() / "scatter-projects"
MANIFEST = "project.json"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class Tool(NamedTuple):
    """A creative tool the user can attach to a project.

    `bin_candidates` is tolerant of distro packaging (Linux Show Player ships as
    `linux-show-player` or `lsp`; VS Code as `code` or `code-oss`).
    `file_pattern` is the relative path inside the project where this tool's
    project file lives (None means the tool has no per-project file — it just
    opens with no args, e.g. OBS, HandBrake).
    `subdir` is a folder pre-created on project init (Ardour needs its own
    session folder).
    """

    id: str
    label: str
    discipline: str
    blurb: str
    bin_candidates: tuple
    file_pattern: object = None  # str or None
    subdir: object = None  # str or None


def _tool_dict(t):
    return {
        "id": t.id,
        "label": t.label,
        "discipline": t.discipline,
        "blurb": t.blurb,
        "bin_candidates": list(t.bin_candidates),
        "file_pattern": t.file_pattern,
        "subdir": t.subdir,
    }


# Catalog. Order within a discipline = display order in catalogs.
# Disciplines: audio · film · graphics · model · write · code.
TOOLS: tuple[Tool, ...] = (
    # ---------- audio ----------
    Tool(
        "ardour", "Ardour", "audio",
        "Multitrack record, mix, host plugins (LV2/VST).",
        ("ardour",),
        file_pattern="ardour/{slug}.ardour",
        subdir="ardour",
    ),
    Tool(
        "lmms", "LMMS", "audio",
        "Patterns, beats, electronic composition.",
        ("lmms",),
        file_pattern="{slug}.mmp",
    ),
    Tool(
        "audacity", "Audacity", "audio",
        "Wave editing, cleanup, quick fixes.",
        ("audacity",),
        file_pattern="{slug}.aup3",
    ),
    Tool(
        "carla", "Carla", "audio",
        "Plugin host / patchbay for experiments.",
        ("carla",),
        file_pattern="{slug}.carxp",
    ),
    Tool(
        "linux-show-player", "Linux Show Player", "audio",
        "Theatrical cue lists, fades — closest OSS analog to QLab.",
        ("linux-show-player", "lsp"),
        file_pattern="{slug}.lsp",
    ),
    # ---------- film ----------
    Tool(
        "kdenlive", "Kdenlive", "film",
        "Non-linear video editor (MLT). The cut.",
        ("kdenlive",),
        file_pattern="{slug}.kdenlive",
    ),
    Tool(
        "shotcut", "Shotcut", "film",
        "Quick clip edits, MLT timeline.",
        ("shotcut",),
        file_pattern="{slug}.mlt",
    ),
    Tool(
        "obs-studio", "OBS Studio", "film",
        "Capture, screen-record, multi-source live.",
        ("obs",),
    ),
    Tool(
        "handbrake", "HandBrake", "film",
        "Final encode / delivery.",
        ("ghb", "handbrake"),
    ),
    # ---------- 3D / VFX (cross-discipline) ----------
    Tool(
        "blender", "Blender", "model",
        "3D, VFX, video sequence editor, all in one.",
        ("blender",),
        file_pattern="{slug}.blend",
    ),
    # ---------- graphics / 2D ----------
    Tool(
        "gimp", "GIMP", "graphics",
        "Raster image editor.",
        ("gimp", "gimp-2.10"),
        file_pattern="{slug}.xcf",
    ),
    Tool(
        "krita", "Krita", "graphics",
        "Painting, illustration, comics.",
        ("krita",),
        file_pattern="{slug}.kra",
    ),
    Tool(
        "inkscape", "Inkscape", "graphics",
        "Vector graphics, SVG.",
        ("inkscape",),
        file_pattern="{slug}.svg",
    ),
    # ---------- write ----------
    Tool(
        "ghostwriter", "ghostwriter", "write",
        "Distraction-free Markdown editor.",
        ("ghostwriter",),
        file_pattern="{slug}.md",
    ),
    Tool(
        "lowriter", "LibreOffice Writer", "write",
        "Long-form word processing — letters, manuscripts, reports.",
        ("lowriter", "libreoffice"),
        file_pattern="{slug}.odt",
    ),
    Tool(
        "localc", "LibreOffice Calc", "write",
        "Spreadsheets, budgets, line-by-line lists.",
        ("localc", "libreoffice"),
        file_pattern="{slug}.ods",
    ),
    Tool(
        "loimpress", "LibreOffice Impress", "write",
        "Decks, slides, talks.",
        ("loimpress", "libreoffice"),
        file_pattern="{slug}.odp",
    ),
    # ---------- code ----------
    Tool(
        "vscode", "VS Code", "code",
        "Code editor (treats project folder as workspace).",
        ("code", "code-oss", "codium"),
        # No file_pattern — code opens the directory itself; see resolve_launch_args.
    ),
)


_TOOL_BY_ID: dict[str, Tool] = {t.id: t for t in TOOLS}


# --------------------------------------------------------------------------- #
# slug + path helpers
# --------------------------------------------------------------------------- #


def is_valid_slug(s: str) -> bool:
    return bool(SLUG_RE.match(s))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:63]
    return s or "untitled"


def project_dir(slug: str) -> Path:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    return PROJECTS_ROOT / slug


def _which_first(candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return None


# --------------------------------------------------------------------------- #
# tool catalog (runtime-discovered)
# --------------------------------------------------------------------------- #


def installed_tools():
    """Tools whose binary is currently on PATH. Order preserved from TOOLS."""
    out = []
    for t in TOOLS:
        if _which_first(t.bin_candidates) is None:
            continue
        out.append(_tool_dict(t))
    return out


def all_tools():
    """Every catalog entry, with `installed: bool` so a UI can show greyed-out tools."""
    out = []
    for t in TOOLS:
        d = _tool_dict(t)
        d["installed"] = _which_first(t.bin_candidates) is not None
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# project fs ops
# --------------------------------------------------------------------------- #


def _ensure_root() -> None:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)


def _read_manifest(slug: str) -> dict | None:
    p = project_dir(slug) / MANIFEST
    if not p.exists():
        return None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if m.get("slug") != slug or not isinstance(m.get("name"), str):
        return None
    return m


def _file_for(slug: str, tool: Tool) -> dict | None:
    """{rel, abs, exists} for a tool's project file, or None if the tool has no per-project file."""
    if tool.file_pattern is None:
        return None
    rel = tool.file_pattern.format(slug=slug)
    abs_path = project_dir(slug) / rel
    return {"rel": rel, "abs": str(abs_path), "exists": abs_path.exists()}


def _project_view(slug: str, manifest: dict) -> dict:
    files: list[dict] = []
    for t in TOOLS:
        f = _file_for(slug, t)
        if f is None:
            continue
        files.append({"tool": t.id, **f})
    return {
        "manifest": manifest,
        "dir": str(project_dir(slug)),
        "files": files,
    }


def list_projects() -> list[dict]:
    _ensure_root()
    out: list[dict] = []
    for child in PROJECTS_ROOT.iterdir():
        if not child.is_dir() or not is_valid_slug(child.name):
            continue
        m = _read_manifest(child.name)
        if m:
            out.append({
                "slug": m["slug"],
                "name": m["name"],
                "createdAt": m.get("createdAt", ""),
            })
    out.sort(key=lambda p: p.get("createdAt", ""), reverse=True)
    return out


def load_project(slug: str) -> dict | None:
    if not is_valid_slug(slug):
        return None
    m = _read_manifest(slug)
    if m is None:
        return None
    return _project_view(slug, m)


def create_project(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name required")
    slug = slugify(name)
    if not is_valid_slug(slug):
        raise ValueError("could not derive a valid slug")
    _ensure_root()
    d = project_dir(slug)
    if d.exists():
        raise FileExistsError(f"project already exists: {slug}")
    d.mkdir(parents=True)
    # Pre-create any tool subdirs (e.g. Ardour wants its own session folder).
    seen: set[str] = set()
    for t in TOOLS:
        if t.subdir and t.subdir not in seen:
            (d / t.subdir).mkdir(exist_ok=True)
            seen.add(t.subdir)
    manifest = {
        "slug": slug,
        "name": name,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (d / MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return _project_view(slug, manifest)


# --------------------------------------------------------------------------- #
# launch
# --------------------------------------------------------------------------- #


def resolve_launch_args(tool_id: str, slug: str | None) -> tuple[list[str], str | None] | None:
    """
    Return (argv, opened_path_or_None) for spawning a tool.

    Returns None if the tool isn't in the catalog or its binary isn't on PATH.
    `argv[0]` is the absolute binary path. If `slug` is given and the tool
    has a per-project file/folder convention, that path is appended as argv[1]
    (only if the file exists, except for VS Code which always opens the dir).
    """
    tool = _TOOL_BY_ID.get(tool_id)
    if tool is None:
        return None
    bin_path = _which_first(tool.bin_candidates)
    if bin_path is None:
        return None

    argv: list[str] = [bin_path]
    opened: str | None = None

    if slug and is_valid_slug(slug):
        d = project_dir(slug)
        if d.exists():
            if tool.id == "vscode":
                # Special case: code opens the project folder as a workspace.
                argv.append(str(d))
                opened = str(d)
            elif tool.file_pattern is not None:
                rel = tool.file_pattern.format(slug=slug)
                abs_path = d / rel
                if abs_path.exists():
                    argv.append(str(abs_path))
                    opened = str(abs_path)
    return argv, opened


def spawn(argv: list[str]) -> bool:
    """Detached spawn — Scatter doesn't supervise these."""
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False
