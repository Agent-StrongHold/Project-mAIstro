---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
---
# auto-2465 — nested DAG failure results and Design exception responses projected at the public boundary (round 2)

Round 2: the CI diff-coverage gate failed the first cut — three of the six
re-anchored Design generic-500 branches (skill listing, discovery form, render
job creation) were bounded in code but not exercised by tests. Three more
sentinel regressions cover those branches; the suite is +17 now.

Issue #2465 (M2-A): `POST /v1/dags/{id}/run` sanitized its top-level `error`
with `_public_failure` but returned `"result"` unfiltered, and
`canonical_dag_runner._node_results`/`_project` placed `node_run.error` into
each failed node's projected `response` and the raw run error into
`result["error"]`. The websocket/SSE frame projection (`graph_runner`) drew
from the same result, and `routes/design.py`'s generic 500 branches answered
`detail=str(e)` / `f"...failed: {e!s}"` — unclassified exception text (paths,
provider replies, diagnostics) straight to the client.

## New tests (`packages/hive-conductor/backend/tests/test_dag_failure_public_projection.py`, +14)

Endpoint-level sentinel regression: a canonical failed-node result is seeded
with four distinctive evidence classes (bearer-token provider reply,
filesystem path, diagnostics dump with internal host credential) and the tests
assert no public surface returns them in any nested field:

- DAG run receipt (`POST /v1/dags/{id}/run`) — canonical failure body fully
  projected; truthful `status`/`run_id` preserved; a failure never reads as
  success; the persisted Recent Runs projection and its SSE event payloads
  clean too (+1);
- successful receipt keeps the caller's own task output verbatim — the
  explicit presentation contract (+1);
- champion receipt projected (+1);
- admission backpressure keeps its retryable 429 + Retry-After contract
  (+1);
- bounded safe failure kinds survive: host-authored budget/deadline failure
  text passes through, the `ALLOW_STUB_LLM` remediation stays actionable,
  unclassified text bounds to the fixed sentence (+3);
- websocket/SSE projection: replayed frames carry no sentinels, failed-node
  frames carry the bounded kind, live `node_failed` frames and the recorded
  SSE event payload carry no response text at all (+4);
- the projection seam itself (`canonical_dag_runner._project`) bounds failed
  node responses at the source so every transport inherits one policy (+1);
- Design routes' generic 500s name the exception kind plus the operation
  name, never the text (6 tests: project fetch, project listing, project
  preparation, skill listing, discovery form, render job creation — every
  re-anchored generic branch, one shared pytest fixture and request/store
  doubles).

## Superseded M1-era pins (same suite, count-neutral edits)

Two assertions relied on raw failure text crossing the boundary and are
narrowed by this change, with the disclosure regression linked to the M2-A
surface inventory (#465/#446) as issue #2465's boundary section directs:

- `test_dags_routes.py::test_run_dag_canonical_failure_stays_failed` now
  asserts the bounded `result["error"]`/node response instead of the raw
  nested text;
- `test_legacy_dag_node_container_composition.py` (2 cases) now assert the
  bounded node response; the no-gateway refusal text remains pinned at the
  run-level `result["error"]`, and the pinned-model guidance remains on the
  canonical NodeRun evidence.

Canonical truth is untouched: the Run/NodeRun/Attempt/Event stores keep the
full bounded evidence, and the #1877 canonical overlay on
`GET /v1/dag-runs/{id}` (authorized inspection) still serves it — pinned by
the unchanged `test_dag_run_canonical_lifecycle.py`.
