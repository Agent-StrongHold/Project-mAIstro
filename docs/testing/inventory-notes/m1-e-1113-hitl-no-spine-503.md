---
inventory-delta:
  packages/hive-conductor/backend/tests: +2/-1
---
# M1-E #1113 HITL no-spine truth and transport-parity spine

Repairs the merge of develop's HITL membership-recheck coverage
(`test_hitl_mutation_rechecks_membership_at_the_store_boundary`, from #364)
with the #1113 no-spine refusal, closes the surface gap that merge exposed,
and re-homes the DAG transport-parity suite on the canonical spine:

- the test restored its own `is_member` patch with a blanket
  `monkeypatch.undo()`, which also dropped the `seeded` fixture's
  `get_run_store` injection; since #1113 removed the process-local fallback
  store, the loop's second request hit the unhandled no-spine refusal. The
  restore is now targeted at `is_member` only;
- `routes/hitl.py::_store()` mapped `GraphExecutionUnavailableError` to an
  unhandled exception, so without the core bridge every HITL surface that
  settles Graph work (pending listing, inspect, answer, cancel, expire)
  returned 500. It now raises the documented 503, matching the settings and
  install surfaces' unavailable contract;
- new `test_no_spine_hitl_surfaces_report_unavailable` drives all five HITL
  surfaces over HTTP in the honest no-Container state and asserts the explicit
  503 with an unavailable detail — no 500, no success from a private store;
- `test_dag_execution_transport_parity.py` asserted `completed`/`failed`
  canonical outcomes from a no-spine test process — exactly the pre-convergence
  universe #1113 retired, so all execution tests in the file broke at the
  cutover. A `canonical_spine` fixture now binds a real local Container
  (`create_container`, in-memory spine, no PostgreSQL) through the same
  `_agent_port` seam the configured product uses, and `_run_ids` reads admitted
  Run identity from the spine's Run store. The SQLite-composition test rewires
  the Container's project scope over the installed SQLite Workspace authority,
  so admission and Workspace resolution share one scope authority, as the
  configured product's shared store does.
