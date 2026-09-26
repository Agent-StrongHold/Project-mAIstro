---
inventory-delta:
  packages/maistro-core/tests: +21
  packages/maistro-server/tests: +6
  packages/hive-conductor/backend/tests: +25
  tests/: +1
---

# #1057 — task principal delegation

Adds contract coverage for the signed Conductor-to-maistro-server delegation envelope,
server-side effective actor binding and two-principal task isolation. The adapter tests
cover propagation of signed user context and fail-closed configuration; the existing
production task bridge tests are updated to provide the required host key. The migration
repair adds live-schema coverage for classifying pre-provenance receipts as explicit
system work, while queue restore coverage rejects a partially migrated ownerless receipt.

Repair-phase re-validation (no test count change): the full battery was re-executed
independently on head `cfe012006` after the 040 re-chain —
`packages/maistro-core/tests/tasks` (315 passed), `packages/maistro-server/tests/api`
(356 passed), the Hive bridge suites `test_production_workspace_scope.py` /
`test_workspace_scoped_submission.py` / `test_adapter_ports.py` (23 passed, including the
two-user E2E through real Hive session login), and the live-PostgreSQL migration chain
(12 passed against `pgvector/pgvector:pg18`, including `test_pre_provenance_receipts_become_explicit_system_work`
asserting `('system', 'system')` for a pre-#1057 row). `ruff check` / `ruff format --check`,
`check-suite-inventory.py`, `verify-monorepo-layout.sh` and `check-compose-secrets.py` all
pass.

Second repair phase (merge head `765284d1d`, one production-code edit + one test-assertion
update): executing `tests/migrations/test_migration_chain.py` against a live
`pgvector/pgvector:pg18` reproduced a real fork — the `8bb344e32` develop sync brought
develop's `036_audit_log_org_scope` (`down_revision = "040"`) while this branch had already
taken 040's child slot with `041_task_identity_provenance`, so `alembic upgrade head` died
with rc 255, "Multiple head revisions are present" (10 of 12 chain tests failed before the
fix). Following the reconciliation convention recorded in the audit revision's own
docstring, `036_audit_log_org_scope` was re-parented onto this branch's chain tip
`042_task_receipt_dispatch_inputs`, and the hard-coded parent assertion in
`tests/migrations/test_audit_scope_migration.py::test_audit_scope_migration_is_the_single_head`
was updated to match (the generic single-head guards in `test_single_migration_head.py` /
`test_revision_metadata.py` passed unchanged). Re-executed after the fix on a fresh
pg18 container: `tests/migrations/` 97 passed (including `upgrade head` on an empty
database, the round-trip, and the explicit-system-actor legacy-receipt check),
`packages/maistro-server/tests/api` 356 passed, `packages/maistro-core/tests/tasks` 315
passed, Hive bridge suites 50 passed, `ruff check` / `ruff format --check`,
`check-compose-secrets.py` and `verify-monorepo-layout.sh` all pass.

Independent repair-phase validation (merge head `cc4ab4db7`, no code or test
changes in this phase — verification only): the full battery was re-executed
from scratch — `packages/maistro-core/tests/tasks` 315 passed,
`packages/maistro-server/tests/api` 356 passed, the three Hive bridge suites
`test_production_workspace_scope.py` / `test_workspace_scoped_submission.py` /
`test_adapter_ports.py` 23 passed (including the two-user E2E through real Hive
session logins with spoofed body user ids), `tests/migrations/` 97 passed
against a fresh `pgvector/pgvector:pg18` container (single-head chain,
upgrade-from-empty, round trip, and
`test_pre_provenance_receipts_become_explicit_system_work` asserting
`('system', 'system')`), plus `ruff check` / `ruff format --check`,
`check-suite-inventory.py`, `check-compose-secrets.py` and
`verify-monorepo-layout.sh`. Harness note for future runs: the live-Postgres
suites must be invoked with only `MAISTRO_TEST_DATABASE_URL` set — also
exporting `DATABASE_URL` silently overrides the fixtures' `DB_HOST/DB_PORT/
DB_NAME/DB_USER/DB_PASSWORD` scratch-database targeting
(`resolve_database_url` precedence), which shows up as spurious
`UndefinedTableError` failures in the store-leg suites, not as a fixture
guard.

Second independent repair-phase validation (merge head `54498b648`, which
merges develop's HITL workspace-authorization commit `60862b6c5`; no code or
test changes in this phase — verification only): re-executed
`packages/maistro-core/tests/tasks` + `tests/migrations/` 332 passed (80
skips without `MAISTRO_TEST_DATABASE_URL`),
`packages/maistro-server/tests/api` task-scope/rate-limit/webhooks 58 passed,
the four Hive bridge suites (`test_api`, `test_engine_service`,
`test_production_workspace_scope`, `test_workspace_scoped_submission`) 80
passed, `ruff check` / `ruff format --check`, `check-suite-inventory.py`,
`check-compose-secrets.py` and `verify-monorepo-layout.sh` all pass. The
live-Postgres chain suite was re-run against a scratch database on the
existing `pgvector/pgvector:pg18` container: 12 passed, including
`test_pre_provenance_receipts_become_explicit_system_work` (re-selected
individually for an explicit PASSED line) plus the named acceptance tests
`TestPrincipalIdentityKeying::test_delegated_users_have_independent_budgets_behind_one_service_key`,
`test_delegated_users_keep_distinct_task_and_run_ownership`,
`test_shared_bridge_keeps_two_authenticated_user_tasks_isolated` and
`test_system_delegation_has_an_explicit_system_actor`. `mypy` on
`maistro-core`/`maistro-server` reports only the 5 pre-existing
`import-not-found` errors for `maistro_bootstrap` stubs in `cli/` files this
branch does not touch. Integration-layer note: PR #1394's status checks have
now concluded — 3 failures (`test`, `quality`/Quality gate, Coverage gate) —
but against PR head `39bdab11f`, the OLD diverged lineage of `auto-1057`
(six linear commits based on trunk's former 038 head) that conflicts with
current develop (`mergeStateStatus: DIRTY`); this worktree's head is the
reconciled lineage (migrations renumbered to 041/042, audit-scope re-parent
`1c1504259`), so the recorded failures do not reproduce here — the remote
branch must be updated to this lineage before integration.

Fourth repair phase (head `ced1c6080`, 44 new tests + one production-neutral
refactor + one test-stability fix): the fail-closed side of the delegation
envelope is now held by tests that forge envelopes directly the way a hostile
client would — non-envelope shapes, unreadable/non-JSON payloads, missing or
non-numeric required claims, unknown and `system`-kind-claiming-a-user
principal kinds, wrong version/audience, inverted and over-long lifetimes,
skew-window and signer-side refusals (empty principals, missing key,
out-of-range ttl), plus a pinned wire header name
(`test_http_contract.py`, +13). Queue restore coverage holds the
restart/replay fail-closed guards: a row with an impossible actor kind or a
blank owner is skipped rather than requeued, an in-memory-held receipt is
never double-counted, a restore-time database outage degrades instead of
crashing, and a corrupt durable receipt never answers an idempotent replay
(`test_queue_persistence.py`, +4; `_admission_provenance` was extracted in
`admission.py` so these hold provenance shape directly — no behavior change).
The server side gains: a delegation envelope with no authenticated caller is
refused, and every unverifiable envelope (garbage, foreign-key, expired)
fails closed at the shared resolver with 403 (`test_task_workspace_scope.py`,
+2); rotating garbage delegation envelopes cannot mint fresh rate-limit
budgets — they are charged to the authenticated service principal's own
bucket (`test_rate_limit.py`, +1). Hive conductor gains principal-scoped
cancel/delete/event-stream refusals (`test_engine_service.py`, +7),
engine-backed mission list/detail/steps scoped to the caller with blank
ownership failing closed and submissions carrying the authenticated user
(`test_mission_controls.py`, +13), and local/HTTP backend delegation-key and
scope refusals (`test_workspace_scoped_submission.py`, +4).

Test-stability fix found by execution, not inspection: the new rate-limit
test tampered with a valid envelope via `valid_alice[:-1] + "f"`, which is a
silent no-op one time in sixteen (when the dropped hex digit was already
`f`) — the then-valid envelope keyed to Alice's fresh delegated bucket and
returned 200 instead of the asserted 429 (reproduced 2/30 single-file runs,
~1/5 triple-file runs, e.g. `AssertionError: assert 200 == 429` at
`test_rate_limit.py:270`). The mutation now deterministically flips the last
signature digit to a different one; 30 consecutive single-file runs pass
after the fix (previously 2/30 failed). Production code was verified
correct — the middleware's fail-closed service-bucket fallback is exactly
what the test claims.

Fourth-phase re-validation: `uv run pytest` over the thirteen PR-relevant
suites (Hive `test_api`/`test_engine_service`/
`test_production_workspace_scope`/`test_workspace_scoped_submission`/
`test_mission_controls`, core `test_http_contract`/`test_idempotency`/
`test_queue_persistence`, server `test_rate_limit`/
`test_task_workspace_scope`/`test_webhooks`, migrations
`test_audit_scope_migration`/`test_migration_chain`) — 241 passed, 12
skipped, 0 failed, repeated 4x for the flake investigation. `uv run ruff
check .` and `uv run ruff format --check .` pass; `uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` passes with `unclassified: 0` and a clean
ratchet (1415 reviewed identities → 1415 findings).
