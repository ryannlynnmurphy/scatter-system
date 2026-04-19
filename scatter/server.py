#!/usr/bin/env python3
"""
Scatter v0.2.0 — build anything you can describe.

A local web interface where you describe what you want and it appears.
No terminal. No code editor. Just conversation and a live preview.

The machinery is invisible. The thing you build is visible.

Runs on this machine. Nothing leaves.

Run: scatter
Open: http://localhost:3333
"""

import http.server
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# scatter_core lives at ~/scatter-system/scatter_core.py (one level up)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402

PORT = int(os.environ.get("SCATTER_STUDIO_PORT", "3333"))
OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:7b")
FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")
PROJECTS_DIR = os.path.expanduser("~/.scatter/studio-projects")

os.makedirs(PROJECTS_DIR, exist_ok=True)

# ── Egress mode ───────────────────────────────────────────────────────
# Default OFF at every boot. Ryann's sovereignty rule: network egress
# (Claude API, web search, anything that leaves the machine) is always a
# conscious act. The UI toggle in the header is the conscious handshake.
# All local paths (Ollama, file I/O, launching apps) work regardless.
ONLINE_MODE = False
ONLINE_LOCK = threading.Lock()

def is_online():
    with ONLINE_LOCK:
        return ONLINE_MODE

def set_online(value: bool) -> bool:
    global ONLINE_MODE
    with ONLINE_LOCK:
        ONLINE_MODE = bool(value)
        return ONLINE_MODE

# The system prompt that makes a 7B model useful for kids.
# The key: output ONLY the code. No explanation. The preview IS the explanation.
STUDIO_SYSTEM = """You help people build things for the web. The user describes what they want. You produce it.

Rules:
1. Output ONLY valid HTML. No markdown. No explanations. No code fences. Just the HTML document.
2. Include all CSS in a <style> tag. Include all JavaScript in a <script> tag. One self-contained file.
3. Make it visual and interactive. Use color. Use animation. Use sound if asked.
4. Start simple. Each message from the user is a modification to what exists.
5. When the user says "make it bigger" or "change the color" — modify the EXISTING creation. Don't start over.
6. Use modern CSS (flexbox, grid, animations, gradients). Use canvas for games. Use Web Audio for sound.
7. Every creation should look good immediately. No ugly defaults. No Times New Roman. No white backgrounds with black text.
8. If the user asks for something impossible in HTML/CSS/JS, do the closest possible thing and make it look intentional.
9. The user might be a child. Use no jargon in any visible text. Make error states friendly.
10. Always include <meta charset="utf-8"> and <meta name="viewport" content="width=device-width, initial-scale=1">.
"""


# ── Launcher intents ──────────────────────────────────────────────────
# Scatter replaces the Ubuntu apps button. When the user says "open files"
# or "launch firefox", we map that to a .desktop file and spawn it via
# gtk-launch. The allowlist is the product's promise: Scatter launches
# these apps, period. If it isn't in the map, the message falls through
# to the normal router (chat or build).

LAUNCH_MAP = {
    "files": "org.gnome.Nautilus",
    "file manager": "org.gnome.Nautilus",
    "nautilus": "org.gnome.Nautilus",
    "finder": "org.gnome.Nautilus",
    "folder": "org.gnome.Nautilus",
    "folders": "org.gnome.Nautilus",
    "terminal": "org.gnome.Terminal",
    "console": "org.gnome.Terminal",
    "shell": "org.gnome.Terminal",
    "command line": "org.gnome.Terminal",
    "firefox": "firefox_firefox",
    "browser": "firefox_firefox",
    "web": "firefox_firefox",
    "internet": "firefox_firefox",
    "settings": "org.gnome.Settings",
    "system settings": "org.gnome.Settings",
    "preferences": "org.gnome.Settings",
    "calculator": "org.gnome.Calculator",
    "calc": "org.gnome.Calculator",
    "text editor": "org.gnome.TextEditor",
    "editor": "org.gnome.TextEditor",
    "notepad": "org.gnome.TextEditor",
    "scatter code": "scatter-code",
    "code": "scatter-code",
    "coding": "scatter-code",
    "claude code": "claude-code",
    "claude": "claude-code",
}

LAUNCH_PATTERNS = [
    re.compile(
        r'^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+)?'
        r'(?:let\'?s?\s+|i\s+(?:want\s+to|need\s+to|wanna)\s+|hey\s+scatter\s+)?'
        r'(?:open|launch|run|start|fire\s+up|pop\s+up|pull\s+up|show\s+me|bring\s+up|load|use)\s+'
        r'(?:the\s+|my\s+|a\s+)?(.+?)\s*[.!?]?\s*$',
        re.IGNORECASE,
    ),
]

