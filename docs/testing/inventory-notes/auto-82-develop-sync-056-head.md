---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: applicability epistemics re-parent as 055, admission generations as 056

This round inherited a mid-flight merge of develop `30144ad0f` into auto-82
`637028c096a5` with four unresolved conflicts. All were resolved semantically;
no tests were added or removed by this branch, so suite inventory is unchanged
against the recorded baseline (`scripts/check-suite-inventory.py` — every
suite ok, 26408 unique node IDs; the +5 reference-greeter and +2
learning-applicability tests came in from develop's side of the merge together
with its baseline rows).

## Conflicts resolved

- `alembic/versions/055_task_admission_generations.py` → renamed
  `056_task_admission_generations.py`: both sides' docstring narratives merged;
  the revision re-parents onto the applicability tip as `056` (down = `055`).
  Internal refusal strings updated to name `056`.
- `alembic/versions/054_learning_applicability_epistemics.py` (develop's new
  M4-B3 migration, #119) → renamed
  `055_learning_applicability_epistemics.py` (down = `054`), continuing the
  chain's documented collision convention (see 046, 052, 051 and 036): this
  branch's backlog work source (#82) holds `053`, develop's lifecycle columns
  re-parented onto it as `054_learning_lifecycle_columns` in the previous
  sync, so the applicability migration — landing second — re-parents onto that
  tip as `055`. Its renumbering-history comment now records the fifth hop, and
  its body comments reference the lifecycle revision by the merged chain's id
  (`054`).
- `quality/durable-table-retention.json`: disjoint union — this branch's
  `backlog_items` / `backlog_events` / `backlog_claims` rows beside develop's
  `extension_installs` / `extension_publishers` rows (94 tables, alphabetical
  position preserved). No row changed on both sides.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  both sides' collision narratives merged; walks to `056` and asserts
  `get_heads() == ["056"]`.
- `tests/migrations/test_task_admission_generation_upgrade.py`: the rollback
  transaction comment now names 054 (lifecycle) + 055 (applicability) rolling
  back with the refusing 056; stamped-version assertions read `056`.
- Current-state cross-references updated for the merged chain:
  `docs/specs/SPEC-100126-5445-learning-epistemics.md` (migration name) and
  `tests/migrations/test_learning_applicability_migration.py` (which revision
  landed the epistemic default). Historical round notes were left as-is.

## Migration chain after resolution

`051 → 052_learning_stage_ladder → 053_backlog_work_source (#82) →
054_learning_lifecycle_columns → 055_learning_applicability_epistemics (#119)
→ 056_task_admission_generations (#1892)`; `alembic heads` → single `056`.

## Executed evidence (local PostgreSQL 18.6 + pgvector 0.8.1, CI-shaped env)

- `pytest tests/migrations` on a **pristine** database — **119 passed** (2:57).
  The same suite on the shared pre-merge `maistro_test` database failed one
  episodic-provenance downgrade test once: that database was still stamped at
  the pre-merge chain's `055` (= task-admission there, = applicability here),
  so alembic resolved the stale stamp onto the wrong revision. CI always
  provisions a fresh postgres, and the pristine-database run is the
  CI-equivalent proof; the shared DB is stamped `056` and green again.
- `alembic downgrade base` → `alembic upgrade head` clean (CI's
  reversibility step).
- `pytest packages/maistro-core/tests/backlog` with PG legs — 53 passed,
  1 skipped, against the migrated chain.
- `pytest packages/maistro-core/tests/persistence` with PG legs — 780 passed,
  84 skipped; the 2 failures in `test_schedule_winner_crash.py` reproduce
  byte-for-byte on the pre-merge HEAD (verified on a throwaway worktree of
  `637028c`), so they are this machine's SIGKILL/timing sensitivity, not the
  merge's.
- `pytest packages/maistro-core/tests/workspaces` with PG legs — 328 passed,
  2 skipped (matches the previous round); `test_container_postgres.py` —
  9 passed, 6 skipped; `test_canvas_supported_path.py` — 7 passed.
- `pytest packages/maistro-core/tests/memory/learnings` — 287 passed
  (develop's M4-B3 suite on the merged store).
- supply chain (the named CI failure): `uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json -r` (audit exit 1 on ecdsa PYSEC-2026-1325
  ×2) → `scripts/pip_audit_gate.py` **exit 0** via the ALLOWED triage
  (`scripts/pip_audit_gate.py:76`); `check-dependency-namespaces.py` exit 0 —
  both legs of the "Supply chain" jobs.
- `check-suite-inventory.py` exit 0 (after `uv sync --locked --extra dev`
  installed the merged tree's new editable `reference-greeter` member);
  vulture gate exit 0 with CI's exact args; `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-radon-baseline.py`,
  `check-route-permissions.py`, `check-convergence-matrix.py`,
  `check-contract-markers.py` (+ provenance), `check-shipped-surface-truth.py`,
  `check-durable-table-inventory.py` (94 tables), `check-merge-markers.py`,
  `check-backlog-consistency.py`, `check-release-consistency.py` — all exit 0.
  mypy on `packages/maistro-core/src` clean (719 files); ruff check/format
  clean.
- Ledger integrity after the merge (AGENTS.md `--numstat` rule): every
  quality ledger verified against both merge parents — `durable-table-retention`
  is the exact disjoint union; `ratchet-authorizations.json` resolved
  byte-identical to this branch's version (develop's delta is the backlog
  grant this branch already carries); the re-banked ledgers are held exact by
  their gates above.

## Residual (unchanged, two-merge)

`maistro.backlog.{__init__,model,pg_store,sqlite_store,store}` remain
unreachable pending the #99/#102 Conductor-UI/authority cutover; the
trusted-base provenance gates (`check-reachability-provenance.py`,
`check-reachability-dispositions-provenance.py`, and the aggregated
`check-ratchet-provenance.py` inventory check) keep failing from this branch
by design until the grants land on develop — candidate gates exit 0.
