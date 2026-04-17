#!/usr/bin/env python3
"""
Scatter Data v0.2.0 — Local data management layer.

Handles the boring critical stuff: backups, integrity checks, schema migrations,
log rotation, and storage monitoring. Works with SQLite, PostgreSQL, filesystem
stores. AI-assisted when it encounters something it can't auto-resolve.

This is the janitor that keeps the lights on. If Scatter Code is the builder
and Scatter Ops is the immune system, Scatter Data is the plumbing.
"""

import json
import os
import subprocess
import sys
import shutil
import hashlib
import datetime
import glob as globlib
from pathlib import Path
from urllib.request import Request, urlopen

# ── Config ──────────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "deepseek-coder-v2:16b")
SCATTER_HOME = os.environ.get("SCATTER_HOME", os.path.expanduser("~/scatter-system"))
DATA_DIR = os.path.expanduser("~/.scatter/data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

def c(color, text):
    return f"{color}{text}{RESET}"


# ── Manifest ────────────────────────────────────────────────────────────────
# Tracks what data sources exist, when they were last backed up, checksums.

def load_manifest():
    if os.path.isfile(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"sources": [], "last_backup": None, "version": "0.2.0"}


def save_manifest(manifest):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


# ── Discovery ──────────────────────────────────────────────────────────────
# Find databases and data stores on the system.

def discover_sqlite_dbs(search_paths=None):
    """Find SQLite databases."""
    paths = search_paths or [
        os.getcwd(),
        os.path.expanduser("~"),
        "/var/lib",
    ]
    found = []
    for base in paths:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            # Skip deep traversal of noisy dirs
            dirs[:] = [d for d in dirs if d not in (
                "node_modules", ".git", "__pycache__", ".cache", "Cache",
                "CachedData", ".local", "snap", ".mozilla"
            ) and not d.startswith(".")]
            # Don't go more than 4 levels deep
            depth = root.replace(base, "").count(os.sep)
            if depth > 4:
                dirs.clear()
                continue
            for f in files:
                if f.endswith((".db", ".sqlite", ".sqlite3")):
                    full = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full)
                        if size > 0:
                            found.append({"path": full, "size": size, "type": "sqlite"})
                    except OSError:
                        pass
    return found


def discover_postgres():
    """Check if PostgreSQL is running and list databases."""
    try:
        result = subprocess.run(
            ["psql", "-l", "-t", "-A"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "PGCONNECT_TIMEOUT": "3"},
        )
        if result.returncode != 0:
            return []
        dbs = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0].strip():
                name = parts[0].strip()
                if name not in ("template0", "template1", "postgres", ""):
                    dbs.append({"name": name, "type": "postgres"})
        return dbs
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


# ── Backup ──────────────────────────────────────────────────────────────────

