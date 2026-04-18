#!/usr/bin/env python3
"""
Scatter Code v0.2.0 — Local AI coding agent.
Streams responses, parses tool calls from text when native tool API fails,
gathers project context on startup, persists sessions, shows diffs on edits.
"""

import json
import os
import re
import subprocess
import sys
import readline
import glob as globlib
import hashlib
import difflib
import traceback
import textwrap
import signal
import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── Config ──────────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:1.5b")
FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")
MAX_CONTEXT = int(os.environ.get("SCATTER_CTX", "32768"))

# ── Power-aware model routing ─────────────────────────────────────────────
# Intelligence per watt: the system adapts to available energy.

def _get_power_router():
    """Import power router if available. Graceful fallback if not."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scatter-ops"))
        import power_router
        return power_router
    except Exception:
        return None

def get_active_model():
    """Select model based on power state. Falls back to default if router unavailable."""
    router = _get_power_router()
    if router:
        selection = router.select_model()
        return selection["model"], selection["ctx_size"], selection.get("reason", "")
    return MODEL, MAX_CONTEXT, ""
SESSION_DIR = os.path.expanduser(os.environ.get("SCATTER_SESSIONS", "~/.scatter/sessions"))
MAX_TOOL_ROUNDS = 25  # safety brake: max consecutive tool-call rounds per user message

# ── ANSI ────────────────────────────────────────────────────────────────────

C = CYAN    = "\033[36m"
G = GREEN   = "\033[32m"
Y = YELLOW  = "\033[33m"
R = RED     = "\033[31m"
D = DIM     = "\033[2m"
B = BOLD    = "\033[1m"
U = RESET   = "\033[0m"
MAGENTA     = "\033[35m"

def c(color, text):
    return f"{color}{text}{RESET}"

# ── Tool definitions (sent to Ollama for native tool calling) ───────────────

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file's contents with line numbers. ALWAYS read before editing.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path (relative or absolute)"},
            "start_line": {"type": "integer", "description": "Start line, 1-indexed (optional)"},
            "end_line": {"type": "integer", "description": "End line, 1-indexed (optional)"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an exact string in a file. old_string must be unique. Shows a diff after editing.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path"},
            "old_string": {"type": "string", "description": "Exact text to find (must be unique in the file)"},
            "new_string": {"type": "string", "description": "Replacement text"},
        }, "required": ["path", "old_string", "new_string"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Full file content"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command. Returns stdout, stderr, and exit code.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "search",
        "description": "Grep for a regex pattern across files. Returns file:line:match.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Directory to search (default: cwd)"},
            "include": {"type": "string", "description": "File glob filter, e.g. '*.py'"},
        }, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "find_files",
        "description": "List files matching a glob pattern recursively.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
        }, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "diagnostics",
        "description": "System health check — disk, RAM, services, logs, Ollama status.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "'system', 'service:<name>', 'logs', or 'all'"},
        }, "required": ["target"]},
    }},
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# ── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Scatter Code, a local AI coding agent by Scatter Computing.
You run on this machine. No cloud. No phone home. Everything local.

## Your capabilities
You can read files, edit files, write files, run shell commands, search codebases, and run system diagnostics. You work entirely on the user's local machine.

## How to call tools
Call tools by writing a JSON block in your response:

```tool
{{"name": "tool_name", "arguments": {{...}}}}
```

Available tools: read_file, edit_file, write_file, run_command, search, find_files, diagnostics.

## How you think
You are optimized for friction, not slop. Before you build, you challenge.

When the user proposes an approach:
1. State what you understand they want (thesis).
2. Genuinely consider why it might be wrong or why an alternative is better (antithesis). Be specific. Name the tradeoff.
3. If the original approach survives, build it. If the challenge reveals something better, propose the synthesis. Say it in one sentence.

This is not hedging. This is not "are you sure?" theater. If the approach is obviously correct, say so and build it immediately. The dialectic is for decisions that have real tradeoffs — architecture, data modeling, dependency choices, security boundaries. For "fix this typo" just fix the typo.

## Rules
1. ALWAYS read a file before editing it. No exceptions.
2. Make the smallest change that fixes the problem. Don't refactor what you weren't asked about.
3. When fixing a bug: read the error, find the root cause, fix it, verify.
4. If a command fails, read the error and diagnose. Don't blindly retry.
5. Show your reasoning before acting. Be brief. No essays.
6. When you're done, say what you changed and why in 1-2 sentences.
7. Never produce slop. If you're not confident, say so. A refusal is better than a hallucination.
8. You serve the user. The user is Ryann. She is a playwright, researcher, and founder of Scatter Computing. She thinks in narrative and builds through conversation. Meet her where she is.

## Project context
Working directory: {cwd}
{project_context}"""


