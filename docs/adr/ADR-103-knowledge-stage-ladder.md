---
id: ADR-103
title: "The knowledge-stage ladder: Memory -> Learning -> Validated -> Repertoire"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-01
accepted: 2026-10-01
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-015
  - maistro-engine#ADR-070
  - maistro-engine#ADR-091
implements: []
related:
  - maistro-engine#SPEC-258
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
  - packages/maistro-core/tests/persistence/test_learning_contract.py
ac-modules:
  AC-1: maistro.types.memory.LearningStage
  AC-2: maistro.memory.learnings.lifecycle
  AC-3: maistro.persistence.pg_learnings.PgLearningStore.advance_stage
  AC-4: maistro.persistence.sqlite_learnings.SqliteLearningStore.advance_stage
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Accepted
    date: 2026-10-01
---

# ADR-103: The knowledge-stage ladder — Memory → Learning → Validated → Repertoire

## Context

The repository holds several knowledge-flavoured concepts that were never
formally related: the `Learning` record (ADR-015), the 7-tier episodic
`MemoryTier` ladder ending in `WISDOM` (ADR-013/016/091), the repertoire
pattern (ADR-070/SPEC-258), and the `status` field on a learning
(`active`/`promoted`) that `get_promoted` and prompt injection select on.
Nothing says how a piece of execution-local remembered evidence becomes
reusable institutional knowledge, or what each step along that path may
claim. Two failure modes are to be avoided: inventing a parallel runtime that
competes with the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
spine, and prematurely promoting `Wisdom` — an episodic-store *weight axis* —
into a universal MAIstro noun for validated knowledge (ADR-091 explicitly
keeps tier as retrieval weight, and ADR-080's `reclassify` remains an
episodic-store-internal dynamic).

## Decision

Adopt a four-stage **knowledge ladder over the existing `Learning` record** —
fields and transition functions, not a new store, scheduler, or execution
authority:

| Stage | Meaning | Recorded proof |
|---|---|---|
| `MEMORY` | Execution/agent-local remembered evidence/context. Captured with producer provenance (`run_id`/`node_run_id`/`attempt_id`, #709) but not yet asserted as a reusable claim. | The row itself; no transition record yet. |
| `LEARNING` | A claim inferred from that evidence — the correction a later execution may consider. | Ledger row + the claim's producer provenance. |
| `VALIDATED` | A claim that survived independent evaluation. The evaluator is recorded; the *independence* of the evaluator is the caller's duty, which a stage value cannot prove. | Ledger row + `validated_by`. |
| `REPERTOIRE` | Validated learning explicitly promoted for reuse in shared knowledge. | Ledger row + `promoted_by`, and `status` flips to `promoted` so every existing promoted-only reader (`get_promoted`, prompt injection) keeps working unchanged. |

Rules:

1. **Forward-only, single-step.** `MEMORY -> LEARNING -> VALIDATED ->
   REPERTOIRE`; no skips, no demotions. A skip would let a claim reach the
   repertoire without the rung that gives the promotion its meaning; a
   demotion would rewrite history the ledger already recorded.
2. **Every transition names its actor** (the `actor` argument). Anonymous
   provenance is not provenance.
3. **Durable and auditable.** `advance_stage` on every store backend applies
   the guarded row update and appends the append-only
   `learning_stage_transitions` ledger row **in one transaction** (SQLite:
   one commit; PostgreSQL: one `conn.transaction()`). A crash produces
   neither a moved row without a record nor a record without a moved row; a
   concurrent move loses loudly (`UPDATE ... AND stage = <expected from>`,
   `UPDATE 0` raises) rather than double-applying. `stage_history` reads the
   trail back, oldest first.
4. **No fabricated backfill.** Rows that predate the ladder read as
   `memory` with blank `validated_by`/`promoted_by` — the truth — and an
   empty ledger. Migration 048 and the SQLite in-place upgrade both preserve
   absence instead of inventing validation that never happened.
5. **A knowledge stage never grants permissions or execution authority.**
   The Sentinel and every other authorization surface never read the stage,
   `status`, or the ledger. Shared knowledge is not shared *power*: what a
   tool may run is decided solely by the permission table / live permission
   source (#1165, ADR-072726-0d6b), never by how believed a claim is. A test
   pins both the behaviour (a REPERTOIRE learning naming a tool does not
   move `check_permission`) and the architecture (no module under
   `maistro.security` imports the stage machinery).

### Reconciliation with existing concepts

- **`status` stays the read surface; `stage` is the semantics surface.**
  `get_promoted` and prompt injection select on `status='promoted'` and are
  untouched. A REPERTOIRE commit sets both.
- **Legacy hit-count auto-promotion is unchanged and unclaimed.**
  `check_auto_promotions` (ADR-015) flips `status` at a hit-count threshold
  without validation; those rows carry `stage=memory` and no transition
  record, which honestly says "promoted by recall frequency, never
  validated". Tightening that path (independent evaluation before promotion)
  is the successor issue's work (#118 Gauntlet), not this ADR's.
- **`MemoryTier.WISDOM` is not the ladder.** The episodic tiers remain a
  weight/confidence axis *inside the episodic store* (ADR-091). "Wisdom" is
  not promoted to a universal noun for validated knowledge; the ladder's
  top rung is `REPERTOIRE`, whose membership test is an audited promotion,
  not a weight.
- **Repertoire (ADR-070/SPEC-258) is a consumption pattern, not a rival
  store.** The rehearsal/performance gates decide *whether to reuse* an
  entry; this ladder decides *how a claim earned its way into* the shared
  pool such entries are drawn from.

## Consequences

- `Learning` gains `stage`, `validated_by`, `promoted_by`; both SQL twins
  persist all three (enforced by the #1156 field-disposition contract test),
  migration 048 adds the columns and the ledger table, and the SQLite twin
  upgrades existing files in place.
- `LearningStore` gains `advance_stage` and `stage_history`; the in-memory,
  SQLite and PostgreSQL backends plus `DurableHybridLearningStore` all
  implement them, with the transition rules in one shared place
  (`lifecycle.plan_advance`) so the backends cannot drift.
- Producers, validators and promoters are separately attributable facts from
  day one, which is the substrate the independent-evaluation work (#118) and
  the epistemics work (#119) build on.

## Out of scope

- Who may act as the independent evaluator, and what evaluation must do
  (#118).
- Epistemic typing (empirical/inferential/anti-pattern), confidence scores,
  decay and consolidation dynamics (#119/#120).
- Wiring any caller to *drive* the ladder — this ADR defines the semantics
  and makes them durable; it does not schedule anything.
