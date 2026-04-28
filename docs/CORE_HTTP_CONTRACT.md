# Scatter Core HTTP Contract — v0

**Status:** Draft, 2026-04-20.
**Owner:** Ryann Murphy. **Implementation target:** scatter-system substrate.
**License:** MIT (same as scatter-system).

---

## Why this exists

Scatter is consolidating from 19 GitHub repos to one product. The 6 real components — substrate, router, voice persona (Scatter), cluster, Studio modes, Academy lessons — must talk through one disciplined surface, or the consolidation is cosmetic. This document is that surface.

The contract is the load-bearing artifact. Ship the contract, conform every component to it, and the consolidation becomes mechanical. Skip the contract, and Scatter remains six tools that share branding.

**Mission constraint:** A child makes their own brain on hardware they own. Every contract decision is judged against legibility (does the operator see what happened?), revocability (can they undo it?), sovereignty (does data stay local by default?), and pedagogy (does the build teach?).

---

## Scope of v0

**In scope:**
- A single HTTP service exposed by `scatter-system` on `127.0.0.1:3333` (the existing port).
- All endpoints prefixed `/v1/`.
- External components — cluster, voice, Studio, Academy — talk to Core only through this contract.
- Multi-user identity stub (header-based `X-Scatter-User`, single user enforced; expansion is profile addition).
- Session state moves from in-memory dict to file-backed store with ETag concurrency.
- Routing policy returns an explicit `RoutingDecision` (cloud / local / cluster + watt estimate + audit id).
- Memory contract over journal / audit / sessions / dialectical, with `forget` semantics preserved.
- Teaching contract for Academy: request a lesson, retrieve from corpus, record checkpoint.

**Out of scope (deferred, with reason):**
- Authentication beyond loopback + identity header. *Reason:* head node is owned by one operator; LAN exposure is a deliberate later choice.
- Multi-machine sync (laptop ↔ Pi cluster head migration). *Reason:* Tailscale is the substrate when this happens; design separately.
- Semantic / vector index over the journal. *Reason:* JSONL stays truth; an SQLite index is derived and rebuildable — ship after first corpus is in.
- Distributed inference (one large model split across Pis). *Reason:* shipping per-node Ollama on workers gives 80% of the user-visible value at 10% of the engineering cost. Distributed inference is research, not product.
- WebSocket streaming. *Reason:* v0 is request/response. Streaming is a v1 add when the voice loop's <2s budget demands it.

**Architectural commitment:** Scatter Core stays in-process for `scatter/server.py` (the GUI host). The 27 existing `scatter_core.*` callsites do **not** migrate to HTTP — they remain direct function calls. The HTTP contract is the surface for *external* clients (cluster, voice daemon, Studio, Academy). This avoids the 3-roundtrip latency tax on the head node while giving every other component one disciplined door.

---

## Identity

```
Header: X-Scatter-User: <user_id>     # required on every endpoint
```

For v0, `user_id` is matched against `~/.scatter/users/<user_id>.json`. If the file does not exist, the request is rejected with `403 unknown_user`. The default install creates one user and that user's id is set as the header on the GUI host. Adding a child means creating a new user file. No tokens, no passwords — the contract trusts loopback. LAN exposure is a separate decision that adds an auth scheme.

Profile (`researcher` / `learner` / `child`) lives on the user record, not in `config.json`. The existing `assert_researcher` gate in `scatter/api.py` keeps working — it just reads from the per-request user instead of the singleton.

**Reason:** Multi-user is the prerequisite for "a child makes their own brain." Without per-user state, every child shares one Scatter; no parent oversight, no per-child curriculum. The header-and-file scheme is the smallest thing that gives this property without forcing a database in v0.

---

## Endpoints

All endpoints respond JSON. Errors are `{ "error": "<code>", "detail": "<human>" }` with appropriate HTTP status.

### Routing

```
POST /v1/route
  body: { task: str, hint?: "fast" | "deep" | "voice", prefer_local?: bool }
  200:  RoutingDecision

RoutingDecision = {
  decision_id: str,         # journaled; pass back on /v1/messages
  destination: "local" | "cloud" | "cluster",
  model: str,               # qwen2.5-coder:7b | claude-sonnet-4-6 | ...
  node: str | null,         # pi-1..pi-4 if destination=cluster, else null
  watt_estimate_j: float,
  audit_id: str | null,     # set if cloud, null if local/cluster
  rationale: str,           # short, surface-able to UI ("local model handles regex tasks")
}
```

The `RoutingDecision` is the single source of truth for the "Claude API button." A UI element renders `destination` + `rationale` + `watt_estimate_j`. No money — per the "no money prompts" rule. Watts and route, that's the disclosure.

```
POST /v1/messages
  body: { decision_id: str, messages: [{role, content}], max_tokens?: int }
  200:  { content: str, watts_actual_j: float, audit_id?: str, latency_ms: int }
```

