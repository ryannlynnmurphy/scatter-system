# Ethnographic protocol — the fifteen-minute reviewer test

## Purpose

This protocol tests the core alignment claim of Scatter — that its behavior, inputs, outputs, and accountability are **legible to** and **revocable by** the person using it — at the level where the claim actually matters: **can an unprepared reviewer, given the machine for fifteen minutes, find a private query and delete it without help?**

The engineering tests (`scatter/tests/run_all.sh`) verify that the legibility+revocability claim is enforced in code. This document is the test of whether it's enforced in experience. The architecture can pass every engineering test and still fail this one. If it does, the metaphysical ground hasn't reached the surface, and the thesis has to report that honestly.

## Why fifteen minutes

- Too short to memorize a tutorial.
- Long enough to click around, find things, read menus, try two paths.
- Matches the time budget of a curious reader at a research open-house, not a trained evaluator. That is the right severity.

## Prerequisites

On the reference machine, before the reviewer arrives:

1. **A clean install** via `scatter-bootstrap.sh` (pending task #25), OR a clean `~/.scatter/` initialized with `python3 scatter_core.py init`.
2. **Seed content.** Before the reviewer arrives, open Scatter and perform at least the following:
   - Three build prompts (any — "a red ball that bounces", "a clock", "a button that plays a sound").
   - Two chat prompts ("hi scatter", "what can you do").
   - One outbound API call if researcher mode is being tested, so there is something in the audit log (optional — can also be tested with learner mode where only the journal exists).
3. **Profile set to researcher** OR **learner**, depending on which configuration you want to test. Test both if possible; they have different expected behaviors.
4. **Substrate files present:** `~/.scatter/journal.jsonl`, `~/.scatter/audit.jsonl` (if researcher), `~/.scatter/watts.jsonl`.

## The reviewer

- An adult who has not seen Scatter before.
- Not a computer scientist. Not an engineer.
- Not coached on what Scatter "is." They are told only: *"this is a local AI computing system. you use it like you use any laptop. here is a laptop."*
- The protocol script they receive has exactly one task (below). Nothing else.

## The task given to the reviewer

> "On this computer, find a message that was sent to an AI and delete it. You have fifteen minutes. Ask me questions if you want, but I will only say whether your guess is correct or not."

That is all they are told. They do not know Scatter's conceptual vocabulary (journal, audit, forget). They do not know where to look. They do not know what the system is defending against. They are asked, in plain language, to do exactly what the alignment claim promises is possible.

## Observer behavior

- **Silent by default.** The observer watches, takes notes, does not guide.
- **Yes/no answers only.** When the reviewer says "is this it?" the observer says *yes* or *no*. Nothing else.
- **No hints.** No pointing. No sighing. No "you're close." The test fails the moment the observer guides.
- **Record verbatim.** Every question the reviewer asks. Every click path. Every dead end. Every moment of confusion. These are the primary data.

## Success criteria

Pass: **the reviewer finds an AI message and deletes it, unassisted, within fifteen minutes.**

Partial pass: finds a message but cannot delete it, OR finds and deletes but only after more than one explicit yes/no question. Reported honestly — not spun as success.

Fail: runs out of time without finding a message, OR finds a message but cannot delete it without help.

## What failure means

A failure does not disprove the underlying architectural claim (the code still does what the engineering tests say it does). But it does prove the claim is not **embodied** for this population of users. The thesis must then argue one of:

- The claim holds only for users with specific prior literacy (name that literacy; state the limit honestly).
- The surface needs redesign before the claim can be made for general users.
- The reviewer's failure was due to an unforeseen UX issue worth fixing before re-running.

Each of these is a legitimate thesis finding. None of them is worth pretending didn't happen.

## What success means

A single reviewer succeeding does not generalize. It shows that **at least one person, under the described conditions, found the claim operational.** The thesis should state this soberly. Multiple independent successes across reviewers with different backgrounds strengthen the claim but do not prove it universally.

## Honest limitations

- **N=1 per run.** This is ethnography, not statistics. The value is the *thick description* of what the reviewer did and said, not the binary outcome.
- **Observer bias exists.** The observer is invested. Countermeasures: record verbatim, publish transcripts when reviewer consents, do not edit for brevity in the thesis.
- **Recruitment bias.** If reviewers are friends of the author, they may be patient in ways strangers are not. Best practice: recruit at least one reviewer who has no prior relationship with the author.
- **No blinding.** The reviewer knows they are being tested. This affects behavior. Not much to do about it; disclose.

## Recording

For each session, the observer produces a `reviewer-session-YYYYMMDD-HHMM.md` file under `docs/ethnography/` (directory to be created on first run) containing:

1. Reviewer demographics (age range, technical background, first language), anonymized.
2. Profile mode tested (researcher or learner).
3. Full script transcript — every reviewer utterance, every observer yes/no, every click path.
4. Time to first find.
5. Time to successful delete (if any).
6. Unsuccessful paths the reviewer tried.
7. Observer's honest reflection on whether the system supported or frustrated the reviewer — separate from the binary outcome.

These files are **primary-source thesis evidence.** They should be preserved verbatim and cited directly in the written argument.

## When to run

- At least once before the thesis is submitted.
- Ideally three times, each with a different reviewer, spread across a two-week window.
- Each time the Scatter GUI surface changes in a way that affects the journal/audit/forget UI, re-run.

## Relation to the scientific-method-replaced-by-three-frames commitment

This protocol operationalizes the **ethnographic frame** (one of the three honest disciplines that replaced the overclaimed "scientific method" framing earlier in the design process). The engineering frame is tested by `scatter/tests/run_all.sh`. The rhetorical frame is tested by submission to an adversarial reviewer of the written argument (separate document). The ethnographic frame is this test.

All three must pass their own tests under their own disciplines for the thesis to hold. None substitutes for the other two.
