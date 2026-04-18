# Scatter

**A system for doing AI safety research at home.**

Scatter is one local-first application for building and thinking — plus the substrate, tests, and documents that make its alignment claims verifiable. It runs on your hardware. Nothing leaves the machine unless you ask and watch.

---

## The metaphysical ground

A system is **aligned** when its behavior, inputs, outputs, and accountability are *legible to* and *revocable by* the person using it.

Everything else — privacy, sovereignty, sustainability, safety — is a consequence of those two conditions. Privacy is what you get when outbound flows are legible. Sovereignty is what you get when state is revocable. Sustainability is what you get when watts are legible. Safety is what you get when harmful actions are revocable before they land.

That definition is the ground under every design decision in this repo. The architecture implements it; the tests enforce it; the dialectical log documents every exchange where a synthesis dissented from the original position.

---

## Three pillars (the three S's)

**Safety.** Every external network call goes through one vetted path (`scatter/api.py`). The learner profile makes that path architecturally unavailable — `unshare --net` tests (coming in task #18) assert it at the kernel level.

**Sustainability.** Every model invocation writes estimated joules to `~/.scatter/watts.jsonl`. The Scatter GUI shows the cumulative cost ambient in a footer strip. Real hardware baselines are planned (task #30) so the numbers become evidence, not aspiration.

**Sovereignty.** One data root (`~/.scatter/`). Plain JSONL files you can `grep`, `tail -f`, or read by hand. Every entry has an id. `scatter forget <id>` appends a tombstone; filtered reads hide the entry. Physical garbage collection is a separate, auditable step.

---

## What ships today

| Component | State | Role |
|---|---|---|
| `scatter_core.py` | ✓ shipping | The substrate. Journal, audit facility, watts log, session store, profile, dialectical log, `forget`. Stdlib only. |
| `scatter/server.py` | ✓ shipping | The GUI backend. Local HTTP server, chat/build router (fast model + build model), build journal, API endpoints. |
| `scatter/launcher.py` | ✓ shipping | Native desktop app wrapper (PyGObject + WebKit2GTK). Chromeless window. URL navigation locked to localhost. |
| `scatter/api.py` | ✓ shipping | The single vetted path for external network calls. Profile-gated, audit-logged, metadata-only. |
| `scatter/tests/` | ✓ shipping | Architectural tests: syntax, leak-free, API self-check. `run_all.sh` runs everything. |
| `scatter/hooks/pre-commit` | ✓ shipping | Secret scan + leak test + syntax check on every commit. |
| `scatter/ui/tokens.css` | ✓ shipping | Design tokens (climate hacker palette, typography, motion). Served at `/ui/tokens.css`. |
| `docs/DIALECTICAL_LOG.md` | ✓ shipping | Generated from `~/.scatter/dialectical/`. Every exchange where synthesis dissented is published. |
| OS-level branding (boot, login, hostname) | pending | Task #6 / #25. |
| Scatter Browser (Firefox + firejail) | pending | Task #7. |
| scatter-welcome | pending | Task #8. |
| Backup facility | pending | Task #11. |
| Commons essay | pending | Task #12. |

Phase-one scaffolding (`scatter-code/`, `scatter-data/`, `scatter-journal/`, `scatter-ops/`) remains in the repo and is pending review under task #28. The architectural claims in this README apply to the distilled system, not the scaffolding.

---

## Threat model

Scatter defends against: accidental leakage, distracted developer drift, user curiosity, child-level exploration, and the loss of legibility that comes from convenience defaults.

Scatter does **not** defend against: a rooted adversary, sophisticated forensic recovery, side-channel attacks, nation-state-level threats, hardware implants, or a determined local attacker with physical access. JSONL audit files are user-editable; no hash chain is maintained.

Stated plainly so every downstream claim is bounded by this statement. If that boundary is tighter than your actual threat model, Scatter is not the right tool.

---

## Dependencies

Small, named, vetted. Rationale for each.

**Runtime (Python, stdlib-only except where noted):**
- Python 3.10+
- `gir1.2-webkit2-4.1`, `python3-gi` — native desktop app shell. On Ubuntu 24.04 LTS these ship by default.
- (future, tasks #11/#13) `cryptography` — for encrypted backup. Vetted package. Declared before the backup facility ships.
- (future, optional) `fonts-jetbrains-mono`, `fonts-inter` — climate hacker typography. Apt-installable. Falls back to Ubuntu Mono gracefully.

**Services:**
- [Ollama](https://ollama.com) running locally. Models: `qwen2.5-coder:7b` (build) and `llama3.2:3b` (intent router, fast replies).

**Explicitly not taken on:**
- No `requests`, `httpx`, `fastapi`, `flask`, `electron`, `react`, `node_modules`, `webpack`.
- No google-fonts CDN, no cdnjs, no unpkg.
- No telemetry.

---

## Reproducibility interval

Substrate named: **Ubuntu 24.04 LTS "Noble Numbat"**.

The bootstrap script (task #25, forthcoming) manipulates Plymouth, GRUB, GDM, gnome-shell favorites, and `/etc/os-release`. Those surfaces evolve between LTS releases. Scatter commits to re-certifying the bootstrap on Ubuntu 26.04 LTS when it ships, with the version-pinned expectations documented here.

The reference machine is an HP Spectre x360 2-in-1 14-eu0xxx. A different machine class (e.g. a Framework 13, a ThinkPad T-series, or a fresh Ubuntu VM) is a different reproduction target — the bootstrap is written to accept these, but "passes on three hardware targets" is an open test (task #25, prediction 1 from the thesis).

---

## Install & quickstart

```bash
git clone git@github.com:ryannlynnmurphy/scatter-system.git
cd scatter-system
export PATH="$PWD/bin:$PATH"    # add to ~/.bashrc to persist

# Ensure Ollama is running and models are pulled
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b

# Initialize the substrate
python3 scatter_core.py init

# Open Scatter (native desktop app)
scatter                  # native window
scatter serve            # dev mode: open in a real browser at localhost:3333
```

---

## Running the tests

```bash
scatter/tests/run_all.sh
```

Three tests, all must pass:
1. **Syntax** — every `.py` under `scatter/` and `scatter_core.py`.
2. **Leak-free** — only an allowlisted set of files imports network modules. Anything else is a leak.
3. **API self-check** — learner profile refuses external calls; researcher without keys raises clearly; stub endpoints raise `NotImplementedError`.

The pre-commit hook (`scatter/hooks/pre-commit`) runs the leak test and a secret scanner on every commit. Enable it locally with:

```bash
git config --local core.hooksPath scatter/hooks
```

---

## The Scatter Method (dialectical practice)

Every major design decision here was subjected to thesis → antithesis → synthesis. The record is in `docs/DIALECTICAL_LOG.md`, generated from `~/.scatter/dialectical/`.

Publication policy: every exchange is preserved, **including the ones where the synthesis rejected the original thesis**. Without that record the method is decorative. With it, the method is falsifiable, and therefore research.

Read the log:
```bash
python3 scatter_core.py dialectical-export
```

Or open `docs/DIALECTICAL_LOG.md` in any markdown viewer.

---

## Commons

Scatter runs on the shoulders of:

- The Linux kernel, Ubuntu, GNOME
- Python (PSF), and its standard library
- Ollama, llama.cpp
- The Qwen and Llama model families
- PyGObject, GTK, WebKit
- Firefox
- Inter (Rasmus Andersson), JetBrains Mono (JetBrains)

These are gifts. They are not Scatter's inventions. The essay *Gifts That Made This Machine* (task #12) will name the lineage loudly rather than gift-wrap it under Scatter branding. Scatter is legible about where it comes from.

---

## Who

**Ryann Murphy** — playwright, researcher, founder of Scatter Computing. BA Playwriting, Fordham University. Incoming MPS, NYU Interactive Telecommunications Program (Fall 2026). Started coding February 2026. No prior CS, ML, or engineering background.

**Scatter Computing** is a nonprofit focused on AI safety through decentralization. New York.

This repo is a thesis project. The primary output is not the software — it is the argument that aligned local computing can be built, operated, and defended by a playwright-researcher working alone at home, and that the argument is stronger when the machine exists to be touched.

---

## License

MIT.

---

*The research was done with Claude (Anthropic) and Claude Code. The dialectical log includes every session that shaped the architecture. The cloud mind helped build the local body; the local body is the one that stays.*
