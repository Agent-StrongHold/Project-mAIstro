---
inventory-delta:
  packages/maistro-design/tests: +3
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
