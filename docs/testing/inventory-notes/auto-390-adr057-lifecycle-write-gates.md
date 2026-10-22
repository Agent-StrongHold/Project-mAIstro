---
inventory-delta:
  packages/maistro-core/tests: +9
---
# auto-390 — ADR-057 write authority on the M4-B5 lifecycle mutations (#390)

Develop's M4-B5 sync (35f2e0158) added learning-store mutation paths with no
ADR-057 write-authority gate: `supersede` (which also retired the old row
*before* the gated `store()` call, so a denied write left partial durable
state), `consolidate`, and the store-level `advance_stage` present on all
three twins. This change set wires the accepted authority decision onto those
paths and pins it with tests.

## What landed

- `InMemoryLearningStore.supersede` / `.consolidate`: gate as ADR-057
  `write` as the first statement; `supersede` carries the same principal
  into the inner `store()` call, so one denial retires nothing and stores
  nothing.
- `advance_stage` on `InMemoryLearningStore`, `SqliteLearningStore`,
  `PgLearningStore` and the `DurableHybridLearningStore` pass-through: gate
  as `write` behind a new `authority: Actor = Agent` principal, kept
  distinct from the ADR-103 `actor: str` attribution string (who is credited
  for a move is not who is authorized to make it).
- Protocol docstrings state the contract; enforcement stays at the store
  boundary. Bookkeeping mutations (`reinforce`, `contradict`, `apply_decay`,
  `mark_used`, `mark_outcome`, `mark_anti_pattern`) stay outside the
  authority matrix, matching the accepted episodic/outcomes surface.

## The +9

- `tests/memory/test_exposure_mode.py` +5: undeclared-mode legs for
  supersede/consolidate/advance_stage on the fail-closed reachability tests
  (in-memory, pg, sqlite — assertions inside existing tests, no new IDs
  there); denied supersede leaves no partial state; system-authority
  supersede carries one principal into the inner store; denied consolidate
  merges nothing; denied agent / allowed system `advance_stage` two-actor
  legs. The supersede no-partial-state test was falsified against the
  pre-gate ordering (fails at the old row's status flip, passes gated).
- `tests/persistence/test_sqlite_learning_stage.py` +2: denied durable stage
  move writes neither row nor ledger; system authority allowed under
  `SYSTEM_MANAGED`.
- `tests/persistence/test_pg_learning_stage.py` +2: the gate precedes every
  stage query (undeclared and denied both issue zero SQL against the
  recording fake); system authority reaches the transaction.

The two develop-sync merges in this round (a58656017, 680329c96..35f2e0158)
are covered by the union note `auto-390-develop-sync-union.md` lineage: their
test files arrived already counted in the baseline via those merges' own
synced notes, and the bare store constructions they reintroduced were
re-declared `AGENT_MANAGED` (non-intentional constructions only — the
fail-closed matrix in `test_exposure_mode.py` stays bare).
