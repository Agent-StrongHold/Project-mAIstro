---
inventory-delta:
  packages/hive-conductor/backend/tests: +0-2
  packages/maistro-core/tests: +0
---
# auto-53 — #53 convergence merge repair (develop ba2f1f07 into auto-53)

Completes the interrupted merge of `ba2f1f077` (develop) into `auto-53` for the
M1-C5 convergence issue. The previous run resolved most conflicts but left three
files unmerged and dropped several develop-side behaviors from
`packages/maistro-core/src/maistro/container.py` while resolving it toward
HEAD's structure. This repair finishes the conflict resolution and restores the
dropped develop work so the merged tree passes both sides' suites.

## Conflicts resolved

- `packages/hive-conductor/backend/services/canonical_dag_runner.py` — union of
  both import blocks; `_scope` reconciled: with an authorized
  `DagExecutionScope` it keeps develop's fail-closed workspace/project match
  checks, without one it takes HEAD's resolver arm (request choice →
  DAG-carried workspace → deployment default, Root Project mapping) that the
  registered-DAG route and the #1174 projection writers call. Scope-less
  EXECUTION stays refused by `execute_dag` itself
  (`test_execute_dag_rejects_a_missing_scope` still pins that).
- `packages/maistro-core/tests/test_container_chat_runs.py` — union imports
  (both sides' symbols are used by the merged bodies).
- `packages/hive-conductor/backend/tests/test_dags_routes.py` — took HEAD's
  real-path tests for the conflicted bodies; ported develop's new regression
  tests onto the canonical seam instead of the retired `graph_runner.execute_dag`
  mock seam (#736): `test_activate_then_run_dag_with_a_selected_workspace_succeeds`
  (create → activate → run with explicit selection, real registered path),
  `test_run_dag_pre_admission_failure_has_no_fake_execution_id` (sanitized
  failure kind, `_public_failure` restored to the route — CodeQL
  stack-trace-exposure), `test_run_dag_projection_failure_does_not_rewrite_execution`
  (broken history projection cannot fail/rewrite the canonical Run).
  develop's `test_run_dag_missing_scope_fails_before_execution` became
  `test_run_dag_without_explicit_scope_uses_the_deployment_default` (the merged
  route deliberately keeps HEAD's deployment-default contract, so no-scope is
  not a 403), and `test_run_dag_carries_distinct_authorized_scopes` now asserts
  distinct canonical scopes through the real path. develop's mock-based
  `test_run_dag_canonical_failure_stays_failed` was not ported: HEAD's
  `test_created_dag_run_uses_one_canonical_run_for_history_projection` and
  `test_run_dag_cannot_project_a_failed_canonical_node_as_completed` pin the
  same failure truth through the real registered path.

## Dropped develop work restored in `container.py`

- `build_node_resolver` authorities-based composition (#1193) with the
  `graph_run_store` parameter, plus the dead `_di_node` helper removed to match.
- `Container.node_resolver()` — the one place consumers get the production
  resolver; the schedule consumer and parked-Run resume call it.
- `recover_stranded_chat_admissions` + `_compensate_if_stranded` +
  `DEFAULT_STRANDED_ADMISSION_AGE` (#338).
- `ChatDispatchUnrecorded` never redispatched (#1108): settlement factored into
  `_settle_chat_turn` / `_settle_unrecorded_dispatch`, shared by `route_request`
  and `route_conversation_request`.
- Durable consumer cursor machinery (#1163): `consumer_cursor_store`,
  `_durable_events_holder`, `_durable_event_holes`, `durable_event_hole_grace_s`,
  leased `process_durable_events` with `_gap_safe_position`, and the four-store
  SQLite/PG durable-event wiring.
- `task_idempotency` field + `wire_task_idempotency` wiring (#1176).
- `_wire_capability_invocations` + durable `capability_effects` (#1063 family).

## Test harness changes

- `packages/hive-conductor/backend/tests/test_chat_brief_interview.py` (+1
  fixture, 1 test adapted): added the same autouse `_canonical_chat_seam`
  fixture `test_chat_routes.py` uses, because interview turns now cross the
  canonical chat seam like every other turn (that is the #53/#1037 contract);
  the non-member test now asserts the route's 403 authorization boundary
  instead of a model turn — a canonical Run must never be admitted into a
  Workspace the caller cannot touch. The brief-interview interception itself
  was restored into `routes/chat.py` (develop's SPEC-091726-7c2a feature) on
  top of HEAD's canonical admission: the deterministic interview answer
  replaces the model callback, not the Run.
- `packages/hive-conductor/backend/tests/test_canonical_dag_runner.py` (1 test
  repointed): `test_resolver_without_a_scope_maps_the_compat_default` pins the
  reconciled `_scope` resolver arm; scope-less execution refusal is pinned by
  `test_execute_dag_rejects_a_missing_scope`.

Net test count is unchanged at the file level for the adapted suites; no
assertions were weakened — the two retired mock-seam tests are replaced by
real-path equivalents, and one expectation moved from "model answers a
non-member" to "route refuses a non-member" to keep the authorization boundary.
