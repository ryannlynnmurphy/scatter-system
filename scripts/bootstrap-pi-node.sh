#!/usr/bin/env bash
# bootstrap-pi-node.sh
# Turn a Raspberry Pi 5 into a Scatter inference node:
#   llama.cpp's llama-server, systemd-managed, listening on the tailnet.
# Idempotent: safe to re-run. Run as root.
#
# Usage on the Pi:
#   sudo bash bootstrap-pi-node.sh
#
# Override the model by env var:
#   sudo MODEL_FILE=phi-3-mini-4k-instruct-q4.gguf \
#        MODEL_URL=https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf \
#        bash bootstrap-pi-node.sh
#
# To skip download, pre-stage the model at /opt/scatter/models/<MODEL_FILE>
# (e.g. scp it from the laptop) and the script will use it.

set -euo pipefail

SCATTER_USER="${SCATTER_USER:-scatter}"
SCATTER_HOME="/opt/scatter"
LLAMA_DIR="${SCATTER_HOME}/llama.cpp"
MODEL_DIR="${SCATTER_HOME}/models"
MODEL_FILE="${MODEL_FILE:-tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf}"
MODEL_URL="${MODEL_URL:-https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf}"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
LISTEN_HOST="${LISTEN_HOST:-0.0.0.0}"
LISTEN_PORT="${LISTEN_PORT:-8080}"
THREADS="${THREADS:-$(nproc)}"
CTX="${CTX:-2048}"

[[ "$(id -u)" -eq 0 ]] || { echo "must run as root: sudo bash $0" >&2; exit 1; }

# Cap memory cgroup so a runaway model can't take the whole Pi down.
# 8GB Pi: leave ~2GB for OS. 4GB Pi: leave ~1GB.
TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if   [[ "${TOTAL_MB}" -ge 7000 ]]; then MEM_MAX="6G"; MEM_HIGH="5G"
elif [[ "${TOTAL_MB}" -ge 3500 ]]; then MEM_MAX="3G"; MEM_HIGH="2500M"
else MEM_MAX="1500M"; MEM_HIGH="1200M"
fi

echo "==> Scatter inference node bootstrap on $(hostname) [${TOTAL_MB}MB RAM, MemMax=${MEM_MAX}]"

# --- service user ---
if ! id -u "${SCATTER_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${SCATTER_HOME}" --shell /usr/sbin/nologin "${SCATTER_USER}"
fi
mkdir -p "${MODEL_DIR}"
chown -R "${SCATTER_USER}:${SCATTER_USER}" "${SCATTER_HOME}"

# --- build deps ---
echo "==> apt deps"
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential cmake git curl ca-certificates pkg-config

# --- llama.cpp ---
if [[ ! -d "${LLAMA_DIR}/.git" ]]; then
  echo "==> cloning llama.cpp"
  sudo -u "${SCATTER_USER}" git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "${LLAMA_DIR}"
else
  echo "==> updating llama.cpp"
  sudo -u "${SCATTER_USER}" git -C "${LLAMA_DIR}" pull --ff-only || true
fi

if [[ ! -x "${LLAMA_DIR}/build/bin/llama-server" ]]; then
  echo "==> building llama-server (5-15min on a Pi 5)"
  sudo -u "${SCATTER_USER}" cmake -S "${LLAMA_DIR}" -B "${LLAMA_DIR}/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=OFF \
    -DGGML_NATIVE=ON
  sudo -u "${SCATTER_USER}" cmake --build "${LLAMA_DIR}/build" --target llama-server -j "${THREADS}"
else
  echo "==> llama-server already built"
fi

# --- model ---
if [[ ! -s "${MODEL_PATH}" ]]; then
  echo "==> downloading ${MODEL_FILE}"
  sudo -u "${SCATTER_USER}" curl -fL --retry 3 --retry-delay 2 \
    -o "${MODEL_PATH}.part" "${MODEL_URL}"
  sudo -u "${SCATTER_USER}" mv "${MODEL_PATH}.part" "${MODEL_PATH}"
else
  echo "==> model already present at ${MODEL_PATH}"
fi

# --- ensure Ollama is not racing us for memory or the port ---
if systemctl list-unit-files | grep -q '^ollama\.service'; then
  echo "==> stopping & disabling ollama (was the crash source)"
  systemctl disable --now ollama.service || true
fi

# --- systemd unit ---
UNIT=/etc/systemd/system/scatter-llama.service
echo "==> writing ${UNIT}"
cat >"${UNIT}" <<UNIT
[Unit]
Description=Scatter llama.cpp inference node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SCATTER_USER}
Group=${SCATTER_USER}
WorkingDirectory=${SCATTER_HOME}
ExecStart=${LLAMA_DIR}/build/bin/llama-server \\
  --model ${MODEL_PATH} \\
  --host ${LISTEN_HOST} \\
  --port ${LISTEN_PORT} \\
  --threads ${THREADS} \\
  --ctx-size ${CTX} \\
  --mlock \\
  --metrics
LimitMEMLOCK=infinity
Restart=on-failure
RestartSec=5
MemoryHigh=${MEM_HIGH}
MemoryMax=${MEM_MAX}

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable scatter-llama.service
systemctl restart scatter-llama.service

# --- verify ---
echo "==> waiting for /health (up to 60s)"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${LISTEN_PORT}/health" >/dev/null 2>&1; then
    echo "==> healthy after ${i}s"
    break
  fi
  sleep 1
done

systemctl --no-pager --lines=8 status scatter-llama.service || true

cat <<EOM

==========================================================
 Done. From your laptop, try:

   curl http://$(hostname):${LISTEN_PORT}/health

   curl http://$(hostname):${LISTEN_PORT}/v1/chat/completions \\
     -H 'Content-Type: application/json' \\
     -d '{"messages":[{"role":"user","content":"say hi in one word"}],"max_tokens":16}'

 Logs:    journalctl -u scatter-llama -f
 Restart: sudo systemctl restart scatter-llama
==========================================================
EOM
