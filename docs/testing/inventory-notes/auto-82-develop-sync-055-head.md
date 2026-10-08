---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: backlog 053 preserved, lifecycle columns re-parent as 054, admission generations as 055

The round inherited a mid-flight merge of develop 2ef76025e into auto-82 with
one unresolved conflict (the vulture per-identity ledger), then merged the
develop tip 9a5eb7ba6 on top, which produced three more conflicts. All were
resolved semantically; no tests were added or removed, so suite inventory is
unchanged against the recorded baseline (`scripts/check-suite-inventory.py`
reports every suite ok).

## Conflicts resolved

- `quality/vulture-baseline.json` (twice — once per merge): multiset-union of
  both sides, then the ledger re-banked exactly to the scan with
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*' --update` (CI's exact arguments). The gate is a
  multiset and the auto-merge had silently unbalanced it: 383 rows
  restored/added, 31 stale rows pruned.
- `packages/maistro-core/src/_vulture_whitelist.py`: union — this branch's
  #98 backlog contract surface beside develop's M4-A9 PromotionContract
  entries.
- `quality/ratchet-authorizations.json`: develop's `exempt::/v1/*`
  route-permission grants (branch side had no rows in the conflicted hunk).

## Migration chain collision, resolved by the documented convention

The merge reintroduced the recurring two-head collision on the same parent:

- this branch's `053_backlog_work_source` (#82) keeps `053` (down = `052`);
- develop's `053_learning_lifecycle_columns` (M4-B, ADR-100126-8c2d) was
  numbered `053` on the `052` base — re-parented onto the backlog tip as
  `054_learning_lifecycle_columns` (down = `053`);
- develop's `054_task_admission_generations` (#1892) was numbered `054` on
  that base — re-parented as `055_task_admission_generations` (down = `054`).

`alembic heads` → single head `055`;
`tests/migrations/test_capability_invocation_effect_index_migration.py`
walks to `055` and asserts `get_heads() == ["055"]`;
`test_task_admission_generation_upgrade.py` asserts the stamped version `055`.

## Executed evidence (pgvector/pgvector:pg18, pristine container, CI-shaped)

- `pytest tests/migrations/test_migration_chain.py` — 13 passed on an empty
  database; `alembic upgrade head` → `downgrade base` → `upgrade head` clean,
  `alembic current` = `055 (head)`.
- `pytest tests/migrations` with the server env — 117 passed (the 98
  DB-gated skips from the offline run included).
- `pytest packages/maistro-core/tests/persistence
  packages/maistro-core/tests/test_container_postgres.py` — 791 passed.
- `MAISTRO_REQUIRE_PG_LEGS=1 pytest packages/maistro-core/tests/workspaces`
  — 328 passed; `backlog` + `workspaces/backlog_history` with PG legs —
  111 passed.
- `pytest packages/maistro-server/tests/api/test_canvas_supported_path.py`
  with PG legs — 7 passed.
- supply chain: `uv pip freeze --exclude-editable` → `pip-audit --strict` →
  `scripts/pip_audit_gate.py` exit 0 (ecdsa PYSEC-2026-1325 triaged in
  `scripts/pip_audit_gate.py:76`), matching ci.yml/security.yml's job shape.
- vulture gate exit 0; radon gate exit 0 after refactoring
  `InMemoryBacklogStore.list_items` (C(11) → B) via an extracted
  `_matches_filter` predicate — behavior-identical, proven by the
  three-backend conformance suites above; mypy on maistro-core clean; ruff
  check/format clean.

## Residual (unchanged, two-merge)

`maistro.backlog.{__init__,model,pg_store,sqlite_store,store}` remain
unreachable pending the #99/#102 Conductor-UI/authority cutover; acceptance
must land on develop first (`ratchet_provenance.load_authorizations` reads
the merge base), so `check-reachability-provenance.py` keeps failing from
this branch by design. Candidate baselines bank them correctly (candidate
gates exit 0).
