#!/usr/bin/env python3
"""
Scatter Ops v0.2.0 — Self-healing system monitor.

The immune system of a Scatter Computing machine. Runs health checks on a
configurable interval, attempts automatic remediation for known failure modes,
and falls back to AI-powered diagnosis when it can't self-heal. Every incident
gets logged to ~/.scatter/incidents/ so the system builds a repair history.

Design principles:
  - Auto-fix what's safe to fix (restart services, clear temp files, free cache).
  - Never auto-fix what's dangerous (never delete user data, never force-kill).
  - When you can't fix it, explain it in plain language the user can act on.
  - Log everything. The incident log IS the system's memory.
"""

import json
import os
import subprocess
import sys
import time
import datetime
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

# ── Config ──────────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "deepseek-coder-v2:16b")
INCIDENT_DIR = os.path.expanduser("~/.scatter/incidents")
CONFIG_PATH = os.path.expanduser("~/.scatter/ops-config.json")

CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"
MAGENTA = "\033[35m"

def c(color, text):
    return f"{color}{text}{RESET}"


# ── Config loading ──────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "check_interval": 60,
    "disk_threshold_pct": 90,
    "memory_min_mb": 400,
    "watched_services": [],
    "watched_ports": [],
    "auto_restart_services": ["ollama"],
    "auto_clear_journal": False,
    "enable_ai_diagnosis": True,
}

def load_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                user_config = json.load(f)
            config.update(user_config)
        except Exception:
            pass
    return config


def save_default_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)


# ── Incident logging ───────────────────────────────────────────────────────