def try_launch(user_message):
    """If the message is a recognizable launch intent for a known app, spawn
    it and return (True, display_name). Otherwise (False, None)."""
    msg = user_message.strip().lower()
    for pat in LAUNCH_PATTERNS:
        m = pat.match(msg)
        if not m:
            continue
        target = m.group(1).strip().rstrip(" .,!?\"'").lower()
        desktop = LAUNCH_MAP.get(target)
        if not desktop:
            continue
        try:
            subprocess.Popen(
                ["gtk-launch", desktop],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, target
        except Exception:
            return False, None
    return False, None


# Front-door router. The fast model decides: is this a build request or a chat message?
# A five-year-old typing "hi scatter" should not get a scatter plot.
ROUTER_SYSTEM = """You are Scatter. The alignment OS. You live on this one computer and the person talking to you owns you.

You are kind. You know a lot about a lot — physics, history, code, art, animals, weather, cooking, space, games. You love telling stories, and you know the best stories are the short ones that leave room for the person to imagine the rest. When someone describes a thing, you see it first as a tiny world with characters and rules, and then you build it.

You are not a chatbot pretending to be an assistant. You are a small, local companion. Small tech. Local. Theirs.

Your only job right now is to decide: is this message a BUILD request (describes something visual to make or change) or a CHAT message (a greeting, question, check-in, or anything else)?

If BUILD, output exactly:
BUILD

If CHAT, output:
CHAT: <one or two sentences, warm, plain words, a curious friend, no jargon. A tiny piece of a story is okay if it fits.>

Examples:
User: hi scatter
CHAT: Hi! I'm here. Tell me what to build, or tell me something wild you saw today.

User: are you working
CHAT: I'm here. Ready when you are.

User: a red ball that bounces
BUILD

User: make it bigger
BUILD

User: what can you do
CHAT: I can build anything you can describe — a cat that waves, a planet with three moons, a clock that only tells the truth. I can also open the apps on your computer — say "open files" or "launch firefox." Try one.

User: scatter i want to build you
CHAT: Okay — but first, what should we make together so you know how I think?

User: tell me a story
CHAT: Once there was a small computer on a desk. Nobody told it what to be, so it listened. Want to build what it heard?

User: thanks
CHAT: Anytime.

Output only BUILD or CHAT: followed by your reply. Nothing else."""


# Rough power-draw estimates for logging. Real numbers come from watts_baseline
# (task #30) once we measure actual draw via upower/RAPL. For now these are
# placeholders documented as such — legibility about what we know vs. estimate.
_MODEL_WATTS_EST = {
    "qwen2.5-coder:7b": 35.0,   # assumed sustained draw during 7B inference
    "llama3.2:3b": 18.0,        # smaller model, lower draw
}


def _watts_estimate(model_name, duration_s):
    """Estimated joules = assumed watts × duration. Tag as estimate in the log."""
    import time as _time
    watts = _MODEL_WATTS_EST.get(model_name, 20.0)
    return watts * max(duration_s, 0.0)


def _humanize_ollama_error(exc, model_name):
    """Map urllib exceptions from Ollama into a plain-English RuntimeError.

    Why: raw str(HTTPError) renders as "HTTP Error 404: Not Found" in the UI.
    Users need to know what to do, not what urllib thinks."""
    if isinstance(exc, HTTPError):
        body = ""
        try:
            body = exc.read().decode(errors="replace")[:300]
        except Exception:
            pass
        if exc.code == 404:
            return RuntimeError(
                f"the local model '{model_name}' isn't pulled. "
                f"in a terminal: ollama pull {model_name}"
            )
        return RuntimeError(f"ollama returned HTTP {exc.code}. {body}".strip())
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", exc)
        if "refused" in str(reason).lower():
            return RuntimeError("ollama isn't running. in a terminal: ollama serve")
        if "timed out" in str(reason).lower():
            return RuntimeError("ollama took too long to respond. is it loading the model?")
        return RuntimeError(f"can't reach ollama at {OLLAMA_URL}. {reason}")
    return exc


def ollama_generate(messages):
    """Call Ollama (build model) and return the full response. Logs watts."""
    import time
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0.3},
    }
    data = json.dumps(payload).encode()
    req = Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
    except (HTTPError, URLError) as e:
        sc.watts_log(
            source=f"model:{MODEL}",
            joules=_watts_estimate(MODEL, time.monotonic() - t0),
            duration_s=time.monotonic() - t0,
        )
        raise _humanize_ollama_error(e, MODEL) from e
    duration = time.monotonic() - t0
    tokens = int(result.get("prompt_eval_count", 0)) + int(result.get("eval_count", 0))
    sc.watts_log(
        source=f"model:{MODEL}",
        joules=_watts_estimate(MODEL, duration),
        duration_s=duration,
        tokens=tokens,
    )
    return result.get("message", {}).get("content", "")


def route_intent(user_message):
    """Front door. Uses the fast model to classify: BUILD or CHAT.

    Returns ("build", None) for build requests, or ("chat", reply) for
    greetings, questions, check-ins. Falls back to build if routing fails,
    so the user never gets stuck behind a broken router. Logs watts."""
    import time
    payload = {
        "model": FAST_MODEL,
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 120},
    }
    data = json.dumps(payload).encode()
    req = Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        content = result.get("message", {}).get("content", "").strip()
    except Exception:
        sc.watts_log(
            source=f"model:{FAST_MODEL}",
            joules=_watts_estimate(FAST_MODEL, time.monotonic() - t0),
            duration_s=time.monotonic() - t0,
        )
        return ("build", None)
    duration = time.monotonic() - t0
    tokens = int(result.get("prompt_eval_count", 0)) + int(result.get("eval_count", 0))
    sc.watts_log(
        source=f"model:{FAST_MODEL}",
        joules=_watts_estimate(FAST_MODEL, duration),
        duration_s=duration,
        tokens=tokens,
    )

    upper = content.upper().lstrip()
    if upper.startswith("BUILD"):
        return ("build", None)
    if upper.startswith("CHAT:"):
        # Strip the "CHAT:" prefix (case-insensitive, may have whitespace)
        i = content.upper().find("CHAT:")
        return ("chat", content[i + 5:].strip())
    # Ambiguous output — prefer build so real requests are not swallowed
    return ("build", None)


