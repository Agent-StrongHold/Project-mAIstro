---
id: ADR-100126-9a4b
title: Validated collective learning — Memory → Learning → Validated Learning → Repertoire
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-01
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-015
  - maistro-engine#ADR-034
  - maistro-engine#ADR-070
  - maistro-engine#ADR-080
  - maistro-engine#ADR-091
implements: []
related:
  - maistro-engine#ADR-083026-e602
  - maistro-engine#SPEC-062126-5d56
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/learnings/test_lifecycle.py
  - packages/maistro-core/tests/memory/learnings/test_gauntlet.py
  - packages/maistro-core/tests/memory/learnings/test_learning_lifecycle_store.py
  - packages/maistro-core/tests/persistence/test_sqlite_learning_lifecycle.py
  - packages/maistro-core/tests/persistence/test_learning_contract.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-01
---

# ADR-100126-9a4b: Validated collective learning

## Context

The `Learning` record (ADR-015) knew exactly two things about itself: that it
existed and how often it had been recalled. Promotion to the collective —
injection into every later Run's prompt in `get_promoted` — turned on
`hit_count` alone. That conflates three different facts:

1. **Recall frequency** — how often a learning was *injected*. A wrong
   learning triggered by common words is recalled constantly.
2. **Local belief** — a correction one scope extracted from its own tool
   history. Untested against anything but its producer's enthusiasm.
3. **Institutional knowledge** — a correction that later, independent Runs
   followed and measurably benefited from.

