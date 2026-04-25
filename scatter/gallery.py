#!/usr/bin/env python3
"""
scatter/gallery.py — persistent store for built artifacts.

The bar and face are ephemeral companions. The gallery is what Scatter
*keeps*: every note, reference, lesson, or freeform build the user makes,
saved to disk and re-openable on the user's accord.

Storage (~/.scatter/artifacts/{id}/):
  meta.json   — id, ts, subtype, prompt, model, title, summary
  index.html  — the rendered artifact, ready to drop into an iframe

Append-only by convention. Removal goes through scatter_core.forget(),
which writes a journal tombstone; filtered reads skip forgotten ids.
Physical deletion is a separate, auditable GC pass (unbuilt, consistent
with the rest of the substrate).

Stdlib only. No html parsing dependency — the title/summary extractor
is a small, forgiving regex pair that handles both typed artifacts (Inter
h1 inside the dark Scatter shell) and freeform HTML.
"""

from __future__ import annotations

import html as _html
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# scatter_core lives one directory up (same trick as server.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


ARTIFACTS_DIR = sc.ROOT / "artifacts"


# ── title extraction ─────────────────────────────────────────────────
# Prefer <h1>, fall back to <title>. Both are unescaped so the card can
# display "Rome's aqueducts" not "Rome&#39;s aqueducts".

_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SUMMARY_RE = re.compile(
    r'<p class="summary"[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL
)
_DEFINITION_RE = re.compile(
    r'<div class="definition"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL
)
_OBJECTIVE_RE = re.compile(
    r'<div class="objective"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL
)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_STRIP.sub("", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(html: str) -> str:
    for pat in (_H1_RE, _TITLE_RE):
        m = pat.search(html)
        if m:
            cleaned = _clean(m.group(1))
            if cleaned:
                return cleaned[:120]
    return "untitled"


def _extract_summary(html: str) -> str:
    for pat in (_SUMMARY_RE, _DEFINITION_RE, _OBJECTIVE_RE):
        m = pat.search(html)
        if m:
            cleaned = _clean(m.group(1))
            if cleaned:
                return cleaned[:240]
    return ""


# ── storage ──────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _artifact_dir(artifact_id: str) -> Path:
    # Defensive: refuse anything that isn't a plain art_<hex> id. This is the
    # bottleneck every public path passes through, so traversal is blocked here
    # rather than at each call site.
    if not re.fullmatch(r"art_[a-f0-9]{12}", artifact_id):
        raise ValueError(f"invalid artifact id: {artifact_id!r}")
    return ARTIFACTS_DIR / artifact_id


def save(
    subtype: str,
    prompt: str,
    html: str,
    model: str,
    session: str | None = None,
) -> str:
    """Persist an artifact to disk and return its id.

    Also appends an `artifact_saved` journal entry so the gallery id is
    cross-referenced from the build journal without duplicating the HTML
    body into journal.jsonl."""
    _ensure_dir()
    artifact_id = _new_id()
    d = _artifact_dir(artifact_id)
    d.mkdir(parents=True, exist_ok=False)

    title = _extract_title(html)
    summary = _extract_summary(html)

    meta = {
        "id": artifact_id,
        "ts": _now(),
        "subtype": subtype,
        "prompt": prompt,
        "model": model,
        "session": session,
        "title": title,
        "summary": summary,
        "bytes": len(html.encode("utf-8")),
    }

    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (d / "index.html").write_text(html, encoding="utf-8")

    sc.journal_append(
        "artifact_saved",
        artifact_id=artifact_id,
        subtype=subtype,
        title=title,
        session=session,
    )
    return artifact_id


def _forgotten_artifact_ids() -> set[str]:
    """Return ids tombstoned via scatter_core.forget().

    scatter_core writes journal_forget entries with target_id=<id>; we reuse
    that single forget mechanism rather than inventing a gallery-local one.
    We go through `_forgotten_ids` (the same helper journal_read uses) because
    journal_read itself hides the tombstone entries from callers."""
    all_forgotten = sc._forgotten_ids(sc.JOURNAL)
    return {tid for tid in all_forgotten if tid.startswith("art_")}


def _read_meta(artifact_id: str) -> dict | None:
    try:
        d = _artifact_dir(artifact_id)
    except ValueError:
        return None
    meta_path = d / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def listing(limit: int = 100) -> list[dict]:
    """List artifacts newest-first, tombstones filtered out.

    Returns meta dicts only — the html body stays on disk until read()."""
    if not ARTIFACTS_DIR.exists():
        return []
    forgotten = _forgotten_artifact_ids()
    metas: list[dict] = []
    for d in ARTIFACTS_DIR.iterdir():
        if not d.is_dir():
            continue
        aid = d.name
        if aid in forgotten:
            continue
        meta = _read_meta(aid)
        if meta is None:
            continue
        metas.append(meta)
    metas.sort(key=lambda m: m.get("ts", ""), reverse=True)
    if limit > 0:
        metas = metas[:limit]
    return metas


def read(artifact_id: str) -> tuple[dict, str] | None:
    """Return (meta, html) for an artifact, or None if missing/forgotten."""
    if artifact_id in _forgotten_artifact_ids():
        return None
    meta = _read_meta(artifact_id)
    if meta is None:
        return None
    try:
        html = (_artifact_dir(artifact_id) / "index.html").read_text(
            encoding="utf-8"
        )
    except (OSError, ValueError):
        return None
    return meta, html
