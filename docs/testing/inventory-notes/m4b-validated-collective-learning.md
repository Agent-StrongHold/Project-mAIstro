---
inventory-delta:
  packages/maistro-core/tests: +67
---
# M4-B — validated collective learning (ADR-100126-9a4b, epic #22; children #117–#121)

Four new test files and one, plus contract updates, covering the learning
pipeline semantics that previously had no tests because the semantics did not
exist: promotion turned on `hit_count` alone, learnings carried no stage,
confidence, epistemic type, applicability, or lifecycle dynamics, and failure
knowledge had no promotable form.

New test nodes (+67):

- `packages/maistro-core/tests/memory/learnings/test_lifecycle.py` (+23) — the
  pure stage ladder (#117): `MEMORY` is never a destination, no skipping
  (REPERTOIRE requires VALIDATED), no reversal, validation records Gauntlet
  provenance and lifts confidence to the floor, repertoire commit flips
  `status` to `promoted` so `get_promoted` readers see it; reinforce/contradict
  bounds; decay anchored at `last_confirmed_at` with the anti-pattern floor and
  slow clock; supersession linking; consolidation evidence folding;
  `effectiveness` returning `None` for zero uses ("no measurement", not "no
  effect").
- `packages/maistro-core/tests/memory/learnings/test_gauntlet.py` (+24) — the
  independence property (#118): `evidence_of` counts uses, never `hit_count`;
  high-recall/failing-outcomes learnings fail `success_rate`; unattributed
  producers fail; chained gauntlets union failures. Promoter integration: only
  Gauntlet-accepted candidates join the repertoire (with `validated_by` set and
  skill mutation gated), rejected ones stay active and local, gauntlet takes
  precedence over the approval gate, legacy no-gauntlet path unchanged.
  Anti-pattern capture (#121): ineffective learnings become retained
  `ANTI_PATTERN` knowledge at the floor, org-scoped, idempotent, and promotable
  through the same Gauntlet; stores without `list_ineffective` yield nothing.
- `packages/maistro-core/tests/memory/learnings/test_learning_lifecycle_store.py`
  (+19) — store-applied lifecycle (#120) with protocol conformance
  (`LearningLifecycleStore`, `IneffectiveLearningSource`), point-read org
  narrowing, supersede-before-insert so dedup cannot fold a replacement into
  the row it replaces, terminal rows exempt from decay sweeps, and
  consolidation of drifted rows (write-time dedup already folds fresh
  duplicates, so the drifted state is built through the public API).
- `packages/maistro-core/tests/persistence/test_sqlite_learning_lifecycle.py`
  (+2) — durability of the pipeline state on the SQLite twin: a validated
  anti-pattern round-trips a real file (stage, epistemic type, confidence,
  applicability, counters, instants, Gauntlet provenance, supersession links),
  and a pre-M4B database upgrades in place with rows reading back as the local
  empirical learnings they implicitly were — never with invented validation.

Contract updates (existing nodes, strengthened not weakened):

- `test_learning_contract.py` now enforces the twelve new fields in the
  #1156 disposition partition, so a future Learning field cannot land in one
  SQL twin only.
- `test_pg_learnings.py::test_store_inserts_new_learning_when_no_existing_match`
  asserts the lifecycle fields are written on insert.
- `tests/migrations` chain-tip pin moves `047` → `048` for the new migration.

Discriminating against the pre-change tree: on the base commit the new tests
fail at import (`LearningStage`/`Gauntlet`/lifecycle module absent), and the
two contract tests fail on the unpartitioned fields — the fixture that guards
the persistence twins against silent field loss.
