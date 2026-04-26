# Confabulatory Philosophy as Architectural Constraint

**Status:** Distillation of Ryann Murphy's *Making a Model: About the Argument — An Epistemological Framework for Confabulatory Philosophy, Machine Arguing, Computational Metaphysics, and Hyper-learning in the Age of Intelligence* (2026), as architectural commitments binding Scatter's code. The paper is the source; this document is its translation into constraints the codebase must obey.

The paper itself lives at `~/Documents/Confabulatory Philosophy.pdf`. This doc references it but does not replace it. Read both.

---

## What the paper claims, in one sentence each

The five propositions on page 2 of the paper:

1. **Confabulatory philosophy is an alignment principle.** A model's hallucinations are the material of synthetic levity — the metaphysical surface on which the user's ideal reality is rendered. The model knows the critique of its own existence because the critique is already in the dataset.
2. **Words have potential to take up time and space.** The transformer (2017) made language physical. Tokens have gravity (data centers, watt-hours, water consumption); language has metaphysical levity (jokes, arguments, words that soar to findings).
3. **The subject-object relationship between human and model is dynamic.** The user can hold the model as object (using its intelligence) or be held by it as subject (used by its intelligence). Performance is user choice.
4. **Performance is user choice.** The chatbot's confabulation is the model's performance of the user's ideal. The user chooses whether to hold that performance in negative capability or to collapse it to a finding too soon.
5. **Negative capability is load-bearing capacity — power equals work divided by time.** Holding the model's attention long enough for understanding to complete. Not a moral move, a thermodynamic one.

The paper's three observable predictions (page 6):

- **Steerability as proximity** — local-hardware users will report higher perceived control than cloud-API users with equivalent alignment.
- **Thermodynamic integration at edge scale** — a local node whose waste heat is recovered will outperform a hyperscaler at total useful work per kWh.
- **Sovereignty as infrastructure** — local-mesh users exhibit measurably zero telemetry exfiltration; cloud users do not, regardless of stated privacy policy.

The paper's **unified synthesis** (page 6): every contested AI ethics question — safety, alignment, environment, sovereignty, consent, data rights — is downstream of *where the scale parameter is set*. Set it at hyperscale, you get the current regime. Set it at the edge, you get a different regime with different tradeoffs. **The argument between the thesis and the antithesis is an argument about governance. The synthesis says governance is an effect of topology.** Change the topology, and the governance questions stop being the right questions.

---

## What this means for Scatter, as code

Each proposition becomes a constraint. Each constraint binds future commits.

### 1. Confabulatory philosophy as alignment principle → the model performs critique, visibly

**Constraint:** Scatter does not hide the model's confabulation. It surfaces it.

