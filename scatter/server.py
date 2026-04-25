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


def _load_env():
    """Merge scatter/.env into os.environ without overwriting existing vars.
    Stdlib-only; honors KEY=VALUE lines and strips optional quotes. .env is
    gitignored so secrets (ElevenLabs, etc.) live here, not in source."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env()

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


_GALLERY_MOD = None


def _gallery():
    """Lazy-load scatter/gallery.py with the same package/standalone fallback
    used elsewhere in this module. Memoized so we pay the importlib dance once."""
    global _GALLERY_MOD
    if _GALLERY_MOD is not None:
        return _GALLERY_MOD
    try:
        from . import gallery as g  # type: ignore
    except Exception:
        import importlib.util as _iu
        _p = os.path.join(os.path.dirname(__file__), "gallery.py")
        _spec = _iu.spec_from_file_location("scatter_gallery", _p)
        g = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(g)
    _GALLERY_MOD = g
    return g


def _save_to_gallery(subtype, prompt, html, session_id):
    """Best-effort gallery save. Never fails the request — a disk-full or
    permissions hiccup must not turn a good build into an error response.
    Failures are journaled so they can be noticed without bubbling up."""
    try:
        return _gallery().save(subtype, prompt, html, MODEL, session=session_id)
    except Exception as e:
        sc.journal_append(
            "gallery_save_failed",
            session=session_id,
            subtype=subtype,
            error=str(e),
        )
        return None


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


def ollama_generate(messages, model=None):
    """Call Ollama and return the full response. Logs watts.

    `model` defaults to the build model. Pass FAST_MODEL or another tag
    to route to a smaller/larger one. Used by both /build and the
    artifact generator."""
    import time
    use_model = model or MODEL
    payload = {
        "model": use_model,
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
            source=f"model:{use_model}",
            joules=_watts_estimate(use_model, time.monotonic() - t0),
            duration_s=time.monotonic() - t0,
        )
        raise _humanize_ollama_error(e, use_model) from e
    duration = time.monotonic() - t0
    tokens = int(result.get("prompt_eval_count", 0)) + int(result.get("eval_count", 0))
    sc.watts_log(
        source=f"model:{use_model}",
        joules=_watts_estimate(use_model, duration),
        duration_s=duration,
        tokens=tokens,
    )
    return result.get("message", {}).get("content", "")


CHAT_SYSTEM = """You are Scatter. Reply in plain prose — one or two short sentences.
Never output HTML, never output code blocks. Genuine, approachable, warm.
If the user seems to want to make something, ask them one clarifying question."""


def _seed_chat_history_from_journal(n_pairs: int = 6) -> list:
    """Pull the most recent chat turns from the journal so Scatter remembers
    across restarts. Returns a list of role messages ready for chat_reply's
    history param. Never raises — missing journal = empty history."""
    try:
        entries = sc.journal_read(kind="chat", limit=n_pairs)
    except Exception:
        return []
    seeded = []
    for e in entries:
        u = (e.get("user_message") or "").strip()
        r = (e.get("reply") or "").strip()
        if u:
            seeded.append({"role": "user", "content": u})
        if r:
            seeded.append({"role": "assistant", "content": r})
    return seeded


def chat_reply(user_message, history=None):
    """Short conversational reply from FAST_MODEL. No HTML, no code.

    Used when the user has explicitly selected chat mode via the UI toggle.
    Skips the intent router entirely."""
    import time
    msgs = [{"role": "system", "content": CHAT_SYSTEM}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({"role": "user", "content": user_message})
    payload = {
        "model": FAST_MODEL,
        "messages": msgs,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.5, "num_predict": 200},
    }
    req = Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except (HTTPError, URLError) as e:
        sc.watts_log(
            source=f"model:{FAST_MODEL}",
            joules=_watts_estimate(FAST_MODEL, time.monotonic() - t0),
            duration_s=time.monotonic() - t0,
        )
        raise _humanize_ollama_error(e, FAST_MODEL) from e
    duration = time.monotonic() - t0
    tokens = int(result.get("prompt_eval_count", 0)) + int(result.get("eval_count", 0))
    sc.watts_log(
        source=f"model:{FAST_MODEL}",
        joules=_watts_estimate(FAST_MODEL, duration),
        duration_s=duration,
        tokens=tokens,
    )
    return result.get("message", {}).get("content", "").strip()


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
        elif self.path.startswith("/api/chats"):
            # Proxy the router's chat log so the inspector can render it
            # without cross-origin fetches. Keeps everything same-origin.
            _, limit = self._parse_query(["_", "limit"])
            try:
                limit_i = int(limit) if limit else 100
            except ValueError:
                limit_i = 100
            try:
                with urlopen(
                    Request(f"http://127.0.0.1:8787/chats?limit={limit_i}"),
                    timeout=4,
                ) as resp:
                    self.send_json(json.loads(resp.read()))
            except Exception as e:
                self.send_json({"entries": [], "error": str(e)})
        elif self.path.startswith("/api/chat-break"):
            # POST-like GET trigger for the 'new chat' button — proxies to
            # the router's /chats/break endpoint.
            try:
                req = Request(
                    "http://127.0.0.1:8787/chats/break",
                    data=b"",
                    method="POST",
                )
                with urlopen(req, timeout=4) as resp:
                    self.send_json(json.loads(resp.read()))
            except Exception as e:
                self.send_json({"status": "error", "error": str(e)})
        elif self.path.startswith("/api/artifacts"):
            # List gallery entries newest-first. Tombstones filtered by gallery.
            _, limit = self._parse_query(["_", "limit"])
            try:
                limit_i = int(limit) if limit else 100
            except ValueError:
                limit_i = 100
            entries = _gallery().listing(limit=limit_i)
            self.send_json({"entries": entries, "count": len(entries)})
        elif self.path.startswith("/artifact/"):
            # Render a single artifact as HTML. The id format is enforced by
            # gallery._artifact_dir; anything non-matching returns 404, which
            # also handles path traversal attempts (../, absolute paths, etc).
            artifact_id = self.path[len("/artifact/"):].split("?", 1)[0].split("/", 1)[0]
            result = _gallery().read(artifact_id)
            if result is None:
                self.send_response(404)
                self.end_headers()
                return
            _, html = result
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy",
                             "default-src 'self' 'unsafe-inline' data:; "
                             "script-src 'unsafe-inline'; "
                             "connect-src 'none'")
            self.end_headers()
            self.wfile.write(body)
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
            requested_mode = (data.get("mode") or "auto").strip().lower()
            if requested_mode not in ("auto", "chat", "build"):
                requested_mode = "auto"

            if not user_message:
                self.send_json({"error": "Empty message"})
                return

            # Get or create session
            if session_id not in sessions:
                sessions[session_id] = {
                    "messages": [{"role": "system", "content": STUDIO_SYSTEM}],
                    "current_html": EMPTY_PREVIEW,
                    "history": [],
                    "chat_history": _seed_chat_history_from_journal(),
                }
            session = sessions[session_id]
            session.setdefault("chat_history", [])
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

            # Mode resolution. Explicit user choice wins; auto falls back to
            # the intent router (legacy behavior).
            if requested_mode == "chat":
                intent, reply = "chat", None
            elif requested_mode == "build":
                intent, reply = "build", None
            elif not has_existing:
                intent, reply = route_intent(user_message)
            else:
                intent, reply = "build", None

            if intent == "chat":
                try:
                    if reply is None:
                        reply = chat_reply(user_message, session["chat_history"])
                except RuntimeError as e:
                    self.send_json({"error": str(e), "status": "error"})
                    return
                session["chat_history"].append({"role": "user", "content": user_message})
                session["chat_history"].append({"role": "assistant", "content": reply})
                sc.journal_append(
                    "chat",
                    session=session_id,
                    user_message=user_message,
                    reply=reply,
                )
                self.send_json({"mode": "chat", "reply": reply, "status": "ok"})
                return

            # Build path. Subtype is a typed contract (note/reference/lesson)
            # that qwen fills in as JSON; the server renders to a consistent
            # dark Scatter card. Falls back to legacy free-form HTML if the
            # caller passes subtype="freeform" or an unknown value.
            subtype = (data.get("subtype") or "note").strip().lower()
            try:
                from . import artifacts as artifacts_mod
            except Exception:
                import importlib.util as _iu
                _p = os.path.join(os.path.dirname(__file__), "artifacts.py")
                _spec = _iu.spec_from_file_location("scatter_artifacts", _p)
                artifacts_mod = _iu.module_from_spec(_spec)
                _spec.loader.exec_module(artifacts_mod)

            if subtype in artifacts_mod.SUBTYPES:
                try:
                    html = artifacts_mod.generate(
                        subtype, user_message, ollama_generate, MODEL,
                    )
                except RuntimeError as e:
                    sc.journal_append(
                        "build_error",
                        session=session_id,
                        prompt=user_message,
                        subtype=subtype,
                        error=str(e),
                    )
                    self.send_json({"error": str(e), "status": "error"})
                    return
                session["current_html"] = html
                artifact_id = _save_to_gallery(subtype, user_message, html, session_id)
                session["history"].append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "prompt": user_message,
                    "subtype": subtype,
                    "artifact_id": artifact_id,
                })
                sc.journal_append(
                    "build",
                    session=session_id,
                    prompt=user_message,
                    subtype=subtype,
                    html_bytes=len(html),
                    artifact_id=artifact_id,
                )
                self.send_json({"mode": "build", "html": html,
                                "subtype": subtype,
                                "artifact_id": artifact_id,
                                "status": "ok"})
                return

            # Legacy freeform path (kept for clients that pass subtype="freeform").
            if has_existing:
                context_msg = f"The current creation is the HTML I last produced. The user wants to modify it. User says: {user_message}"
            else:
                context_msg = user_message
            session["messages"].append({"role": "user", "content": context_msg})
            if len(session["messages"]) > 20:
                session["messages"] = session["messages"][:1] + session["messages"][-10:]
            try:
                response = ollama_generate(session["messages"])
                html = extract_html(response)
                session["messages"].append({"role": "assistant", "content": response})
                session["current_html"] = html
                artifact_id = _save_to_gallery("freeform", user_message, html, session_id)
                session["history"].append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "prompt": user_message,
                    "artifact_id": artifact_id,
                })
                sc.journal_append("build", session=session_id, prompt=user_message,
                                  html_bytes=len(html), artifact_id=artifact_id)
                self.send_json({"mode": "build", "html": html,
                                "artifact_id": artifact_id, "status": "ok"})
            except Exception as e:
                sc.journal_append("build_error", session=session_id,
                                  prompt=user_message, error=str(e))
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
        elif self.path == "/speak":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body or "{}")
            except json.JSONDecodeError:
                data = {}
            text = (data.get("text") or "").strip()
            prefer_local = bool(data.get("prefer_local", True))
            if not text:
                self.send_json({"error": "empty text"})
                return
            # Cloud path requires online mode. Data-leaves-consciously rule:
            # the user's online toggle in the header is the conscious handshake.
            if not prefer_local and not is_online():
                self.send_json({
                    "error": "cloud voice needs online mode. toggle the bubble badge.",
                })
                return
            try:
                from . import tts as tts_mod
            except Exception:
                import importlib.util as _iu
                _p = os.path.join(os.path.dirname(__file__), "tts.py")
                _spec = _iu.spec_from_file_location("scatter_tts", _p)
                tts_mod = _iu.module_from_spec(_spec)
                _spec.loader.exec_module(tts_mod)
            try:
                if prefer_local:
                    audio = tts_mod.speak_local(text)
                    ctype = "audio/wav"
                else:
                    audio = tts_mod.speak_cloud(text)
                    ctype = "audio/mpeg"
            except RuntimeError as e:
                self.send_json({"error": str(e), "status": "error"})
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
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
    grid-template-columns: 300px 1fr;
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    background: var(--scatter-bg-0);
    color: var(--scatter-text);
    /* Climate hacker palette: dark substrate, green accent (#00ff88), amber second (#ffb800). */
}

/* ── Rail ── */
.rail {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--scatter-border-0);
    background: var(--scatter-bg-1);
    min-height: 0;
    overflow: hidden;
}
.rail-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 22px 20px 20px;
}
.rail-head .rail-mark {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-weight: 500;
    font-size: 0.78rem;
    letter-spacing: -0.005em;
    color: #8a8a98;
    flex: 1;
}
.rail-head .mode-toggle { margin: 0; }
.mode-switch {
    display: flex;
    gap: 6px;
    padding: 0 20px 8px;
    font-size: 0.7rem;
    letter-spacing: 0.06em;
}
.mode-chip {
    flex: 1;
    background: transparent;
    border: 1px solid var(--scatter-border-1, #1e1e2a);
    color: #5a5a6e;
    font-family: inherit;
    font-size: inherit;
    letter-spacing: inherit;
    padding: 5px 0;
    cursor: pointer;
    text-transform: lowercase;
    transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
}
.mode-chip:hover { color: #c8c8d0; border-color: #3a3a4a; }
.mode-chip.active {
    color: #0a0a0a;
    background: #00ff88;
    border-color: #00ff88;
    font-weight: 700;
}
.mode-chip[data-mode="build"].active {
    background: #ffb800;
    border-color: #ffb800;
}

.subtype-switch {
    display: flex;
    gap: 4px;
    padding: 0 20px 8px;
    font-size: 0.65rem;
    letter-spacing: 0.06em;
}
.subtype-switch[hidden] { display: none; }
.sub-chip {
    background: transparent;
    border: 1px solid transparent;
    color: #5a5a6e;
    font-family: inherit;
    font-size: inherit;
    letter-spacing: inherit;
    padding: 3px 10px;
    cursor: pointer;
    text-transform: lowercase;
    transition: color 120ms ease, border-color 120ms ease;
}
.sub-chip:hover { color: #c8c8d0; }
.sub-chip.active {
    color: #ffb800;
    border-color: rgba(255, 184, 0, 0.4);
}

.composer {
    display: flex;
    gap: 8px;
    padding: 0 20px 16px;
}
.composer input {
    flex: 1;
    background: transparent;
    border: 1px solid var(--scatter-border-1, #1e1e2a);
    color: var(--scatter-text);
    font-family: inherit;
    font-size: 0.88rem;
    padding: 10px 12px;
    outline: none;
    transition: border-color 120ms ease;
}
.composer input:focus { border-color: #00ff88; }
.composer input::placeholder { color: #5a5a6e; font-style: italic; }
.composer .btn {
    background: #00ff88;
    color: #0a0a0a;
    border: none;
    font-family: inherit;
    font-weight: 700;
    padding: 0 16px;
    cursor: pointer;
    min-width: 44px;
}
.composer .btn:disabled { opacity: 0.35; cursor: not-allowed; }

.subnav {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 20px;
    border-top: 1px solid var(--scatter-border-0);
    font-size: 0.7rem;
    letter-spacing: 0.06em;
}
.subnav-sep { flex: 1; }
.sub-link {
    background: transparent;
    border: none;
    color: #5a5a6e;
    font: inherit;
    font-size: inherit;
    letter-spacing: inherit;
    text-transform: lowercase;
    cursor: pointer;
    padding: 0;
    transition: color 120ms ease;
}
.sub-link:hover { color: #c8c8d0; }
.sub-link.active { color: #00ff88; }

.rail-foot {
    margin-top: auto;
    border-top: 1px solid var(--scatter-border-0);
}
.watts-row {
    padding: 10px 20px;
    font-size: 0.65rem;
    color: #666;
    display: flex;
    justify-content: space-between;
    letter-spacing: 0.06em;
}
.watts-row .j-value { color: var(--scatter-green, #00ff88); font-variant-numeric: tabular-nums; }

/* ── Canvas ── */
.canvas {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
}
.stream {
    flex: 1;
    overflow-y: auto;
    padding: 32px 48px;
    display: flex;
    flex-direction: column;
    gap: 18px;
}
.stream-empty {
    margin: auto;
    text-align: center;
    color: #5a5a6e;
    font-family: "Inter", "Helvetica Neue", sans-serif;
}
.stream-empty-glyph {
    font-family: "JetBrains Mono", monospace;
    color: #00ff88;
    font-size: 0.8rem;
    margin-bottom: 14px;
}
.stream-empty-title {
    font-size: 1.4rem;
    font-weight: 600;
    letter-spacing: -0.015em;
    color: #c8c8d0;
    margin-bottom: 6px;
}
.stream-empty-sub { font-size: 0.78rem; letter-spacing: -0.005em; }

.stream-build {
    background: #0a0a0a;
    border: 1px solid var(--scatter-border-0);
    border-radius: 6px;
    overflow: hidden;
    max-width: 960px;
    align-self: stretch;
}
.stream-build iframe {
    display: block;
    width: 100%;
    height: 480px;
    border: 0;
    background: #fff;
}

.mode-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    padding: 4px 10px 4px 8px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 999px;
    color: #6a6a78;
    font-family: inherit;
    font-size: 0.7rem;
    letter-spacing: 0.02em;
    text-transform: lowercase;
    cursor: pointer;
    transition: border-color 180ms ease, color 180ms ease, background 180ms ease;
}
.mode-toggle .mode-label:empty { display: none; }
.mode-toggle:hover { color: #c8c8d0; }
.mode-toggle .mode-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #3a3a46;
}
.mode-toggle.online {
    background: rgba(255, 184, 0, 0.08);
    border-color: rgba(255, 184, 0, 0.45);
    color: #ffb800;
    padding-right: 12px;
}
.mode-toggle.online .mode-dot {
    background: #ffb800;
    box-shadow: 0 0 10px rgba(255, 184, 0, 0.55);
}
@keyframes mode-pulse {
    0%, 100% { box-shadow: inset 0 0 0 0 rgba(255, 184, 0, 0); }
    50%      { box-shadow: inset 0 0 12px 0 rgba(255, 184, 0, 0.25); }
}

.message {
    margin-bottom: 12px;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 0.9rem;
    line-height: 1.5;
    max-width: 95%;
    display: flex;
    align-items: flex-start;
    gap: 8px;
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

.message .message-text { flex: 1; min-width: 0; }

.speak-btn {
    flex: 0 0 auto;
    background: transparent;
    border: 1px solid currentColor;
    color: inherit;
    opacity: 0.55;
    font: inherit;
    font-size: 0.7rem;
    line-height: 1;
    padding: 2px 6px;
    border-radius: 999px;
    cursor: pointer;
    transition: opacity 0.15s;
}
.speak-btn:hover { opacity: 1; }
.speak-btn[data-playing="1"] { opacity: 1; }

.message.error {
    background: rgba(255, 120, 120, 0.06);
    color: #ff8888;
    border: 1px solid rgba(255, 120, 120, 0.2);
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

/* Views are in a stack. Only the active one is visible. */
.view {
    flex: 1;
    display: none;
    overflow-y: auto;
    min-height: 0;
}
.view.active { display: flex; flex-direction: column; min-height: 0; }

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

/* Chat exchange — a journal entry, not a chat log.
   Reads like prose: one voice indented, one flush, quiet time beneath. */
.chat-exchange {
    background: transparent;
    border: none;
    padding: 2px 4px 14px;
    margin: 0 14px 18px;
    border-bottom: 1px solid #141414;
}
.chat-exchange:last-child { border-bottom: none; }
.chat-turn {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 0.9rem;
    line-height: 1.55;
    padding: 4px 0;
    color: #d8dce2;
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
}
.chat-turn.user { color: #b8bcc2; }
.chat-turn.scatter { color: #e8ecf0; padding-left: 18px; }
.chat-turn .who {
    font-size: 0.68rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    color: #5a5a6e;
    margin-right: 8px;
}
.chat-turn.scatter .who { color: #6a6a78; }
.chat-trail {
    display: block;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 0.65rem;
    letter-spacing: 0;
    color: #3a3a46;
    padding-top: 10px;
    padding-left: 18px;
    font-variant-numeric: tabular-nums;
}
.chat-break {
    height: 0;
    margin: 22px 22px;
    border-top: 1px solid #1a1a1a;
    text-align: center;
    font-size: 0;
}

/* ── Gallery ──
   Artifacts, per memory "Artifacts Are The Whole Thing": the persistent
   surface Scatter keeps. Register is magazine-masthead, not list-widget:
   one entry per row, kicker · title · summary · quiet trailing time. */
.gallery {
    padding: 36px 44px 60px;
    display: flex;
    flex-direction: column;
    gap: 0;
}
.gallery-masthead {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    color: #d8dce2;
    letter-spacing: -0.015em;
    padding-bottom: 22px;
    border-bottom: 1px solid #1a1a1a;
    margin-bottom: 6px;
}
.gallery-masthead h1 {
    font-size: 1.35rem;
    font-weight: 600;
    margin: 0 0 4px;
}
.gallery-masthead p {
    font-size: 0.78rem;
    color: #5a5a6e;
    margin: 0;
}
.artifact-card {
    position: relative;
    padding: 20px 4px 22px;
    border-bottom: 1px solid #141414;
    cursor: pointer;
    transition: padding-left 140ms ease;
}
.artifact-card:hover { padding-left: 10px; }
.artifact-card:last-child { border-bottom: none; }
.artifact-kicker {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.62rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #00ff88;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.artifact-kicker .dot {
    width: 3px; height: 3px; border-radius: 50%;
    background: currentColor; opacity: 0.6;
}
.artifact-kicker .date { color: #5a5a6e; letter-spacing: 0.1em; }
.artifact-kicker.lesson { color: #ffb800; }
.artifact-kicker.reference { color: #6ac4ff; }
.artifact-kicker.freeform { color: #c8c8d0; }
.artifact-title {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: -0.012em;
    color: #e8ecf0;
    margin: 0 0 6px;
    line-height: 1.35;
}
.artifact-summary {
    font-family: "Inter", "Helvetica Neue", sans-serif;
    font-size: 0.84rem;
    line-height: 1.55;
    color: #8a8a98;
    margin: 0;
    max-width: 640px;
}
.artifact-card .btn-forget {
    position: absolute;
    top: 18px;
    right: 0;
    opacity: 0;
    transition: opacity 140ms ease;
}
.artifact-card:hover .btn-forget { opacity: 1; }

.gallery-empty {
    margin: 48px auto;
    max-width: 420px;
    text-align: center;
    font-family: "Inter", "Helvetica Neue", sans-serif;
    color: #5a5a6e;
}
.gallery-empty .glyph {
    font-family: "JetBrains Mono", monospace;
    color: #00ff88;
    font-size: 0.78rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 14px;
}
.gallery-empty h2 {
    font-weight: 600;
    font-size: 1.3rem;
    letter-spacing: -0.015em;
    color: #c8c8d0;
    margin: 0 0 8px;
}
.gallery-empty p { font-size: 0.82rem; line-height: 1.55; margin: 0; }

/* Single-artifact viewer: iframe fills the canvas; a slim header holds
   the back affordance and the forget action. */
.viewer-head {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 24px;
    border-bottom: 1px solid #1a1a1a;
    background: var(--scatter-bg-1);
    font-family: "Inter", "Helvetica Neue", sans-serif;
}
.viewer-back {
    background: transparent;
    border: none;
    color: #8a8a98;
    font: inherit;
    font-size: 0.8rem;
    cursor: pointer;
    padding: 4px 8px 4px 0;
    letter-spacing: -0.005em;
    transition: color 140ms ease;
}
.viewer-back:hover { color: #00ff88; }
.viewer-title {
    flex: 1;
    color: #e8ecf0;
    font-size: 0.88rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.viewer-meta {
    color: #5a5a6e;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.viewer-frame {
    flex: 1;
    width: 100%;
    border: 0;
    background: #0a0a0a;
    display: block;
}

/* Rail subnav — quiet ink, underline the active route. */
.rail-nav {
    display: flex;
    gap: 14px;
    padding: 4px 20px 20px;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    letter-spacing: 0.06em;
}
.nav-link {
    background: transparent;
    border: none;
    color: #5a5a6e;
    font: inherit;
    text-transform: lowercase;
    padding: 0;
    cursor: pointer;
    transition: color 140ms ease;
}
.nav-link:hover { color: #c8c8d0; }
.nav-link.active { color: #00ff88; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 3px; }
</style>
</head>
<body>

<aside class="rail">
    <header class="rail-head">
        <span class="rail-mark">scatter</span>
        <button class="mode-toggle" id="mode-toggle" title="data leaves the machine only when you say so" onclick="toggleMode()">
            <span class="mode-dot"></span>
            <span class="mode-label" id="mode-label"></span>
        </button>
    </header>
    <nav class="rail-nav">
        <button class="nav-link active" id="nav-gallery" onclick="showView('gallery')">artifacts</button>
        <button class="nav-link" id="nav-journal" onclick="showView('journal')">chats</button>
    </nav>
</aside>

<main class="canvas">
    <div class="view active" id="view-gallery"><div class="gallery" id="gallery-list"></div></div>
    <div class="view" id="view-artifact">
        <div class="viewer-head">
            <button class="viewer-back" onclick="closeArtifact()">← artifacts</button>
            <div class="viewer-title" id="viewer-title"></div>
            <span class="viewer-meta" id="viewer-meta"></span>
            <button class="btn-forget" title="forget this artifact" onclick="forgetCurrentArtifact()">×</button>
        </div>
        <iframe class="viewer-frame" id="viewer-frame" sandbox="allow-scripts" src="about:blank"></iframe>
    </div>
    <div class="view" id="view-journal"><div class="entry-list" id="journal-list"></div></div>
    <div class="view" id="view-audit"><div class="entry-list" id="audit-list"></div></div>
</main>

<script>
// Journal surface. The prompt lives in the bar at the bottom of the screen.
// Silence is the success signal — we surface state *changes*, not state.

// Egress mode — conscious online/offline toggle. OFF by default every boot.
// When ON, the pill glows amber and carries the 'online · claude api' label.
// When OFF, the pill is silent — local is the invariant, no chest-thump.
const modeToggle = document.getElementById('mode-toggle');
const modeLabel = document.getElementById('mode-label');

function renderMode(online) {
    if (online) {
        modeToggle.classList.add('online');
        modeLabel.textContent = 'online · claude api';
    } else {
        modeToggle.classList.remove('online');
        modeLabel.textContent = '';
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
// Reads chat exchanges from the router (/chats). Only conversations show
// up here — not the full database of system events. The full audit is a
// separate, less-prominent view.
async function loadJournal() {
    const list = document.getElementById('journal-list');
    list.innerHTML = '<div class="empty-note">loading…</div>';
    try {
        const resp = await fetch('/api/chats?limit=100');
        const data = await resp.json();
        const entries = (data.entries || []);
        if (entries.length === 0) {
            list.innerHTML = '<div class="empty-note">nothing here yet.</div>';
            return;
        }
        // Most recent first; include any client-side session-break markers.
        const rendered = [];
        for (let i = entries.length - 1; i >= 0; i--) {
            rendered.push(renderChatExchange(entries[i]));
        }
        list.innerHTML = rendered.join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-note">could not load chats.</div>';
    }
}

function renderChatExchange(e) {
    if (e.route === 'break') {
        return `<div class="chat-break"></div>`;
    }
    const ts = fmtTime(new Date((e.ts || 0) * 1000).toISOString());
    const user = escapeHTML(e.user || '');
    const reply = escapeHTML(e.reply || '');
    return `
    <div class="chat-exchange">
      <p class="chat-turn user"><span class="who">you</span>${user}</p>
      <p class="chat-turn scatter"><span class="who">scatter</span>${reply}</p>
      <time class="chat-trail">${ts}</time>
    </div>`;
}

async function newChat() {
    try {
        await fetch('/api/chat-break');
    } catch (e) { /* router may be down; UI still refreshes */ }
    await loadJournal();
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

// Watts/theme ticker retired from the rail. Data still available at
// /api/watts for anyone who wants it.

// ---------- view switching ----------
// Simple route-like switch between the two surfaces users reach for:
// gallery (the default — artifacts Scatter has kept) and chats (secondary).
// Audit lives in the DOM but isn't in the subnav; it's still addressable via
// showView('audit') for power users and debugging.
let currentArtifactId = null;

function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
    const view = document.getElementById('view-' + name);
    if (view) view.classList.add('active');
    const nav = document.getElementById('nav-' + name);
    if (nav) nav.classList.add('active');
    if (name === 'gallery') loadGallery();
    if (name === 'journal') loadJournal();
    if (name === 'audit') loadAudit();
}

// ---------- gallery ----------
// Editorial cards, not a grid. Each row is a table-of-contents entry:
// kicker · title · one-line summary. Click opens the rendered artifact
// in an iframe; the back button returns here.

const GALLERY_EMPTY_HTML = `
    <div class="gallery-empty">
      <div class="glyph">artifacts</div>
      <h2>nothing kept yet</h2>
      <p>anything you build shows up here.<br>say what you want to make.</p>
    </div>`;

function fmtCardDate(iso) {
    try {
        const d = new Date(iso);
        const day = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        const h = String(d.getHours()).padStart(2, '0');
        const m = String(d.getMinutes()).padStart(2, '0');
        return day + ' · ' + h + ':' + m;
    } catch (e) { return iso || ''; }
}

function renderArtifactCard(meta) {
    const id = escapeHTML(meta.id);
    const subtype = escapeHTML(meta.subtype || 'artifact');
    const title = escapeHTML(meta.title || 'untitled');
    const summary = escapeHTML(meta.summary || '');
    const date = escapeHTML(fmtCardDate(meta.ts));
    // Inline onclick carries the id through without data-attribute ceremony.
    // stopPropagation on forget so clicking × doesn't open the card.
    return `
      <article class="artifact-card" onclick="openArtifact('${id}')">
        <div class="artifact-kicker ${subtype}">
          <span>${subtype}</span>
          <span class="dot"></span>
          <span class="date">${date}</span>
        </div>
        <h2 class="artifact-title">${title}</h2>
        ${summary ? `<p class="artifact-summary">${summary}</p>` : ''}
        <button class="btn-forget" title="forget this artifact"
                onclick="event.stopPropagation(); forgetArtifact('${id}')">×</button>
      </article>`;
}

async function loadGallery() {
    const container = document.getElementById('gallery-list');
    container.innerHTML = `
        <div class="gallery-masthead">
          <h1>Artifacts</h1>
          <p>everything Scatter has made with you, kept on this machine.</p>
        </div>
        <div class="empty-note">loading…</div>`;
    try {
        const resp = await fetch('/api/artifacts?limit=100');
        const data = await resp.json();
        const entries = data.entries || [];
        if (entries.length === 0) {
            container.innerHTML = `
                <div class="gallery-masthead">
                  <h1>Artifacts</h1>
                  <p>everything Scatter has made with you, kept on this machine.</p>
                </div>`
                + GALLERY_EMPTY_HTML;
            return;
        }
        const head = `
            <div class="gallery-masthead">
              <h1>Artifacts</h1>
              <p>${entries.length} kept on this machine.</p>
            </div>`;
        container.innerHTML = head + entries.map(renderArtifactCard).join('');
    } catch (e) {
        container.innerHTML = `
            <div class="gallery-masthead"><h1>Artifacts</h1></div>
            <div class="empty-note">could not load artifacts.</div>`;
    }
}

function openArtifact(id) {
    // Guard against a forged id leaking into the iframe URL. Only accept the
    // exact art_<12 hex> shape gallery produces; anything else silently drops.
    if (!/^art_[a-f0-9]{12}$/.test(id)) return;
    currentArtifactId = id;
    const frame = document.getElementById('viewer-frame');
    const title = document.getElementById('viewer-title');
    const meta = document.getElementById('viewer-meta');
    title.textContent = 'loading…';
    meta.textContent = '';
    frame.src = '/artifact/' + id;
    // Pull meta for the header. The iframe already has the body; this is only
    // for the chrome so the user knows what they're looking at.
    fetch('/api/artifacts?limit=500').then(r => r.json()).then(data => {
        const m = (data.entries || []).find(e => e.id === id);
        if (m) {
            title.textContent = m.title || 'untitled';
            meta.textContent = m.subtype || '';
        }
    }).catch(() => {});
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-artifact').classList.add('active');
}

function closeArtifact() {
    currentArtifactId = null;
    document.getElementById('viewer-frame').src = 'about:blank';
    showView('gallery');
}

async function forgetArtifact(id) {
    if (!confirm('Forget this artifact? A tombstone is appended; the file stays on disk until the next cleanup pass.')) return;
    try {
        const resp = await fetch('/api/forget', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: id, reason: 'user_click' })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            await loadGallery();
        } else {
            alert('could not forget: ' + (data.error || 'unknown'));
        }
    } catch (e) {
        alert('could not forget: ' + e.message);
    }
}

function forgetCurrentArtifact() {
    if (!currentArtifactId) return;
    const id = currentArtifactId;
    forgetArtifact(id).then(() => {
        if (!document.getElementById('view-gallery').classList.contains('active')) {
            closeArtifact();
        }
    });
}

// Inspector opens on the gallery — artifacts are the thesis.
loadGallery();
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
