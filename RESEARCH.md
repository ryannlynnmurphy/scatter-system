# Scatter OS — Research Hypotheses

Applied: Thesis → Antithesis → Synthesis → Scientific Method → Thesis' → Antithesis' → Synthesis''

This document is the conclusion of the dialectical process applied to the v0.2.0 codebase.
It specifies what we believe, what would prove us wrong, and what we're measuring.

## Hypothesis 1: Power-Aware Routing Increases Useful Queries Per Charge Cycle

**Claim:** Adaptive model selection based on battery state (7B at full power, 3B at moderate, minimal at critical) produces more total useful queries per charge cycle than fixed model selection.

**Measurement:** Total queries answered between 100% and 5% battery, user satisfaction per query.

**Implementation:** `scatter-ops/power_router.py` — selects model and context window based on battery tier.

**Falsification:** If fixed-model produces equal or more queries per cycle at equivalent satisfaction, the router adds complexity without benefit. Threshold: adaptive must deliver >15% more queries to justify the routing overhead.

## Hypothesis 2: Intelligence Per Watt Is Measurable and Meaningful

**Claim:** The ratio of tokens generated to watt-seconds consumed is a stable, meaningful metric that correlates with user-perceived usefulness.

**Measurement:** `~/.scatter/ipw-log.jsonl` tracks tokens, elapsed time, estimated power, and query type for every local inference call.

**Falsification:** If the metric varies by >50% for identical query types on the same hardware, it's too noisy to be useful. If users rate high-IPW responses as less useful than low-IPW responses, the metric doesn't capture what matters.

## Hypothesis 3: The Dialectical System Prompt Produces Different Outputs Than a Standard Prompt on a 7B Model

**Claim:** scatter-code's system prompt (which asks the model to present thesis/antithesis/synthesis before building) produces architecturally different code than a standard "you are a helpful coding assistant" prompt.

**Measurement:** Run identical tasks through both prompts. Compare: number of alternatives considered, architectural decisions surfaced, user-reported helpfulness.

**Falsification:** If synthesis collapses to thesis >80% of the time (the model just agrees with the user in fancier language), the dialectical prompt is theater on a 7B model. This is the most likely failure mode. The experiment is designed to catch it.

## Hypothesis 4: The Journal Produces Usable Research Data

**Claim:** Dialectical decision traces recorded through `scatter journal` constitute structured research data suitable for analysis in an ITP thesis.

**Measurement:** After 3 months of use, export the journal. Count: total entries, entries with full dialectical traces, entries where the antithesis changed the decision.

**Falsification:** If <10% of entries have full traces, the tool is being used as a note-taking app, not a research instrument. If the antithesis never changes the decision, the dialectic is performative.

## Hypothesis 5: A Non-Technical User Can Complete the Chatbot Project

**Claim:** The "Build a Local AI Chatbot" project in Scatter Studio (7 steps, concept/action/decision/build) can be completed by a person with no prior programming experience.

**Measurement:** Recruit 5 non-technical users. Give them a machine with Scatter installed. Time them. Record where they get stuck. Measure: completion rate, time to complete, self-reported understanding.

**Falsification:** If <3 of 5 complete the project, or if average completion time exceeds 6 hours, the teaching design fails for the target audience.

## The Experiment We're Running Right Now

**Subject:** Ryann Murphy, playwright, no CS background prior to February 2026.
**Method:** Build the Scatter OS using Claude Code as the primary tool and scatter-code as the local fallback.
**Data collection:** scatter-journal for decisions, ipw-log for energy metrics, git history for code evolution.
**Duration:** Now through ITP Fall 2026.

This codebase is simultaneously the product and the experiment.
The method proves itself by building itself.
The building documents the method.

Paper VI, Section 2.3: The recursive build.
The cloud trains the edge.
