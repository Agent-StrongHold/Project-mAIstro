---
inventory-delta:
  packages/maistro-core/tests: +74
---
# M4-B — validated collective learning (ADR-100126-8c2d, epic #22; children #117–#121)

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
  (+3) — durability of the pipeline state on the SQLite twin: a validated
  anti-pattern round-trips a real file (stage, epistemic type, confidence,
  applicability, counters, instants, Gauntlet provenance, supersession links),
  a pre-M4B database upgrades in place with rows reading back as the local
  empirical learnings they implicitly were — never with invented validation,
  and the #121 capture path runs against the durable twin itself: the twin
  answers the `IneffectiveLearningSource` read with the in-memory predicate,
  the promoter's reclassification is written back through `mark_anti_pattern`
  (org binds exactly), and a cold read sees the anti-pattern, not the
  empirical row first stored.
- `packages/maistro-core/tests/memory/learnings/test_gauntlet.py` reuse half
  (+3, `TestAntiPatternKnowledgeReuse`) — a captured anti-pattern is surfaced
  by retrieval into the bounded advisory corrections block, org-bound in both
  directions, and through `get_promoted` after the repertoire commit;
  contrary evidence supersedes a captured anti-pattern with the lineage kept
  and the retired row no longer retrieved; repeated failures are measured
  before adoption (`list_ineffective`, `effectiveness == -1.0`) and after it
  through the same public outcome path (effectiveness flips positive, the
  Gauntlet accepts the evidence).
- `packages/maistro-core/tests/agents/test_base.py` (+3) — the turn-path
  wiring: a failed turn with injected learnings records the outcome and then
  runs the capture sweep on the same turn; a successful turn and a failed
  turn with no injected learnings do not.

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

## CI-repair round (develop reconciliation, #121)

Develop landed its own ADR-092 (capability-vs-control posture) and migration
`048` (canvas retry backoff) while this branch was open, colliding with this
branch's ADR-092 and `048_learning_lifecycle_columns`. Per ADR-062026-9b30
(new records take date-based IDs; migration collisions re-parent onto the
develop chain head) this branch renumbers: the M4-B ADR is now
`ADR-100126-8c2d` (all references updated, index row moved), and the
lifecycle-columns migration is now `051` re-parented onto develop's `050`
head. The migration chain-tip pin now asserts `get_heads() == ["051"]` —
same test node, extended asserts, no node count change.

The radon gate flagged four new C-grade blocks introduced by the M4-B code
(`_check_with_gauntlet`, `consolidate`, two `_row_to_learning` twins); all
four were refactored below the C boundary by extraction (`_gauntlet_candidates`,
`_admit_validated`, `_consolidation_anchor`, `_provenance_fields`/
`_lifecycle_fields`) — behavior-preserving, pinned by the same test nodes
above (567 memory/persistence/agents tests re-run green after each refactor).
No test nodes were added or removed in this round, so the delta above stands.

Ledger deltas (exact-debt repair): `quality/vulture-baseline.json` banks the
four reviewed M4-B public-surface identities (`OutcomeEvidenceGauntlet`,
`ChainedGauntlet`, `effectiveness`, `LearningLifecycleStore`) and prunes
`store.py::list_ineffective` (the promoter now calls it, so the debt was
fixed, not retained); `quality/reachability-baseline.json` +
`reachability-dispositions.json` bank `maistro.memory.learnings.gauntlet` as
CONNECT library-only surface; matching reviewed grants are recorded in
`quality/ratchet-authorizations.json`. Per the two-merge rule those grants
take effect once they sit at the integration base, not in this change.
