---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
  packages/maistro-core/tests: +18
  packages/maistro-server/tests: +10
---
# 96-api-content-negotiation

Implemented ADR-076's API-wide HTTP content negotiation (#96, M3-B6). The
mechanism is one shared middleware, `maistro.api_versioning.VersionNegotiationMiddleware`
in `maistro-core`, wired into both `maistro-server` and hive-conductor next to
the security-headers layer, so the tests pin the contract at three levels:

- `packages/maistro-core/tests/api_versioning/test_middleware.py` (+18) — the
  mechanism itself: the three selector forms (`Accept: application/vnd.maistro.vN`,
  `api_version` query parameter, `api_version` JSON body field), their
  precedence, the advertised default (`Maistro-API-Version` /
  `Maistro-API-Default`), 406/400 on unsupported/malformed selectors, the
  Accept-conditional `application/vnd.maistro.vN+json` rewrite (with the
  vendor-media-type carve-out that keeps canvas's
  `application/vnd.canvas+json;version=2` untouched), deprecation signalling
  proven against a fixture version, and the body cache-and-replay that keeps
  downstream consumers (payload limits, webhook signatures) seeing the same
  bytes. Nine of the eighteen carry `@pytest.mark.contract("boundary")` — the
  ADR's boundary contract — but the ADR's front matter still lists no `tests:`,
  so the contract-markers ledger entry for ADR-076 is unchanged and needed no
  ledger edit.
- `packages/maistro-server/tests/api/test_version_negotiation.py` (+10) — the
  app wiring against the live route table: negotiation on `/v1` business
  routes, infrastructure paths (`/health`, `/metrics`, `/a2a`, docs) excluded,
  and the body-form selector leaving a real task-creation payload intact
  through the replay.
- `packages/hive-conductor/backend/tests/test_version_negotiation.py` (+9) —
  the same wiring for the conductor: public and auth-gated routes alike,
  rejections still carrying the security-header set (ordering proof), and
  `/health` out of scope.

No compensating removals: every test here is new coverage for new behavior.
Ordinary requests without a selector keep their pre-change semantics plus two
advertisement headers, which is why the pre-existing suites needed no edits.