def log_incident(category, summary, details="", resolution=""):
    """Write an incident to the persistent log. This is how the system remembers what broke."""
    os.makedirs(INCIDENT_DIR, exist_ok=True)
    now = datetime.datetime.now()
    incident = {
        "timestamp": now.isoformat(),
        "category": category,
        "summary": summary,
        "details": details,
        "resolution": resolution,
    }
    filename = now.strftime("%Y%m%d_%H%M%S") + f"_{category}.json"
    filepath = os.path.join(INCIDENT_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(incident, f, indent=2)
    return filepath


def get_recent_incidents(hours=24, limit=20):
    """Load recent incidents for context."""
    if not os.path.isdir(INCIDENT_DIR):
        return []
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
    incidents = []
    for fname in sorted(os.listdir(INCIDENT_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(INCIDENT_DIR, fname)) as f:
                inc = json.load(f)
            ts = datetime.datetime.fromisoformat(inc["timestamp"])
            if ts >= cutoff:
                incidents.append(inc)
            if len(incidents) >= limit:
                break
        except Exception:
            continue
    return incidents


# ── Shell helper ────────────────────────────────────────────────────────────

def _run(cmd, timeout=10):
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {timeout}s", -1
    except Exception as e:
        return "", str(e), -1


# ── Health checks ───────────────────────────────────────────────────────────
# Each returns a list of Issue dicts: {"category", "summary", "details", "severity"}

def check_disk(config):
    threshold = config["disk_threshold_pct"]
    issues = []
    stdout, _, rc = _run("df -h --output=pcent,avail,target 2>/dev/null")
    if rc != 0:
        return issues
    for line in stdout.split("\n")[1:]:
        parts = line.split()
        if len(parts) >= 3:
            try:
                pct = int(parts[0].replace("%", ""))
            except ValueError:
                continue
            avail = parts[1]
            mount = parts[2]
            if pct >= threshold:
                sev = "critical" if pct >= 98 else "warning"
                issues.append({
                    "category": "disk",
                    "summary": f"Disk {mount} is {pct}% full ({avail} free)",
                    "details": f"Threshold: {threshold}%",
                    "severity": sev,
                })
    return issues


def check_memory(config):
    min_mb = config["memory_min_mb"]
    issues = []
    stdout, _, rc = _run("free -m")
    if rc != 0:
        return issues
    for line in stdout.split("\n"):
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                total = int(parts[1])
                available = int(parts[-1])
                if available < min_mb:
                    sev = "critical" if available < 100 else "warning"
                    issues.append({
                        "category": "memory",
                        "summary": f"Low memory: {available}MB available of {total}MB",
                        "details": f"Threshold: {min_mb}MB minimum",
                        "severity": sev,
                    })
    return issues


def check_swap():
    issues = []
    stdout, _, rc = _run("free -m")
    if rc != 0:
        return issues
    for line in stdout.split("\n"):
        if line.startswith("Swap:"):
            parts = line.split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                if total > 0 and used > total * 0.8:
                    issues.append({
                        "category": "swap",
                        "summary": f"Swap heavily used: {used}MB of {total}MB",
                        "details": "System may be thrashing. Consider closing applications or adding RAM.",
                        "severity": "warning",
                    })
    return issues


def check_ollama():
    issues = []
    try:
        req = Request(f"{OLLAMA_URL}/api/tags")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if not models:
            issues.append({
                "category": "ollama",
                "summary": "Ollama running but no models pulled",
                "details": f"Pull a model: ollama pull {MODEL}",
                "severity": "warning",
            })
    except Exception:
        issues.append({
            "category": "ollama",
            "summary": "Ollama is not running",
            "details": f"Expected at {OLLAMA_URL}",
            "severity": "critical",
        })
    return issues


def check_services(config):
    issues = []
    for svc in config.get("watched_services", []):
        stdout, _, rc = _run(f"systemctl is-active {svc} 2>/dev/null")
        state = stdout.strip()
        if state != "active":
            issues.append({
                "category": "service",
                "summary": f"Service '{svc}' is {state or 'unknown'}",
                "details": "",
                "severity": "critical" if state in ("failed", "inactive") else "warning",
            })
    return issues


def check_ports(config):
    issues = []
    for port in config.get("watched_ports", []):
        _, _, rc = _run(f"ss -tlnp 2>/dev/null | grep -q ':{port} '")
        if rc != 0:
            issues.append({
                "category": "port",
                "summary": f"Nothing listening on port {port}",
                "details": "",
                "severity": "warning",
            })
    return issues


def check_load():
    issues = []
    stdout, _, rc = _run("nproc")
    if rc != 0:
        return issues
    cpus = int(stdout.strip())
    stdout, _, rc = _run("cat /proc/loadavg")
    if rc != 0:
        return issues
    load_1m = float(stdout.split()[0])
    if load_1m > cpus * 2:
        issues.append({
            "category": "load",
            "summary": f"High CPU load: {load_1m:.1f} (machine has {cpus} cores)",
            "details": "Something is consuming excessive CPU.",
            "severity": "warning",
        })
    return issues


def check_journal():
    issues = []
    stdout, _, rc = _run(
        "journalctl --priority=err --since='10 minutes ago' --no-pager -q 2>/dev/null",
        timeout=10
    )
    if rc == 0 and stdout.strip():
        lines = stdout.strip().split("\n")
        count = len(lines)
        if count > 0:
            issues.append({
                "category": "journal",
                "summary": f"{count} error(s) in system log (last 10 min)",
                "details": "\n".join(lines[:10]),
                "severity": "warning" if count < 10 else "critical",
            })
    return issues


# ── Auto-remediation ────────────────────────────────────────────────────────

REMEDIATION = {
    # category -> function that attempts a fix. Returns (fixed: bool, action: str)
}

def remediate_ollama(issue, config):
    """Try to start Ollama if it's down."""
    if "not running" not in issue["summary"]:
        return False, ""

    # Check if ollama binary exists
    _, _, rc = _run("which ollama")
    if rc != 0:
        return False, "Ollama binary not found — needs installation."

    # Try starting it
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=open(os.devnull, "w"),
            stderr=open(os.devnull, "w"),
        )
    except Exception as e:
        return False, f"Failed to start: {e}"

    # Wait and verify
    time.sleep(4)
    try:
        req = Request(f"{OLLAMA_URL}/api/tags")
        with urlopen(req, timeout=5):
            return True, "Started Ollama server."
    except Exception:
        return False, "Started Ollama process but it's not responding yet. May need more time."


def remediate_service(issue, config):
    """Restart a watched service if it's in the auto-restart list."""
    svc_match = None
    for svc in config.get("auto_restart_services", []):
        if svc in issue["summary"]:
            svc_match = svc
            break
    if not svc_match:
        return False, ""

    _, stderr, rc = _run(f"systemctl restart {svc_match} 2>&1")
    if rc == 0:
        # Verify
        time.sleep(2)
        stdout, _, rc2 = _run(f"systemctl is-active {svc_match}")
        if stdout.strip() == "active":
            return True, f"Restarted service '{svc_match}'."
    return False, f"Restart attempted but failed: {stderr}"


def remediate_memory(issue, config):
    """Drop filesystem caches if memory is critically low. This is always safe."""
    if "Low memory" not in issue["summary"]:
        return False, ""
    # Only drop caches if we can (needs /proc access, not root)
    _, _, rc = _run("sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null")
    if rc == 0:
        return True, "Dropped filesystem caches to free memory."
    # Can't drop caches without root — not an error, just can't auto-fix
    return False, ""


def attempt_remediation(issue, config):
    """Try to auto-fix an issue. Returns (fixed, action_taken)."""
    category = issue["category"]

    if category == "ollama":
        return remediate_ollama(issue, config)
    elif category == "service":
        return remediate_service(issue, config)
    elif category == "memory":
        return remediate_memory(issue, config)

    return False, ""


# ── AI diagnosis ────────────────────────────────────────────────────────────

def ai_diagnose(issues, config):
    """Ask the local model to diagnose unfixed issues."""
    if not config.get("enable_ai_diagnosis", True):
        return None

    # Check if Ollama is reachable (can't diagnose if the brain is down)
    if any(i["category"] == "ollama" for i in issues):
        return None

    recent = get_recent_incidents(hours=24)
    history_ctx = ""
    if recent:
        history_ctx = "\n\nRecent incident history (last 24h):\n"
        for inc in recent[:10]:
            history_ctx += f"- [{inc['timestamp'][:16]}] {inc['category']}: {inc['summary']}"
            if inc.get("resolution"):
                history_ctx += f" → {inc['resolution']}"
            history_ctx += "\n"

    issue_text = "\n".join(
        f"- [{i['severity'].upper()}] {i['summary']}" + (f"\n  {i['details']}" if i['details'] else "")
        for i in issues
    )

    prompt = f"""You are the diagnostic AI inside a Scatter Computing machine. These issues were just detected:

{issue_text}
{history_ctx}
For each issue, give:
1. What's happening (one sentence, plain language).
2. The exact fix — a command to run or a specific action.
3. If it's recurring (check the history), say what the root cause likely is.

Be direct. No filler. The user sees this on a status screen when something is wrong."""

    try:
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are Scatter Ops. Diagnose system issues. Be concise and actionable."},
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
        return result.get("message", {}).get("content", "")
    except Exception as e:
        return f"(Diagnosis failed: {e})"


# ── Check cycle ─────────────────────────────────────────────────────────────

def run_all_checks(config):
    """Run every health check. Returns list of issues."""
    issues = []
    issues.extend(check_disk(config))
    issues.extend(check_memory(config))
    issues.extend(check_swap())
    issues.extend(check_ollama())
    issues.extend(check_services(config))
    issues.extend(check_ports(config))
    issues.extend(check_load())
    issues.extend(check_journal())
    return issues


def run_cycle(config, quiet=False):
    """Run one full check-remediate-diagnose cycle. Returns True if healthy."""
    now = datetime.datetime.now().strftime("%H:%M:%S")
    issues = run_all_checks(config)

    if not issues:
        if not quiet:
            print(c(GREEN, f"  [{now}] All systems healthy"))
        return True

    # Attempt auto-remediation
    fixed = []
    remaining = []
    for issue in issues:
        was_fixed, action = attempt_remediation(issue, config)
        if was_fixed:
            fixed.append((issue, action))
            log_incident(issue["category"], issue["summary"],
                         issue.get("details", ""), f"Auto-fixed: {action}")
        else:
            remaining.append(issue)

    # Report auto-fixes
    for issue, action in fixed:
        print(c(GREEN, f"  [{now}] Auto-fixed: {action}"))

    if not remaining:
        return True

    # Report remaining issues
    print(c(RED, f"\n  [{now}] {len(remaining)} issue(s) detected:"))
    for issue in remaining:
        sev_color = RED if issue["severity"] == "critical" else YELLOW
        print(c(sev_color, f"    [{issue['severity'].upper()}] {issue['summary']}"))
        if issue["details"] and not quiet:
            for line in issue["details"].split("\n")[:3]:
                print(c(DIM, f"      {line}"))

    # Log unresolved issues
    for issue in remaining:
        log_incident(issue["category"], issue["summary"], issue.get("details", ""), "Unresolved")

    # AI diagnosis
    if remaining and config.get("enable_ai_diagnosis", True):
        print(c(DIM, f"\n  Diagnosing..."))
        diagnosis = ai_diagnose(remaining, config)
        if diagnosis:
            print()
            for line in diagnosis.split("\n"):
                print(f"  {line}")
            print()

            # Log the diagnosis
            log_incident("diagnosis", f"AI diagnosis for {len(remaining)} issue(s)",
                         diagnosis, "Presented to user")
    elif remaining:
        # Ollama is down, give manual guidance
        print(c(DIM, "\n  (AI diagnosis unavailable — Ollama is down)"))
        print(c(DIM, "  Manual fixes:"))
        for issue in remaining:
            if issue["category"] == "ollama":
                print(c(DIM, "    ollama serve   # start the AI engine"))
            elif issue["category"] == "service":
                svc = issue["summary"].split("'")[1] if "'" in issue["summary"] else "?"
                print(c(DIM, f"    sudo systemctl restart {svc}"))
            elif issue["category"] == "disk":
                print(c(DIM, "    sudo apt clean && docker system prune   # free disk space"))
            elif issue["category"] == "memory":
                print(c(DIM, "    Close unused applications or restart the machine"))
        print()

    return False


# ── Daemon mode ─────────────────────────────────────────────────────────────

def daemon(config):
    interval = config["check_interval"]
    print(f"\n{BOLD}{CYAN}  Scatter Ops{RESET} {DIM}v0.2.0{RESET}")
    print(c(DIM, f"  Monitoring every {interval}s"))
    print(c(DIM, f"  Watched services: {', '.join(config['watched_services']) or 'none'}"))
    print(c(DIM, f"  Auto-restart: {', '.join(config['auto_restart_services']) or 'none'}"))
    print(c(DIM, f"  Incidents log: {INCIDENT_DIR}"))
    print(c(DIM, f"  Ctrl+C to stop\n"))

    consecutive_healthy = 0
    while True:
        try:
            healthy = run_cycle(config, quiet=(consecutive_healthy > 0 and consecutive_healthy % 5 != 0))
            if healthy:
                consecutive_healthy += 1
            else:
                consecutive_healthy = 0
            time.sleep(interval)
        except KeyboardInterrupt:
            print(c(DIM, "\n  Stopped."))
            break


# ── CLI ─────────────────────────────────────────────────────────────────────

def print_status(config):
    """One-shot status report."""
    print(f"\n{BOLD}{CYAN}  Scatter System Status{RESET}")
    print(c(DIM, f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"))

    issues = run_all_checks(config)
    if not issues:
        print(c(GREEN, "  Everything is healthy.\n"))
        return

    for issue in issues:
        sev_color = RED if issue["severity"] == "critical" else YELLOW
        print(c(sev_color, f"  [{issue['severity'].upper()}] {issue['summary']}"))
    print()


def print_incidents():
    """Show recent incident history."""
    incidents = get_recent_incidents(hours=72, limit=30)
    if not incidents:
        print(c(DIM, "  No incidents in the last 72 hours."))
        return

    print(f"\n{BOLD}  Incident History (72h){RESET}\n")
    for inc in incidents:
        ts = inc["timestamp"][:16].replace("T", " ")
        cat = inc["category"]
        summary = inc["summary"]
        resolution = inc.get("resolution", "")
        if "Auto-fixed" in resolution:
            color = GREEN
        elif "Unresolved" in resolution:
            color = YELLOW
        else:
            color = DIM
        print(c(color, f"  [{ts}] {cat}: {summary}"))
        if resolution and "diagnosis" not in cat:
            print(c(DIM, f"    → {resolution}"))
    print()


def main():
    config = load_config()
    save_default_config()

    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(f"""
  {BOLD}Scatter Ops{RESET} — self-healing system monitor

  Usage:
    scatter ops                One-shot health check
    scatter ops --daemon       Continuous monitoring
    scatter ops --incidents    Show incident history
    scatter ops --init         Write default config to ~/.scatter/ops-config.json
    scatter ops --version      Version
        """)
        return

    arg = sys.argv[1]

    if arg == "--version":
        print("Scatter Ops v0.2.0")
    elif arg == "--daemon":
        # Allow CLI overrides
        for a in sys.argv[2:]:
            if a.startswith("--interval="):
                config["check_interval"] = int(a.split("=")[1])
            elif a.startswith("--watch="):
                config["watched_services"].append(a.split("=")[1])
        daemon(config)
    elif arg == "--incidents":
        print_incidents()
    elif arg == "--once":
        ok = run_cycle(config)
        sys.exit(0 if ok else 1)
    elif arg == "--init":
        save_default_config()
        print(c(GREEN, f"  Config written to {CONFIG_PATH}"))
    else:
        # Default: one-shot status
        print_status(config)


if __name__ == "__main__":
    main()
