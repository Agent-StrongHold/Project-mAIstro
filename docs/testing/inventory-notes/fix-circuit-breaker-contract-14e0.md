---
inventory-delta:
  packages/maistro-core/tests: +26
---
# fix-circuit-breaker-contract-14e0

All twenty-six are in `packages/maistro-core/tests/test_circuit_breaker.py`, the
PR #828 contract suite for banked circuit-breaker probe release. Nothing removed
or moved; existing cases were rewritten to inject a fake clock instead of
`time.sleep`, but their node count is unchanged.

Additive coverage:

- `TestSlidingFailureWindow` (2) — spaced failures age out of the window; exact
  boundary vs one instant past it.
- `TestHalfOpenProbe` (8) — single-lease admission, unleased success cannot close,
  probe timeout/reopen, async cancel and stale-result guards, and explicit
  `release_probe`.
- Constructor validation (16 node IDs) — `@parametrize` over invalid
  `failure_threshold`, duration fields (`recovery_timeout`, `failure_window`,
  `probe_timeout`), and non-callable `clock`.

The root `tests/test_circuit_breaker.py` smoke file only gained `allow_request()`
assertions; its count stays at six.