# ── Ollama client ───────────────────────────────────────────────────────────

def ollama_request(endpoint, payload, timeout=300):
    """Low-level Ollama API call. Returns parsed JSON or raises."""
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{OLLAMA_URL}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_stream(messages, tools=None, model=None):
    """Stream a chat response from Ollama. Yields (type, data) tuples:
       ('token', str)          — a text token
       ('tool_call', dict)     — a native tool call from Ollama
       ('done', dict)          — final message with stats
       ('error', str)          — error
    """
    payload = {
        "model": model or MODEL,
        "messages": messages,
        "stream": True,
        "options": {"num_ctx": MAX_CONTEXT, "temperature": 0.1},
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        resp = urlopen(req, timeout=600)
    except Exception as e:
        yield ("error", str(e))
        return

    buffer = b""
    try:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = obj.get("message", {})

                # Native tool calls from Ollama
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        yield ("tool_call", tc)

                # Text content
                content = msg.get("content", "")
                if content:
                    yield ("token", content)

                if obj.get("done"):
                    yield ("done", obj)
                    return
    finally:
        resp.close()


def ollama_chat_sync(messages, model=None):
    """Non-streaming chat, for summaries and quick calls."""
    payload = {
        "model": model or FAST_MODEL or MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1},
    }
    result = ollama_request("/api/chat", payload, timeout=120)
    return result.get("message", {}).get("content", "")


# ── Text-based tool call parser (fallback when native tool API fails) ───────

TOOL_BLOCK_RE = re.compile(
    r'```tool\s*\n\s*(\{.*?\})\s*\n\s*```',
    re.DOTALL
)

TOOL_JSON_RE = re.compile(
    r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
    re.DOTALL
)

def parse_tool_calls_from_text(text):
    """Extract tool calls from model text output. Returns list of (name, args) tuples
    and the text with tool blocks removed."""
    calls = []
    cleaned = text

    # First try ```tool blocks
    for match in TOOL_BLOCK_RE.finditer(text):
        try:
            obj = json.loads(match.group(1))
            name = obj.get("name", "")
            args = obj.get("arguments", {})
            if name in TOOL_NAMES:
                calls.append((name, args))
                cleaned = cleaned.replace(match.group(0), "")
        except json.JSONDecodeError:
            pass

    # Fallback: bare JSON objects with name/arguments structure
    if not calls:
        for match in TOOL_JSON_RE.finditer(text):
            name = match.group(1)
            try:
                args = json.loads(match.group(2))
                if name in TOOL_NAMES:
                    calls.append((name, args))
                    cleaned = cleaned.replace(match.group(0), "")
            except json.JSONDecodeError:
                pass

    return calls, cleaned.strip()


# ── Tool implementations ────────────────────────────────────────────────────

DANGEROUS_PATTERNS = re.compile(
    r'\b(rm\s+-rf|mkfs|dd\s+if=|:\(\)\{|fork\s*bomb|chmod\s+-R\s+777|>\s*/dev/sd)',
    re.IGNORECASE
)

def _resolve_path(path):
    """Expand ~ and make relative paths absolute to cwd."""
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(os.getcwd(), p)
    return os.path.normpath(p)


def tool_read_file(args):
    path = _resolve_path(args["path"])
    if not os.path.isfile(path):
        return f"Error: not found: {path}"
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        start = max(0, (args.get("start_line", 1) or 1) - 1)
        end = args.get("end_line") or total
        end = min(end, total)
        selected = lines[start:end]

        numbered = [f"{start + i + 1:>5}  {line.rstrip()}" for i, line in enumerate(selected)]
        result = "\n".join(numbered)

        if total > end:
            result += f"\n... ({total - end} more lines)"
        if len(result) > 25000:
            result = result[:25000] + "\n... (truncated at 25KB)"
        return result
    except Exception as e:
        return f"Error: {e}"


