---
inventory-delta:
  packages/maistro-core/tests: +7
---

Adds canonical Invocation quota coverage: a governed model effect records provider usage once despite effect deduplication, missing provider usage is explicit unreported evidence, and verifier outages return reconciliation-unavailable evidence without raising. The production model adapter is exercised through the existing ModelChatEgress and Invocation authorities rather than independent Agent callbacks.

## Independent verification (2026-09-08, head bfeff9a539edf731ee54141c91279a271d7a11e0)

Re-executed on the exact head, not inherited from the repair run:

- Lane battery: `uv run pytest` over test_conductor/test_governed_quota/test_model_chat_egress/test_reconciled_usage_quota/conftest/test_sqlite_quota/test_reconciliation → 96 passed.
- hive adapter: `test_maistro_core_adapter.py` → 9 passed.
- Wider affected suites (quota+capabilities+agents+persistence) → 1673 passed, 157 skipped (pre-existing `MAISTRO_TEST_PG_DSN` environmental skips).
- Server suite → 369 passed. `ruff check` + `format --check` clean. Canonical mypy (712 files) clean.
- Live chain: `MAISTRO_TEST_DATABASE_URL` against the lane Postgres → test_migration_chain + test_audit_scope_migration → 14 passed; `quota_invocation_evidence` present in the applied catalog, single alembic head (041 re-ID confirmed).
- Quality gates with CI args, `RATCHET_BASE_REV=<develop base>`: vulture exit 0 (`_quota_tracker` prune consistent — no longer flagged), reachability exit 0 (186 unreachable modules dispositioned), dispositions exit 0.
- Wiring re-derived from source: `new_effect_context` installs `CanonicalInvocationUsageRecorder` as the single `InvocationExecutionService.on_completed` hook; `container.py` passes the container `quota_tracker`; server `ConductorAgent` and hive `create_agents` (all four authorities present) route ordinary completions through `ModelChatEgress` → `effects.invocations.invoke`. No production caller supplies `on_response`/`build_quota_recording_hook` (grep over packages/); the hook is documented compatibility-only, and the explicit-verifier half remains CONNECT-dispositioned as owed.
- Known gap (accepted, recorded): `pg_quota.record_invocation` has no direct unit test — the sqlite twin + in-memory tracker cover the at-most-once projection, and the live migration chain validates the evidence schema; the SQL was reviewed (evidence-PK `ON CONFLICT DO NOTHING` gates the aggregate update inside one transaction).
