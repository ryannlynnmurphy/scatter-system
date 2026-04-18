#!/usr/bin/env python3
"""
scatter_core — the substrate.

One module. Every Scatter app writes legibility here and reads it back.
No abstraction before 3 call sites justify it. No external dependencies.

Architecture: ~/.scatter/ is the single source of truth.
- journal.jsonl  — append-only stream of every build, decision, event
- audit.jsonl    — append-only stream of every external API call (researcher profile only)
- watts.jsonl    — append-only energy timeseries
- sessions/      — per-session live state
- config.json    — profile (researcher/learner) + API keys (gitignored)
- dialectical/   — saved thesis/antithesis/synthesis exchanges

Append-only is honesty about history. `forget(id)` writes a tombstone.
Filtered reads skip tombstoned entries. Physical garbage collection is
a separate, auditable step.

Threat model: defends against accidental leakage, distracted developer
drift, and user curiosity. Does NOT defend against a rooted adversary
or forensic recovery. State this loudly in the thesis.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional


ROOT = Path(os.environ.get("SCATTER_ROOT", os.path.expanduser("~/.scatter")))

JOURNAL = ROOT / "journal.jsonl"
AUDIT = ROOT / "audit.jsonl"
WATTS = ROOT / "watts.jsonl"
SESSIONS_DIR = ROOT / "sessions"
DIALECTICAL_DIR = ROOT / "dialectical"
CONFIG_FILE = ROOT / "config.json"


# ---------- internals ----------

def _ensure_root() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    DIALECTICAL_DIR.mkdir(exist_ok=True)
    for f in (JOURNAL, AUDIT, WATTS):
        if not f.exists():
            f.touch()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _append(path: Path, entry: dict) -> None:
    _ensure_root()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _iter(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ---------- journal (every build, decision, event) ----------

def journal_append(kind: str, **fields: Any) -> str:
    entry_id = _new_id("j")
    entry = {"id": entry_id, "ts": _now(), "kind": kind, **fields}
    _append(JOURNAL, entry)
    return entry_id


def journal_read(
    kind: Optional[str] = None,
    limit: Optional[int] = None,
    include_forgotten: bool = False,
) -> list[dict]:
    forgotten_ids = set() if include_forgotten else _forgotten_ids(JOURNAL)
    entries = [
        e for e in _iter(JOURNAL)
        if (kind is None or e.get("kind") == kind)
        and e.get("kind") != "journal_forget"
        and e.get("id") not in forgotten_ids
    ]
    if limit is not None:
        entries = entries[-limit:]
    return entries


# ---------- audit (every outbound call — researcher profile only) ----------

def audit_begin(service: str, endpoint: str, payload_summary: str) -> str:
    audit_id = _new_id("a")
    _append(AUDIT, {
        "id": audit_id,
        "ts": _now(),
        "phase": "begin",
        "service": service,
        "endpoint": endpoint,
        "payload_summary": payload_summary,
    })
    return audit_id


def audit_commit(
    audit_id: str,
    response_summary: str,
    bytes_out: int,
    bytes_in: int,
    watts_est: float,
) -> None:
    _append(AUDIT, {
        "id": audit_id,
        "ts": _now(),
        "phase": "commit",
        "response_summary": response_summary,
        "bytes_out": bytes_out,
        "bytes_in": bytes_in,
        "watts_est": watts_est,
    })


def audit_fail(audit_id: str, error: str) -> None:
    _append(AUDIT, {
        "id": audit_id,
        "ts": _now(),
        "phase": "fail",
        "error": error,
    })


def audit_read(limit: Optional[int] = None, include_forgotten: bool = False) -> list[dict]:
    forgotten_ids = set() if include_forgotten else _forgotten_ids(AUDIT)
    entries = [
        e for e in _iter(AUDIT)
        if e.get("phase") != "forget" and e.get("id") not in forgotten_ids
    ]
    if limit is not None:
        entries = entries[-limit:]
    return entries


# ---------- watts (energy accounting) ----------

def watts_log(source: str, joules: float, duration_s: float) -> None:
    _append(WATTS, {
        "ts": _now(),
        "source": source,
        "joules": joules,
        "duration_s": duration_s,
    })


def watts_total(since_iso: Optional[str] = None) -> float:
    total = 0.0
    for e in _iter(WATTS):
        if since_iso is None or e.get("ts", "") >= since_iso:
            total += float(e.get("joules", 0))
    return total


# ---------- forget (local revocability) ----------

def forget(target_id: str, reason: str = "user_request") -> None:
    """Append a tombstone. Filtered reads skip the target.

    Local revocability only. Upstream retention is recorded in the original
    audit entry (see audit_begin: entries record service/endpoint so the user
    can see whose retention policies apply). Physical deletion is a separate,
    auditable GC pass (not yet built)."""
    if target_id.startswith("a_"):
        _append(AUDIT, {
            "id": _new_id("af"),
            "ts": _now(),
            "phase": "forget",
            "target_id": target_id,
            "reason": reason,
        })
    else:
        _append(JOURNAL, {
            "id": _new_id("jf"),
            "ts": _now(),
            "kind": "journal_forget",
            "target_id": target_id,
            "reason": reason,
        })


def _forgotten_ids(path: Path) -> set[str]:
    out: set[str] = set()
    for e in _iter(path):
        if e.get("kind") == "journal_forget" or e.get("phase") == "forget":
            tid = e.get("target_id")
            if tid:
                out.add(tid)
    return out


# ---------- sessions ----------

def session_write(session_id: str, state: dict) -> None:
    _ensure_root()
    path = SESSIONS_DIR / f"{session_id}.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def session_read(session_id: str) -> Optional[dict]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def session_delete(session_id: str) -> bool:
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
        journal_append("session_deleted", session_id=session_id)
        return True
    return False


# ---------- config (profile + API keys) ----------

DEFAULT_CONFIG = {
    "profile": "researcher",
    "apis": {},
    "models": {"build": "qwen2.5-coder:7b", "fast": "llama3.2:3b"},
}


def config_read() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def config_write(cfg: dict) -> None:
    _ensure_root()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def profile() -> str:
    return config_read().get("profile", "researcher")


VALID_PROFILES = ("researcher", "learner")


def set_profile(new_profile: str) -> None:
    """Set the installation profile. Two values only: researcher | learner.

    Legibility: every profile change is journaled so the history of the
    machine's identity is visible. Revocability: any future set_profile
    call is itself appended, and `scatter forget <journal_id>` can tombstone
    mistaken changes (though the underlying config is mutated; the journal
    entry is the record)."""
    if new_profile not in VALID_PROFILES:
        raise ValueError(f"profile must be one of {VALID_PROFILES}, got {new_profile!r}")
    cfg = config_read()
    old = cfg.get("profile", "researcher")
    cfg["profile"] = new_profile
    config_write(cfg)
    journal_append("profile_changed", old=old, new=new_profile)


class ProfileMismatch(Exception):
    """Raised when code tries to call an external service under the learner profile."""


def assert_researcher(action: str = "external call") -> None:
    """Gate for code paths that require the researcher profile.

    Call this at the top of any function that reaches out to an external
    service. The learner profile refuses, loudly. Not a fallback, a refusal."""
    p = profile()
    if p != "researcher":
        raise ProfileMismatch(f"{action} requires researcher profile (current: {p})")


# ---------- dialectical log (thesis/antithesis/synthesis exchanges) ----------

def dialectical_save(title: str, thesis: str, antithesis: str, synthesis: str) -> str:
    _ensure_root()
    entry_id = _new_id("d")
    path = DIALECTICAL_DIR / f"{entry_id}.json"
    entry = {
        "id": entry_id,
        "ts": _now(),
        "title": title,
        "thesis": thesis,
        "antithesis": antithesis,
        "synthesis": synthesis,
    }
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    journal_append("dialectical_saved", title=title, path=str(path), entry_id=entry_id)
    return entry_id


def dialectical_read_all() -> list[dict]:
    """Return every dialectical entry, oldest first."""
    if not DIALECTICAL_DIR.exists():
        return []
    entries = []
    for p in sorted(DIALECTICAL_DIR.glob("*.json")):
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    entries.sort(key=lambda e: e.get("ts", ""))
    return entries


def dialectical_export_markdown() -> str:
    """Render every saved dialectical exchange as markdown.

    The intended use is thesis-appendix publication: each exchange with
    thesis / antithesis / synthesis visible, and a "which side won"
    annotation when the synthesis dissents from the original thesis."""
    entries = dialectical_read_all()
    if not entries:
        return "# Scatter Dialectical Log\n\n_No entries yet._\n"

    lines = [
        "# Scatter Dialectical Log",
        "",
        "_Every design decision in the Scatter thesis was subjected to the Method:",
        "thesis → antithesis → synthesis. This document publishes the record,",
        "including exchanges where the synthesis rejected the original thesis._",
        "",
        f"_Total exchanges: {len(entries)}_",
        "",
        "---",
        "",
    ]
    for i, e in enumerate(entries, 1):
        title = e.get("title", "Untitled")
        ts = e.get("ts", "").split("T")[0]
        lines.append(f"## {i}. {title}")
        lines.append(f"_{ts} · id {e.get('id', '?')}_")
        lines.append("")
        lines.append("**Thesis**")
        lines.append("")
        lines.append(e.get("thesis", "_(no thesis recorded)_"))
        lines.append("")
        lines.append("**Antithesis**")
        lines.append("")
        lines.append(e.get("antithesis", "_(no antithesis recorded)_"))
        lines.append("")
        lines.append("**Synthesis**")
        lines.append("")
        lines.append(e.get("synthesis", "_(no synthesis recorded)_"))
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---------- CLI ----------

_HELP = """scatter_core — inspect and manage the Scatter substrate.

