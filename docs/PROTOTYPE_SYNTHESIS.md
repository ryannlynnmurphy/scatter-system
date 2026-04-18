# What the prototype era was reaching for

A synthesis read of Ryann's early-2026 prototype work. The code is
exploratory research, not production. The ideas inside are not.

*(Note: prototype-era directories on disk still carry legacy names for
git-history reasons. In this document and everywhere forward, the apps
are referred to by their Scatter names — never the retired prototype
names — and the prototype phase itself is referred to as "prototype Scatter."
This is the discipline of a distillation: say the current name.)*

---

## The through-line

Every prototype-era app shares the same posture:

> "Most \[tool category\] is built by developers who don't \[do the craft\].
> This is built for \[the craft\]."

- **Scatter Draft (prototype)** — *"Three produced plays... the formatting rules aren't arbitrary constraints; they're the muscle memory of the craft."*
- **Scatter Film (prototype)** — *"Most editing software is built around the footage. This is built for writers: the shot list lives alongside the timeline."*
- **Scatter Music (prototype)** — *"Tuba player, marching band director, show choir arranger built this. Most DAWs are built for producers. This is built for writers."*
- **Scatter Write (prototype)** — *"Every writing app is either too simple or too complex. This is neither."*

Each app is a critique of an industry default rewritten by someone who lives the work. That posture is the moat. No amount of Anthropic funding or Apple polish can reproduce it — it comes from having written the play, shot the film, arranged the score.

## The AI commitment (consistent across apps)

> *"AI helps. It does not replace."*

AI assist panels slide in when requested and disappear when dismissed. The user's words stay at the center. The AI proposes; the writer decides. This is the embodiment of the legibility + revocability ground — at the level of *craft authorship*, not just data.

## The ambitious AI tool in prototype Scatter Film

Reading the prototype design spec, the tool is more specifically:

> **Script-aware media ingestion and coverage analysis.** Import footage from a workspace or SD card. Compare against the shot list (which comes from Scatter Draft). For each scene, report: how many shots are planned vs. how many have corresponding clips. Suggest shot types based on scene content ("Scene 4 is dialogue-heavy — consider close-ups"). Detect coverage gaps before the director wraps.

This is genuinely novel. Not "transcribe my footage" (Premiere has that) — *"know what the script called for and tell me what I still need."* The moat is the script-first worldview: film **comes from** writing.

## The stack mismatch (and why it doesn't matter)

Prototype-era apps are Next.js 15 + TypeScript + Tailwind + Tone.js.
Phase-two distilled Scatter is Python stdlib + vanilla HTML + no framework.

These are not the same stack. There is no cheap port. There is no cheap rewrite.

**The resolution is not to rewrite.** The resolution is to accept that the prototype era produced three things of value that are stack-independent:

1. **The manifesto READMEs** — each app's README is a first-person statement of intent from the practitioner. These are publishable thesis evidence.
2. **The design language** — charcoal/cream/gold, Courier-for-scripts, DM Sans body. A warm, printed-page aesthetic distinct from Phase-two's climate hacker dark. Both should coexist as named *themes*.
3. **The AI-tool concepts** — script-aware coverage analysis, arrangement-first composition, format-aware drafting. These are **primitives** that can be re-implemented in any stack, including Python.

## What builds productively on top

Four moves, each small. None of them requires rewriting Next.js apps.

### 1. Wrap the prototype apps under Scatter (same pattern as Commons)

`scatter wrap` (already shipping) is the right instrument. Add the prototype apps to its registry with:
- **Provenance** = *"Built by Ryann Murphy, Scatter prototype, early 2026"* (not an upstream foundation — the gift is from the author to herself)
- **Exec** = a wrapper that starts `npm run dev` in the prototype directory and opens a native GTK window pointing at the dev server port
- **Firejail profile** = offline unless the app explicitly needs net (most don't)
- **Scatter name** = already defined in each README (Scatter Draft, Scatter Film, Scatter Music, Scatter Write)

This makes every prototype app visible from the Scatter app menu, firejailed into a bubble, and journal-logged on launch. Zero rewrite. Preserved intact.

### 2. Pull the AI primitives into scatter_core / scatter/ai_local.py

Three AI services the craft apps all want:
- **transcribe(audio_path) → text** (Whisper local if available, Ollama if not)
- **caption(image_path) → text** (llava:7b via Ollama, or equivalent)
- **coverage(script_path, clips_dir) → gap_report** (Ollama Q&A over two indexed inputs)

These become `scatter-ai <verb> <args>` CLI commands. Any Scatter app (or any shell script) can call them. Centralizing here means the moat tool exists once, not reimplemented per app.

### 3. Name both design languages as themes

- **Studio theme** = prototype-era charcoal/cream/gold, DM Sans, Courier for code-shaped text. Writing-daytime feel.
- **Research theme** = phase-two climate hacker dark, JetBrains Mono, green/amber. Ops-nighttime feel.

Both shipped in `scatter/ui/tokens.css` with a `data-theme="..."` selector. The user picks. The moat isn't the color palette — it's *having two honest palettes each matched to a working posture.*

### 4. The manifesto READMEs become the welcome experience

scatter-welcome (task #8) is the first-boot introduction. Instead of writing a new introduction from scratch, the welcome app cycles through the prototype READMEs verbatim as the narrative of Scatter — "here is the playwright explaining the draft tool... here is the tuba player explaining the music tool..." This is thesis-grade pedagogy: the designer of each app is the introducer.

---

## What does not productively build on top (honest cuts)

- **Scatter Schools prototype material** (in legacy academy directories) — education platform work. Out of scope for the distilled alignment artifact. Preserve as-is; do not integrate into phase-two.
- **Cluster / CLI / core prototype scaffolding** — infrastructure that has been superseded by `scatter_core.py`. Preserve for git-blame lineage; do not bring into the distilled system.
- **Pre-prototype code from the earliest era** (before the Scatter name stabilized) — archived; nothing carries forward.

Retirement is part of distillation. Keeping everything is sprawl. Naming what doesn't carry forward is discipline.

---

## One-line summary for the thesis

*The prototype era built the vocabulary. Phase two built the ground under the vocabulary. Phase three —* that is, the carry-forward named above — *binds them so the craft-apps speak the alignment language without losing the craft voice.*
