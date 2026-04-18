#!/usr/bin/env python3
"""
scatter-backup restore — extract an encrypted snapshot.

Reverse of backup.py. Takes an encrypted .tar.gz.enc file, decrypts it
via openssl (same AES-256-CBC + PBKDF2 params), untars it to a chosen
directory. Passphrase prompted (or --passphrase-file / env).

By default restores to a *staging* directory (~/scatter-restore-<ts>/)
so the user can inspect before overwriting anything. --into <dir>
overrides the destination.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


def _get_passphrase(args) -> str:
    if args.passphrase_file:
        return Path(args.passphrase_file).read_text().splitlines()[0]
    env = os.environ.get("SCATTER_BACKUP_PASSPHRASE", "")
    if env:
        return env
    return getpass.getpass("backup passphrase: ")


def restore(args) -> int:
    src = Path(args.snapshot).expanduser()
    if not src.is_file():
        print(f"snapshot not found: {src}", file=sys.stderr)
        return 2

    # Default: staging dir in home
    if args.into:
        dest = Path(args.into).expanduser()
    else:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = Path.home() / f"scatter-restore-{ts}"
    dest.mkdir(parents=True, exist_ok=True)

    passphrase = _get_passphrase(args)

    tmp_tar = dest / "._scatter_restore.tar.gz"

    sc.journal_append("restore_started", source=str(src), destination=str(dest))

    try:
        # Decrypt
        dec_cmd = [
            "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-d",
            "-in", str(src),
            "-out", str(tmp_tar),
            "-pass", "stdin",
        ]
        result = subprocess.run(dec_cmd, input=passphrase.encode(), capture_output=True)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:300]
            raise RuntimeError(f"decryption failed (wrong passphrase?): {err}")

        # Untar
        tar_cmd = ["tar", "--extract", "--gzip", "--file", str(tmp_tar), "-C", str(dest)]
        result = subprocess.run(tar_cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"untar failed: {result.stderr.decode(errors='replace')[:300]}")

        tmp_tar.unlink(missing_ok=True)
        sc.journal_append("restore_complete", destination=str(dest))
        print(f"  ✓ restored to {dest}")
        print(f"  ▸ inspect the contents, then move pieces into place as needed.")
        return 0
    except Exception as e:
        if tmp_tar.exists():
            tmp_tar.unlink()
        sc.journal_append("restore_failed", error=str(e)[:300])
        print(f"  ✗ restore failed: {e}", file=sys.stderr)
        return 1


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scatter-backup restore")
    parser.add_argument("snapshot", help="path to a scatter-backup-*.tar.gz.enc file")
    parser.add_argument("--into", default=None, help="destination directory (default: ~/scatter-restore-<ts>/)")
    parser.add_argument("--passphrase-file", default=None)
    args = parser.parse_args(argv)
    return restore(args)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