Caller passes the `decision_id` returned from `/v1/route`; Core enforces that the call matches the decision (no quietly upgrading from local to cloud). For local routes, Core proxies Ollama. For cloud, Core routes through `scatter/api.py` (existing audit-logged path). For cluster, Core forwards to `scatter-cluster`'s `/route` (next section).

### Cluster (when present)

If `~/.scatter/cluster.json` declares a cluster head, `/v1/route` may return `destination: "cluster"`. Core then forwards `/v1/messages` to the cluster head's `/route` endpoint. The cluster's existing routing — UDP discovery, circuit breakers, capability scoring — applies. Worker nodes must run an inference engine (Ollama is v0; vLLM is later). Cluster integration follows **Option A**: Core makes the inference call once it has the routing decision. **Option B** (workers run inference, Core calls a `/cluster-inference` endpoint and waits) is the next phase.

This is where today's theater stops. Until workers run real models, `destination: "cluster"` is unavailable in `/v1/route`. No silent fallback; no marketing "your own AI" before workers serve it.

### Memory: journal

```
POST /v1/memory/journal
  body: { kind: str, fields: object }
  201:  { id: str, ts: float }

GET  /v1/memory/journal?kind=<k>&limit=<n>&since_ts=<t>
  200:  { entries: [...] }   # honors forget tombstones

POST /v1/memory/forget
  body: { id: str, reason: str }
  200:  { tombstoned: true }
```

Mirrors `scatter_core.journal_*` exactly. JSONL stays truth. A future SQLite derived index is an internal implementation detail, never a separate API.

### Memory: audit

```
POST /v1/memory/audit/begin
  body: { service, endpoint, payload_summary }
  200:  { audit_id: str }

POST /v1/memory/audit/commit
  body: { audit_id, status: "ok"|"fail", duration_ms, tokens?, joules? }
  200:  { committed: true }

GET  /v1/memory/audit?limit=<n>
  200:  { entries: [...] }
```

Existing pattern in `scatter/api.py`, formalized as a contract so Studio's 12 `/api/*-ai` routes use the same audit path as `claude_chat` does today.

### Memory: sessions

```
GET  /v1/memory/session/<session_id>
  200:  { state: object, etag: str }
  404:  if absent

PUT  /v1/memory/session/<session_id>
  headers: If-Match: <etag>
  body: { state: object }
  200:  { etag: str }
  409:  if etag mismatch (caller must re-fetch and merge)
```

This solves the audit's #1 blocker: the in-memory `sessions` dict shared across requests. Sessions move to `~/.scatter/sessions/<user_id>/<session_id>.json`. ETag is the file's mtime+hash. Standard optimistic-concurrency pattern; well-understood failure mode (caller re-fetches and merges); no database required for v0.

### Memory: dialectical

```
POST /v1/memory/dialectical
  body: { title, thesis, antithesis, synthesis }
  201:  { id: str }

GET  /v1/memory/dialectical?since=<ts>&q=<text>
  200:  { entries: [...] }

GET  /v1/memory/dialectical/export.md
  200:  text/markdown   # mirrors current dialectical-export
```

The Scatter Method is publishable evidence that the architecture survived dissent. The contract surface lets Studio and Academy log dialectical exchanges — for instance, every time a child's lesson plan is rejected and revised, that exchange is recorded.

### Identity

```
GET  /v1/identity/me
  200:  { user_id, profile, display_name }

GET  /v1/identity/users
  200:  { users: [{user_id, profile, display_name}] }   # operator only
```

The contract surface for the parent/teacher view. No surveillance creep — operator sees what users exist; per-user activity reads come from journal / audit endpoints with a `user_id` filter (already implicit since each request carries the header).

### Accounting

```
GET  /v1/accounting/watts?since=<ts>&by=source|user
  200:  { total_joules: float, breakdown: {...}, tokens_per_joule?: float }
```

Existing endpoint, scoped by user.

### Teaching (the Academy hook)

```
POST /v1/teach/request
  body: { goal: str, age?: int, prior?: object }
  200:  LessonPlan

LessonPlan = {
  lesson_id: str,
  steps: [
    { step_id: str, kind: "explain"|"do"|"check", body: str, citations: [{url, source}] }
  ],
  artifact_kind: "note"|"reference"|"lesson",   # uses artifacts.py types
}

POST /v1/teach/checkpoint
  body: { lesson_id, step_id, response: str }
  200:  { passed: bool, feedback: str, next_step_id?: str }

GET  /v1/corpus/search?q=<text>&grade=<n>&standard=<ccss_code>
  200:  { hits: [{snippet, citation: {url, source, ccss?}}] }
```

This is where the existing `teaching.py` (3-tier routing) and `artifacts.py` (typed outputs) become the basis of Scatter Academy. The corpus is RAG'd from `~/.scatter/corpus/<corpus_id>/`. **First corpus: CK-12 K-5 math** as the engineering proving ground. **Second corpus: Eureka Math / EngageNY** as the pedagogical primary (per the corpus survey). Both CC BY-NC; commercial posture is settled before either ships to users beyond Ryann.

