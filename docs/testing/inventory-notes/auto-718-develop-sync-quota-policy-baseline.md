# auto-718 develop-sync merge resolution + fail-closed policy baseline alignment

inventory-delta:
  added: 0
  removed: 0
  modified: 4
  note: >
    No test inventory change (no tests added or removed). This round resolved
    the preserved origin/develop sync conflict (migration chain + container
    composition), then aligned the #718 quota-evidence fixtures with the
    merged #846 fail-closed policy contract: fixtures that exercise a governed
    call now name the explicit binding_scope_policy M1 baseline, exactly as
    develop's own repair (73060a7ee) did for its sibling fixtures.

## Merge resolution (MERGE_HEAD=b43175c1d, origin/develop)

Three unmerged paths:

- `packages/maistro-core/src/maistro/container.py`: kept BOTH sides of the
  `capability_effects` composition — the #718 canonical quota wiring
  (`usage_log=get_default_usage_log()`, `quota_tracker=quota_tracker`) and
  develop's `policy_evaluator=binding_scope_policy` composition-root
  requirement. Either side alone loses a required property (quota evidence vs
  governed admission).
- `alembic/versions/036_audit_log_org_scope.py` +
  `alembic/versions/041_quota_invocation_evidence.py`: develop's #1057 branch
  and this lane's #718 branch had both taken 040's child slot. Resolution
  re-parents `041_quota_invocation_evidence` onto develop's chain tip
  `042_task_receipt_dispatch_inputs`; `036_audit_log_org_scope` follows it.
  The joined chain is linear with the single head `044`
  (`001 -> ... -> 040 -> 041_task_identity_provenance ->
  042_task_receipt_dispatch_inputs -> 041_quota_invocation_evidence ->
  036_audit_log_org_scope -> 042 -> 039_quota_usage_event_identity -> 044`),
  verified via `alembic.script.ScriptDirectory.get_heads() == ["044"]`.
- `tests/migrations/test_audit_scope_migration.py`: kept the
  `041_quota_invocation_evidence` parent assertion with the joined-chain
  provenance comment. 17 passed / DB-backed suites skip without
  `MAISTRO_TEST_DATABASE_URL`.

## Fail-closed policy baseline alignment (post-merge test repairs)

develop's #846 change makes an omitted `policy_evaluator` an unavailable
dependency that DENIES (`invocation.unconfigured`). Nine #718 fixture
constructions still built bare contexts and were denied before reaching the
provider, failing with `InvocationDenied: capability invocation policy
unavailable`:

- `packages/maistro-core/tests/capabilities/test_model_chat_egress.py`
  (3 constructions: canonical-quota-once, missing-usage-unreported,
  minted-turn identity),
- `packages/maistro-core/tests/capabilities/test_reconciled_usage_quota.py`
  (5 constructions),
- `packages/maistro-core/tests/agents/test_governed_quota.py` (1),
- `packages/hive-conductor/backend/tests/test_legacy_dag_governed_quota.py`
  (1).

Four test files (nine fixture constructions) now pass `policy_evaluator=binding_scope_policy` — the same explicit
M1 baseline the production container selects — matching develop's own fixture
repair pattern. No production code changed in this step; the canonical
recording path is untouched.

## Validation

- `uv run pytest packages/maistro-core/tests/capabilities -q`: 383 passed.
- `uv run pytest packages/maistro-core/tests -q`: 10769 passed / 726 skipped /
  1 xfailed (after the `test_governed_quota.py` repair).
- `uv run pytest packages/maistro-server/tests -q`: 416 passed.
- `uv run pytest packages/hive-conductor/backend/tests -q`: 2943 passed.
- `uv run mypy packages/maistro-core/src`: clean (640 files, after
  `uv sync --locked --all-extras` to match CI's environment).
- `uv run ruff check .` / `ruff format --check .`: clean.
- `scripts/check-model-egress.py`: OK, 23 direct callers, inventory matches.
- `scripts/check-vulture-baseline.py` (min-confidence 60): exit 0.