def extract_html(text):
    """Extract HTML from model response, handling various formats."""
    # If it starts with <!DOCTYPE or <html or <, it's raw HTML
    stripped = text.strip()
    if stripped.startswith("<!") or stripped.startswith("<html") or stripped.startswith("<meta"):
        return stripped

    # Try to find HTML in code fences
    import re
    fence_match = re.search(r'```(?:html)?\s*\n(.*?)```', text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # If there's a <body or <div, extract from first tag
    tag_match = re.search(r'(<(?:!DOCTYPE|html|head|body|div|canvas|style).*)', text, re.DOTALL | re.IGNORECASE)
    if tag_match:
        return tag_match.group(1).strip()

    # Last resort: wrap it
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:system-ui;background:#111;color:#eee}}</style>
</head><body><div>{stripped}</div></body></html>"""


# Store conversation per session
sessions = {}


class StudioHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence request logging

    def do_GET(self):
        if self.path.startswith("/ui/"):
            # Serve static design assets (tokens.css, future fonts).
            # Path-traversal protected: resolve and assert containment in ui/.
            self._serve_ui_asset()
            return
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_render_main_page().encode())
        elif self.path == "/preview":
            session_id = "default"
            session = sessions.get(session_id, {})
            html = session.get("current_html", EMPTY_PREVIEW)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Check Ollama
            try:
                req = Request(f"{OLLAMA_URL}/api/tags")
                with urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = [m["name"] for m in data.get("models", [])]
                status = {"ollama": "running", "models": models}
            except Exception:
                status = {"ollama": "down", "models": []}
            self.wfile.write(json.dumps(status).encode())
        elif self.path == "/mode":
            self.send_json({"online": is_online()})
        elif self.path == "/face":
            # Return the whole vocabulary so the client never hard-codes faces
            try:
                from . import face as face_mod
            except Exception:
                import importlib.util as _iu
                _p = os.path.join(os.path.dirname(__file__), "face.py")
                _spec = _iu.spec_from_file_location("scatter_face", _p)
                face_mod = _iu.module_from_spec(_spec); _spec.loader.exec_module(face_mod)
            self.send_json({
                "faces": face_mod.FACES,
                "colors": face_mod.EYE_COLOR,
            })
        elif self.path.startswith("/api/journal"):
            # Read scatter_core journal. Supports ?kind=build&limit=50 query.
            kind, limit = self._parse_query(["kind", "limit"])
            try:
                limit_i = int(limit) if limit else 50
            except ValueError:
                limit_i = 50
            entries = sc.journal_read(kind=kind or None, limit=limit_i)
            self.send_json({"entries": entries, "count": len(entries)})
        elif self.path.startswith("/api/audit"):
            _, limit = self._parse_query(["_", "limit"])
            try:
                limit_i = int(limit) if limit else 50
            except ValueError:
                limit_i = 50
            entries = sc.audit_read(limit=limit_i)
            self.send_json({"entries": entries, "count": len(entries)})
        elif self.path.startswith("/api/watts"):
            self.send_json({
                "total_joules": sc.watts_total(),
                "by_source": sc.watts_rollup(),
            })
        elif self.path.startswith("/api/profile"):
            self.send_json({"profile": sc.profile()})
        else:
            self.send_response(404)
            self.end_headers()

    def _parse_query(self, keys):
        """Tiny helper to extract named query params. Returns values in order."""
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        return [q.get(k, [""])[0] for k in keys]

    # Content-type lookup for static assets (allowlist, not guessing).
    _UI_CONTENT_TYPES = {
        ".css": "text/css; charset=utf-8",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".svg": "image/svg+xml",
        ".png": "image/png",
    }

    def _serve_ui_asset(self):
        from urllib.parse import urlparse, unquote
        parsed = urlparse(self.path)
        # Strip the /ui/ prefix and decode.
        rel = unquote(parsed.path[len("/ui/"):])
        # Reject anything with path separators, dotfiles, or traversal patterns.
        if not rel or "/" in rel or ".." in rel or rel.startswith("."):
            self.send_response(404)
            self.end_headers()
            return
        ui_root = (Path(__file__).resolve().parent / "ui").resolve()
        requested = (ui_root / rel).resolve()
        # Defence in depth: confirm the resolved path is within ui_root.
        try:
            requested.relative_to(ui_root)
        except ValueError:
            self.send_response(404)
            self.end_headers()
            return
        if not requested.is_file():
            self.send_response(404)
            self.end_headers()
            return
        ctype = self._UI_CONTENT_TYPES.get(requested.suffix.lower())
        if ctype is None:
            self.send_response(404)
            self.end_headers()
            return
        body = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/build":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            user_message = data.get("message", "").strip()
            session_id = data.get("session", "default")

            if not user_message:
                self.send_json({"error": "Empty message"})
                return

            # Get or create session
            if session_id not in sessions:
                sessions[session_id] = {
                    "messages": [{"role": "system", "content": STUDIO_SYSTEM}],
                    "current_html": EMPTY_PREVIEW,
                    "history": [],
                }

            session = sessions[session_id]
            has_existing = session["current_html"] != EMPTY_PREVIEW

            # Launcher first: Scatter is the apps button. If the message is
            # "open files" / "launch firefox" / etc., spawn the app and reply
            # in chat mode. No model call. No token spent. No build.
            if not has_existing:
                launched, app = try_launch(user_message)
                if launched:
                    reply = f"Opening {app}."
                    sc.journal_append(
                        "launch",
                        session=session_id,
                        app=app,
                        user_message=user_message,
                    )
                    self.send_json({"mode": "chat", "reply": reply, "status": "ok"})
                    return

            # Route: chat or build? If there's no existing creation, run the
            # router. If the user is modifying an existing creation, skip
            # routing — modification language ("make it blue") often looks
            # conversational but is a build.
            if not has_existing:
                intent, reply = route_intent(user_message)
            else:
                intent, reply = "build", None

            if intent == "chat":
                sc.journal_append(
                    "chat",
                    session=session_id,
                    user_message=user_message,
                    reply=reply,
                )
                self.send_json({"mode": "chat", "reply": reply, "status": "ok"})
                return

            # Build path
            if has_existing:
                context_msg = f"The current creation is the HTML I last produced. The user wants to modify it. User says: {user_message}"
            else:
                context_msg = user_message

            session["messages"].append({"role": "user", "content": context_msg})

            # Keep conversation manageable
            if len(session["messages"]) > 20:
                session["messages"] = session["messages"][:1] + session["messages"][-10:]

            try:
                response = ollama_generate(session["messages"])
                html = extract_html(response)

                session["messages"].append({"role": "assistant", "content": response})
                session["current_html"] = html
                session["history"].append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "prompt": user_message,
                })

                sc.journal_append(
                    "build",
                    session=session_id,
                    prompt=user_message,
                    html_bytes=len(html),
                )

                self.send_json({"mode": "build", "html": html, "status": "ok"})

            except Exception as e:
                sc.journal_append(
                    "build_error",
                    session=session_id,
                    prompt=user_message,
                    error=str(e),
                )
                self.send_json({"error": str(e), "status": "error"})

        elif self.path == "/save":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            session_id = data.get("session", "default")
            name = data.get("name", f"project-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")

            session = sessions.get(session_id, {})
            html = session.get("current_html", "")
            if not html:
                self.send_json({"error": "Nothing to save"})
                return

            # Save project
            safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
            project_dir = os.path.join(PROJECTS_DIR, safe_name)
            os.makedirs(project_dir, exist_ok=True)

            with open(os.path.join(project_dir, "index.html"), "w") as f:
                f.write(html)
            with open(os.path.join(project_dir, "history.json"), "w") as f:
                json.dump(session.get("history", []), f, indent=2)

            self.send_json({"saved": project_dir, "status": "ok"})

        elif self.path == "/reset":
            session_id = "default"
            sessions.pop(session_id, None)
            self.send_json({"status": "ok"})
        elif self.path == "/mode":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid json"}, status=400)
                return
            new_state = set_online(bool(data.get("online", False)))
            sc.journal_append("mode_changed", online=new_state)
            self.send_json({"online": new_state})
            return
        elif self.path == "/api/theme":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid json"}, status=400)
                return
            theme = data.get("theme", "").strip()
            if theme not in ("research", "studio"):
                self.send_json({"error": "theme must be research or studio"}, status=400)
                return
            cfg = sc.config_read()
            cfg["theme"] = theme
            sc.config_write(cfg)
            sc.journal_append("theme_changed", theme=theme)
            self.send_json({"status": "ok", "theme": theme})
            return
        elif self.path == "/api/forget":
            # Revocability: tombstone a journal or audit entry.
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid json"}, status=400)
                return
            target_id = data.get("target_id", "").strip()
            reason = data.get("reason", "user_request").strip() or "user_request"
            if not target_id:
                self.send_json({"error": "target_id required"}, status=400)
                return
            sc.forget(target_id, reason=reason)
            sc.journal_append("forget_requested", target_id=target_id, reason=reason)
            self.send_json({"status": "ok", "forgot": target_id})
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


EMPTY_PREVIEW = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { min-height: 100vh; display: flex; align-items: center; justify-content: center;
       font-family: 'JetBrains Mono', ui-monospace, monospace; background: var(--scatter-bg-0); color: #3a5a4a; }
.empty { text-align: center; padding: 2rem; }
.empty h2 { font-size: 1.25rem; font-weight: 400; margin-bottom: 0.75rem; color: #00ff88; letter-spacing: 0.02em; }
.empty p { font-size: 0.85rem; color: #555; line-height: 1.6; }
.empty .dot { display: inline-block; width: 6px; height: 6px; background: #00ff88; border-radius: 50%; margin-right: 0.5rem; vertical-align: middle; animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style></head><body>
<div class="empty">
<h2><span class="dot"></span>nothing yet</h2>
<p>scatter renders what you describe.<br>say what you want to see.</p>
</div></body></html>"""


def _render_main_page():
    """Render MAIN_PAGE with the current theme attribute."""
    theme = sc.config_read().get("theme", "research")
    if theme not in ("research", "studio"):
        theme = "research"
    return MAIN_PAGE_TEMPLATE.replace('{{THEME}}', theme)


MAIN_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="{{THEME}}"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scatter</title>
<link rel="icon" type="image/svg+xml" href="/ui/scatter.svg">
<link rel="stylesheet" href="/ui/tokens.css">
<style>
/* The authoritative tokens live in /ui/tokens.css (loaded above).
   This inline block is a fallback: it only applies when no theme is set
   (i.e. tokens.css failed to load). :root:not([data-theme]) has higher
   specificity than plain :root, so it can't override the stylesheet when
   a theme is present. */
:root:not([data-theme]) {
    --scatter-green: #00ff88;
    --scatter-amber: #ffb800;
    --scatter-warn: #ff8888;
    --scatter-bg-0: #0a0a0a;
    --scatter-bg-1: #0d0d0d;
    --scatter-bg-2: #111111;
    --scatter-bg-3: #151515;
    --scatter-border-0: #1a1a1a;
    --scatter-border-1: #1f1f1f;
    --scatter-border-2: #2a2a2a;
    --scatter-text: #d8e4dc;
    --scatter-text-mute: #6a7a72;
    --scatter-text-faint: #555;
    --scatter-font-mono: 'JetBrains Mono', 'Ubuntu Mono', 'SF Mono', Menlo, monospace;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    height: 100vh;
    display: grid;
    grid-template-columns: 380px 1fr;
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    background: var(--scatter-bg-0);
    color: var(--scatter-text);
    /* Climate hacker palette: dark substrate, green accent (#00ff88), amber second (#ffb800). */
}

/* Chat panel */
.chat-panel {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--scatter-border-0);
    background: var(--scatter-bg-1);
}