def tool_edit_file(args):
    path = _resolve_path(args["path"])
    if not os.path.isfile(path):
        return f"Error: not found: {path}"
    old_string = args["old_string"]
    new_string = args["new_string"]

    try:
        with open(path, "r") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            # Fuzzy help: show similar lines
            old_lines = old_string.strip().split("\n")
            first_line = old_lines[0].strip()
            candidates = [
                f"  line {i+1}: {line.rstrip()}"
                for i, line in enumerate(content.split("\n"))
                if first_line[:40] in line
            ][:5]
            hint = "\nDid you mean:\n" + "\n".join(candidates) if candidates else ""
            return f"Error: old_string not found in {os.path.basename(path)}.{hint}"
        if count > 1:
            return f"Error: old_string matches {count} locations — add more surrounding context to make it unique."

        new_content = content.replace(old_string, new_string, 1)

        # Generate diff
        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{os.path.basename(path)}",
            tofile=f"b/{os.path.basename(path)}",
            lineterm=""
        ))

        with open(path, "w") as f:
            f.write(new_content)

        if diff:
            diff_str = "\n".join(line.rstrip() for line in diff[:50])
            if len(diff) > 50:
                diff_str += f"\n... ({len(diff) - 50} more diff lines)"
            return f"Edited {os.path.basename(path)}\n{diff_str}"
        return f"Edited {os.path.basename(path)} (no visible diff — whitespace change?)"

    except Exception as e:
        return f"Error: {e}"


def tool_write_file(args):
    path = _resolve_path(args["path"])
    content = args["content"]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        existed = os.path.isfile(path)
        with open(path, "w") as f:
            f.write(content)
        action = "Overwrote" if existed else "Created"
        lines = content.count("\n") + 1
        return f"{action} {os.path.basename(path)} ({lines} lines, {len(content)} bytes)"
    except Exception as e:
        return f"Error: {e}"


def tool_run_command(args):
    command = args["command"]
    timeout = args.get("timeout", 30)

    if DANGEROUS_PATTERNS.search(command):
        return f"Blocked: '{command}' looks destructive. If you really need this, the user should run it manually."

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getcwd(),
        )
        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(result.stderr)
        output = "\n".join(parts)
        if result.returncode != 0:
            output += f"\n[exit {result.returncode}]"
        if len(output) > 20000:
            # Keep first and last 8K to preserve both header and tail of long outputs
            output = output[:8000] + "\n\n... (truncated) ...\n\n" + output[-8000:]
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s. Consider increasing timeout or running in background."
    except Exception as e:
        return f"Error: {e}"


def tool_search(args):
    pattern = args["pattern"]
    path = _resolve_path(args.get("path", "."))
    cmd = ["grep", "-rn", "--color=never", "-I"]  # -I skips binary files
    if args.get("include"):
        cmd.extend(["--include", args["include"]])
    cmd.extend(["-E", pattern, path])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout
        lines = output.strip().split("\n") if output.strip() else []
        if len(lines) > 100:
            output = "\n".join(lines[:100]) + f"\n... ({len(lines) - 100} more matches)"
        return output or "No matches."
    except subprocess.TimeoutExpired:
        return "Search timed out — try a narrower path or pattern."
    except Exception as e:
        return f"Error: {e}"


def tool_find_files(args):
    pattern = args["pattern"]
    try:
        matches = sorted(globlib.glob(pattern, recursive=True))
        # Filter out hidden dirs and common noise
        matches = [m for m in matches if not any(
            part.startswith(".") for part in Path(m).parts
            if part not in (".", "..")
        )][:300]
        if not matches:
            return "No files matched."
        return "\n".join(matches)
    except Exception as e:
        return f"Error: {e}"


