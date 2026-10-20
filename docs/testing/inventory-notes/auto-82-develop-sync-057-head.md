---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: quota door re-parents onto 056, user-model facts renumber to 057

This round inherited a mid-flight merge of develop `b672b799a` into auto-82
`540f1a611` with three unresolved conflicts, and completed the sync with a
second merge of the then-current `origin/develop` (`c560d4cca`). No tests were
added or removed; suite inventory is unchanged against the recorded baseline
(`tests/migrations` still 119, `packages/maistro-core/tests/backlog` still
53+1 skip with PG legs).

## Conflicts resolved

- `alembic/versions/043_invocation_quota_door.py` (develop's new quota-admission
  migration, #1196/#718): re-parented from develop's `055_task_admission_generations`
  onto this branch's chain tip — the admission revision having been renumbered
  `056` here by the previous sync — so its `down_revision` is `056` and its
  re-parenting narrative now records the hop through `056`.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  both sides' collision narratives merged twice (once per merge); the walk
  target and `get_heads()` assertion followed the tip through `056` → quota
  door → `057`.
- `tests/migrations/test_task_admission_generation_upgrade.py`: the rollback
  transaction comments merged; the refused-downgrade stamp assertion now reads
  the merged head (`057`).
- `alembic/versions/056_user_model_facts.py` (develop's M3-E1 migration,
  #1047/ADR-092526-4391, arriving with the `c560d4cca` merge) collided a fourth
  time — its `056` against this branch's renumbered `056` admission revision —
  so per the chain's documented convention (see 046, 051, 052, 056) it
  renumbers to `057_user_model_facts.py`, keeping `down_revision =
  043_invocation_quota_door`; its renumbering-history docstring records the
  fourth and fifth hops.
- `quality/vulture-baseline.json`: git's textual merge had duplicated four
  whole rule blocks (`bootstrap-builder-surface`,
  `core-public-api-surface` ×2 at 998/1001 rows,
  `session-run-correlation-read-surface`, `pytest-discovered-test-surface`)
  because both sides had rewritten adjacent ledger regions. The gate keys
  scan classification by rule id, so duplicates made shared rows report as
  both missing and stale. Resolved by consolidating each duplicate pair into
  one rule with the **max-per-key multiset union** of both copies' findings
  (15 rules, 1342 reviewed identities) and pruning the one fixed debt the
  scan no longer finds
  (`code_registry/types.py::unused variable 'trusted'`, fixed by develop's
  #1980 cleanup).

## Migration chain after resolution

`052_learning_stage_ladder → 053_backlog_work_source (#82) →
054_learning_lifecycle_columns → 055_learning_applicability_epistemics (#119)
→ 056_task_admission_generations (#1892) → 043_invocation_quota_door
(#1196/#718) → 057_user_model_facts (#1047)`; `alembic heads` → single `057`.

## Executed evidence (local PostgreSQL 18.6, CI-shaped env)

- `pytest tests/migrations` on a **pristine** database — **119 passed**
  (2:46), including the two resolved files and
  `test_single_migration_head.py` (exactly one head).
- `alembic upgrade head` on a second pristine database walked the full merged
  chain: `… 055 → 056 → 043_invocation_quota_door → 057`.
- `pytest packages/maistro-core/tests/backlog` with PG legs — 53 passed,
  1 skipped, against the migrated chain.
- ruff `check` + `format --check` — clean (2990 files).
- vulture gate with CI's exact args
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  `RATCHET_BASE_REV=origin/develop`) — **exit 0** (1342 reviewed → 1339
  findings; the maistro.backlog identities remain covered by the in-source
  `_vulture_whitelist.py`, so no ledger rows are needed).
- supply chain (the named CI failure): `uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json -r` (audit exit 1, findings present) →
  `scripts/pip_audit_gate.py` **exit 0** — "1 known, all triaged in ALLOWED";
  direct-dependency usage OK. Both the ci.yml and security.yml supply-chain
  legs end at this gate.
- `check-reachability.py` exit 0 (175 unreachable of 1292, all disposed);
  `check-reachability-dispositions.py` exit 0 (50 groups).

## Residual (unchanged, two-merge)

`maistro.backlog.{__init__,model,pg_store,sqlite_store,store}` remain
unreachable pending the #99/#102 Conductor-UI/authority cutover. The
trusted-base provenance gates (`check-reachability-provenance.py`,
`check-reachability-dispositions-provenance.py`, and the aggregated
`check-ratchet-provenance.py`) exit 1 on exactly those five modules: the
candidate baseline/dispositions carry the rows, but
`ratchet_provenance.load_authorizations` reads `quality/ratchet-authorizations.json`
**from the merge base** (`scripts/ratchet_provenance.py:478`, #534), so the
grants must land on develop before any branch carrying the backlog module can
pass. All candidate-side gates exit 0.