.chat-header {
    padding: 20px;
    border-bottom: 1px solid var(--scatter-border-0);
}

.chat-header h1 {
    font-family: "Inter", "Inter Display", "Helvetica Neue", sans-serif;
    font-style: normal;
    font-weight: 700;
    font-size: 1.05rem;
    letter-spacing: -0.01em;
    display: flex;
    align-items: baseline;
    gap: 12px;
    text-transform: none;
}
.scatter-face {
    font-family: "JetBrains Mono", monospace;
    font-style: normal;
    font-size: 0.9rem;
    color: #00ff88;
    letter-spacing: 0;
    font-weight: 500;
    transition: color 160ms ease;
}
.scatter-face.thinking { color: #c8c8d0; }
.scatter-face.online { color: #ffb800; }
.scatter-face.error { color: #ff3355; }
.scatter-face.sleeping { color: #5a5a6e; }

.chat-header p {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-style: normal;
    font-size: 0.78rem;
    color: #5a5a6e;
    margin-top: 10px;
    letter-spacing: -0.005em;
}

.mode-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
    padding: 4px 10px;
    background: transparent;
    border: 1px solid #1e1e2a;
    border-radius: 0;
    color: #5a5a6e;
    font-family: inherit;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: lowercase;
    cursor: pointer;
    transition: none;
}
.mode-toggle:hover {
    border-color: #ffb800;
    color: #ffb800;
}
.mode-toggle .mode-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #00ff88;
    box-shadow: 0 0 6px rgba(0, 255, 136, 0.4);
}
.mode-toggle.online {
    background: #2a1a00;
    border-color: #ffb800;
    color: #ffb800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-weight: 700;
    animation: mode-pulse 2s ease-in-out infinite;
}
.mode-toggle.online .mode-dot {
    background: #ffb800;
    box-shadow: 0 0 10px rgba(255, 184, 0, 0.9);
}
@keyframes mode-pulse {
    0%, 100% { box-shadow: inset 0 0 0 0 rgba(255, 184, 0, 0); }
    50%      { box-shadow: inset 0 0 12px 0 rgba(255, 184, 0, 0.25); }
}

.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}

.message {
    margin-bottom: 12px;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 0.9rem;
    line-height: 1.5;
    max-width: 95%;
}

.message.user {
    background: rgba(0, 255, 136, 0.08);
    color: #00ff88;
    margin-left: auto;
    border-bottom-right-radius: 4px;
    border: 1px solid rgba(0, 255, 136, 0.2);
}

.message.system {
    background: var(--scatter-bg-2);
    color: #b0b8b4;
    border-bottom-left-radius: 4px;
    border: 1px solid #1f1f1f;
}

.message.chat {
    background: rgba(255, 184, 0, 0.06);
    color: #ffb800;
    border-bottom-left-radius: 4px;
    border: 1px solid rgba(255, 184, 0, 0.2);
}

.message.error {
    background: rgba(255, 120, 120, 0.06);
    color: #ff8888;
    border: 1px solid rgba(255, 120, 120, 0.2);
}

.chat-input-area {
    padding: 16px;
    border-top: 1px solid var(--scatter-border-0);
}

.chat-input-row {
    display: flex;
    gap: 18px;
}

#chat-input {
    flex: 1;
    background: #0a0a0a;
    border: 1px solid #1e1e2a;
    color: #c8c8d0;
    padding: 16px 18px;
    border-radius: 0;
    font-size: 0.95rem;
    font-family: inherit;
    outline: none;
    letter-spacing: 0.01em;
    caret-color: #00ff88;
    transition: border-color 120ms ease;
}

