---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# claude-ws-736-assert-exactly-one-canonical-run-per-dag-678c

Added one behavioral test to `test_dag_execution_transport_parity.py`
(`test_http_and_ws_run_each_admit_exactly_one_canonical_run`, #736). It counts
canonical Runs whose `provenance.admission_source == "hive_legacy_dag"` and
`legacy_dag_id == stored_dag` via `services.dag_agents.get_run_store()` before
and after one `POST /v1/dags/{id}/run` and one WS `/v1/ws/dags/{id}/run`, in a
real Workspace, and asserts each request admits exactly one new canonical Run
whose id equals the response's `run_id` and the `DagRunStore` projection's
`canonical_run_id`. No production code changed — the invariant already held;
this closes the "exactly one canonical Run per request" test-coverage gap
that #736's triage flagged as missing (only distinctness across runs was
previously asserted, not the +1-per-request count).