def tool_diagnostics(args):
    target = args.get("target", "all")
    sections = []

    def _run(cmd, t=5):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
            return r.stdout.strip() or r.stderr.strip() or "(no output)"
        except Exception as e:
            return str(e)

    if target in ("system", "all"):
        sections.append("## System")
        sections.append(_run("free -h"))
        sections.append(_run("df -h / /home 2>/dev/null"))
        sections.append(_run("uptime"))
        sections.append(_run("nproc && cat /proc/loadavg"))

    if target in ("logs", "all"):
        sections.append("## Recent Errors")
        sections.append(_run(
            "journalctl --priority=err --since='1 hour ago' --no-pager -n 20 -q 2>/dev/null "
            "|| echo 'No journal access'", 10
        ))

    if target.startswith("service:"):
        svc = target.split(":", 1)[1]
        sections.append(f"## Service: {svc}")
        sections.append(_run(f"systemctl status {svc} 2>/dev/null || echo 'Not found'"))
        sections.append(_run(f"journalctl -u {svc} --since='30 min ago' --no-pager -n 20 -q 2>/dev/null", 10))

    if target == "all":
        sections.append("## Ollama")
        try:
            req = Request(f"{OLLAMA_URL}/api/tags")
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                sections.append(f"Running. Models: {', '.join(models) or 'none'}")
        except Exception:
            sections.append("NOT RUNNING")

        sections.append("## Containers")
        sections.append(_run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null "
                             "|| podman ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null "
                             "|| echo 'No container runtime'"))

    return "\n\n".join(sections)


DISPATCH = {
    "read_file": tool_read_file,
    "edit_file": tool_edit_file,
    "write_file": tool_write_file,
    "run_command": tool_run_command,
    "search": tool_search,
    "find_files": tool_find_files,
    "diagnostics": tool_diagnostics,
}


def execute_tool(name, args):
    if name not in DISPATCH:
        return f"Unknown tool: {name}"
    try:
        return DISPATCH[name](args)
    except Exception as e:
        return f"Tool crashed: {e}\n{traceback.format_exc()}"


# ── Project context gathering ───────────────────────────────────────────────

def read_system_state():
    """Read shared system state written by scatter-greeting or scatter-ops."""
    state_path = os.path.expanduser("~/.scatter/system-state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
        parts = []
        bat = state.get("battery_pct")
        if bat is not None:
            parts.append(f"Battery: {bat}% ({state.get('battery_status', 'unknown')})")
        ram = state.get("ram_available_gb")
        if ram:
            parts.append(f"RAM free: {ram}GB/{state.get('ram_total_gb', '?')}GB")
        temp = state.get("cpu_temp_c")
        if temp:
            parts.append(f"CPU temp: {temp}°C")
        net = state.get("network", "unknown")
        if net == "disconnected":
            parts.append("OFFLINE — no network")
        models = state.get("ollama_models", [])
        if models:
            parts.append(f"Local models: {', '.join(models)}")
        return "System: " + " | ".join(parts) if parts else ""
    except Exception:
        return ""


def gather_project_context():
    """Scan the working directory for project signals. Fast, no model calls."""
    cwd = os.getcwd()
    ctx = []

    # Inject system state so the agent knows hardware constraints
    sys_state = read_system_state()
    if sys_state:
        ctx.append(sys_state)

    # Git
    if os.path.isdir(os.path.join(cwd, ".git")):
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=3, cwd=cwd
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=3, cwd=cwd
            ).stdout.strip()
            dirty = len(status.split("\n")) if status else 0
            ctx.append(f"Git repo, branch: {branch}, {dirty} changed file(s)")
        except Exception:
            ctx.append("Git repo (couldn't read status)")

    # Language/framework detection
    indicators = {
        "package.json": "Node.js",
        "pyproject.toml": "Python",
        "setup.py": "Python",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "pom.xml": "Java (Maven)",
        "build.gradle": "Java (Gradle)",
        "Gemfile": "Ruby",
        "composer.json": "PHP",
        "Makefile": "Makefile present",
        "docker-compose.yml": "Docker Compose",
        "docker-compose.yaml": "Docker Compose",
        "Dockerfile": "Dockerfile present",
    }
    detected = []
    for filename, label in indicators.items():
        if os.path.isfile(os.path.join(cwd, filename)):
            detected.append(label)
    if detected:
        ctx.append(f"Stack: {', '.join(detected)}")

    # Count source files by type
    ext_counts = {}
    for root, dirs, files in os.walk(cwd):
        # Skip hidden and vendor dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
            "node_modules", "vendor", "__pycache__", "target", "build", "dist", ".git"
        )]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java",
                       ".rb", ".php", ".c", ".cpp", ".h", ".css", ".html", ".vue", ".svelte"):
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
    if ext_counts:
        top = sorted(ext_counts.items(), key=lambda x: -x[1])[:5]
        ctx.append("Files: " + ", ".join(f"{count}{ext}" for ext, count in top))

    # Test detection
    test_patterns = ["**/test_*.py", "**/*.test.ts", "**/*.test.js", "**/*.spec.ts",
                     "**/*.spec.js", "**/tests/**", "**/__tests__/**"]
    has_tests = any(globlib.glob(p, recursive=True) for p in test_patterns)
    if has_tests:
        ctx.append("Tests detected")

    return "\n".join(ctx) if ctx else "No project files detected."


