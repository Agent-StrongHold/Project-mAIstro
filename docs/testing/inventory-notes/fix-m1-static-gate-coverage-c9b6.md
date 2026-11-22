---
inventory-delta:
  tests/: +12
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

Codex review of the first head added six more in
`tests/test_shipped_surface_truth.py`, one per finding: two decorated
handlers sharing a name are both discovered (decorator discovery walks every
function node, not a by-name map); an `add_api_route(path=..., endpoint=...)`
registration with only keyword arguments is discovered and its handler
resolved; a non-literal `methods=` collection on either registration form
becomes the `<dynamic-methods>` stand-in the matrix must classify rather than
a dropped route; a qualified endpoint (`handlers.build`) keeps its qualifier
as identity and is never resolved by its bare name to an unrelated local
function; a write through an attribute or subscript (and a `del`) counts as
real work so a state-mutating handler is not an obvious fake success while an
inert local binding still is; and a dynamic route's identity carries a digest
of its expression, so rewriting the f-string on the same line yields a new
surface.
