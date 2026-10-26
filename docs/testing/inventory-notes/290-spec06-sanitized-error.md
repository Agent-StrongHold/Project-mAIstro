---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# 290 spec 06 sanitized-error repair + template-reuse unit pin

## What moved and why

Two repairs after the hosted CI round at `af7519a5ea68` failed
`hive-conductor-e2e-ui` deterministically (1 failed / 240 passed; the same
failure at `cc4b793e6`), which is the `integration-scope` gate failure:

1. `packages/hive-conductor/tests/e2e/pm-workflow.spec.ts` spec 06 asserted
   `run.error` contains `host policy` — unpassable since the final develop
   sync (`af7519a5e`) merged #2288's `py/stack-trace-exposure` sanitization,
   which maps the `CanonicalDagExecutionError` branch to
   `"CanonicalDagExecutionError: execution failed; see server logs"`
   (`routes/dags.py`, unit-pinned in `test_dags_routes.py`). The spec now
   pins the sanitized kind (which still proves the request traversed the
   canonical executor — the spine-absent refusal surfaces a different kind
   and no execution id) and pins the host-policy refusal where production
   actually carries it: the canonical result's `error` fact. No test count
   change; the Playwright suite is not a suite-inventory ledger suite.

2. `packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py::test_foreign_workspace_template_is_reused_and_the_run_lands_in_the_schedules_workspace`
   (+1, the delta above) pins the f283f41a contract end to end on the tick
   path: a `(template_id, version)` already registered under a foreign
   Workspace is reused without refusal (the old code raised `ValueError:
   GraphTemplate ... belongs to Workspace ...`), the store entry is not
   rewritten, and the admitted Run's `workspace_id` is the schedule's —
   never the template's provenance. Verified to fail against `f283f41af^`
   with exactly that `ValueError`, and to pass at HEAD.

## Verification record (this round, independently re-executed)

- Red-proof re-verified first-hand: at a throwaway worktree on
  `f283f41af^` with only the test hunk applied, the new test fails with
  `ValueError: GraphTemplate 'scheduled-template' belongs to Workspace
  'ws-other', not 'ws-1'` (raised at `services/scheduler.py` `_prime_template`);
  the full admission file is 19 passed at HEAD.
- The `result.error` pin is grounded in production, not the unit stub:
  the node refusal is `PermissionError("Execution blocked: host policy did
  not authorize this node")` (`services/legacy_dag_node.py`), carried into
  the durable result by `canonical_dag_runner._project` (run error, else
  the first failed node's response) and returned verbatim under
  `result["error"]` while the top-level `error` field is `_public_failure`'s
  kind-only text (`routes/dags.py`, `services/graph_runner.py`).
- CI-exact `hive-conductor-e2e-ui` phase, fresh stack, at this tree
  (compose image `sha256:f9e9101549194e679be284d636f5505c7fed62d865e77f22037502d73762fb98`):
  **241 passed (4.6m), exit 0** — spec 06 green with the sanitized-error +
  `result.error` pins, vs the hosted failure `1 failed / 240 passed` at
  `af7519a5ea68` (job 121252949160) that motivated this repair.
- Suite-inventory ledger reconciliation proven both ways: with the note the
  backend suite reads `ok` (4105); with the note removed the same scan
  drifts (`expected 4104, collected 4105`) — the +1 delta above is exactly
  what reconciles the gate.
- Gates at this tree: `ruff check .` / `ruff format --check .` clean;
  CI-exact vulture ledger (1256 identities = 1256 findings, no ledger
  change); targeted backend run (`test_scheduler_canonical_admission.py` +
  `test_dags_routes.py` + `test_scheduler_timezone_health.py` + `test_api.py`
  + `test_degraded_mode_surface.py`) 106 passed.
