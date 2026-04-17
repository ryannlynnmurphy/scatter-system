#!/usr/bin/env python3
"""
Scatter Watchdog — Process supervisor for off-grid operation.

This is the one process that must never die. It:
  1. Ensures Ollama stays running (the brain)
  2. Runs periodic health checks via Scatter Ops
  3. Runs periodic backups via Scatter Data
  4. Writes a heartbeat file so external monitors can verify it's alive

Design: single-threaded event loop. No threads, no async, no dependencies
beyond the Python stdlib. If this crashes, the system restarts it via
systemd/cron/init (configured during scatter install).
"""

import json
import os
import subprocess
import sys
import time
import datetime
from pathlib import Path

SCATTER_HOME = os.environ.get("SCATTER_HOME", os.path.expanduser("~/scatter-system"))
HEARTBEAT_PATH = os.path.expanduser("~/.scatter/heartbeat")
PID_PATH = os.path.expanduser("~/.scatter/watchdog.pid")
LOG_PATH = os.path.expanduser("~/.scatter/watchdog.log")
OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")

# ── Intervals (seconds) ────────────────────────────────────────────────────
HEALTH_CHECK_INTERVAL = 60       # Ops check every minute
BACKUP_INTERVAL = 3600 * 6      # Backup every 6 hours
HEARTBEAT_INTERVAL = 30          # Write heartbeat every 30s
OLLAMA_CHECK_INTERVAL = 15       # Check Ollama every 15s

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
        # Rotate log if > 1MB
        if os.path.getsize(LOG_PATH) > 1_000_000:
            os.rename(LOG_PATH, LOG_PATH + ".old")
    except Exception:
        pass


def write_heartbeat():
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            json.dump({
                "pid": os.getpid(),
                "timestamp": datetime.datetime.now().isoformat(),
                "status": "alive",
            }, f)
    except Exception:
        pass


def write_pid():
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))


def is_ollama_running():
    try:
        from urllib.request import Request, urlopen
        req = Request(f"{OLLAMA_URL}/api/tags")
        with urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def start_ollama():
    """Attempt to start Ollama."""
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=open(os.devnull, "w"),
            stderr=open(os.devnull, "w"),
        )
        time.sleep(3)
        return is_ollama_running()
    except FileNotFoundError:
        return False
    except Exception:
        return False


def run_health_check():
    """Run Scatter Ops in one-shot mode."""
    try:
        ops_path = os.path.join(SCATTER_HOME, "scatter-ops", "scatter_ops.py")
        result = subprocess.run(
            ["python3", ops_path, "--once"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Health check failed: {e}")
        return False


def run_backup():
    """Run Scatter Data backup."""
    try:
        data_path = os.path.join(SCATTER_HOME, "scatter-data", "scatter_data.py")
        result = subprocess.run(
            ["python3", data_path, "--backup"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            log("Backup completed successfully")
        else:
            log(f"Backup failed: {result.stderr[:200]}")
        return result.returncode == 0
    except Exception as e:
        log(f"Backup error: {e}")
        return False


def main_loop():
    log("Watchdog started")
    write_pid()

    last_health = 0
    last_backup = 0
    last_heartbeat = 0
    last_ollama_check = 0
    ollama_restart_count = 0

    while True:
        now = time.time()

        # Heartbeat
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            write_heartbeat()
            last_heartbeat = now

        # Ollama keepalive
        if now - last_ollama_check >= OLLAMA_CHECK_INTERVAL:
            if not is_ollama_running():
                if ollama_restart_count < 5:
                    log("Ollama down — attempting restart")
                    if start_ollama():
                        log("Ollama restarted")
                        ollama_restart_count = 0
                    else:
                        ollama_restart_count += 1
                        log(f"Ollama restart failed (attempt {ollama_restart_count}/5)")
                elif ollama_restart_count == 5:
                    log("Ollama restart limit reached — manual intervention needed")
                    ollama_restart_count += 1  # stop logging
            else:
                ollama_restart_count = 0
            last_ollama_check = now

        # Health check
        if now - last_health >= HEALTH_CHECK_INTERVAL:
            run_health_check()
            last_health = now

        # Periodic backup
        if now - last_backup >= BACKUP_INTERVAL:
            run_backup()
            last_backup = now

        time.sleep(5)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--version":
            print("Scatter Watchdog v0.2.0")
            return
        if sys.argv[1] == "--status":
            if os.path.isfile(HEARTBEAT_PATH):
                with open(HEARTBEAT_PATH) as f:
                    hb = json.load(f)
                ts = hb.get("timestamp", "unknown")
                pid = hb.get("pid", "?")
                # Check if pid is still running
                try:
                    os.kill(int(pid), 0)
                    print(f"  Watchdog: RUNNING (pid {pid}, last heartbeat {ts})")
                except (OSError, ValueError):
                    print(f"  Watchdog: DEAD (last seen {ts}, pid {pid} not running)")
            else:
                print("  Watchdog: NOT STARTED")
            return
        if sys.argv[1] == "--stop":
            if os.path.isfile(PID_PATH):
                with open(PID_PATH) as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 15)  # SIGTERM
                    print(f"  Stopped watchdog (pid {pid})")
                except OSError:
                    print(f"  Pid {pid} not running")
            else:
                print("  No watchdog pid file found")
            return

    # Check for existing instance
    if os.path.isfile(PID_PATH):
        with open(PID_PATH) as f:
            try:
                old_pid = int(f.read().strip())
                os.kill(old_pid, 0)
                print(f"  Watchdog already running (pid {old_pid}). Use --stop first.")
                sys.exit(1)
            except (OSError, ValueError):
                pass  # Old pid is dead, we can take over

    try:
        main_loop()
    except KeyboardInterrupt:
        log("Watchdog stopped by user")
    finally:
        if os.path.isfile(PID_PATH):
            os.remove(PID_PATH)


if __name__ == "__main__":
    main()
