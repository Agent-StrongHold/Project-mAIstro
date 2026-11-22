---
inventory-delta:
  packages/maistro-core/tests: +30
  tests/: +3
---

# M4-B1 #117 — the knowledge-stage ladder (Memory → Learning → Validated → Repertoire)

Formalizes the semantic path from execution-local remembered evidence to
reusable institutional knowledge on the one `Learning` record (ADR-103), with
no parallel runtime: fields + lifecycle functions + durable transitions.

## What landed

- `maistro.types.memory`: `LearningStage` (`memory`/`learning`/`validated`/
  `repertoire`), `LEARNING_STAGE_ORDER`, and three `Learning` fields
  (`stage`, `validated_by`, `promoted_by`).
- `maistro.memory.learnings.lifecycle`: `plan_advance` — the one place the
  transition rules live (forward-only, single-step, actor-attributed;
  REPERTOIRE flips `status` to `promoted` so promoted-only readers keep
  working), plus the `StageTransition` audit record and
  `InvalidStageTransition`.
- Stores: `advance_stage` / `stage_history` on `InMemoryLearningStore`,
  `SqliteLearningStore`, `PgLearningStore` (guarded `UPDATE ... AND stage =
  <from>` + append-only `learning_stage_transitions` ledger row in one
  transaction), pass-through on `DurableHybridLearningStore`, and the two
  methods on the `LearningStore` protocol.
- Durability: migration `052_learning_stage_ladder.py` (stage columns +
  ledger table, `IF NOT EXISTS` posture like 046/047); SQLite twin upgrades
  existing files in place. No backfill: pre-ladder rows read `memory` with
  blank actors — absence preserved, nothing fabricated. Numbered 048 when
  written; develop claimed 048 for #398 and then 049/050/051 for #780/#774
  and the re-parented #792 eval evidence while this branch was open, so per
  the chain's collision convention (039/043/045 precedents) the revision
  re-parented onto the `051_canonical_run_eval_scores` chain tip as 052 —
  one linear head, no duplicate revision ids (`tests/migrations/`
  `test_capability_invocation_effect_index_migration.py` pins head `052`;
  `test_migration_chain.py`'s exact-table-set assertion gained
  `learning_stage_transitions`).
- Authority invariant: nothing on the authorization path reads knowledge
  state; pinned by test.

## Tests (+5 files, 33 cases)

- `packages/maistro-core/tests/memory/learnings/test_durable_hybrid.py` —
  the hybrid wrapper's `advance_stage` / `stage_history` delegation held to
  the same contract as every other forwarded method: passes what it was given
  (all five ladder arguments, keyword-only downstream) and returns what it
  got back, with the audit read scoped by `org_id`. These cover the two
  wrapper methods the production container path calls that no test reached
  (found by the diff-coverage gate).

- `packages/maistro-core/tests/memory/learnings/test_learning_lifecycle.py`
  — the pure rule set (`plan_advance`) and the in-memory store run: backward
  and skip rejections, anonymous-actor rejection, evaluator/promoter
  attribution, status flip, ordered audit trail, illegal transition leaves
  neither row nor ledger touched, cross-org advance/read refused.
- `packages/maistro-core/tests/memory/learnings/test_stage_grants_no_authority.py`
  — behavioural (a REPERTOIRE learning naming `bash` does not move the
  fail-closed `check_permission` for `bash`) and architectural (no module
  under `maistro/security` imports any stage machinery fragment).
- `packages/maistro-core/tests/persistence/test_sqlite_learning_stage.py` —
  real in-process SQLite: row+ledger co-persistence, restart survival (a
  reconnect cannot demote a validated learning or erase its trail),
  promoted-reader compatibility, pre-ladder file upgrade without fabricated
  provenance, illegal-transition atomicity, scope-bound writes, and the
  concurrent-loser contract: two racing writers for the same rung produce
  exactly one applied transition and one ledger row — the loser raises
  `InvalidStageTransition` from the guarded UPDATE's rowcount check (ADR-103
  rule 3, same `UPDATE 0` contract as the PG twin) instead of half-applying.
- `packages/maistro-core/tests/persistence/test_pg_learning_stage.py` —
  FakeConnection twin: transaction ordering (transaction → select → guarded
  update → ledger insert), `UPDATE 0` raises instead of half-applying,
  scoped reads/writes, stage columns on the INSERT contract.
- `tests/migrations/test_learning_stage_ladder_migration.py` — migration 052
  upgrade/downgrade/re-upgrade round trip against a real PostgreSQL
  (executed live this round on pgvector:pg18; ledger table and NOT NULL
  stage columns land, downgrade un-lands the whole ladder, re-upgrade
  restores; `alembic downgrade base && alembic upgrade head` re-lands on
  the chain tip with the ledger table present). Skips without
  `MAISTRO_TEST_DATABASE_URL`, per house pattern.
- `packages/maistro-core/tests/persistence/test_pg_learnings.py` — the exact
  INSERT-args pin gained the three new column values (the pin's job).
- `packages/maistro-core/tests/persistence/test_learning_contract.py` —
  unchanged; enforces that the new fields are persisted by both twins.

## Reconciliation notes

- `status` stays the read surface; `stage` is semantics. Legacy hit-count
  auto-promotion (`check_auto_promotions`, ADR-015) is behaviorally
  unchanged and honestly unclaimed: those rows carry `stage=memory` and no
  ledger row — "promoted by recall frequency, never validated".
- `MemoryTier.WISDOM` is untouched and stays an episodic-store weight axis
  (ADR-091); it is not the ladder's top and not a universal noun.
