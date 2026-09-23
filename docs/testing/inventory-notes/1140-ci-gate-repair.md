---
inventory-delta:
  packages/maistro-core/tests: +42
  packages/maistro-turing/backend/tests: +4
  tests/: +19
---

# Issue #1140 CI-gate repair validation

Scope: the three required-CI failures reported at reviewed head `6ebc7503`
(quality radon ratchet, coverage-gate diff floor, formal-conformance drift) and
the focused tests that close them. No gate, baseline, grant, or ledger was
weakened; the radon fix reduces the complexity of the two flagged blocks
instead of granting them.

- `packages/maistro-core/tests/security/test_http_route_policy.py` (+42, new):
  behavioral contract of the shared matcher `maistro.security.http_routes` at
  the library level — fail-closed `load_route_policy` validation for every
  malformed declaration shape, canonical `scope.verb` permission vocabulary,
  boundary-safe prefix matching, exact-over-prefix and longest-prefix
  selection, HEAD-through-GET, single-segment templates, ambiguous-declaration
  refusal, and the `canonical_permission` transport-spelling bridge consumed by
  `Principal.scopes`. This is also the publish-set coverage producer for the
  module: the CI `coverage-unit` job measures `packages/maistro-core/tests`
  only, so matcher tests living in root `tests/` never counted toward the
  diff-coverage floor for this file (measured 35% in CI).
- `tests/test_route_permission_gate.py` (+17): fail-closed branches of the
  shared gate — Turing public-table/middleware agreement (`audit_turing_public`),
  malformed registry readers, unreadable route-policy-map entries, unknown
  matching kinds, unusable route identities, `create_app`-factory discovery and
  app-less backend refusal, per-shape declaration failures, unusable access
  decisions (bad permission vocabulary, incomplete exemption, unparseable
  expiry, unknown access), ambiguous equal-specificity declarations, missing
  registry application sections, and `main()` failing closed when route
  discovery dies, plus unchanged-entry ratchet tolerance.
- `tests/test_check_enumerations.py` (+2): the routes check driven against the
  real Conductor application (no anonymous mutating `/v1` route), and a fired
  gap when the middleware's public tables and the registry agree on making
  `POST /v1/agents` anonymous — proving the checker reports rather than stays
  green.
- `packages/maistro-turing/backend/tests/test_auth.py` (+4): the Turing
  middleware's public fast-path refusals (an undeclared method inside a public
  family; a registry entry classified non-public on a public-table path), a
  permission declaration missing its permission name (deny, not allow), and the
  no-principal deny paths of `_has_permission`/`_principal`.
- `formal/generated/security-constants.json`: regenerated (`scope_count` 38 ->
  39 from the branch's added Turing scope); committed artifact, not a test.

Local validation: `scripts/check-diff-coverage.py` over combined
core+turing+conductor+scripts producers reports every measured changed file at
or above the 90%/80% floors; `check-radon-baseline.py` reports 71 -> 71 C-blocks
with no new findings; `check-public-routes.py` and `check_enumerations.py` pass
against base `ffd6fdb1`; ruff lint/format clean.
