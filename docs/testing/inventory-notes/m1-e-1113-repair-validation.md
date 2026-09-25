---
---
# M1-E #1113 repair-round validation record

Focused validation of the `auto-1113` branch at `2f8577e8896a868cce0208c2dfddbbaad51a503b`
(repair round for issue #1113, "Retire Hive standalone pre-convergence Graph
execution fallback"). No production or test code changed in this round; this
note records the acceptance evidence gathered against the tree as it stands.

## What was executed

- `uv run ruff check .` — all checks passed (repo-wide).
- `uv run ruff format --check .` — 2534 files already formatted.
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src` — success,
  713 source files.
- `uv run pytest` (hive-conductor, targeted): `test_graph_spine_architecture_gate.py`,
  `test_dag_agents.py`, `test_canonical_dag_runner.py`, `test_optimizer.py`,
  `test_substrate_tools.py` — 108 passed; `test_dag_execution_transport_parity.py`,
  `test_dag_run_history_durability.py`, `test_dag_run_scope.py`,
  `test_dag_run_scope.py`, `test_dags_routes.py`, `test_engine_service.py`,
  `test_graph_runner.py`, `test_hitl_door.py`, `test_hitl_timeout_cancel.py`,
  `test_node_metrics_are_measured.py`, `test_scheduler.py`,
  `test_dag_condition_trust.py` — 293 passed; `test_dag_recovery.py` +
  `test_canonical_recovery_cadence.py` — 21 passed.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs/
  test_legacy_archive.py test_recovery_wakeup.py` — 65 passed.
- `uv run python scripts/check-convergence-matrix.py` — OK (52 subsystems,
  1117 production modules classified).
- `uv run python scripts/check-execution-lifecycles.py` — OK (19 lifecycles
  classified, 3 CANONICAL).
- `uv run python scripts/check-wiring-reads.py` — OK (wiring ledger matches).
- `uv run python scripts/check-reachability.py` — OK (1117 modules, 188
  unreachable attributed).

## Acceptance mapping (as executed)

- `run_registered_dag` fails closed without the spine:
  `services/dag_agents.py` `_canonical_execution_stores()` raises
  `GraphExecutionUnavailableError` before any Graph work; proven by
  `test_registered_dag_fails_closed_without_the_canonical_spine`,
  `test_without_a_bridge_graph_nodes_are_unavailable`,
  `test_an_unavailable_engine_does_not_select_a_private_graph_store`.
- `execute_dag` cannot fabricate scope: `_scope()` requires an authorized
  `DagExecutionScope` plus canonical stores; the only shipped
  `DagExecutionScope(...)` constructor call lives in
  `services/dag_execution_scope.py` (`authorize_hive_dag_scope`);
  `hive-standalone-compat` survives only as a test fixture string.
- Explicit unavailable/degraded results: HITL 503 (`routes/hitl.py`),
  optimizer short-circuit (`routes/optimizer.py`), chat synth/hill-climb
  unavailable projection (`services/chat_completion.py`,
  `services/substrate_tools.py`), scheduler leaves the occurrence owed
  (`services/scheduler.py`), engine `graph_execution_available`.
- Fallback store confined to tests + architecture gate:
  `test_graph_spine_architecture_gate.py` fails shipped `run_durable_graph`
  without `run_store=` and any shipped `InMemoryDurableRunStore` /
  `_fallback_*` reference.
- Legacy pre-convergence records: readable through
  `maistro.graph.durable_runs.legacy_archive`; resumption is refused by name
  per accepted ADR-082826-d9f5 (AC-6), which reconciles the issue's
  "readable/resumable" wording — re-admitting an archived record would mint a
  new out-of-spine identity, exactly what the issue's stop condition forbids.
- Restart/replica: `test_admitted_run_persists_execution_mode_needed_after_restart`,
  recovery/wakeup ownership by canonical `admission_source` provenance, and
  transport-parity tests driving a real canonical `create_container` spine.

No test inventory changed in this round (`+0/-0`); the suites above were
added and noted by the earlier rounds listed in this directory.
