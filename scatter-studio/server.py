#!/usr/bin/env python3
"""
Scatter Studio v0.1.0 — Build things by talking.

A local web interface where you describe what you want to see
and it appears. No terminal. No code editor. Just conversation
and a live preview of the thing you're making.

The AI is invisible. The thing you build is visible.

Run: scatter studio
Open: http://localhost:3333
"""

import http.server
import json
import os
import sys
import threading
import webbrowser
import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

PORT = int(os.environ.get("SCATTER_STUDIO_PORT", "3333"))
OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:7b")
FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")
PROJECTS_DIR = os.path.expanduser("~/.scatter/studio-projects")

os.makedirs(PROJECTS_DIR, exist_ok=True)

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


def ollama_generate(messages):
    """Call Ollama and return the full response."""
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
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
    return result.get("message", {}).get("content", "")


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
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(MAIN_PAGE.encode())
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
        else:
            self.send_response(404)
            self.end_headers()

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

            # Add context about current creation if it exists
            if session["current_html"] != EMPTY_PREVIEW:
                context_msg = f"The current creation is the HTML I last produced. The user wants to modify it. User says: {user_message}"
            else:
                context_msg = user_message

            session["messages"].append({"role": "user", "content": context_msg})

            # Keep conversation manageable
            if len(session["messages"]) > 20:
                # Keep system + last 10 exchanges
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

                self.send_json({"html": html, "status": "ok"})

            except Exception as e:
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
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


EMPTY_PREVIEW = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { min-height: 100vh; display: flex; align-items: center; justify-content: center;
       font-family: system-ui, -apple-system, sans-serif; background: #0a0a0a; color: #555; }
.empty { text-align: center; }
.empty h2 { font-size: 1.5rem; font-weight: 300; margin-bottom: 0.5rem; color: #333; }
.empty p { font-size: 0.9rem; color: #444; }
</style></head><body>
<div class="empty">
<h2>Describe what you want to build</h2>
<p>Type something like "a red ball that bounces" or "a clock"</p>
</div></body></html>"""


MAIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scatter Studio</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    height: 100vh;
    display: grid;
    grid-template-columns: 380px 1fr;
    font-family: system-ui, -apple-system, sans-serif;
    background: #0a0a0a;
    color: #e0e0e0;
}

/* Chat panel */
.chat-panel {
    display: flex;
    flex-direction: column;
    border-right: 1px solid #1a1a1a;
    background: #0d0d0d;
}

.chat-header {
    padding: 20px;
    border-bottom: 1px solid #1a1a1a;
}

.chat-header h1 {
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: 0.05em;
}

.chat-header p {
    font-size: 0.75rem;
    color: #555;
    margin-top: 4px;
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
    background: #1a3a2a;
    color: #a0e0b0;
    margin-left: auto;
    border-bottom-right-radius: 4px;
}

.message.system {
    background: #1a1a2a;
    color: #a0a0e0;
    border-bottom-left-radius: 4px;
}

.message.error {
    background: #2a1a1a;
    color: #e0a0a0;
}

.chat-input-area {
    padding: 16px;
    border-top: 1px solid #1a1a1a;
}

.chat-input-row {
    display: flex;
    gap: 8px;
}

#chat-input {
    flex: 1;
    background: #151515;
    border: 1px solid #2a2a2a;
    color: #e0e0e0;
    padding: 12px 16px;
    border-radius: 12px;
    font-size: 0.9rem;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
}

#chat-input:focus {
    border-color: #3a5a4a;
}

#chat-input::placeholder {
    color: #444;
}

.btn {
    background: #1a3a2a;
    color: #a0e0b0;
    border: none;
    padding: 12px 20px;
    border-radius: 12px;
    font-size: 0.85rem;
    cursor: pointer;
    font-family: inherit;
    transition: background 0.2s;
}

.btn:hover { background: #2a4a3a; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.chat-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
}

.btn-small {
    background: #151515;
    color: #666;
    border: 1px solid #2a2a2a;
    padding: 6px 12px;
    border-radius: 8px;
    font-size: 0.75rem;
    cursor: pointer;
    font-family: inherit;
    transition: all 0.2s;
}

.btn-small:hover { color: #aaa; border-color: #444; }

/* Preview panel */
.preview-panel {
    display: flex;
    flex-direction: column;
}

.preview-header {
    padding: 12px 20px;
    border-bottom: 1px solid #1a1a1a;
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
    background: #5a5a2a;
    animation: pulse 1s ease-in-out infinite;
}

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
        <h1>SCATTER STUDIO</h1>
        <p>describe what you want to build</p>
    </div>
    <div class="chat-messages" id="messages"></div>
    <div class="chat-input-area">
        <div class="chat-input-row">
            <input id="chat-input" type="text" placeholder="a red ball that bounces..." autocomplete="off">
            <button class="btn" id="send-btn" onclick="send()">Build</button>
        </div>
        <div class="chat-actions">
            <button class="btn-small" onclick="saveProject()">Save</button>
            <button class="btn-small" onclick="resetProject()">New</button>
        </div>
    </div>
</div>

<div class="preview-panel">
    <div class="preview-header">
        <span><span class="status-dot" id="status-dot"></span><span id="status-text">Ready</span></span>
        <span id="model-info">local model</span>
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
const modelInfo = document.getElementById('model-info');

// Check health on load
fetch('/health').then(r => r.json()).then(data => {
    if (data.ollama === 'running' && data.models.length > 0) {
        modelInfo.textContent = data.models[0].split(':')[0];
    } else {
        modelInfo.textContent = 'offline';
        addMessage('Ollama is not running. Start it with: ollama serve', 'error');
    }
}).catch(() => {
    modelInfo.textContent = 'error';
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
    statusText.textContent = 'Building...';

    try {
        const resp = await fetch('/build', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });
        const data = await resp.json();

        if (data.error) {
            addMessage('Error: ' + data.error, 'error');
        } else if (data.html) {
            // Update preview
            frame.srcdoc = data.html;
            addMessage('Updated.', 'system');
        }
    } catch (e) {
        addMessage('Connection error: ' + e.message, 'error');
    }

    sendBtn.disabled = false;
    statusDot.classList.remove('working');
    statusText.textContent = 'Ready';
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

// Focus input on load
input.focus();
</script>
</body></html>"""


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    if "--version" in sys.argv or "-v" in sys.argv:
        print("Scatter Studio v0.1.0")
        return

    print(f"\n  \033[1mScatter Studio\033[0m v0.1.0")
    print(f"  \033[2mhttp://localhost:{PORT}\033[0m")
    print(f"  \033[2mPress Ctrl+C to stop\033[0m\n")

    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(1)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    server = http.server.HTTPServer(("127.0.0.1", PORT), StudioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  \033[2mStopped.\033[0m")
        server.server_close()


if __name__ == "__main__":
    main()
