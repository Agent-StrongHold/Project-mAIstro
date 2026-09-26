---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
---

# auto-1113 repair round 2: develop sync + honest AC criterion registration + e2e no-spine truth

Repair of the round-1 CI findings on lane L1113 (#1113), plus resolution of the
preserved develop-sync conflict block.

## Develop sync resolved

- Merged `9e9f5037e` (#1443, HITL authorization) — one conflict in
  `test_hitl_door.py::test_blocked_answers_name_each_verified_requester_without_settling_approval`:
  develop's body called `get_run_store()` directly, which fails closed under
  #1113; kept this branch's construct-and-patch seam and the union of imports.
- Merged `a71fc2e43` + `031bd0746` (develop tip, clean).
- `test_hitl_timeout_cancel.py::test_expiry_endpoint_only_settles_authorized_workspace_projects`
  relied on develop's retired `get_canonical_run_store` / no-spine fallback
  singleton. Rebound to the same explicit test seam the merged
  `test_hitl_door.py` uses: construct `InMemoryDurableRunStore()` and patch
  `services.dag_agents.get_run_store` — production still refuses this store.

## AC criterion registration (fixes `markers_without_criterion 4>2` + `design_coverage 37.9642<38.0924`)

The lane's four `M1-E-1113/*` markers name no declared criterion (a marker
prefix must be a document id; `M1-E-1113` is a GitHub issue id and no
`SPEC-*`/ADR carries it), and leaving `ADR-082526-3ca6/AC-5` untagged dropped
that ADR's fifth criterion from `reachable` — exactly the observed 0.1282pp
fall.

`M1-E-1113/*` cannot be registered as a document, so the honest repair is the
other direction: **ADR-082526-3ca6/AC-5's declared text was amended** to the
superseding fail-closed contract (#44/#1113 retire the no-arg-resolver
fallback the criterion originally ratified), with an inline provenance note,
and the four markers were retagged to `ADR-082526-3ca6/AC-5`, which the tests
now genuinely prove:

- `test_without_a_bridge_graph_nodes_are_unavailable` (resolver refuses),
- `test_an_unavailable_engine_does_not_select_a_private_graph_store`
  (run-store seam refuses),
- `test_registered_dag_fails_closed_without_the_canonical_spine`
  (registered-DAG entry point refuses),
- `test_a_refused_execution_is_unavailable_not_a_generic_error` (the refusal
  keeps its `unavailable` shape through the chat tool).

Gate reproduced locally with CI parity (pgvector:pg18 + `MAISTRO_TEST_PG_DSN`;
note: the local quality gate silently loses ~5pp of `reachable` criteria when
`MAISTRO_TEST_PG_DSN` is unset — CI sets it, local reproductions must too):
`check-ac-state.py --run-tests --ratchet --mandate 031bd0746f30a` exits 0 with
`design_coverage 38.0924` (exactly at floor) and `markers_without_criterion 2`
(before: exit 1, 37.9642/4).

## e2e-ui repair (round-1 finding 2: `expect(run.execution_id).toBeTruthy()` ×2)

Root-caused, no longer UNVERIFIED: `pm-workflow.spec.ts` tests 06/07 asserted
the retired pre-convergence behavior — `POST /v1/dags/{id}/run` minting an
execution id. In the compose harness hive boots without the maistro-core
bridge, so under #1113 the route truthfully returns HTTP 200 with
`status: "unavailable"`, `execution_id: null` (routes/dags.py
`CanonicalDagExecutionError` branch), and no projection row is recorded.

Rewritten to assert the new contract: 06 proves activation works and the run
attempt reports `unavailable` with no execution identity; 07 proves feedback
against a run id the spine never admitted is a 404 refusal, not a silently
accepted write. Both verified against the real stack:
`docker compose --profile test up --build --exit-code-from e2e-tests` →
87/87 Playwright tests pass, including the rewritten 06/07, exit 0.
(`integration-scope` requires exactly this job, so its transitive red is
addressed by the same repair; `docker-build`'s image is proven by the same
compose build.)

## Counts

- `packages/hive-conductor/backend/tests`: 0 (retags + one seam fix; 2832
  passed / 6 skipped locally, unchanged count).
- `packages/hive-conductor/tests/e2e`: 0 (two tests rewritten in place).
