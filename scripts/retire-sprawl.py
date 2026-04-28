#!/usr/bin/env python3
"""
retire-sprawl — audit and archive phase-one scaffolding.

Reads the prototype-synthesis policy (docs/PROTOTYPE_SYNTHESIS.md) and
applies it to the filesystem: tells you which directories carry forward,
which should be archived, and which are load-bearing to keep intact.

This script is conservative:
  - Default: dry-run. Prints the plan. Touches nothing.
  - --apply: creates compressed source-only archives under
    ~/.scatter/archive/YYYYMMDD/ for every directory classified as
    ARCHIVE. Excludes node_modules, .next, .git, __pycache__ to keep
    archive sizes honest (source preserved, not 700MB of dependencies).
  - Never calls `rm`. After a successful archive, the original is left
    in place. The user runs `rm -rf <original>` themselves when they
    verify the archive is readable. That separation is the safety.

Classifications:
  KEEP     — part of the distilled system; leave alone
  ARCHIVE  — superseded by phase-two; source gets snapshotted, original
             left for user to remove
  DEFER    — decision genuinely not made yet; stays in place, flagged

Journal: every archive write appends a retire_archived entry with the
source path, archive path, size, and reason.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


# (path, classification, reason)
POLICY: list[tuple[str, str, str]] = [
    # --- scatter-system internal cleanup ---
    (
        "~/scatter-system/scatter-data",
        "ARCHIVE",
        "phase-one data-management prototype; superseded by scatter-backup",
    ),
    (
        "~/scatter-system/scatter-journal",
        "ARCHIVE",
        "phase-one journal prototype; merged into Scatter GUI (task #5)",
    ),
    (
        "~/scatter-system/scatter/teaching.py",
        "ARCHIVE",
        "phase-one teaching engine; out of scope for distilled alignment artifact",
    ),
    (
        "~/scatter-system/scatter-code",
        "KEEP",
        "part of distilled set (local coding agent, referenced in README)",
    ),
    (
        "~/scatter-system/scatter-ops",
        "KEEP",
        "self-healing ops daemon still running; decision about future role deferred",
    ),

    # --- prototype apps we chose to wrap (keep source, prototypes are launchable) ---
    (
        "~/projects/scatter/scatter-draft",
        "KEEP",
        "wrapped as Scatter Draft (prototype); running dev-server app",
    ),
    (
        "~/projects/scatter/scatter-film",
        "KEEP",
        "wrapped as Scatter Film (prototype); script-aware coverage analysis lives here",
    ),
    (
        "~/projects/scatter/scatter-music",
        "KEEP",
        "wrapped as Scatter Sound (prototype)",
    ),
    (
        "~/projects/scatter/scatter-write",
        "KEEP",
        "wrapped as Scatter Write (prototype)",
    ),

    # --- prototype-era infrastructure superseded by scatter_core ---
    (
        "~/projects/scatter/hzl-cli",
        "ARCHIVE",
        "superseded by bin/scatter and scatter_core CLI",
    ),
    (
        "~/projects/scatter/hzl-core",
        "ARCHIVE",
        "superseded by scatter_core.py substrate",
    ),
    (
        "~/projects/scatter/hzl-cluster",
        "ARCHIVE",
        "distributed-routing prototype; out of scope for current thesis",
    ),
    (
        "~/projects/scatter/scatter-studio-os",
        "KEEP",
        "wrapped as Scatter Studio (prototype)",
    ),

    # --- earliest prototype-era (retired names) ---
    (
        "~/projects/scatter/Hazel",
        "ARCHIVE",
        "earliest prototype-era voice stack (codename retired); carries nothing forward",
    ),
    (
        "~/projects/scatter/hazel-os",
        "ARCHIVE",
        "earliest prototype-era OS shell; carries nothing forward",
    ),

    # --- genuinely-deferred ---
    (
        "~/projects/scatter/hzl-academy",
        "DEFER",
        "Scatter Schools course prototype; future work, not distilled yet",
    ),
    (
        "~/projects/scatter/hzl-academy-demo",
        "DEFER",
        "Scatter Schools demo; paired with academy worktrees",
    ),
    (
        "~/projects/scatter/HZL Academy (D-drive)",
        "DEFER",
        "Scatter Schools archive from another drive; leave until Schools revisit",
    ),
    (
        "~/projects/scatter/hzl-game",
        "DEFER",
        "game prototype; out of current distilled set, decision not made",
    ),
    (
        "~/projects/scatter/scatter-stream",
        "KEEP",
        "wrapped as Scatter Stream (prototype)",
    ),
]

EXCLUDE_PATTERNS = ["node_modules", ".next", ".git", "__pycache__", "dist", "build", ".turbo"]


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, dirs, files in os.walk(path):
        # prune exclusions so we don't walk through node_modules
        dirs[:] = [d for d in dirs if d not in EXCLUDE_PATTERNS]
        for f in files:
            try:
                total += Path(root, f).stat().st_size
            except OSError:
                pass
    return total


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}TB"


def _color(kind: str) -> str:
    return {
        "KEEP": "\033[0;32m",      # green
        "ARCHIVE": "\033[0;33m",   # yellow
        "DEFER": "\033[0;36m",     # cyan
    }.get(kind, "")


def print_plan() -> list[tuple[Path, str, str, int]]:
    """Print the classification table. Return the list of items found."""
    found = []
    print()
    print(f"  {'STATUS':<8} {'SIZE':>10}  PATH")
    print(f"  {'------':<8} {'-----':>10}  ----")
    for path_str, kind, reason in POLICY:
        p = Path(os.path.expanduser(path_str))
        if not p.exists():
            continue
        size = _size(p)
        col = _color(kind)
        print(f"  {col}{kind:<8}\033[0m {_fmt_size(size):>10}  {path_str}")
        print(f"           {reason}")
        found.append((p, kind, reason, size))
    return found


def archive(path: Path, reason: str, dest_root: Path, dry: bool) -> Optional[Path]:
    """Create a source-only tar.gz of `path` under dest_root. Return the archive path."""
    dest_root.mkdir(parents=True, exist_ok=True)
    archive_name = f"{path.name}.tar.gz".replace(" ", "_")
    archive_path = dest_root / archive_name
    if archive_path.exists():
        # Idempotent: already archived, report and skip
        return archive_path
    if dry:
        return None
    cmd = ["tar", "--create", "--gzip", "--file", str(archive_path)]
    for pat in EXCLUDE_PATTERNS:
        cmd += ["--exclude", pat]
    cmd += ["-C", str(path.parent), path.name]
    result = subprocess.run(cmd, capture_output=True)
    # tar exit 1 is file-changed-during-read (tolerable for this use case)
    if result.returncode not in (0, 1) or not archive_path.exists():
        if archive_path.exists():
            archive_path.unlink()
        stderr = result.stderr.decode(errors="replace")[:200]
        raise RuntimeError(f"tar failed on {path.name}: {stderr}")
    sc.journal_append(
        "retire_archived",
        source=str(path),
        archive=str(archive_path),
        size_bytes=archive_path.stat().st_size,
        reason=reason,
    )
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="retire-sprawl", description=__doc__.splitlines()[1])
    parser.add_argument("--apply", action="store_true", help="actually create archives (default: dry-run)")
    args = parser.parse_args()

    print(f"\033[1mScatter sprawl retirement\033[0m")
    print(f"\033[2mPolicy source: docs/PROTOTYPE_SYNTHESIS.md\033[0m")

    found = print_plan()
    print()

    to_archive = [x for x in found if x[1] == "ARCHIVE"]
    archived_total = sum(x[3] for x in to_archive)

    if not to_archive:
        print("  nothing to archive.")
        return 0

    print(f"  {len(to_archive)} director{'y' if len(to_archive) == 1 else 'ies'} classified ARCHIVE "
          f"(source-only total: {_fmt_size(archived_total)})")

    if not args.apply:
        print()
        print("  \033[2m[dry-run] — pass --apply to create the archives\033[0m")
        print("  \033[2m          (originals are NEVER deleted; run `rm -rf <original>` yourself after you verify)\033[0m")
        return 0

    dest_root = Path.home() / ".scatter" / "archive" / datetime.datetime.now().strftime("%Y%m%d")

    print()
    print(f"  Writing archives to {dest_root}:")
    errs = 0
    for path, kind, reason, _size_bytes in to_archive:
        try:
            ap = archive(path, reason, dest_root, dry=False)
            if ap:
                asize = ap.stat().st_size
                print(f"    \033[0;32m✓\033[0m {path.name} → {ap.name} ({_fmt_size(asize)})")
        except Exception as e:
            print(f"    \033[0;31m✗\033[0m {path.name}: {e}", file=sys.stderr)
            errs += 1

    print()
    if errs:
        print(f"  \033[0;31m{errs} archive(s) failed\033[0m")
        return 1
    print(f"  \033[0;32mall archives created.\033[0m")
    print(f"  \033[2mVerify each archive is readable, then remove the original directory:")
    print(f"    for d in <paths above>; do rm -rf \"$d\"; done\033[0m")
    print(f"  \033[2m(not doing it automatically — this is destructive and deserves your hands)\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
