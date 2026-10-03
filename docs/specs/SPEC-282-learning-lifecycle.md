---
id: SPEC-282
title: "Learning lifecycle — contradiction, reinforcement, decay, supersession, consolidation (issue #120 / M4-B4)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-10-01
accepted: 2026-10-01
substrate:
  - maistro-engine#ADR-015
  - maistro-engine#ADR-080
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#ADR-016
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
  - maistro-engine#SPEC-243
  - maistro-engine#SPEC-090226-e4a1
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/learnings/test_lifecycle.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-01
  - status: Accepted
    date: 2026-10-01
---

# SPEC-282: Learning lifecycle — contradiction, reinforcement, decay, supersession, consolidation

## Context

ADR-015's learnings are institutional knowledge injected into agent system prompts, and
ADR-080 gave *episodic* memory its dynamics (decay, reinforcement, consolidation,
conflict flags). Learnings had no dynamics: the stores were append-only or, worse, the
dedup path overwrote content in place — an update to institutional knowledge silently
erased the version it replaced, with no evidence of what changed or why. Issue #120
(M4-B4) makes that knowledge revisable: new evidence can reinforce, contradict, weaken,
combine, supersede or retire an earlier learning while preserving history.

## Decision

`maistro.memory.learnings.lifecycle` ships an `InMemoryLearningLifecycle` over
`InMemoryLearningStore`, holding three append-only ledgers beside the store (the same
side-record shape as `SkillMutation` and `LearningApproval`):

- **Evidence ledger** — one `LearningEvidence` per lifecycle event, globally
  sequence-ordered. Reinforcement, contradiction, weakening, supersession and
  consolidation are **evidence-driven kinds**: each carries an `EvidenceLink` naming the
  exact canonical Run (`run_id`/`node_run_id`/`attempt_id`, the #709 axes) or the
  evaluation (`eval_id`) that drove the change, and construction is refused without one.
  Creation adopts the provenance the store filled from the ambient execution context;
  decay and retirement are system-driven and stand without a link.
- **Revision ledger** — every mutation snapshots the prior `Learning` state *before*
  mutating (`LearningRevision`), so confidence and status updates never erase prior
  versions. Retired and superseded records keep their rows and remain visible to
  `list_all`; only active learnings are retrievable.
- **Conflict ledger** — `record_contradiction` lowers both sides' confidence
  (`CONTRADICT_DELTA`), keeps both active, and registers a `ConflictRecord` for human
  review (ADR-080 part B, applied to learnings; no auto-resolution, no winner). Re-
  registering an unresolved pair appends evidence without duplicating the record;
  `resolve_conflict` marks the review outcome and leaves disposal of the sides
  (supersede/weaken/retire) to explicit calls.

Operations: `reinforce`/`weaken` move confidence by the bounded deltas and refresh the
decay clock; `decay` charges `decay_per_hour` per silent hour (never past
`decay_floor`, optionally retiring at `retire_below`, never double-charging the same
silent interval); `supersede` stores the replacement and marks the old row
`superseded`; `consolidate` stores a **new derived row** whose `ConsolidationRecord`
names the exact source ids and marks sources `consolidated` — sources are preserved.
`find_relevant` keeps the store's keyword score as the primary key and orders equal
relevance by lifecycle confidence; its `LearningRetrieval` result **surfaces** every
unresolved conflict touching a returned learning, including conflicts whose counterpart
was not retrieved, and `find_conflicts` enumerates contradictions between *active*
learnings for evaluation harnesses and review queues.

Two orderings are load-bearing: in `supersede` and `consolidate` the outgoing rows
leave the `active` set **before** the new row is stored, because the store's dedup
probe matches `active` rows only — storing first would land the new content on the old
row and erase it in place, exactly what this lifecycle exists to prevent.

The lifecycle tracks the learnings it observed and holds the store's own instances
(after a dedup hit, the store keeps the pre-existing object). The ledger is in-memory
and states so; durable twins follow, as they did for the episodic store.

## Acceptance criteria

- [ ] Reinforcement and contradiction evidence name the exact Run (or evaluation) that
      drove them; updates without any link are refused and leave no trace.
- [ ] Confidence and status updates snapshot the prior version first; superseded,
      retired and consolidated records stay in the store and in the revision history.
- [ ] Silent learnings lose confidence over time (floor-limited, optionally retired);
      a superseded learning drops out of retrieval while its record and history remain.
- [ ] Consolidation stores a new derived record whose provenance names the exact source
      ids, and preserves the deactivated sources.
- [ ] Conflicting active learnings are enumerable (`find_conflicts`) and surfaced to
      retrieval (`LearningRetrieval.conflicts`, both sides attached); resolution is
      explicit and review-driven.

## Out of scope

- Durable (SQLite/PostgreSQL) twins of the evidence/revision/conflict ledgers.
- Semantic contradiction *detection* (which pairs conflict) — registration is
  evidence-driven, mirroring SPEC-241's injected `ContradictionFn`.
- The engine wiring that calls the lifecycle during runs and evaluations.
