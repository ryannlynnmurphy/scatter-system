#!/usr/bin/env python3
"""
scatter-backup — encrypted snapshot of the Scatter substrate.

Sovereignty dies on drive failure unless backup is part of the architecture.
This tool is that part.

Snapshots these locations (configurable in ~/.scatter/config.json → backup):
  - ~/.scatter/              (the substrate — journal, audit, watts, dialectical, sessions, config)
  - ~/scatter-system/        (the code — though this is also in git; backup covers local-only state)
  - any paths listed in config.backup.include (e.g. ~/Documents/scatter-workspace/)

Encryption: AES-256-CBC with PBKDF2, via `openssl enc` subprocess. No
Python cryptography dependency. The passphrase is read from:
  1. --passphrase-file <path>     (a file with the passphrase on the first line)
  2. SCATTER_BACKUP_PASSPHRASE    (environment variable)
  3. interactively prompted (getpass)
The passphrase is NEVER written to disk or the journal.

Destination: the first of these that exists and is writable:
  1. --dest <path>                (command-line override)
  2. config.backup.destination    (if set)
  3. ~/scatter-backups/           (fallback, honest default)

Output: scatter-backup-YYYYMMDD-HHMMSS.tar.gz.enc

Rotation: keeps the last N (default 10, config.backup.keep) and removes
older snapshots. If rotation is 0, nothing is ever deleted.

Journal: every run appends backup_started + backup_complete / backup_failed.
The audit log is NOT touched — nothing left the machine.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


DEFAULT_INCLUDES = [
    str(Path.home() / ".scatter"),
    str(Path.home() / "scatter-system"),
]

DEFAULT_EXCLUDES = [
    "node_modules",
    ".next",
    "__pycache__",
    ".git",
    "scatter-backups",          # never recursively back up our own backups
]

DEFAULT_DEST = str(Path.home() / "scatter-backups")
DEFAULT_KEEP = 10


def _get_passphrase(args) -> str:
    if args.passphrase_file:
        return Path(args.passphrase_file).read_text().splitlines()[0]
    env = os.environ.get("SCATTER_BACKUP_PASSPHRASE", "")
    if env:
        return env
    pw1 = getpass.getpass("backup passphrase: ")
    pw2 = getpass.getpass("confirm passphrase: ")
    if pw1 != pw2:
        print("passphrases do not match", file=sys.stderr)
        sys.exit(2)
    if len(pw1) < 8:
        print("passphrase too short (need at least 8 chars)", file=sys.stderr)
        sys.exit(2)
    return pw1


def _config_backup() -> dict:
    return sc.config_read().get("backup", {})


def _resolve_includes() -> list[str]:
    cfg = _config_backup()
    custom = cfg.get("include", [])
    if custom:
        return [os.path.expanduser(p) for p in custom]
    return DEFAULT_INCLUDES


def _resolve_excludes() -> list[str]:
    cfg = _config_backup()
    return DEFAULT_EXCLUDES + cfg.get("exclude", [])


def _resolve_dest(cli_dest: Optional[str]) -> Path:
    if cli_dest:
        p = Path(os.path.expanduser(cli_dest))
    else:
        cfg_dest = _config_backup().get("destination")
        if cfg_dest:
            p = Path(os.path.expanduser(cfg_dest))
        else:
            p = Path(DEFAULT_DEST)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_keep() -> int:
    return int(_config_backup().get("keep", DEFAULT_KEEP))


def _build_tar_command(includes: list[str], excludes: list[str], out_path: Path) -> list[str]:
    cmd = ["tar", "--create", "--gzip", "--file", str(out_path)]
    for pattern in excludes:
        cmd += ["--exclude", pattern]
    for path in includes:
        cmd.append(path)
    return cmd


def backup(args) -> int:
    includes = _resolve_includes()
    # Filter to paths that actually exist
    includes = [p for p in includes if Path(p).exists()]
    if not includes:
        print("no paths to back up (nothing in config.backup.include exists)", file=sys.stderr)
        return 2

    excludes = _resolve_excludes()
    dest = _resolve_dest(args.dest)
    keep = _resolve_keep()

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_name = f"scatter-backup-{timestamp}.tar.gz"
    tar_path = dest / base_name
    enc_path = dest / f"{base_name}.enc"

    sc.journal_append(
        "backup_started",
        destination=str(dest),
        includes=includes,
        excludes=excludes,
    )

    passphrase = _get_passphrase(args)

    try:
        # Step 1: tar + gzip
        tar_cmd = _build_tar_command(includes, excludes, tar_path)
        if args.verbose:
            print(f"  ▸ tar: {' '.join(tar_cmd)}")
        result = subprocess.run(tar_cmd, capture_output=True)
        # tar returns nonzero on 'file changed as we read it' warnings; tolerate
        # non-fatal warnings (exit 1 with something in the archive is ok).
        if result.returncode not in (0, 1):
            raise RuntimeError(f"tar failed: {result.stderr.decode(errors='replace')[:300]}")

        if not tar_path.exists() or tar_path.stat().st_size == 0:
            raise RuntimeError("tar produced no output")

        # Step 2: encrypt with openssl
        enc_cmd = [
            "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt",
            "-in", str(tar_path),
            "-out", str(enc_path),
            "-pass", "stdin",
        ]
        if args.verbose:
            print(f"  ▸ openssl: {' '.join(enc_cmd[:6])} ... [passphrase via stdin]")
        result = subprocess.run(
            enc_cmd,
            input=passphrase.encode(),
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"openssl failed: {result.stderr.decode(errors='replace')[:300]}")

        # Step 3: remove the intermediate unencrypted tar
        tar_path.unlink()

        size_mb = enc_path.stat().st_size / 1_000_000
        print(f"  ✓ {enc_path.name} ({size_mb:.1f} MB)")

        # Step 4: rotation
        if keep > 0:
            snapshots = sorted(dest.glob("scatter-backup-*.tar.gz.enc"))
            for old in snapshots[:-keep]:
                old.unlink()
                if args.verbose:
                    print(f"  ▸ rotated: removed {old.name}")

        sc.journal_append(
            "backup_complete",
            path=str(enc_path),
            size_bytes=enc_path.stat().st_size,
        )
        return 0
    except Exception as e:
        # Clean up partial artifacts
        if tar_path.exists():
            tar_path.unlink()
        if enc_path.exists():
            enc_path.unlink()
        sc.journal_append("backup_failed", error=str(e)[:300])
        print(f"  ✗ backup failed: {e}", file=sys.stderr)
        return 1


def list_snapshots(args) -> int:
    dest = _resolve_dest(args.dest)
    snapshots = sorted(dest.glob("scatter-backup-*.tar.gz.enc"))
    if not snapshots:
        print(f"no snapshots in {dest}")
        return 0
    print(f"{'SNAPSHOT':<40} {'SIZE':>10} {'MTIME'}")
    for s in snapshots:
        size_mb = s.stat().st_size / 1_000_000
        mtime = datetime.datetime.fromtimestamp(s.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"{s.name:<40} {size_mb:>8.1f}MB  {mtime}")
    return 0


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scatter-backup")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_run = sub.add_parser("run", help="create an encrypted snapshot now")
    p_run.add_argument("--dest", default=None, help="override destination path")
    p_run.add_argument("--passphrase-file", default=None)
    p_run.add_argument("--verbose", action="store_true")

    p_list = sub.add_parser("list", help="list existing snapshots")
    p_list.add_argument("--dest", default=None)

    args = parser.parse_args(argv)

    if args.verb == "run":
        return backup(args)
    if args.verb == "list":
        return list_snapshots(args)
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