The episodic side of memory solved this long ago (ADR-080: weight-bounded
tiers, REGRET's structural floor, decay and consolidation). The learning side
had no stage semantics, no epistemic typing, no contradiction or decay
dynamics, and no promotion gate stricter than the hit count — so a
failure-followed learning recalled fifty times promoted exactly as easily as a
genuinely validated one, and failure knowledge (RCA output) had no retained,
promotable form at all.

## Decision

Four decisions, one per M4-B child:

### 1. The stage ladder formalizes Memory → Learning → Validated → Repertoire (#117)

`Learning.stage` (`LearningStage`) positions a row on the pipeline:

- `MEMORY` — the source tier (episodic records). Never a learning's stage; it
  exists so the ladder is total.
- `LEARNING` — local belief, extracted by one scope. Every stored learning
  starts here.
- `VALIDATED` — an independent Gauntlet accepted the recorded evidence (#118).
  Still scoped; now believed.
- `REPERTOIRE` — collective, reusable knowledge. **The only door in is through
  `VALIDATED`; stages cannot be skipped or reversed.** Reaching REPERTOIRE
  flips row `status` to `promoted` so existing promoted-only readers keep
  working; `status` stays the store-level row state, `stage` the epistemic
  position.

### 2. An independent Gauntlet stands between threshold and repertoire (#118)

`hit_count` only makes a learning a *candidate*. A `LearningGauntlet` judges
`GauntletEvidence` — the outcome counters later Runs recorded
(`success_after_use`, `failure_after_use`, contradictions, reinforcements) and
whether a producing Run is named at all (ADR-083026-e602: unattributed
knowledge cannot be validated). **`hit_count` is deliberately absent from the
evidence**: a learning recalled fifty times and followed by failures must fail,
which is exactly the case hit-count promotion waved through.
`OutcomeEvidenceGauntlet` is the concrete judge; `ChainedGauntlet` composes.
A learning the Gauntlet rejects stays active and local, untouched — promotable
once later Runs record better evidence.

### 3. Learnings carry applicability, confidence, provenance, epistemic type (#119)

New durable fields: `applicability` (task types/tools where the correction
applies), `confidence` (0..1, decayed toward an epistemic floor),
`epistemic_type` (`EMPIRICAL` observed correction, `INFERENTIAL` RCA-derived
diagnosis, `ANTI_PATTERN` failure knowledge), and Gauntlet provenance
(`validated_by`, `validated_at`). Producer provenance
(`run_id`/`node_run_id`/`attempt_id`, #709) predates this ADR; validation
provenance names *which independent judge* accepted.

### 4. Learnings get the dynamics episodic memory always had (#120, #121)

- **Reinforce/contradict**: counters plus bounded confidence movement
  (reinforcement never past 1.0; contradiction never through the epistemic
  floor).
- **Decay**: exponential, anchored at `last_confirmed_at` (a just-confirmed
  learning does not decay from birth), 30-day half-life for empirical
  knowledge. **Anti-patterns decay on a 120-day half-life toward a 0.6 floor**
  — failure knowledge is structurally unforgettable, the learning-side mirror
  of REGRET: an anti-pattern cost a real failure to learn, and forgetting it
  re-buys the failure.
- **Supersession**: both rows survive, linked in both directions
  (`supersedes`/`superseded_by`); institutional knowledge is retained, never
  deleted.
- **Consolidation**: drifted near-duplicates merge; the survivor inherits the
  union of trigger keys and the summed outcome evidence, because evidence
  belongs to the knowledge, not to whichever duplicate held it.
- **Failure knowledge is promotable (#121)**: `capture_anti_patterns`
  reclassifies repeatedly-followed-into-failure learnings as `ANTI_PATTERN`
  and lifts them to the floor. Reclassification is *not* validation — joining
  the repertoire still requires the Gauntlet, and anti-patterns whose
  avoidance still fails often fail it like any other learning.

All twelve new fields are durable in both SQL twins; migration 048 adds the
columns, and #1156's disposition contract enforces that a future Learning
field cannot land in one twin only.

## Alternatives considered

- **Trust hit_count with a higher threshold.** Rejected: frequency is not
  effectiveness; any fixed threshold waves through a consistently harmful
  learning that is consistently recalled.
- **Human approval only** (the existing `LearningApprovalGate`). Retained for
  the legacy path, but a human queue does not scale to per-Run learning and
  answers a different question ("should we ship this?") than the Gauntlet's
  ("has this measurably helped later Runs?"). When both are configured the
  Gauntlet decides; the approval gate governs the legacy path.
- **Reuse `Repertoire` (ADR-070) types for the verdict.** Rejected for now:
  `Verdict` is the Rehearse-step outcome for candidate *solutions*; the
  Gauntlet judges accumulated *evidence* on a stored record. The shapes are
  cousins (`ok` + reason); converging them is deferred until a consumer needs
  both in one cascade.

## Consequences

- Promotion is evidence-gated by default only where a Gauntlet is wired; the
  legacy auto-promotion path is unchanged for existing callers (no behavior
  breaks, but callers must opt into validation).
- Validation is only as good as outcome attribution: a scope that never calls
  `mark_outcome` starves its own Gauntlet (min_uses fails), which fails closed
  toward *not* promoting — the safe direction.
- The durable schema grows by 11 columns (migration 048). SQLite files upgrade
  in place; pre-M4B rows read back as the local empirical learnings they were.

## Acceptance criteria

- [ ] A learning cannot reach REPERTOIRE without passing VALIDATED (no skip,
      no reversal; `MEMORY` is never a destination).
- [ ] A Gauntlet-configured promoter promotes only Gauntlet-accepted
      candidates, records `validated_by`/`validated_at`, and leaves rejected
      rows active and local.
- [ ] The Gauntlet's evidence excludes `hit_count`; high-recall/failing
      learnings fail it.
- [ ] Unattributed learnings (no producing Run) fail validation.
- [ ] Contradiction of an anti-pattern never drops its confidence below 0.6;
      anti-patterns decay on the slow clock.
- [ ] `capture_anti_patterns` converts ineffective learnings to retained
      anti-pattern knowledge; they remain promotable through the same
      Gauntlet.
- [ ] Supersession links both rows and retires neither from readability;
      consolidation folds evidence into one survivor.
- [ ] Lifecycle state is durable in both SQL twins (round-trip test; #1156
      partition test covers the disposition).