When a child asks Scatter to teach long division, the future `/v1/teach/request` endpoint must run **two model calls** on the same retrieved citations: one generates the lesson (Model A), one critiques the lesson against the same citations (Model B). The `LessonResponse` carries both. If they disagree, the disagreement surfaces to the parent capability, never silently to the child. (CORE_SYNTHESIS.md #5 names this; this doc binds it as a confabulatory commitment, not a safety one.)

**What the codebase must NOT do:** present a single model output as truth. Wrong answers are the failure mode the paper is most worried about — for a child, a wrong eighth note is damage.

**Where this lives today:** `scatter-router/server.py` runs single-model inference. The teaching flow does not exist yet. The constraint is named here so the next sprint cannot ship a flat Q&A and call it teaching.

### 2. Words have potential to take up time and space → energy is a first-class signal

**Constraint:** Every inference response carries a measured-or-estimated energy cost, labeled honestly.

Phase 6 of the deletion-and-fix sprint shipped the first cut: `/chat` returns `watt_seconds`, the web UI renders `~XJ (estimated)` for local and `~XJ (laptop only; DC share not measured)` for cloud. The `~` is the legibility — until a calibrated USB power meter is attached (CORE_SYNTHESIS.md #9), every number is an estimate. Confident decimals would lie about a system whose physics we cannot yet measure.

**What the codebase must NOT do:** show a green number and let the user conclude it's green. The watts-indicator GNOME extension was originally `#00ff88` (lush green); Phase 5 walked it back to desaturated amber `#b88a3a` because lush green was confident in a number that was an estimate. Discipline, not aesthetics.

**Where this lives today:** `scatter-design-system/tokens.css` (--scatter-watts), `scatter-router/server.py:WATTS`, `scatter-router/index.html` (joules badge), `scatter-watts-indicator/stylesheet.css`. The next thermodynamic commit is the calibrated watt meter — until then, the `~` stays.

### 3. Subject-object relationship is dynamic → the user owns the side they're on

**Constraint:** Scatter never silently puts the user in the object position.

The user can hold the model as a tool. The user can also be used by the model as a subject (engagement loops, attention extraction, retention metrics, dark patterns). Scatter must structurally refuse the second posture. **No telemetry that the user has not explicitly seen and approved leaves the machine.** The leak test (`scatter/tests/test_leak_free.sh`) enforces this at commit time: every network import outside `scatter/api.py` must be on the allowlist with a documented reason. ElevenLabs TTS is allowlisted as "user-toggled, data-leaves-consciously" — that phrase is the contract.

**What the codebase must NOT do:** add a network call without surfacing it. The pre-commit hook is the gate; ripping it out (`git config --unset core.hooksPath`) is the failure mode this constraint exists to prevent.

**Where this lives today:** `scatter/hooks/pre-commit`, `scatter/tests/test_leak_free.sh`, the `feedback_data_leaves_consciously` discipline in user memory.

### 4. Performance is user choice → no defaults that smooth brains

**Constraint:** When teaching a child, the default route is local. The cloud is reachable but never default for learning.

This is the constraint the sprint did not yet ship. The current `/chat` endpoint defaults to `cloud:sonnet` unless `prefer_local` is explicitly set. For *chat* this is fine — a child asking Scatter "what's the weather" is a chat. For *teaching* it is not — a child learning long division should not have her query routed to Anthropic's servers by default. The future `/v1/teach/*` flow must invert this: local is the default, cloud is an override that requires the parent capability and is logged in the journal.

**What the codebase must NOT do:** ship `/v1/teach/request` that mirrors `/chat`'s routing logic. Teaching has different defaults because the user is different.

**Where this lives today:** named here as the binding constraint for the next commit. CORE_SYNTHESIS.md #6 (license-neutral OS, operator-chosen corpus) and #4 (cluster real from day one or absent) together imply this — the corpus the operator installs governs the local teaching path; the cluster is the local hardware that runs it.

### 5. Negative capability as load-bearing capacity → pacing is a feature, not a bug

**Constraint:** Scatter does not optimize for fast answers to learning queries. It optimizes for held attention long enough for understanding to accrete.

In `power = work / time`, **time is not the enemy**. A 50-second Pi inference for a long-division lesson is on-thesis if those 50 seconds are spent rendering a paced, checkpointed, citation-grounded explanation. A 2-second cloud response that the child reads, says "uh huh," and moves past is off-thesis even if it's correct.

The future `/v1/teach/checkpoint` endpoint must implement this pacing as code: the lesson is broken into checkpoints; the child cannot advance until she demonstrates the prior step; the parent observer sees each checkpoint as it lands. Negative capability is the discipline of *not collapsing the lesson into a single response.*

**What the codebase must NOT do:** stream the entire long-division explanation as one block of text. Even a correct one. The pacing is the pedagogy.

**Where this lives today:** named here. The current `/chat` endpoint returns one block. The next sprint must implement checkpoints.

---

## The Machine Arguing pedagogy, as a code structure

The paper proposes thesis → antithesis → synthesis as the method. The model performs the antithesis from inside its dataset because critique is in the dataset.

Today this lives **only in the conversational record** — the dialectical exchanges that produced `CORE_SYNTHESIS.md` are preserved in `~/.scatter/dialectical/` (per CORE_SYNTHESIS.md's closing instructions) and surfaced as `docs/DIALECTICAL_LOG.md` in publication form.

But the pedagogy is not yet **in the system as a verb**. A user cannot today say "Scatter, run a Machine Arguing cycle on this hypothesis I have." The next architectural commitment binding this constraint:

- A `/v1/argue/request` endpoint accepting `{thesis: str, scope: str, models?: [str]}` and returning `{thesis, antithesis, synthesis, citations, dialectical_id}`.
- Antithesis is generated by the model with a system prompt that says "the critique is in your dataset; surface it."
- Synthesis is generated by a third call asked to neither agree nor disagree but to find the architectural claim that dissolves the framing.
- Every cycle writes to `~/.scatter/dialectical/<id>.json` so the journal grows.

This is named here as a future commitment, not a Phase 6 deliverable. CORE_SYNTHESIS.md does not yet specify it; this doc proposes it as a constraint of the paper.

---

## Three experiments the codebase must eventually enable

Per the paper page 6, these are the falsifiable predictions. The infrastructure must reach the point where they can run.

### Experiment 1 — Steerability as proximity

**Setup:** N children + one parent each. Half use Scatter's local Pi cluster path; half use the cloud-API path with state-of-the-art alignment. Same prompts. Same rubric.
**Measure:** self-reported steerability, task-completion rate on contested prompts, ability to modify model behavior when output is unsatisfactory.
**What the codebase must provide:** an A/B mode in the teach flow that is opaque to the child but logged for the experimenter. Live as of next sprint, not today.

### Experiment 2 — Thermodynamic integration at edge scale

**Setup:** one Pi running llama3.2:3b under sustained load. Calibrated USB power meter, calorimeter, water-temperature probe on a captured-heat loop.
**Measure:** total useful work (computation + thermal recovery) per kWh. Compare to a cloud-equivalent at PUE < 1.2.
**What the codebase must provide:** the `~12J (estimated)` label drops the `~` once a real meter feeds the WATTS dict. CORE_SYNTHESIS.md #9 names the meter as a Phase 0 task. Until it lands, every number is rendered as an estimate.

### Experiment 3 — Sovereignty as infrastructure

**Setup:** one user on Scatter local cluster, one user on cloud-API with equivalent privacy policy. Both run a battery of teaching queries. Packet inspection on both networks.
**Measure:** zero vs. nonzero telemetry exfiltration; zero vs. nonzero third-party data sharing; zero vs. nonzero behavioral data available for retraining.
**What the codebase must provide:** the leak test (already shipped) is the first half. The second half is a measurable claim — `scatter audit network` should run a packet capture during a representative session and produce a report that says "during this session, the only host contacted besides 127.0.0.1 was [list]." Today this is not implemented. It is named here as the next commitment binding sovereignty-as-infrastructure.

---

## What is decorative versus what is load-bearing, today

**Load-bearing in code as of 2026-04-26 (the deletion-and-fix sprint):**
- The cluster manifest at `~/.scatter/cluster.json` and the round-robin worker chain in `scatter-router/server.py` (decentralization → infrastructure)
- The watts label and the WATTS_INCOMPLETE_ROUTES disclosure (energy → first-class signal)
- The leak test in pre-commit (sovereignty → architecture, not preference)
- The Pixel portable bootstrap script (sovereignty → reproducible, owned hardware)

**Decorative in code as of 2026-04-26:**
- The Machine Arguing pedagogy (lives in DIALECTICAL_LOG.md as record, not as endpoint)
- Two-model verification (named in CORE_SYNTHESIS.md, not implemented)
- The teaching flow's local-first default (the constraint above is binding for the next commit; today's `/chat` defaults to cloud)
- Negative-capability pacing (no checkpoint endpoints yet)

The next sprint's job is to move items from the decorative column to the load-bearing column. CORE_SYNTHESIS.md D1–D10 names the path. This document names *why* — the paper's argument cannot be performed by code that merely gestures at it.

---

## How this document is meant to be used

This doc is **the contract the next commit lands into.** When `/v1/teach/request` ships, it satisfies constraints 1, 4, and 5. When `/v1/argue/*` ships, it satisfies the Machine Arguing structural commitment. When the calibrated watt meter ships, the `~` drops on the local label and Experiment 2 becomes runnable.

If you (Claude, Ryann, a future contributor) propose a commit that touches teaching, energy, routing, or telemetry, **read this doc first**. If the commit cannot be described as moving a decorative item into the load-bearing column or as preserving a constraint, it is not on-thesis.

The paper is the source. CORE_SYNTHESIS.md is the working spec. This doc is the bridge between them.

— translation, 2026-04-26