Citation enforcement: Core refuses to return a teach response without retrieved citations. "Scatter teaches" is grounded against a real corpus or it doesn't run.

---

## What this changes for each component

| Component | Today | Under contract |
|---|---|---|
| `scatter-system` (head node) | 27 in-process callers, 14 ad-hoc endpoints | Same in-process, formalize endpoints under `/v1/`, add identity + sessions + teach |
| `scatter` (small router) | Standalone FastAPI on :8787 | **Folds into Core.** `/v1/route` replaces it. |
| `scatter-cluster` (formerly separate routing repo) | Standalone routing facade, no inference | Becomes Core's cluster backend; workers gain Ollama (Phase 2 of cluster) |
| Scatter (voice persona) | Direct Anthropic + Whisper + Spotify SDK calls | Talks to Core for routing + memory; voice loop stays its own daemon for latency |
| tiny-scatter shell (universal shell) | llama.cpp local with 40+ instant handlers | Folds in as the engine behind the bottom bar; Core registers it as a local model |
| `StreamClipper` → `Scatter Studio` | 12 `/api/*-ai` routes call Anthropic directly | One adapter wraps all 12 to POST `/v1/route` then `/v1/messages`. State migrates from legacy `localStorage scatter_*` keys to Core sessions. |
| Academy (new) | Doesn't exist | Rides on `/v1/teach/*` + `/v1/corpus/search` against ingested CK-12 |

---

## Test contract

The leak-free test pattern (`scatter/tests/test_leak_free.sh`) extends to the contract. Three new architectural tests:

1. **No external client may import `scatter_core` directly.** Cluster, voice, Studio, Academy all reach Core through HTTP. Test: grep for `import scatter_core` outside of `scatter-system/scatter/`.
2. **No external client may touch `~/.scatter/` filesystem.** Same story — go through the contract. Test: grep for `~/.scatter` paths outside of `scatter-system/`.
3. **Every external call records a `RoutingDecision`.** No quiet bypass to Anthropic. Test: every `/v1/messages` request must carry a `decision_id` that exists in journal.

Tests run on every commit via the existing pre-commit hook.

---

## Versioning

`/v1/` is fixed. Breaking changes go to `/v2/`. Additive changes (new endpoints, new fields) stay on `/v1/`. The contract version is independent of the scatter-system release version — Core can ship multiple versions simultaneously when transitioning.

---

## What gets built first (Phase 0, this week)

To prove the contract round-trips end-to-end with a single user and the existing components:

1. Move profile from `config.json` to `~/.scatter/users/default.json`. Add `X-Scatter-User` header parsing to `server.py`. Default user is `default`. Existing single-user behavior unchanged.
2. Move sessions from in-memory dict to `~/.scatter/sessions/default/<id>.json` with ETag.
3. Add `/v1/route` returning a `RoutingDecision` (today's `route_intent` already does this internally — formalize the response shape).
4. Add `/v1/messages` taking a `decision_id`. Existing `claude_chat` and Ollama paths get called from here.
5. The "Claude API button": a Studio UI element that calls `/v1/route` first, displays `destination` + `rationale` + watts, and only then issues `/v1/messages`. The button working = the contract working.

Phase 0 ships when one Studio mode (Write) makes a Claude call through the contract end-to-end, with the routing decision visible in the UI and the audit entry visible in `/v1/memory/audit`.

---

## Open questions to resolve before v1

- **Voice latency budget under contract.** Scatter's voice loop targets <2s end-to-end. If `/v1/route` + `/v1/messages` adds >150ms, voice gets its own fast path (direct intent classification, skip routing for voice-flagged requests).
- **Child profile vs learner profile.** Current scatter-system has `learner` (network-isolated). Child UX likely needs a separate profile with: corpus-only retrieval, no shell access, parent-revocable history. Define before Academy ships.
- **Corpus storage layout.** Per-corpus subdir under `~/.scatter/corpus/`? Per-user or shared? Citations must survive offline (per "data leaves consciously" — the `saythanks` link can't be the only attribution surface).
- **Cluster head failover.** When the laptop is one client among many (school deployment), which Pi becomes Core? Answer is "the one declared in `cluster.json`" but the failover semantics need design.
- **Distillation of `scatter` into `scatter-system`.** The small router has a clean web UI worth keeping. Either fold the UI into scatter-system's `scatter/ui/` or keep it as a thin example client of Core.

---

## How this aligns with what's already there

The audit found that scatter-system already has more contract surface than expected: 14 endpoints, typed artifacts, three-tier routing in `teaching.py`, leak-free tests. **This contract is mostly a renaming and a versioning of what Ryann already shipped**, plus identity + sessions + teach. That's the honest news: the substrate to make Scatter one product is built. The contract is the discipline that turns six tools into one product.