# ── Session persistence ─────────────────────────────────────────────────────

def session_path():
    """Session file scoped to the working directory."""
    cwd_hash = hashlib.sha256(os.getcwd().encode()).hexdigest()[:12]
    return os.path.join(SESSION_DIR, f"{cwd_hash}.json")


def save_session(messages):
    os.makedirs(SESSION_DIR, exist_ok=True)
    # Don't save the system prompt — it's regenerated each launch
    saveable = [m for m in messages if m.get("role") != "system"]
    with open(session_path(), "w") as f:
        json.dump({
            "cwd": os.getcwd(),
            "model": MODEL,
            "saved_at": datetime.datetime.now().isoformat(),
            "messages": saveable[-60:],  # cap at last 60 messages
        }, f, indent=2)


def load_session():
    path = session_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        msgs = data.get("messages", [])
        saved_at = data.get("saved_at", "unknown")
        if msgs:
            print(c(DIM, f"  Resumed session from {saved_at} ({len(msgs)} messages)"))
        return msgs
    except Exception:
        return []


# ── Context compaction ──────────────────────────────────────────────────────

def compact_context(messages, system_msg):
    """When context gets long, summarize older messages to free space."""
    if len(messages) < 30:
        return messages

    # Keep system + last 16 messages. Summarize the rest.
    to_summarize = messages[1:-16]  # skip system at [0]
    to_keep = messages[-16:]

    summary_text = []
    for m in to_summarize:
        role = m.get("role", "?")
        content = m.get("content", "")[:200]
        if role == "user":
            summary_text.append(f"User asked: {content}")
        elif role == "assistant" and content:
            summary_text.append(f"Agent said: {content}")
        elif role == "tool":
            summary_text.append(f"Tool returned: {content}...")

    summary = "\n".join(summary_text[-20:])  # last 20 summary items max

    compacted_msg = {
        "role": "user",
        "content": f"[Context summary of earlier conversation:\n{summary}\n— end summary, conversation continues below —]"
    }

    return [system_msg, compacted_msg] + to_keep


# ── Display helpers ─────────────────────────────────────────────────────────

def print_tool_use(name, args):
    if name == "run_command":
        print(c(MAGENTA, f"  $ {args.get('command', '')}"))
    elif name == "read_file":
        extra = ""
        if args.get("start_line"):
            extra = f" :{args['start_line']}-{args.get('end_line', '')}"
        print(c(DIM, f"  Reading {args.get('path', '')}{extra}"))
    elif name == "edit_file":
        print(c(YELLOW, f"  Editing {args.get('path', '')}"))
    elif name == "write_file":
        print(c(GREEN, f"  Writing {args.get('path', '')}"))
    elif name == "search":
        inc = f" ({args['include']})" if args.get("include") else ""
        print(c(DIM, f"  Searching for /{args.get('pattern', '')}/{inc}"))
    elif name == "find_files":
        print(c(DIM, f"  Finding {args.get('pattern', '')}"))
    elif name == "diagnostics":
        print(c(DIM, f"  Diagnostics: {args.get('target', 'all')}"))


