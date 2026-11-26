---
inventory-delta:
  packages/maistro-design/tests: +4
  packages/hive-conductor/backend/tests: +5
---
# Issue #52 Design canonical execution

Adds canonical Design Studio execution coverage for Run/NodeRun/Attempt success and failure, bound Workspace/Project scope enforcement, and truthful refusal of the legacy local render-job lifecycle.

Round 2 (develop sync ab8b3737 + repair):

- `test_design_scope.py`: +1 — anonymous request without the middleware's
  `state.principal` is refused (401) instead of fabricating an actor for the
  canonical spine; the render-boundary test was reconciled with develop's
  merged 501 "canonical Canvas rendering seam" contract (no local job
  lifecycle either way).
- `test_design_service_startup.py`: +2 — `TestCanonicalExecutionWiring` pins
  the production decision itself: `start_design_service` builds the
  `DesignCanonicalExecution` adapter over the container's run store and the
  canonical Root Project scope (`create_root`, idempotent) when the spine is
  available, and leaves the action truthfully unavailable (never stubbed)
  when it is not.
- Route principal resolution moved to the canonical `require_actor_id`
  helper (`services.request_principal`), the boundary AuthMiddleware actually
  stamps — the previous `state.user` dict read never existed in the live app
  and would have 401'd every authenticated Design request.

Round 3 (develop sync fad17a87c):

- All three `design_service.py` conflicts were additive — develop's
  `store_cause`/`DesignStoreConfigurationError` (#1826) vs this branch's
  `canonical_execution_available`/`get_design_canonical_execution` (#52) —
  so the resolution keeps both exports, both status fields, and both
  constructor arguments; `to_dict` on both parents already carried both keys.
- `canonical_execution.py`: removed a redundant `cast(str, run.run_id)` that
  CI's full-scope `mypy --strict` invocation flagged (a single-package mypy
  run cannot see `maistro.*` from source and misreports the package untyped).
- No test counts changed this round; the front-matter deltas still match
  collection (`scripts/check-suite-inventory.py`: ok, 21 suites).

Round 4 (replay result fidelity):

- `test_canonical_execution.py`: +1 — replaying a completed Design Run now
  rebuilds the `DesignProject` domain object from durable Attempt evidence
  instead of returning the JSON-hydrated dict (review finding: `project
  .to_dict()` on a replay raised `AttributeError`). The adapter persists
  `DesignProject.to_payload()` under a tagged envelope as the Attempt's
  evidence — plain-dict results pass through unchanged — and reconstructs via
  `DesignProject.from_payload()` on replay (BLOB leaves ride a base64
  envelope). The test also asserts the evidence survives a literal JSON round
  trip and never re-enters the provider.
- Front-matter delta updated to match collection (+4).