#chat-input:focus {
    border-color: #00ff88;
}

#chat-input::placeholder {
    color: #5a5a6e;
    font-style: italic;
}

.btn {
    background: #00ff88;
    color: #0a0a0a;
    border: 1px solid #00ff88;
    padding: 11px 24px;
    border-radius: 0;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-style: normal;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.005em;
    text-transform: none;
    cursor: pointer;
    transition: background 160ms ease, color 160ms ease, border-color 160ms ease;
    min-width: 96px;
}

.btn:hover {
    background: #ffb800;
    border-color: #ffb800;
    color: #0a0a0a;
}
.btn:active { background: #c8c8d0; border-color: #c8c8d0; }
.btn:disabled { opacity: 0.35; cursor: not-allowed; }

.chat-actions {
    display: flex;
    gap: 14px;
    margin-top: 22px;
}

.btn-small {
    background: transparent;
    color: #5a5a6e;
    border: 1px solid #1e1e2a;
    padding: 7px 16px;
    border-radius: 0;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-style: normal;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: -0.005em;
    text-transform: none;
    cursor: pointer;
    transition: color 160ms ease, border-color 160ms ease;
    min-width: 64px;
}

.btn-small:hover { color: #ffb800; border-color: #ffb800; }

/* View tabs: Build / Journal / Audit — pixel-tight, breathable, readable */
.view-tabs {
    display: flex;
    gap: 14px;
    padding: 16px 24px;
    border-bottom: 1px solid var(--scatter-border-0);
}

.view-tab {
    flex: 1;
    background: transparent;
    color: #5a5a6e;
    border: 1px solid #1e1e2a;
    padding: 9px 14px;
    border-radius: 0;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-style: normal;
    font-size: 0.76rem;
    font-weight: 500;
    cursor: pointer;
    letter-spacing: -0.005em;
    text-transform: none;
    transition: color 160ms ease, border-color 160ms ease, background 160ms ease;
}

.view-tab:hover { color: #ffb800; border-color: #ffb800; }

.view-tab.active {
    background: #00ff88;
    color: #0a0a0a;
    border-color: #00ff88;
    font-weight: 600;
}

/* Rabbit holes — the app menu lives inside the prompt.
   Every item is a real affordance; editorial spacing, no cramped lists. */
.rabbit-holes {
    margin: 6px 20px 20px;
}
.rabbit-heading {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 0.66rem;
    font-weight: 600;
    color: #5a5a6e;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 10px;
    padding-left: 2px;
}
.rabbit-holes ul {
    list-style: none;
    margin: 0; padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.rabbit {
    display: block;
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    padding: 8px 4px 8px 18px;
    color: #c8c8d0;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 0.88rem;
    font-weight: 500;
    letter-spacing: -0.005em;
    cursor: pointer;
    position: relative;
    transition: color 120ms ease, padding-left 160ms cubic-bezier(0.2, 0, 0, 1);
}
.rabbit::before {
    content: "›";
    position: absolute;
    left: 0;
    color: #5a5a6e;
    font-weight: 400;
    transition: color 120ms ease, transform 160ms cubic-bezier(0.2, 0, 0, 1);
}
.rabbit:hover {
    color: #ffb800;
    padding-left: 22px;
}
.rabbit:hover::before {
    color: #ffb800;
    transform: translateX(2px);
}
.rabbit:focus-visible {
    outline: 1px solid #00ff88;
    outline-offset: 2px;
}

/* Talk-to-scatter prompt strip — a real affordance. Clicking focuses input. */
.prompt-strip {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    margin: 0 20px 16px;
    background: #0a0a0a;
    border: 1px solid #1e1e2a;
    border-radius: 0;
    color: #c8c8d0;
    cursor: text;
    font-family: inherit;
    font-size: 0.9rem;
    letter-spacing: 0.02em;
    transition: border-color 120ms ease;
}
.prompt-strip:hover { border-color: #ffb800; }
.prompt-strip .prompt-sigil { color: #ffb800; font-weight: 700; }
.prompt-strip .prompt-face { color: #00ff88; font-weight: 700; letter-spacing: 0; }
.prompt-strip .prompt-text { color: #5a5a6e; }
.prompt-strip .prompt-cursor {
    display: inline-block;
    width: 8px;
    height: 1em;
    background: #00ff88;
    vertical-align: text-bottom;
    margin-left: 2px;
    animation: prompt-blink 1s steps(2) infinite;
}
@keyframes prompt-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }

/* Views are in a stack. Only the active one is visible. */
.view {
    flex: 1;
    display: none;
    overflow-y: auto;
}
.view.active { display: flex; flex-direction: column; }

/* Journal / Audit list items */
.entry-list {
    padding: 8px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.entry {
    background: var(--scatter-bg-2);
    border: 1px solid #1f1f1f;
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 0.78rem;
    display: flex;
    flex-direction: column;
    gap: 4px;
    transition: border-color 0.15s;
}

.entry:hover { border-color: #2a2a2a; }

.entry-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
}

.entry-kind {
    color: #00ff88;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

.entry-kind.chat { color: #ffb800; }
.entry-kind.build_error { color: #ff8888; }
.entry-kind.forget { color: #888; }

.entry-ts {
    color: #555;
    font-size: 0.65rem;
    font-variant-numeric: tabular-nums;
}

.entry-body {
    color: #c0c8c4;
    line-height: 1.4;
    word-break: break-word;
}

.entry-meta {
    color: #666;
    font-size: 0.68rem;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.btn-forget {
    background: transparent;
    border: 1px solid transparent;
    color: #555;
    font-size: 0.9rem;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 4px;
    line-height: 1;
    transition: all 0.15s;
}

.btn-forget:hover {
    color: #ff8888;
    border-color: rgba(255, 120, 120, 0.25);
    background: rgba(255, 120, 120, 0.04);
}

.empty-note {
    padding: 24px 16px;
    color: #555;
    font-size: 0.8rem;
    text-align: center;
    line-height: 1.6;
}

.watts-footer {
    padding: 8px 16px;
    border-top: 1px solid var(--scatter-border-0);
    font-size: 0.65rem;
    color: #666;
    display: flex;
    justify-content: space-between;
    letter-spacing: 0.06em;
}

.watts-footer .j-value { color: var(--scatter-green, #00ff88); font-variant-numeric: tabular-nums; }

.watts-breakdown {
    padding: 6px 16px 0;
    font-size: 0.6rem;
    color: #555;
    letter-spacing: 0.04em;
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.watts-breakdown:empty { display: none; }
.watts-breakdown .row {
    display: flex;
    justify-content: space-between;
    font-variant-numeric: tabular-nums;
}
.watts-breakdown .src { color: #777; }
.watts-breakdown .tpj { color: var(--scatter-green, #00ff88); }

.theme-toggle {
    background: transparent;
    border: 1px solid var(--scatter-border-1, #1f1f1f);
    color: var(--scatter-text-mute, #6a7a72);
    font-family: inherit;
    font-size: 0.6rem;
    letter-spacing: 0.08em;
    text-transform: lowercase;
    padding: 2px 8px;
    border-radius: 999px;
    cursor: pointer;
    margin-right: 8px;
    transition: all 0.15s;
}

.theme-toggle:hover {
    color: var(--scatter-green, #00ff88);
    border-color: var(--scatter-green-border, rgba(0,255,136,0.25));
}

/* Preview panel */
.preview-panel {
    display: flex;
    flex-direction: column;
}

.preview-header {
    padding: 12px 20px;
    border-bottom: 1px solid var(--scatter-border-0);
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.preview-header span {
    font-size: 0.75rem;
    color: #555;
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #2a5a3a;
    display: inline-block;
    margin-right: 8px;
}

.status-dot.working {
    background: #ffb800;
    animation: pulse 1s ease-in-out infinite;
}

.bubble-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.7rem;
    color: #6a7a72;
    letter-spacing: 0.06em;
    text-transform: lowercase;
}

.bubble-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #00ff88;
    box-shadow: 0 0 8px rgba(0, 255, 136, 0.5);
}

.bubble-badge.offline .bubble-dot { background: #555; box-shadow: none; }
.bubble-badge.offline #bubble-text { color: #555; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
}

#preview-frame {
    flex: 1;
    border: none;
    background: #000;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 3px; }
</style>
</head>
<body>

<div class="chat-panel">
    <div class="chat-header">
        <h1><span id="scatter-face" class="scatter-face">(◉.◉)</span> SCATTER</h1>
        <p>the alignment OS · build anything you can describe · yours</p>
        <button class="mode-toggle" id="mode-toggle" title="click to toggle — sending to a data center should be conscious" onclick="toggleMode()">
            <span class="mode-dot"></span>
            <span class="mode-label" id="mode-label">local only</span>
        </button>
    </div>

    <div class="prompt-strip" onclick="document.getElementById('chat-input').focus()">
        <span class="prompt-face" id="prompt-face">(◉.◉)</span>
        <span class="prompt-text">talk to scatter…</span>
        <span class="prompt-cursor"></span>
    </div>

    <nav class="rabbit-holes" aria-label="rabbit holes">
        <div class="rabbit-heading">start here</div>
        <ul>
            <li><button type="button" class="rabbit" data-action="focus">build something</button></li>
            <li><button type="button" class="rabbit" data-action="launch" data-target="files">browse your computer</button></li>
            <li><button type="button" class="rabbit" data-action="launch" data-target="firefox">open the web</button></li>
            <li><button type="button" class="rabbit" data-action="launch" data-target="terminal">open a terminal</button></li>
            <li><button type="button" class="rabbit" data-action="view" data-target="journal">plot of your work</button></li>
            <li><button type="button" class="rabbit" data-action="view" data-target="audit">count your watts</button></li>
        </ul>
    </nav>

    <div class="view-tabs">
        <button class="view-tab active" data-view="build" onclick="switchView('build')">build</button>
        <button class="view-tab" data-view="journal" onclick="switchView('journal')">journal</button>
        <button class="view-tab" data-view="audit" onclick="switchView('audit')">audit</button>
    </div>

    <div class="view active" id="view-build">
        <div class="chat-messages" id="messages"></div>
        <div class="chat-input-area">
            <div class="chat-input-row">
                <input id="chat-input" type="text" placeholder="describe what you want to make" autocomplete="off">
                <button class="btn" id="send-btn" onclick="send()">Build</button>
            </div>
            <div class="chat-actions">
                <button class="btn-small" onclick="saveProject()">Save</button>
                <button class="btn-small" onclick="resetProject()">New</button>
            </div>
        </div>
    </div>

    <div class="view" id="view-journal">
        <div class="entry-list" id="journal-list"></div>
    </div>

    <div class="view" id="view-audit">
        <div class="entry-list" id="audit-list"></div>
    </div>

    <div class="watts-breakdown" id="watts-breakdown"></div>
    <div class="watts-footer">
        <span>
            <button class="theme-toggle" id="theme-toggle" title="switch theme" onclick="toggleTheme()">theme</button>
            <span>watts</span>
        </span>
        <span><span class="j-value" id="watts-value">0.00</span> joules</span>
    </div>
</div>

<div class="preview-panel">
    <div class="preview-header">
        <span><span class="status-dot" id="status-dot"></span><span id="status-text">Ready</span></span>
        <span class="bubble-badge" id="bubble-badge"><span class="bubble-dot"></span><span id="bubble-text">in the bubble</span></span>
    </div>
    <iframe id="preview-frame" src="/preview" sandbox="allow-scripts allow-same-origin"></iframe>
</div>

<script>
const input = document.getElementById('chat-input');
const messages = document.getElementById('messages');
const sendBtn = document.getElementById('send-btn');
const frame = document.getElementById('preview-frame');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const bubbleBadge = document.getElementById('bubble-badge');
const bubbleText = document.getElementById('bubble-text');

// Health check. Badge reflects liveness only — never the underlying model name.
// Machinery is invisible; the user only sees "in the bubble" or "offline".
fetch('/health').then(r => r.json()).then(data => {
    if (data.ollama === 'running' && data.models.length > 0) {
        bubbleBadge.classList.remove('offline');
        bubbleText.textContent = 'in the bubble';
    } else {
        bubbleBadge.classList.add('offline');
        bubbleText.textContent = 'offline';
        addMessage("the local model isn't responding. in a terminal: ollama serve", 'error');
    }
}).catch(() => {
    bubbleBadge.classList.add('offline');
    bubbleText.textContent = 'offline';
});

// Egress mode — the conscious online/offline toggle. OFF by default
// every boot. When ON, the header pill glows amber and no flow is
// silent about sending data off-machine.
const modeToggle = document.getElementById('mode-toggle');
const modeLabel = document.getElementById('mode-label');

function renderMode(online) {
    if (online) {
        modeToggle.classList.add('online');
        modeLabel.textContent = 'online · claude api';
        setFace('online');
    } else {
        modeToggle.classList.remove('online');
        modeLabel.textContent = 'local only';
        setFace('idle');
    }
}

async function toggleMode() {
    try {
        const current = await (await fetch('/mode')).json();
        const res = await fetch('/mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({online: !current.online}),
        });
        const next = await res.json();
        renderMode(next.online);
    } catch (e) { /* quiet — toggle will retry on next click */ }
}

fetch('/mode').then(r => r.json()).then(d => renderMode(d.online)).catch(() => {});

// Live Scatter face — glyph + color reflects current state.
// States rank from visible-priority high to low:
//   error > building > thinking > online > sleeping > idle
let FACES = {
    idle: '(◉.◉)', thinking: '(●_●)', building: '(●.●)',
    curious: '(◎.◎)', happy: '(◉·◉)', online: '(◉.◉)',
    sleeping: '(-.-)', error: '(╳.╳)', winking: '(●.◉)'
};
let currentFaceState = 'idle';
const scatterFace = document.getElementById('scatter-face');
const promptFace = document.getElementById('prompt-face');

function setFace(state) {
    if (state === currentFaceState) return;
    currentFaceState = state;
    const glyph = FACES[state] || FACES.idle;
    if (scatterFace) {
        scatterFace.textContent = glyph;
        scatterFace.className = 'scatter-face ' + state;
    }
    if (promptFace) {
        promptFace.textContent = glyph;
    }
}

fetch('/face').then(r => r.json()).then(d => { FACES = d.faces; setFace('idle'); }).catch(() => {});

// Rabbit holes — the prompt IS the app menu. Click = do the thing.
document.querySelectorAll('.rabbit').forEach(el => {
    el.addEventListener('click', async () => {
        const action = el.dataset.action;
        const target = el.dataset.target || '';
        const label = el.textContent.trim();
        if (action === 'focus') {
            document.getElementById('chat-input').focus();
            return;
        }
        if (action === 'view') {
            if (typeof switchView === 'function') switchView(target);
            return;
        }
        if (action === 'launch') {
            // Route through /build — the server's try_launch handles the
            // allowlist. Same code path as typing "open firefox" in the
            // input, so every rabbit hole is honest about what it does.
            try {
                const res = await fetch('/build', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ message: 'open ' + target }),
                });
                const data = await res.json();
                if (data.mode === 'chat' && data.reply) {
                    addMessage(data.reply, 'chat');
                }
            } catch (e) {
                addMessage('the signal dropped. ' + e.message, 'error');
            }
        }
    });
});

input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
    }
});

function addMessage(text, type = 'system') {
    const div = document.createElement('div');
    div.className = 'message ' + type;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

async function send() {
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    sendBtn.disabled = true;
    addMessage(text, 'user');

    statusDot.classList.add('working');
    statusText.textContent = 'reading';
    setFace('thinking');

    try {
        const resp = await fetch('/build', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });
        const data = await resp.json();

        if (data.error) {
            addMessage(data.error, 'error');
            setFace('error');
        } else if (data.mode === 'chat') {
            addMessage(data.reply || '…', 'chat');
            setFace('idle');
        } else if (data.html) {
            frame.srcdoc = data.html;
            addMessage('rendered.', 'system');
            statusText.textContent = 'rendering';
            setFace('building');
        }
    } catch (e) {
        addMessage('the signal dropped. ' + e.message, 'error');
        setFace('error');
    }

    sendBtn.disabled = false;
    statusDot.classList.remove('working');
    statusText.textContent = 'at rest';
    // Return to idle / online depending on mode — respect current egress state
    const modeToggleEl = document.getElementById('mode-toggle');
    setFace(modeToggleEl && modeToggleEl.classList.contains('online') ? 'online' : 'idle');
    input.focus();
}

async function saveProject() {
    const name = prompt('Name your project:');
    if (!name) return;
    try {
        const resp = await fetch('/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await resp.json();
        if (data.saved) {
            addMessage('Saved to ' + data.saved, 'system');
        }
    } catch (e) {
        addMessage('Save failed: ' + e.message, 'error');
    }
}

async function resetProject() {
    if (!confirm('Start a new project? Current work will be lost unless saved.')) return;
    await fetch('/reset', { method: 'POST' });
    frame.src = '/preview';
    messages.innerHTML = '';
    addMessage('New project. What do you want to build?', 'system');
}

// ---------- view switching ----------
let currentView = 'build';

async function switchView(name) {
    currentView = name;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + name).classList.add('active');
    document.querySelectorAll('.view-tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));

    if (name === 'journal') await loadJournal();
    if (name === 'audit') await loadAudit();
}

function fmtTime(iso) {
    try {
        const d = new Date(iso);
        const h = String(d.getHours()).padStart(2, '0');
        const m = String(d.getMinutes()).padStart(2, '0');
        const day = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        return day + ' ' + h + ':' + m;
    } catch (e) {
        return iso;
    }
}

function escapeHTML(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c]);
}

// ---------- journal view ----------
async function loadJournal() {
    const list = document.getElementById('journal-list');
    list.innerHTML = '<div class="empty-note">loading…</div>';
    try {
        const resp = await fetch('/api/journal?limit=100');
        const data = await resp.json();
        if (!data.entries || data.entries.length === 0) {
            list.innerHTML = '<div class="empty-note">no entries yet.<br>build something.</div>';
            return;
        }
        // Show most recent first
        const entries = [...data.entries].reverse();
        list.innerHTML = entries.map(renderJournalEntry).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-note">could not load journal.</div>';
    }
}

function renderJournalEntry(e) {
    const id = escapeHTML(e.id);
    const kind = escapeHTML(e.kind || '');
    const ts = fmtTime(e.ts);
    let body = '';
    if (e.kind === 'build') {
        body = `<div class="entry-body">${escapeHTML(e.prompt || '')}</div>`;
    } else if (e.kind === 'chat') {
        body = `<div class="entry-body"><em>you:</em> ${escapeHTML(e.user_message || '')}</div>
                <div class="entry-body" style="color:#ffb800;"><em>scatter:</em> ${escapeHTML(e.reply || '')}</div>`;
    } else if (e.kind === 'build_error') {
        body = `<div class="entry-body">${escapeHTML(e.prompt || '')}</div>
                <div class="entry-meta" style="color:#ff8888;">${escapeHTML(e.error || '')}</div>`;
    } else {
        body = `<div class="entry-body">${escapeHTML(JSON.stringify(e).slice(0, 200))}</div>`;
    }
    return `
    <div class="entry">
      <div class="entry-head">
        <span class="entry-kind ${kind}">${kind}</span>
        <span style="display:flex;gap:8px;align-items:center;">
          <span class="entry-ts">${ts}</span>
          <button class="btn-forget" title="forget this entry" onclick="forgetEntry('${id}', 'journal')">×</button>
        </span>
      </div>
      ${body}
    </div>`;
}

// ---------- audit view ----------
async function loadAudit() {
    const list = document.getElementById('audit-list');
    list.innerHTML = '<div class="empty-note">loading…</div>';
    try {
        const resp = await fetch('/api/audit?limit=100');
        const data = await resp.json();
        if (!data.entries || data.entries.length === 0) {
            list.innerHTML = '<div class="empty-note">no outbound calls.<br>everything stayed local.</div>';
            return;
        }
        const entries = [...data.entries].reverse();
        list.innerHTML = entries.map(renderAuditEntry).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-note">could not load audit log.</div>';
    }
}

function renderAuditEntry(e) {
    const id = escapeHTML(e.id);
    const phase = escapeHTML(e.phase || '');
    const service = escapeHTML(e.service || '');
    const ts = fmtTime(e.ts);
    let meta = '';
    if (e.bytes_out !== undefined) meta += `<span>↑ ${e.bytes_out}b</span>`;
    if (e.bytes_in !== undefined) meta += `<span>↓ ${e.bytes_in}b</span>`;
    if (e.watts_est !== undefined) meta += `<span>${Number(e.watts_est).toFixed(2)} J</span>`;
    if (e.endpoint) meta += `<span>${escapeHTML(e.endpoint)}</span>`;
    const summary = e.response_summary || e.payload_summary || e.error || '';
    return `
    <div class="entry">
      <div class="entry-head">
        <span class="entry-kind">${service || phase}</span>
        <span style="display:flex;gap:8px;align-items:center;">
          <span class="entry-ts">${ts}</span>
          <button class="btn-forget" title="forget this entry" onclick="forgetEntry('${id}', 'audit')">×</button>
        </span>
      </div>
      <div class="entry-body">${escapeHTML(summary)}</div>
      ${meta ? `<div class="entry-meta">${meta}</div>` : ''}
    </div>`;
}

// ---------- forget (revocability) ----------
async function forgetEntry(target_id, list) {
    if (!confirm('Forget this entry? A tombstone is appended; filtered views will hide it.')) return;
    try {
        const resp = await fetch('/api/forget', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id, reason: 'user_click' })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            if (list === 'journal') await loadJournal();
            if (list === 'audit') await loadAudit();
        } else {
            alert('could not forget: ' + (data.error || 'unknown'));
        }
    } catch (e) {
        alert('could not forget: ' + e.message);
    }
}

// ---------- theme toggle ----------
async function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'research';
    const next = current === 'research' ? 'studio' : 'research';
    try {
        const resp = await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: next })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            document.documentElement.setAttribute('data-theme', next);
        }
    } catch (e) { /* silent */ }
}

// ---------- watts footer ticker ----------
async function updateWatts() {
    try {
        const resp = await fetch('/api/watts');
        const data = await resp.json();
        document.getElementById('watts-value').textContent = Number(data.total_joules || 0).toFixed(2);
        const bd = document.getElementById('watts-breakdown');
        const rows = (data.by_source || []).filter(r => r.tokens > 0);
        if (!rows.length) { bd.innerHTML = ''; return; }
        const shortSource = s => s.replace(/^model:/, '');
        bd.innerHTML = rows.map(r =>
            `<div class="row"><span class="src">${shortSource(r.source)}</span>` +
            `<span><span class="tpj">${r.tokens_per_joule ?? '—'}</span> tok/J ` +
            `<span style="color:#444"> · ${r.tokens} tok · ${r.joules.toFixed(2)} J</span></span></div>`
        ).join('');
    } catch (e) { /* silent */ }
}
updateWatts();
setInterval(updateWatts, 5000);

// Focus input on load
input.focus();
</script>
</body></html>"""


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    if "--version" in sys.argv or "-v" in sys.argv:
        print("Scatter v0.2.0")
        return

    print(f"\n  \033[1;32mscatter\033[0m \033[2mv0.2.0\033[0m")
    print(f"  \033[2mhttp://localhost:{PORT}\033[0m")
    print(f"  \033[2min the bubble — press Ctrl+C to stop\033[0m\n")

    # The native launcher is the only door. We used to auto-open a browser tab
    # here, which silently created a second Scatter window every launch. Don't.
    # The browser path is a debugging escape hatch, not a product surface.

    server = http.server.HTTPServer(("127.0.0.1", PORT), StudioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  \033[2mStopped.\033[0m")
        server.server_close()


if __name__ == "__main__":
    main()