Usage:
  python3 scatter_core.py init
  python3 scatter_core.py profile [--set researcher|learner]
  python3 scatter_core.py journal [--kind KIND] [--limit N]
  python3 scatter_core.py audit [--limit N]
  python3 scatter_core.py watts
  python3 scatter_core.py forget <id> [--reason R]
  python3 scatter_core.py dialectical-export [--out FILE]
"""


def _cli(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(_HELP)
        return 0

    cmd = argv[1]

    if cmd == "init":
        _ensure_root()
        if not CONFIG_FILE.exists():
            config_write(DEFAULT_CONFIG)
        print(f"scatter substrate at {ROOT}")
        print(f"profile: {profile()}")
        return 0

    if cmd == "profile":
        if "--set" in argv:
            i = argv.index("--set")
            if i + 1 < len(argv):
                try:
                    set_profile(argv[i + 1])
                    print(f"profile set: {profile()}")
                    return 0
                except ValueError as e:
                    print(str(e), file=sys.stderr)
                    return 2
            print("--set requires a value", file=sys.stderr)
            return 2
        print(profile())
        return 0

    if cmd == "journal":
        kind = None
        limit = 20
        i = 2
        while i < len(argv):
            if argv[i] == "--kind" and i + 1 < len(argv):
                kind = argv[i + 1]; i += 2
            elif argv[i] == "--limit" and i + 1 < len(argv):
                limit = int(argv[i + 1]); i += 2
            else:
                i += 1
        for e in journal_read(kind=kind, limit=limit):
            print(json.dumps(e, ensure_ascii=False))
        return 0

    if cmd == "audit":
        limit = 20
        if "--limit" in argv:
            i = argv.index("--limit")
            if i + 1 < len(argv):
                limit = int(argv[i + 1])
        for e in audit_read(limit=limit):
            print(json.dumps(e, ensure_ascii=False))
        return 0

    if cmd == "watts":
        total = watts_total()
        print(f"total joules logged: {total:.2f}")
        return 0

    if cmd == "forget":
        if len(argv) < 3:
            print("usage: scatter_core forget <id> [--reason R]", file=sys.stderr)
            return 2
        target = argv[2]
        reason = "user_request"
        if "--reason" in argv:
            i = argv.index("--reason")
            if i + 1 < len(argv):
                reason = argv[i + 1]
        forget(target, reason=reason)
        print(f"tombstoned {target}")
        return 0

    if cmd == "dialectical-export":
        md = dialectical_export_markdown()
        out = None
        if "--out" in argv:
            i = argv.index("--out")
            if i + 1 < len(argv):
                out = argv[i + 1]
        if out:
            Path(out).write_text(md, encoding="utf-8")
            print(f"wrote {out}")
        else:
            print(md)
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
