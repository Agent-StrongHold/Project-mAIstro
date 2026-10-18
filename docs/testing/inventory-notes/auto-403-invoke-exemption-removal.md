---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  tests/: +3
---
# `/invoke` elevation exemption removal (#403)

`middleware/auth.py::_required_permission` no longer exempts any path ending
in `/invoke` from permission gating. The route the exemption was written for
(POST `/v1/agents/{id}/invoke`) no longer exists, so the suffix check only
served future routes — each of which would have inherited a silent privilege
bypass decided by URL naming. Elevation now binds exclusively to the
capability identifiers registered in `_PROTECTED_OPS` (prefix → permission)
plus the named, reviewed exceptions in that method.

Companion changes:

- `scripts/check_enumerations.py::_route_is_scoped` lost its mirrored
  `endswith("/invoke")` shortcut, so check A fails the build on any new
  mutating `/invoke` route that is neither scoped nor explicitly exempt in
  `ROUTE_EXEMPT` (new routes default to protected, explicit reviewed policy
  to unscope). The real-tree ratchet still reports "no new enumeration gaps"
  because no live route ends in `/invoke` — the exemption was dead code.
- `packages/hive-conductor/backend/tests/test_auth_middleware.py`: the
  `TestInvokeSubstringCarveOutBoundary` class (3 tests, pinning the old
  suffix exemption) was replaced by `TestInvokeSuffixExemptionRemoved`
  (5 tests): an `/invoke` path resolves through the capability table (403
  without `agents.write`; passes the gate with the capability + elevation);
  a hypothetical unscoped future `/invoke` route gets no implicit exemption
  and no implicit gate; invoke-containing siblings resolve like any other
  path. `temp_route` gained a `methods` parameter; the seeding helper moved
  to module level as `_user_client` (net +2 node IDs).
- `tests/test_check_enumerations.py`: `TestInvokeSuffixCarveOutRemoved` pins
  `_route_is_scoped`'s new truth — an unclassified future `/invoke` route is
  a gap, scoping comes only from a registered capability prefix or an
  explicit reviewed `ROUTE_EXEMPT` entry (net +3 node IDs in `tests/`).