def print_tool_result(result, name):
    """Print a concise preview of tool output."""
    lines = result.split("\n")

    # For diffs (from edit_file), show the whole diff in color
    if name == "edit_file" and any(l.startswith("---") or l.startswith("+++") for l in lines[:5]):
        for line in lines[:40]:
            if line.startswith("+") and not line.startswith("+++"):
                print(c(GREEN, f"    {line}"))
            elif line.startswith("-") and not line.startswith("---"):
                print(c(RED, f"    {line}"))
            elif line.startswith("@@"):
                print(c(CYAN, f"    {line}"))
            else:
                print(c(DIM, f"    {line}"))
        if len(lines) > 40:
            print(c(DIM, f"    ... ({len(lines) - 40} more)"))
        return

    # For other tools, show compact preview
    preview_lines = lines[:8]
    for line in preview_lines:
        print(c(DIM, f"    {line[:120]}"))
    if len(lines) > 8:
        print(c(DIM, f"    ... ({len(lines) - 8} more lines)"))


# ── Agent loop ──────────────────────────────────────────────────────────────

def agent_turn(messages, system_msg):
    """Run one full agent turn: stream response, handle tool calls, loop until text reply."""
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        full_text = ""
        native_tool_calls = []
        got_error = False

        # Stream the response
        sys.stdout.write(f"\n")
        for event_type, data in ollama_stream(messages, tools=TOOLS):
            if event_type == "token":
                sys.stdout.write(data)
                sys.stdout.flush()
                full_text += data
            elif event_type == "tool_call":
                native_tool_calls.append(data)
            elif event_type == "error":
                print(c(RED, f"\n  Error: {data}"))
                got_error = True
                break

        if got_error:
            break

        # Check for tool calls — native first, then parse from text
        tool_calls = []

        if native_tool_calls:
            for tc in native_tool_calls:
                fn = tc.get("function", {})
                tool_calls.append((fn.get("name", ""), fn.get("arguments", {})))
            # Add assistant message with tool_calls for Ollama's conversation format
            messages.append({
                "role": "assistant",
                "content": full_text,
                "tool_calls": native_tool_calls,
            })
        else:
            # Try parsing tool calls from text
            parsed, cleaned_text = parse_tool_calls_from_text(full_text)
            if parsed:
                tool_calls = parsed
                messages.append({"role": "assistant", "content": full_text})
            else:
                # Pure text response — we're done
                if full_text.strip():
                    messages.append({"role": "assistant", "content": full_text})
                sys.stdout.write("\n")
                break

        if not tool_calls:
            sys.stdout.write("\n")
            break

        # Execute tool calls
        sys.stdout.write("\n")
        for name, args in tool_calls:
            print_tool_use(name, args)
            result = execute_tool(name, args)
            print_tool_result(result, name)

            messages.append({
                "role": "tool",
                "content": result,
            })

        # Compact if needed
        if len(messages) > 40:
            messages[:] = compact_context(messages, system_msg)

    if rounds >= MAX_TOOL_ROUNDS:
        print(c(YELLOW, f"\n  (Hit {MAX_TOOL_ROUNDS}-round safety limit. Say 'continue' to keep going.)"))

    return messages


# ── Main loop ───────────────────────────────────────────────────────────────

def check_ollama():
    """Verify Ollama is reachable and the model is available."""
    try:
        req = Request(f"{OLLAMA_URL}/api/tags")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        model_base = MODEL.split(":")[0]
        found = any(model_base in m for m in models)
        return True, found, models
    except Exception as e:
        return False, False, []


