#!/usr/bin/env python3
"""
Scatter Journal v0.1.0 — Decision capture and knowledge persistence.

Not a chat log. Not a diary. A research instrument.

Every time you make an architecture decision, learn a concept, hit a wall,
or change direction — journal it. Scatter Journal stores these as structured
entries with timestamps, tags, and the dialectical trace (what you thought,
what challenged it, what survived).

This is your thesis writing itself as you build.

Usage:
    scatter journal                         # interactive entry
    scatter journal "switched to SQLite"    # quick entry
    scatter journal --search "database"     # search entries
    scatter journal --review                # review recent decisions
    scatter journal --export                # export for research
"""

import json
import os
import sys
import datetime
import readline
from pathlib import Path
from urllib.request import Request, urlopen

JOURNAL_DIR = os.path.expanduser("~/.scatter/journal")
OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def load_entries():
    """Load all journal entries."""
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    entries = []
    for f in sorted(Path(JOURNAL_DIR).glob("*.json")):
        try:
            with open(f) as fh:
                entries.append(json.load(fh))
        except Exception:
            pass
    return entries


def save_entry(entry):
    """Save a journal entry."""
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(JOURNAL_DIR, f"{ts}.json")
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)
    return path


def read_system_state():
    """Read current system state for context."""
    state_path = os.path.expanduser("~/.scatter/system-state.json")
    try:
        with open(state_path) as f:
            return json.load(f)
    except Exception:
        return {}


def quick_entry(text):
    """Single-line journal entry."""
    state = read_system_state()
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "type": "note",
        "content": text,
        "system_state": {
            "battery": state.get("battery_pct"),
            "network": state.get("network"),
            "models": state.get("ollama_models", []),
        },
    }
    path = save_entry(entry)
    print(f"  {DIM}Saved to {os.path.basename(path)}{RESET}")


