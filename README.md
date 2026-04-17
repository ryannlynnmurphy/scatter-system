# Scatter

**An operating system that is its own interface.**

Scatter is a local-first AI computing system. It runs on your hardware. It reads its own sensors. It adapts to your power state. It teaches you to build things. It records every decision as research data. It argues with you before it builds for you.

The optimization target is **intelligence per watt** — useful cognitive work per unit of energy consumed. Not shareholder value. Not benchmark scores. Intelligence per watt.

## What this is

Five components forming one organism:

| Component | Role | What it does |
|-----------|------|-------------|
| `scatter code` | Local reflexes | AI coding agent on Ollama. Argues before it builds. |
| `scatter ops` | Immune system | Self-healing monitor. Keeps services alive. |
| `scatter data` | Preservation | Backup, integrity checks, schema migration. |
| `scatter journal` | Memory | Decision capture with dialectical traces. Research instrument. |
| `scatter studio` | Teaching | Project-based learning. Build things by describing them. |

Plus the nervous system:
- `scatter-greeting` reads your hardware (battery, thermal, memory, network, Ollama) and writes `~/.scatter/system-state.json`
- Every component reads that shared state
- The greeting IS the interface — the system's self-description is what the user sees

## Architecture

Scatter is the body. [Claude Code](https://claude.ai/claude-code) is the mind.

The body reads sensors and produces awareness. The mind takes awareness and builds the future. The journal records what both produce.

This is the two-model architecture described in the research:
- **Model A** (Scatter / local Ollama) — reads hardware state, produces concise awareness
- **Model B** (Claude Code / cloud) — takes that awareness, reasons, builds
- **The handoff** — `system-state.json` — human-readable, auditable, one file

When Claude Code opens this repo, it reads `CLAUDE.md` and knows the system's state, the user's context, and the project's principles. The cloud mind has a local body.

## The Method

Scatter uses the **Scatter Method** — a research methodology that applies dialectical philosophy to AI interaction:

1. **Thesis** — state what you want to build
2. **Antithesis** — genuinely consider how it might be wrong
3. **Synthesis** — build what survives

Applied recursively: Synthesis → Scientific Method → Thesis' → Antithesis' → Synthesis''

The system prompt in `scatter code` implements this. The agent doesn't just write what you ask. It challenges your approach when the decision has real tradeoffs. The friction is the feature. Slop is what you get without friction.

## Intelligence Per Watt

Every local inference is logged to `~/.scatter/ipw-log.jsonl` with tokens generated, time elapsed, and estimated power consumed. The ratio is the metric.

The power router (`scatter-ops/power_router.py`) adapts in real time:
- **Battery >50%** — full model (qwen2.5-coder:7b), full context
- **Battery 20-50%** — fast model (llama3.2:3b), reduced context  
- **Battery <20%** — minimal inference, conserve energy
- **Charging** — full capability always

The system gets more efficient as energy gets scarce. That's the optimization.

## Install

Requires: Linux, Python 3.10+, [Ollama](https://ollama.com)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b

# Clone Scatter
git clone git@github.com:ryannlynnmurphy/scatter-system.git
cd scatter-system

# Add to PATH (add to ~/.bashrc for persistence)
export PATH="$PWD/bin:$PATH"

# Check installation
scatter setup

# Start using
scatter code        # local AI coding agent
scatter journal     # record a decision
scatter studio      # teaching environment (opens browser)
scatter status      # system report
scatter ipw         # intelligence per watt summary
```

## For researchers

This codebase is simultaneously a product and an experiment. See `RESEARCH.md` for five falsifiable hypotheses with measurement plans and falsification criteria.

The system measures itself. The journal captures dialectical decision traces. The IPW log tracks energy efficiency. Git history documents the evolution. Together they constitute a longitudinal case study in AI-assisted development by a non-technical researcher.

## The research question

Can a person with no prior computer science background, using AI tools through a disciplined interaction protocol, build the local infrastructure that makes cloud AI optional?

This repo is the answer in progress.

## Who

**Ryann Murphy** — playwright, researcher, founder of Scatter Computing.

BA Playwriting, Fordham University. Incoming MPS, NYU Interactive Telecommunications Program (Fall 2026). Started coding February 2026. Three produced plays including a one-woman show at Edinburgh Fringe. No prior CS, ML, or engineering background.

**Scatter Computing** is a nonprofit focused on AI safety through decentralization. New York, NY.

## The thesis

The AI industry is optimizing for shareholder value when it should be optimizing for intelligence per watt. A business model built on data extraction cannot produce an aligned model. The alternative architecture — distributed, local, quantized inference running on hardware thermally integrated with the spaces it serves — is achievable now, using tools that already exist.

The method is free. The method is open. The method does not require a data center to run. Neither does the future of AI.

## License

MIT

---

*This system was built using Claude Code by Anthropic. The cloud trained the edge.*
