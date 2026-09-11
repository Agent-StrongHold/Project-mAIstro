---
inventory-delta:
  tests/: +6
---
# fix-m1-static-gate-coverage-c9b6

Widens `scripts/shipped_surface_truth.py`'s fake-success/route-discovery
scanner (#1144): a route registered via `router.add_api_route(...)` was
never discovered at all, a dynamically-built route path (an f-string or
similar) was silently dropped instead of recorded as unresolved, and the
"obvious fake success" check flagged any handler whose reachable returns
all agreed on a literal, even when the handler did real `await`/`try`
work first.

`tests/test_shipped_surface_truth.py` (+6): new cases cover a fake-success
literal surviving logging/assignment before the return, a handler doing
real async I/O correctly NOT being flagged, the real-work detector
stopping at a nested helper function rather than looking inside it,
`add_api_route` registration being discovered and its handler resolved,
an `add_api_route` call whose endpoint can't be resolved still being
recorded (as unresolved, not dropped), and a dynamically-built route path
never being silently dropped from the matrix.