def interactive_entry():
    """Structured journal entry following the dialectical trace."""
    print(f"\n  {BOLD}Scatter Journal{RESET}")
    print(f"  {DIM}Record a decision, a lesson, or a direction change.{RESET}")
    print()

    # What happened?
    print(f"  {CYAN}What did you decide or learn?{RESET}")
    content = input(f"  > ").strip()
    if not content:
        print(f"  {DIM}Nothing entered.{RESET}")
        return

    # What kind of entry?
    print(f"\n  {CYAN}Type?{RESET} {DIM}(d)ecision, (l)esson, (b)lock, (i)dea, (n)ote{RESET}")
    type_input = input(f"  > ").strip().lower()
    entry_type = {
        "d": "decision", "decision": "decision",
        "l": "lesson", "lesson": "lesson",
        "b": "block", "block": "block",
        "i": "idea", "idea": "idea",
    }.get(type_input, "note")

    # The dialectical trace — optional
    print(f"\n  {CYAN}What did you think before? (thesis — optional, Enter to skip){RESET}")
    thesis = input(f"  > ").strip()

    antithesis = ""
    synthesis = ""
    if thesis:
        print(f"\n  {CYAN}What challenged it? (antithesis){RESET}")
        antithesis = input(f"  > ").strip()

        if antithesis:
            print(f"\n  {CYAN}What survived? (synthesis){RESET}")
            synthesis = input(f"  > ").strip()

    # Tags
    print(f"\n  {CYAN}Tags? {DIM}(comma-separated, optional){RESET}")
    tags_input = input(f"  > ").strip()
    tags = [t.strip() for t in tags_input.split(",") if t.strip()] if tags_input else []

    # Build entry
    state = read_system_state()
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "type": entry_type,
        "content": content,
        "dialectic": {
            "thesis": thesis,
            "antithesis": antithesis,
            "synthesis": synthesis,
        } if thesis else None,
        "tags": tags,
        "system_state": {
            "battery": state.get("battery_pct"),
            "network": state.get("network"),
            "models": state.get("ollama_models", []),
        },
    }

    path = save_entry(entry)
    print(f"\n  {GREEN}Recorded.{RESET} {DIM}{os.path.basename(path)}{RESET}")

    # If we have a local model, generate a one-sentence reflection
    if state.get("ollama") == "running" and state.get("ollama_models"):
        try:
            prompt = f"In one sentence, what's the deeper implication of this decision for a distributed AI system? Decision: {content}"
            if synthesis:
                prompt += f" (arrived at through: thesis='{thesis}', antithesis='{antithesis}', synthesis='{synthesis}')"

            payload = {
                "model": FAST_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_ctx": 2048, "temperature": 0.3},
            }
            data = json.dumps(payload).encode()
            req = Request(
                f"{OLLAMA_URL}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                reflection = result.get("message", {}).get("content", "").strip()
                if reflection:
                    print(f"\n  {DIM}Scatter reflects: {reflection}{RESET}")
                    entry["reflection"] = reflection
                    # Re-save with reflection
                    with open(path, "w") as f:
                        json.dump(entry, f, indent=2)
        except Exception:
            pass  # Model reflection is optional, never block on it

    print()


def search_entries(query):
    """Search journal entries."""
    entries = load_entries()
    query_lower = query.lower()
    matches = []
    for e in entries:
        searchable = json.dumps(e).lower()
        if query_lower in searchable:
            matches.append(e)

    if not matches:
        print(f"  {DIM}No entries matching '{query}'.{RESET}")
        return

    print(f"\n  {BOLD}Found {len(matches)} entries:{RESET}\n")
    for e in matches[-20:]:  # last 20 matches
        ts = e.get("timestamp", "?")[:16].replace("T", " ")
        etype = e.get("type", "note")
        content = e.get("content", "")[:80]
        tags = ", ".join(e.get("tags", []))
        tag_str = f" [{tags}]" if tags else ""
        print(f"  {DIM}{ts}{RESET}  {YELLOW}{etype}{RESET}  {content}{DIM}{tag_str}{RESET}")
    print()


def review_recent():
    """Review recent entries — the last week of decisions."""
    entries = load_entries()
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    recent = [e for e in entries if e.get("timestamp", "") >= week_ago]

    if not recent:
        print(f"  {DIM}No entries in the last 7 days.{RESET}")
        return

    print(f"\n  {BOLD}Last 7 days — {len(recent)} entries{RESET}\n")

    # Group by type
    by_type = {}
    for e in recent:
        t = e.get("type", "note")
        by_type.setdefault(t, []).append(e)

    for etype, entries_of_type in by_type.items():
        print(f"  {YELLOW}{etype}s ({len(entries_of_type)}){RESET}")
        for e in entries_of_type[-5:]:
            ts = e.get("timestamp", "?")[:10]
            content = e.get("content", "")[:70]
            print(f"    {DIM}{ts}{RESET}  {content}")
            if e.get("dialectic") and e["dialectic"].get("synthesis"):
                print(f"    {CYAN}  → {e['dialectic']['synthesis'][:70]}{RESET}")
        print()


def export_research():
    """Export journal as a structured research document."""
    entries = load_entries()
    if not entries:
        print(f"  {DIM}No entries to export.{RESET}")
        return

    export_path = os.path.expanduser("~/.scatter/journal-export.md")

    lines = [
        "# Scatter Computing — Research Journal",
        f"Exported: {datetime.datetime.now().isoformat()[:16]}",
        f"Total entries: {len(entries)}",
        "",
    ]

    # Decisions with dialectical traces are the most valuable
    decisions = [e for e in entries if e.get("type") == "decision"]
    if decisions:
        lines.append("## Decisions")
        lines.append("")
        for d in decisions:
            ts = d.get("timestamp", "?")[:10]
            lines.append(f"### {ts} — {d.get('content', '')}")
            if d.get("dialectic"):
                dia = d["dialectic"]
                if dia.get("thesis"):
                    lines.append(f"- **Thesis:** {dia['thesis']}")
                if dia.get("antithesis"):
                    lines.append(f"- **Antithesis:** {dia['antithesis']}")
                if dia.get("synthesis"):
                    lines.append(f"- **Synthesis:** {dia['synthesis']}")
            if d.get("reflection"):
                lines.append(f"- *Reflection:* {d['reflection']}")
            if d.get("tags"):
                lines.append(f"- Tags: {', '.join(d['tags'])}")
            lines.append("")

    # Lessons
    lessons = [e for e in entries if e.get("type") == "lesson"]
    if lessons:
        lines.append("## Lessons")
        lines.append("")
        for l in lessons:
            ts = l.get("timestamp", "?")[:10]
            lines.append(f"- **{ts}:** {l.get('content', '')}")
        lines.append("")

    # Ideas
    ideas = [e for e in entries if e.get("type") == "idea"]
    if ideas:
        lines.append("## Ideas")
        lines.append("")
        for i in ideas:
            ts = i.get("timestamp", "?")[:10]
            lines.append(f"- **{ts}:** {i.get('content', '')}")
        lines.append("")

    # Blocks
    blocks = [e for e in entries if e.get("type") == "block"]
    if blocks:
        lines.append("## Blocks & Obstacles")
        lines.append("")
        for b in blocks:
            ts = b.get("timestamp", "?")[:10]
            lines.append(f"- **{ts}:** {b.get('content', '')}")
        lines.append("")

    with open(export_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  {GREEN}Exported to {export_path}{RESET}")
    print(f"  {DIM}{len(entries)} entries, {len(decisions)} decisions, {len(lessons)} lessons{RESET}")


def main():
    os.makedirs(JOURNAL_DIR, exist_ok=True)

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--version", "-v"):
            print("Scatter Journal v0.1.0")
            return
        if arg in ("--search", "-s"):
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
            if not query:
                print("  Usage: scatter journal --search <query>")
                return
            search_entries(query)
            return
        if arg in ("--review", "-r"):
            review_recent()
            return
        if arg in ("--export", "-e"):
            export_research()
            return
        if arg in ("--help", "-h"):
            print(__doc__)
            return
        # Quick entry
        quick_entry(" ".join(sys.argv[1:]))
        return

    interactive_entry()


if __name__ == "__main__":
    main()
