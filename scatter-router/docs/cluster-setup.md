# Home Data Center: Ollama on 4× Pi 5

Turn four Pi 5s into a distributed inference pool that the Scatter router round-robins across. **No k3s, no DaemonSet, no Helm.** Plain Ollama systemd units on each Pi, exposed on `0.0.0.0:11434`, listed in `~/.scatter/cluster.json`. The router (`scatter-router/server.py`) loads the manifest at startup and dispatches `/api/chat` calls to whichever Pi is next in the cycle, falling back through the chain on failure.

Estimated total time (first run): **30–45 min**, mostly spent on per-Pi model pulls (~2GB each) running in parallel.

## Prerequisites

Physical:
- 4× Raspberry Pi 5 (8GB recommended), each with power + microSD
- All on the same subnet as the laptop (10.42.0.0/24 over USB ethernet, in this house)

SSH:
- Aliases `pi-1` through `pi-4` resolved in `~/.ssh/config`
- Key auth working
- `sudo` available with password (for the one-time Ollama install)

## Stage 1 — Install Ollama on each Pi

Run from the laptop:

```bash
~/deploy-ollama-to-pis.sh
```

This is idempotent. Per Pi it:
1. Installs Ollama if missing (`curl -fsSL https://ollama.com/install.sh | sh`)
2. Writes `/etc/systemd/system/ollama.service`
3. Adds `OLLAMA_HOST=0.0.0.0:11434` override so the laptop can reach it
4. `systemctl enable --now ollama`
5. Verifies port 11434 is listening

Sudo password prompts will pass through the `-tt` allocation.

## Stage 2 — Pull a model on each Pi

In parallel from the laptop:

```bash
for p in pi-1 pi-2 pi-3 pi-4; do
  ssh -f $p "ollama pull llama3.2:3b > /tmp/ollama-pull.log 2>&1"
done
```

Each Pi pulls ~2GB independently (no laptop bandwidth). Watch progress with:

```bash
ssh pi-1 "tail -f /tmp/ollama-pull.log"
```

## Stage 3 — Write the cluster manifest

`~/.scatter/cluster.json`:

```json
{
  "head_node": "localhost",
  "workers": [
    {"host": "pi-1", "endpoint": "http://pi-1:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-2", "endpoint": "http://pi-2:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-3", "endpoint": "http://pi-3:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "pi-4", "endpoint": "http://pi-4:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "primary"},
    {"host": "localhost", "endpoint": "http://127.0.0.1:11434", "model": "llama3.2:3b", "capabilities": ["inference"], "role": "fallback"}
  ]
}
```

`role: primary` workers are round-robined. `role: fallback` workers are tried only if every primary fails. Localhost as fallback means the laptop's own Ollama answers if every Pi is down.

## Stage 4 — Restart the router

```bash
pkill -f "uvicorn server:app"
cd ~/scatter-system/scatter-router
setsid ./.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8787 \
  >> ~/.scatter/router.log 2>&1 < /dev/null &
```

Or just log out and log back in — the autostart entry at `~/.config/autostart/scatter-router.desktop` brings it up.

## Stage 5 — Smoke test

```bash
curl -sS -X POST http://127.0.0.1:8787/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hi","prefer_local":true}'
```

Expected: `{"response":"Hi back!","route":"local:llama3.2","tokens":...,"ms":...}`. Inference latency on Pi 5 is ~40–60s for a short reply on llama3.2:3b — that's the cost of CPU inference on edge hardware. If it returns in <2s, the call probably hit `cloud:sonnet` instead — drop `prefer_local: true` and you'll see that path.

To confirm which Pi served a request, check loaded-model state right after:

```bash
for p in pi-1 pi-2 pi-3 pi-4; do
  printf "%s: " "$p"
  curl -sS http://${p}:11434/api/ps \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print([m['name'] for m in d.get('models',[])])"
done
```

Each Pi loads the model on first request and evicts it after `OLLAMA_KEEP_ALIVE` seconds (default 5 min).

## Recovery

If a Pi goes offline, the router transparently skips it via the fallback chain — no edits needed. Bring it back with `ssh pi-N "sudo systemctl start ollama"` and the next round-robin tick picks it up.

If the manifest is missing or corrupt, the router degrades to localhost-only (default workers list in `_load_workers()` in `server.py`).

## Why not k3s

The earlier draft of this doc spec'd k3s + an Ollama DaemonSet behind a NodePort. Three reasons we walked back:

1. **Operational weight.** k3s on a Pi 5 idles at ~200 MB RAM and 2–3% CPU per node. For a 4-node cluster that exists to run *one daemon per node*, the orchestration layer is heavier than what it orchestrates.
2. **Failure surface.** k3s adds etcd, the control plane, the kubelet, the CNI, and the LB. Ollama on bare systemd has one failure mode: the unit didn't start. k3s has dozens.
3. **The thermodynamic argument.** Scatter's whole posture is intelligence-per-watt. Burning ~5 W per Pi on Kubernetes overhead to dispatch inference jobs that Ollama can answer directly is the opposite move.

The bare-systemd path is simpler, lighter, and more aligned. k3s remains a valid choice for clusters that *also* need to run other workloads — but a homelab inference pool is not that cluster.