def file_checksum(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_sqlite(db_path):
    """Backup a SQLite database using the .backup command for consistency."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    basename = os.path.basename(db_path)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{basename}.{timestamp}.bak"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    # Use sqlite3 .backup for a consistent copy (handles WAL mode properly)
    result = subprocess.run(
        ["sqlite3", db_path, f".backup '{backup_path}'"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        # Fallback: file copy
        try:
            shutil.copy2(db_path, backup_path)
        except Exception as e:
            return None, f"Backup failed: {e}"

    checksum = file_checksum(backup_path)
    size = os.path.getsize(backup_path)
    return {
        "path": backup_path,
        "source": db_path,
        "checksum": checksum,
        "size": size,
        "timestamp": timestamp,
    }, None


def backup_postgres(db_name):
    """Backup a PostgreSQL database using pg_dump."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{db_name}.{timestamp}.sql.gz"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    result = subprocess.run(
        f"pg_dump {db_name} | gzip > {backup_path}",
        shell=True, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return None, f"pg_dump failed: {result.stderr}"

    size = os.path.getsize(backup_path)
    return {
        "path": backup_path,
        "source": f"postgres:{db_name}",
        "size": size,
        "timestamp": timestamp,
    }, None


def backup_directory(dir_path, label=None):
    """Tar+gzip a directory."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    label = label or os.path.basename(dir_path.rstrip("/"))
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{label}.{timestamp}.tar.gz"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    result = subprocess.run(
        ["tar", "czf", backup_path, "-C", os.path.dirname(dir_path), os.path.basename(dir_path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return None, f"tar failed: {result.stderr}"

    size = os.path.getsize(backup_path)
    return {
        "path": backup_path,
        "source": dir_path,
        "size": size,
        "timestamp": timestamp,
    }, None


def run_backup_all():
    """Discover and backup everything."""
    manifest = load_manifest()
    results = []
    errors = []

    print(c(DIM, "  Discovering data sources..."))

    # SQLite databases in cwd
    sqlite_dbs = discover_sqlite_dbs([os.getcwd()])
    for db in sqlite_dbs:
        print(c(DIM, f"  Backing up {db['path']}..."))
        info, err = backup_sqlite(db["path"])
        if err:
            errors.append(err)
            print(c(RED, f"    FAILED: {err}"))
        else:
            results.append(info)
            size_mb = info["size"] / (1024 * 1024)
            print(c(GREEN, f"    OK ({size_mb:.1f}MB)"))

    # PostgreSQL
    pg_dbs = discover_postgres()
    for db in pg_dbs:
        print(c(DIM, f"  Backing up postgres:{db['name']}..."))
        info, err = backup_postgres(db["name"])
        if err:
            errors.append(err)
            print(c(RED, f"    FAILED: {err}"))
        else:
            results.append(info)
            size_mb = info["size"] / (1024 * 1024)
            print(c(GREEN, f"    OK ({size_mb:.1f}MB)"))

    # Scatter system config
    scatter_conf = os.path.expanduser("~/.scatter")
    if os.path.isdir(scatter_conf):
        print(c(DIM, f"  Backing up Scatter config..."))
        info, err = backup_directory(scatter_conf, "scatter-config")
        if err:
            errors.append(err)
        else:
            results.append(info)
            print(c(GREEN, f"    OK"))

    # Update manifest
    manifest["last_backup"] = datetime.datetime.now().isoformat()
    manifest["sources"] = [r.get("source", "") for r in results]
    save_manifest(manifest)

    return results, errors


# ── Integrity checks ───────────────────────────────────────────────────────

def check_sqlite_integrity(db_path):
    """Run PRAGMA integrity_check on a SQLite database."""
    try:
        result = subprocess.run(
            ["sqlite3", db_path, "PRAGMA integrity_check;"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if output == "ok":
            return True, "OK"
        return False, output
    except FileNotFoundError:
        return False, "sqlite3 not installed"
    except Exception as e:
        return False, str(e)


def run_integrity_check():
    """Check integrity of all discovered databases."""
    print(c(DIM, "  Checking database integrity...\n"))
    sqlite_dbs = discover_sqlite_dbs([os.getcwd()])
    all_ok = True

    for db in sqlite_dbs:
        ok, msg = check_sqlite_integrity(db["path"])
        if ok:
            print(c(GREEN, f"  [OK] {db['path']}"))
        else:
            print(c(RED, f"  [FAIL] {db['path']}: {msg}"))
            all_ok = False

    if not sqlite_dbs:
        print(c(DIM, "  No SQLite databases found in current directory."))

    return all_ok


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_old_backups(keep_days=30):
    """Remove backups older than keep_days."""
    if not os.path.isdir(BACKUP_DIR):
        return 0

    cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    removed = 0

    for fname in os.listdir(BACKUP_DIR):
        fpath = os.path.join(BACKUP_DIR, fname)
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                removed += 1
        except Exception:
            pass

    return removed


def show_backup_inventory():
    """List all backups with sizes and dates."""
    if not os.path.isdir(BACKUP_DIR):
        print(c(DIM, "  No backups yet."))
        return

    files = []
    total_size = 0
    for fname in sorted(os.listdir(BACKUP_DIR)):
        fpath = os.path.join(BACKUP_DIR, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            files.append((fname, size, mtime))
            total_size += size

    if not files:
        print(c(DIM, "  No backups yet."))
        return

    print(f"\n{BOLD}  Backup Inventory{RESET}")
    print(c(DIM, f"  Location: {BACKUP_DIR}\n"))

    for fname, size, mtime in files:
        size_str = f"{size / (1024*1024):.1f}MB" if size > 1024*1024 else f"{size/1024:.0f}KB"
        age = datetime.datetime.now() - mtime
        if age.days > 0:
            age_str = f"{age.days}d ago"
        else:
            age_str = f"{age.seconds // 3600}h ago"
        print(f"  {fname:<50} {size_str:>8}  {age_str}")

    total_str = f"{total_size / (1024*1024):.1f}MB" if total_size > 1024*1024 else f"{total_size/1024:.0f}KB"
    print(c(DIM, f"\n  {len(files)} backup(s), {total_str} total"))
    print()


# ── AI-assisted migration helper ───────────────────────────────────────────

def ai_migration_help(db_path, description):
    """Ask the AI to generate a migration for a schema change."""
    try:
        # Get current schema
        result = subprocess.run(
            ["sqlite3", db_path, ".schema"],
            capture_output=True, text=True, timeout=10,
        )
        schema = result.stdout.strip()
    except Exception:
        schema = "(couldn't read schema)"

    prompt = f"""Current SQLite schema for {os.path.basename(db_path)}:

{schema}

The user wants to: {description}

Generate a safe SQL migration. Include:
1. The ALTER/CREATE statements
2. A rollback plan
3. Any data migration needed

Output the SQL inside a ```sql block. Be conservative — don't drop data."""

    try:
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a database migration expert. Generate safe, reversible SQL migrations."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.1},
        }
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{OLLAMA_URL}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("message", {}).get("content", "No response.")
    except Exception as e:
        return f"AI unavailable: {e}"


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", ""):
        print(f"""
  {BOLD}Scatter Data{RESET} — local data management

  Usage:
    scatter data                  Show backup inventory
    scatter data --backup         Discover and backup all databases
    scatter data --check          Run integrity checks
    scatter data --cleanup        Remove backups older than 30 days
    scatter data --cleanup=7      Remove backups older than 7 days
    scatter data --discover       List discovered data sources
    scatter data --migrate DB "description"
                                  AI-assisted schema migration
    scatter data --version        Version
        """)
        return

    arg = sys.argv[1]

    if arg == "--version":
        print("Scatter Data v0.2.0")

    elif arg == "--backup":
        print(f"\n{BOLD}{CYAN}  Scatter Data — Backup{RESET}\n")
        results, errors = run_backup_all()
        print()
        if results:
            total = sum(r["size"] for r in results)
            print(c(GREEN, f"  {len(results)} backup(s) created ({total / (1024*1024):.1f}MB total)"))
        if errors:
            print(c(RED, f"  {len(errors)} error(s)"))
        print(c(DIM, f"  Location: {BACKUP_DIR}\n"))

    elif arg == "--check":
        print(f"\n{BOLD}{CYAN}  Scatter Data — Integrity Check{RESET}\n")
        ok = run_integrity_check()
        print()
        sys.exit(0 if ok else 1)

    elif arg.startswith("--cleanup"):
        days = 30
        if "=" in arg:
            days = int(arg.split("=")[1])
        removed = cleanup_old_backups(days)
        print(c(DIM if removed == 0 else GREEN,
                f"  Removed {removed} backup(s) older than {days} days."))

    elif arg == "--discover":
        print(f"\n{BOLD}  Data Sources{RESET}\n")
        sqlite_dbs = discover_sqlite_dbs([os.getcwd()])
        pg_dbs = discover_postgres()
        if sqlite_dbs:
            print(c(DIM, "  SQLite:"))
            for db in sqlite_dbs:
                size_str = f"{db['size'] / (1024*1024):.1f}MB" if db['size'] > 1024*1024 else f"{db['size']/1024:.0f}KB"
                print(f"    {db['path']}  ({size_str})")
        if pg_dbs:
            print(c(DIM, "  PostgreSQL:"))
            for db in pg_dbs:
                print(f"    {db['name']}")
        if not sqlite_dbs and not pg_dbs:
            print(c(DIM, "  No databases found in current directory."))
        print()

    elif arg == "--migrate":
        if len(sys.argv) < 4:
            print("  Usage: scatter data --migrate <db_path> \"description of change\"")
            sys.exit(1)
        db_path = sys.argv[2]
        description = " ".join(sys.argv[3:])
        print(c(DIM, f"  Generating migration for {db_path}...\n"))
        result = ai_migration_help(db_path, description)
        print(result)
        print()

    else:
        # Default: show inventory
        show_backup_inventory()


if __name__ == "__main__":
    main()
