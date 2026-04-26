#!/usr/bin/env bash
# bootstrap-pixel-portable.sh
#
# Turn a GrapheneOS Pixel into "portable Scatter" — a self-contained
# Scatter node that:
#   • Joins the home cluster over Tailscale when networked
#   • Falls back to local Ollama on the phone when offline
#   • Runs the same scatter-router/server.py as the laptop
#
# RUN THIS ON THE PHONE, INSIDE TERMUX'S PROOT DEBIAN.
# Workflow on the phone:
#   1. Install F-Droid (browser → f-droid.org → APK)
#   2. From F-Droid: install Termux (NOT the Play Store version — stale)
#   3. Open Termux:
#        pkg update && pkg upgrade -y
#        pkg install -y proot-distro tailscale openssh git python curl
#   4. Install Tailscale (Termux side, NOT inside proot — needs Android VPN):
#        tailscale up
#        # follow the URL to authenticate the phone into the tailnet
#   5. Drop into Debian proot:
#        proot-distro install debian
#        proot-distro login debian
#   6. Inside the proot, fetch + run this script:
#        curl -fsSL https://raw.githubusercontent.com/ryannlynnmurphy/scatter-system/master/scripts/bootstrap-pixel-portable.sh | bash
#
# After bootstrap completes, on the LAPTOP, add the phone to ~/.scatter/cluster.json
# as a fifth worker with role:"burst" (see "On the laptop" section at the bottom of
# this script, printed at the end of run).

set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

say()  { printf "${GREEN}>> %s${RESET}\n" "$*"; }
warn() { printf "${YELLOW}!! %s${RESET}\n" "$*"; }
die()  { printf "${RED}xx %s${RESET}\n" "$*"; exit 1; }

# ── Sanity ──────────────────────────────────────────────────────────────

if [ ! -f /etc/debian_version ]; then
  die "this script must run inside the Debian proot (proot-distro login debian)."
fi

if [ "$(uname -m)" != "aarch64" ]; then
  warn "expected aarch64, got $(uname -m). continuing but Ollama may not start."
fi

say "bootstrapping portable Scatter on $(uname -mr)"

# ── 1. System packages ──────────────────────────────────────────────────

say "apt update + base packages"
apt-get update -qq
apt-get install -y -qq curl git ca-certificates python3 python3-venv python3-pip
say "  ok"

# ── 2. Ollama ───────────────────────────────────────────────────────────

if ! command -v ollama >/dev/null 2>&1; then
  say "installing Ollama (CPU build for aarch64)"
  curl -fsSL https://ollama.com/install.sh | sh
else
  say "ollama already installed: $(ollama --version 2>&1 | head -1)"
fi

# Ollama in proot can't use systemd, so run as a background process.
if ! pgrep -fa "ollama serve" >/dev/null; then
  say "starting ollama serve in background"
  mkdir -p ~/.ollama
  nohup ollama serve > ~/.ollama/serve.log 2>&1 &
  sleep 3
fi

if ! curl -sS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  die "ollama serve didn't come up — check ~/.ollama/serve.log"
fi
say "  ollama listening on 127.0.0.1:11434"

# ── 3. Pull the model (~2GB, takes a while on cellular) ─────────────────

if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
  say "pulling llama3.2:3b (~2GB; consider being on Wi-Fi)"
  ollama pull llama3.2:3b
else
  say "llama3.2:3b already present"
fi

# ── 4. Clone scatter-system ─────────────────────────────────────────────

if [ ! -d ~/scatter-system ]; then
  say "cloning scatter-system"
  git clone https://github.com/ryannlynnmurphy/scatter-system.git ~/scatter-system
else
  say "scatter-system already cloned, pulling latest"
  git -C ~/scatter-system pull --rebase || warn "pull failed; continuing"
fi

# ── 5. Python venv + deps for the router ────────────────────────────────

cd ~/scatter-system/scatter-router
if [ ! -d .venv ]; then
  say "creating venv"
  python3 -m venv .venv
fi

say "installing python deps"
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q fastapi uvicorn anthropic httpx python-dotenv pydantic

# ── 6. Phone-side cluster.json ──────────────────────────────────────────
# The phone's manifest prefers the home tailnet workers (when reachable)
# and falls back to its own Ollama. Edit the LAPTOP_TAILNET_NAME below
# after `tailscale status` shows your tailnet (e.g. "scatter-lan.ts.net").

mkdir -p ~/.scatter

if [ ! -f ~/.scatter/cluster.json ]; then
  say "writing phone cluster.json (edit the .ts.net name to match your tailnet)"
  cat > ~/.scatter/cluster.json <<'JSON'
{
  "head_node": "localhost",
  "_note": "edit endpoints below: replace EXAMPLE.ts.net with your tailnet's MagicDNS suffix from `tailscale status`",
  "workers": [
    {"host": "pi-1",      "endpoint": "http://pi-1.EXAMPLE.ts.net:11434",   "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-2",      "endpoint": "http://pi-2.EXAMPLE.ts.net:11434",   "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-3",      "endpoint": "http://pi-3.EXAMPLE.ts.net:11434",   "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-4",      "endpoint": "http://pi-4.EXAMPLE.ts.net:11434",   "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "laptop",    "endpoint": "http://laptop.EXAMPLE.ts.net:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pixel-self","endpoint": "http://127.0.0.1:11434",             "model": "llama3.2:3b", "capabilities": ["inference"], "role": "fallback"}
  ]
}
JSON
else
  say "~/.scatter/cluster.json already exists, leaving it alone"
fi

# ── 7. Smoke test ───────────────────────────────────────────────────────

say "smoke testing local inference (this loads the model — ~30s on first run)"
cd ~/scatter-system/scatter-router
./.venv/bin/python - <<'PY'
import server
data, w = server._ollama_chat({
    "model": "llama3.2:3b",
    "messages": [{"role": "user", "content": "say hi in three words"}],
    "stream": False,
    "options": {"num_predict": 16},
}, timeout=120)
print(f"  worker: {w['host']}  reply: {data['message']['content'][:60]}")
PY

# ── 8. Persistent autostart for the router (Termux side) ────────────────

cat <<'POST'

──────────────────────────────────────────────────────────────────────
portable Scatter bootstrap complete on the phone.

NEXT (still on the phone):
  • Edit ~/.scatter/cluster.json — replace EXAMPLE.ts.net with your real
    tailnet suffix (run `tailscale status` from a Termux shell to see it).
  • Start the router whenever you want it running:
        cd ~/scatter-system/scatter-router
        ./.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8787 &
  • Open http://127.0.0.1:8787/ in any phone browser to use Scatter.

NEXT (back on the laptop):
  • Add the phone as a fifth worker in ~/.scatter/cluster.json:
        {"host": "pixel-9a",
         "endpoint": "http://pixel-9a.<your-tailnet>.ts.net:11434",
         "model": "llama3.2:3b",
         "capabilities": ["inference"],
         "role": "burst"}
    (role:"burst" means the laptop only spills over to the phone when
    every Pi primary is exhausted — phones throttle under sustained load.)
  • Restart the router so it re-reads cluster.json:
        pkill -f "uvicorn server:app"
        # autostart will bring it back, or run setsid manually
  • Smoke test:
        curl http://pixel-9a.<your-tailnet>.ts.net:11434/api/tags

──────────────────────────────────────────────────────────────────────
POST
