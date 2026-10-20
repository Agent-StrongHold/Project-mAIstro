---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 1058 repair 4: migrate the last un-migrated `submit_hitl_answer` call

At head bd6dc3e3b the mandatory-`HitlAuthorization` cutover left exactly one
deterministic failure: `packages/hive-conductor/backend/tests/
test_registered_dag_recovery.py::test_an_answered_scheduled_hitl_pause_resumes_on_the_next_tick`
called `CanonicalDurableRunStore.submit_hitl_answer` without the now-required
keyword-only `authorization` evidence (`TypeError`), failing in isolation and
in the full backend suite.

Repair: the test now builds the same typed evidence the routes manufacture
(`HitlAuthorization(effective_principal="rdr-operator",
workspace_ids=frozenset({"ws-rdr"}), membership_check=...)`) and passes it to
the store, which re-checks Workspace membership inside the mutation. No
production code changed; no test count delta.

Validation at this head: full backend suite 2660 passed / 1 skipped / 0
failed; `packages/maistro-core/tests/graph/durable_runs` 472 passed / 21
skipped; `ruff check .` and `ruff format --check .` clean;
`check-suite-inventory` ok for both suites.
