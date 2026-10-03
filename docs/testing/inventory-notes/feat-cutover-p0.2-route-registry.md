---
inventory-delta:
  quality/: +3
---
# feat-cutover-p0.2-route-registry

Workspace cutover Wave 2 Lane B — P0.2 route-permission registry burn (#53 AC-P2).

`check-route-permissions.py` against `origin/develop` enumerated 40 mounted `/v1/*`
prefixes. This PR declares 17 elevation-gated prefixes in
`quality/route-permissions.json` (matching `middleware/auth.py` `_PROTECTED_OPS`)
and ratchets the baseline from 40 to 23 tolerated undeclared rows.

Also lands 23 `exempt::/v1/*` grants in `quality/ratchet-authorizations.json` so a
follow-up PR can declare the authenticated-only prefixes with `exempt_reason` and
zero the baseline without widening the reviewed surface in one commit.

No Python test delta — existing `tests/test_check_route_permissions.py` covers the
registry contract; the repo-level gate runs in `quality.yml`.
