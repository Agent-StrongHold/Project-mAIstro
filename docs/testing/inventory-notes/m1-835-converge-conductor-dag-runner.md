---
inventory-delta:
  packages/hive-conductor/backend/tests: +61
  tests/: +5
---
# m1-835-converge-conductor-dag-runner

All +66 are #835 convergence tests; nothing was removed, so there are no
compensating changes to read past. The branch replaces the Conductor's
product-private DAG scheduler with the canonical durable Run executor
(`services/canonical_dag_runner.py` + `services/legacy_dag_node.py`), and the
suite grew to pin that move. Recorded in one note because the branch's earlier
commits landed tests ahead of their ledger entry; the repair pass that closed
the branch's red gates (format, model-egress ratchet, node-metrics seams,
diff-coverage gaps) added the last 49.

- `packages/hive-conductor/backend/tests/test_canonical_dag_runner.py` (new,
  +26): the adapter's contract — legacy dialect normalization, Run identity,
  terminal-state truth, queued-Run recovery, plus the repair's admission-time
  rejection table (invalid shapes, scope resolution, credential env scoping,
  resolver/refusal seams, metrics-failure isolation).
- `test_dag_recovery.py` (new, +8): the recovery cadence owns only
  hive_legacy_dag admissions — including covering tests for the invalid
  `execution_mode` branch of `_recovery_resolver`, the failing/positive tick
  logging, in-tick cancellation, and idempotent start.
- `test_legacy_dag_node.py` (new, +23): the extracted one-node adapter —
  tool-node dispatch (web_search iterate/template fallbacks, clarify,
  browse_url, generic, unknown, failing), per-node isolation classification
  tiers, the compatibility dependency/wave helpers, and the adapter node's
  blocked/sandbox execution paths.
- `test_ws_auth.py` (+2): the websocket principal stays the canonical Run
  actor, and a stream that ends without a terminal event closes the socket.
- `test_node_metrics_are_measured.py` (+1 net, one rename): the ingest records
  the model the runner reported now that measurement moved off the route onto
  `record_run_completion`; the route-pinning scan test was renamed to follow
  the recording seam it inspects.
- `test_dags_routes.py` (+1): a result with no canonical run id projects
  nothing into Recent Runs.
- `tests/test_check_model_egress.py` (+5): the CANDIDATE_MIGRATIONS ratchet
  exception that recognizes the graph_runner -> legacy_dag_node module move as
  a relocation, not an expansion of direct model egress.