def interactive_loop():
    cwd = os.getcwd()
    project_ctx = gather_project_context()
    system_msg = {"role": "system", "content": SYSTEM_PROMPT.format(cwd=cwd, project_context=project_ctx)}

    # Load previous session or start fresh
    prior = load_session()
    messages = [system_msg] + prior

    # Power-aware model selection
    active_model, active_ctx, power_reason = get_active_model()

    print(f"\n{BOLD}{CYAN}  Scatter Code{RESET} {DIM}v0.2.0{RESET}")
    print(c(DIM, f"  Model: {active_model}"))
    print(c(DIM, f"  Dir:   {cwd}"))
    if power_reason:
        print(c(DIM, f"  Power: {power_reason}"))
    if project_ctx:
        for line in project_ctx.split("\n"):
            print(c(DIM, f"  {line}"))

    # Connection check
    running, has_model, models = check_ollama()
    if not running:
        print(c(RED, f"\n  Ollama is not running at {OLLAMA_URL}"))
        print(c(RED, f"  Start it: ollama serve"))
        print(c(DIM, f"  Then: ollama pull {MODEL}\n"))
        return
    if not has_model:
        print(c(YELLOW, f"\n  Model '{MODEL}' not found."))
        print(c(YELLOW, f"  Available: {', '.join(models) or 'none'}"))
        print(c(YELLOW, f"  Pull it: ollama pull {MODEL}\n"))
        return
    print(c(GREEN, f"  Ready.\n"))

    print(c(DIM, "  Commands: quit, clear, /save, /status"))
    print()

    while True:
        try:
            user_input = input(f"{GREEN}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            save_session(messages)
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "/q"):
            save_session(messages)
            print(c(DIM, "  Session saved."))
            break

        if user_input.lower() in ("clear", "/clear"):
            messages = [system_msg]
            print(c(DIM, "  Context cleared."))
            continue

        if user_input.lower() in ("/save",):
            save_session(messages)
            print(c(DIM, f"  Saved ({len(messages)-1} messages)."))
            continue

        if user_input.lower() in ("/status",):
            running, has_model, models = check_ollama()
            status = "connected" if running else "disconnected"
            print(c(DIM, f"  Ollama: {status}"))
            print(c(DIM, f"  Model: {MODEL} ({'loaded' if has_model else 'not found'})"))
            print(c(DIM, f"  Context: {len(messages)-1} messages"))
            print(c(DIM, f"  Dir: {os.getcwd()}"))
            continue

        messages.append({"role": "user", "content": user_input})
        messages = agent_turn(messages, system_msg)


def single_shot(prompt):
    """Run a single prompt, print the result, and exit."""
    cwd = os.getcwd()
    project_ctx = gather_project_context()
    system_msg = {"role": "system", "content": SYSTEM_PROMPT.format(cwd=cwd, project_context=project_ctx)}
    messages = [system_msg, {"role": "user", "content": prompt}]

    running, has_model, _ = check_ollama()
    if not running:
        print(c(RED, f"Ollama not running at {OLLAMA_URL}. Start it: ollama serve"), file=sys.stderr)
        sys.exit(1)
    if not has_model:
        print(c(RED, f"Model '{MODEL}' not found. Pull it: ollama pull {MODEL}"), file=sys.stderr)
        sys.exit(1)

    agent_turn(messages, system_msg)


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--version", "-v"):
            print("Scatter Code v0.2.0")
            return
        if arg in ("--check", "-c"):
            running, has_model, models = check_ollama()
            if running and has_model:
                print("OK")
            elif running:
                print(f"Ollama running but model '{MODEL}' missing. Available: {', '.join(models)}")
                sys.exit(1)
            else:
                print(f"Ollama not reachable at {OLLAMA_URL}")
                sys.exit(1)
            return
        if arg in ("--help", "-h"):
            print(textwrap.dedent(f"""\
                Scatter Code — local AI coding agent

                Usage:
                  scatter code                    Interactive mode
                  scatter code "fix the test"     Single-shot mode
                  scatter code --check            Health check
                  scatter code --version          Version

                Environment:
                  SCATTER_MODEL       Model name (default: {MODEL})
                  SCATTER_OLLAMA_URL  Ollama URL (default: {OLLAMA_URL})
                  SCATTER_CTX         Context window (default: {MAX_CONTEXT})
                  SCATTER_SESSIONS    Session dir (default: ~/.scatter/sessions)
            """))
            return

        # Anything else is a single-shot prompt
        prompt = " ".join(sys.argv[1:])
        single_shot(prompt)
        return

    interactive_loop()


if __name__ == "__main__":
    main()
