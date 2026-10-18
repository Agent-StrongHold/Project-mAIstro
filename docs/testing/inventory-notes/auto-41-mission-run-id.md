---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# auto-41-mission-run-id

Issue #41 (M1-B1) repair round: the hive missions receipt now carries the
canonical execution identity and provenance.

- `packages/hive-conductor/backend/tests` +2, both in
  `test_workspace_scoped_submission.py`:
  - `test_the_mission_response_exposes_its_canonical_run_id` — POST
    `/v1/tasks` (engine-backed) must return the `TaskRecord.run_id` it was
    admitted with. Guards the `_task_to_mission` fix; the dropped-field
    regression previously surfaced as the `MISSION_RUN_ID_NOT_EXPOSED`
    probe.
  - `test_mission_creation_is_audited_to_the_authenticated_principal` —
    `mission_create` audit entries must name the logged-in principal (via
    `_user_id(request)`), not the literal `"system"`, with the mission id as
    target.

Same round, no count delta: `test_api.py::test_mission_create_dispatches_task`
sets its `MagicMock` record's `run_id` explicitly (auto-attributes are not
valid strings and fail `Mission` validation) and now asserts the wire body
carries the canonical run id — parity coverage for the same fix.

Test-infrastructure hardening with no count delta (recorded here because it
is part of the same repair): `packages/maistro-server/tests/api/
test_tasks_idempotency.py` now tracks every connection `_sqlite_claims`
opens and closes them in an autouse fixture while the test's loop still
runs, eliminating the intermittent `PytestUnhandledThreadExceptionWarning:
Event loop is closed` noise from leaked aiosqlite connections (13 collected
nodes unchanged; the suite stays at 407).
