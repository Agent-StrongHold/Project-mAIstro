---
id: SPEC-100426-b103
title: "Knowledge-stage ladder — Memory -> Learning -> Validated -> Repertoire semantics (issue #117 / M4-B1)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-10-04
accepted: 2026-10-04
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-015
  - maistro-engine#ADR-070
  - maistro-engine#ADR-091
implements:
  - maistro-engine#ADR-103
related:
  - maistro-engine#SPEC-258
  - maistro-engine#SPEC-283
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/learnings/test_learning_lifecycle.py
  - packages/maistro-core/tests/memory/learnings/test_stage_grants_no_authority.py
  - packages/maistro-core/tests/persistence/test_sqlite_learning_stage.py
  - packages/maistro-core/tests/persistence/test_pg_learning_stage.py
ac-modules:
  AC-1: maistro.memory.learnings.lifecycle
  AC-2: maistro.persistence.sqlite_learnings
  AC-3: maistro.persistence.sqlite_learnings
  AC-4: maistro.security.sentinel.policy
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-04
  - status: Accepted
    date: 2026-10-04
---

# SPEC-100426: Knowledge-stage ladder — Memory → Learning → Validated → Repertoire

## Context

ADR-103 defines the four knowledge stages a `Learning` record moves through on
its way from execution-local remembered evidence to reusable institutional
knowledge: `MEMORY` (remembered evidence/context, captured with producer
provenance but not yet asserted as a claim), `LEARNING` (a claim inferred from
that evidence), `VALIDATED` (a claim that survived independent evaluation),
and `REPERTOIRE` (validated learning explicitly promoted for reuse in shared
knowledge). This spec pins those semantics to measurable acceptance criteria
over the machinery that already implements them: `LearningStage` and
`plan_advance` in `maistro.memory.learnings.lifecycle`, and the
`advance_stage`/`stage_history` pair every `LearningStore` backend implements
(in-memory, SQLite, PostgreSQL, and the durable hybrid that composes them).

Two lines the ladder must not cross are part of the contract, not commentary:

- **No parallel runtime.** The ladder is fields and transition functions over
  the one `Learning` record — never a scheduler, store, or execution authority
  beside the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` spine.
- **Knowledge state never grants permissions or execution authority.** The
  Sentinel and every other authorization surface never read the stage,
  `status`, or the transition ledger; what a tool may run is decided solely by
  the permission table / live permission source (#1165), never by how believed
  a claim is.

`status` remains the read surface (`get_promoted`, prompt injection); `stage`
is the semantics surface. A REPERTOIRE commit writes both. Legacy rows that
predate the ladder read as `memory` with blank `validated_by`/`promoted_by` —
the truth — and the migration never fabricates validation that never happened.

## Acceptance criteria

- [x] **AC-1**: A fresh learning starts at `MEMORY`, and `plan_advance`
      permits exactly the forward single-step order MEMORY → LEARNING →
      VALIDATED → REPERTOIRE: skipping a rung, moving backward, advancing past
      the top, an anonymous (blank) actor, and an unknown stage value are each
      rejected with `InvalidStageTransition` and leave the record unmoved.
- [x] **AC-2**: Every accepted transition is durable and auditable: the store
      applies the guarded row update and appends the append-only transition
      ledger row in one transaction (SQLite commit; PostgreSQL
      `conn.transaction()`), `stage_history` reads the trail back oldest
      first scoped to the caller's org, a restart keeps both stage and trail,
      a rejected transition writes neither row nor ledger row, and a
      concurrently-losing writer raises instead of half-applying.
- [x] **AC-3**: Producer, validator and promoter are separately attributable
      facts: advancing to `VALIDATED` stamps `validated_by` with the recorded
      evaluator, advancing to `REPERTOIRE` stamps `promoted_by` and flips
      `status` to `promoted` so every existing promoted-only reader
      (`get_promoted`, prompt injection) keeps working unchanged, and a
      database created before the ladder upgrades in place with no fabricated
      provenance backfilled.
- [x] **AC-4**: A knowledge stage never grants permissions or execution
      authority: a REPERTOIRE learning naming a tool does not move the
      Sentinel's fail-closed `check_permission` decision for that tool, no
      module under `maistro.security` imports the stage machinery
      (`memory.learnings`, `LearningStage`, `advance_stage`,
      `learning_stage_transitions`, `stage_history`), and the ladder's public
      surface returns data records — never stores, runners, or permission
      tokens.

## Out of scope

- Who may act as the independent evaluator and what evaluation must do
  (#118 Gauntlet); the ladder records the evaluator, it does not judge one.
- Epistemic typing, confidence dynamics, decay/consolidation of learnings
  (#119/#120 — SPEC-283 owns the revisable lifecycle).
- Wiring any caller to *drive* the ladder; this spec proves the semantics and
  their durability, not a scheduler (none is wanted — see ADR-103's scope).
