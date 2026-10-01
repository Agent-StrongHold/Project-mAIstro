---
id: ADR-076
title: "HTTP API Versioning via content negotiation"
repo: maistro-engine
kind: adr
status: Implemented
accepted: 2026-06-10
created: 2026-05-30
implemented: 2026-10-01
substrate: []
implements: []
related:
  - maistro-engine#ADR-059
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Accepted
    date: 2026-06-10
  - status: Implemented
    date: 2026-10-01
---

# ADR-076: HTTP API Versioning via content negotiation

**Status:** Implemented
**Date:** 2026-06-10
**Fixes the HTTP surface contract** so the API can evolve without forking the URL space, and so every
client (TUI, web, third-party) talks to one canonical, fully-featured surface.

**Implementation status (2026-10-01, #96): implemented.** The negotiation
scheme now runs on both business HTTP surfaces — `maistro-server` and
`hive-conductor` — as one shared middleware, `maistro.api_versioning.VersionNegotiationMiddleware`
(in `maistro-core`), wired just inside each app's security-headers layer. A
request selects a version via `Accept: application/vnd.maistro.vN`, an
`api_version` query parameter, or an `api_version` JSON body field (precedence
in that order); every response advertises `Maistro-API-Version` and
`Maistro-API-Default`; an unsupported selector is a `406` and a malformed one
a `400`, both answered before any route handler; a plain-JSON response to an
Accept-negotiated request is returned as `application/vnd.maistro.vN+json`;
deprecation signalling (`Deprecation`/`Sunset`/`Link`) ships behind the version
table. Health, metrics, OpenAPI/docs and A2A paths are out of scope, matching
the Out-of-scope list below. Evidence:
`packages/maistro-core/tests/api_versioning/test_middleware.py`,
`packages/maistro-server/tests/api/test_version_negotiation.py`,
`packages/hive-conductor/backend/tests/test_version_negotiation.py`.

What this implementation deliberately does not claim: no second version
exists yet, so the breaking-change criterion below is implemented as
mechanism (a version table) but not yet exercised by a real v2; nothing is
deprecated, so the signalling headers are proven by a fixture version only;
and the canonical-surface parity property is a separate standing rule, not
something this negotiation layer can prove. The canvas
`application/vnd.canvas+json;version=2` media-type check remains a
canvas-local response-format mechanism — it never was this ADR's general
scheme, and the middleware explicitly leaves vendor media types untouched.

---

**Earlier status (2026-07-29, D2/#290; historical):** the decision was
Accepted but no code implemented the scheme; every business route was mounted
under a plain `/v1` prefix and the only negotiation code in the tree was the
canvas-local `/v2/canvas` media-type check. That deferral was tracked in
[KNOWN-GAPS.md](../../KNOWN-GAPS.md) and closed by the implementation above.

---

## Context

The HTTP API spans `maistro-server` and the hive-conductor `/v*` surface. As the API grows we need a
versioning discipline that (a) lets breaking changes land without stranding existing clients and
(b) does not splinter the route space into `/v1/...`, `/v2/...` duplicates that drift apart and double
the test/maintenance surface. We also need a single principle for what "the API" *is*: the engine is
library-first with a thin app wrapper, and the various UIs (TUI, web, others) should be peers, not one
privileged client with private routes. This ADR sets both: how versions are selected, and that the
HTTP API is the canonical surface every client shares.

## Decision

The HTTP API versions via **content negotiation on a header/field**, not by path-splitting.

### Version selection

A request selects a version one of two ways:

- **Header** (preferred): `Accept: application/vnd.maistro.v2`
- **Body/query field**: `api_version: 2`

A **single endpoint serves all versions**. There is no `/v1/...` vs `/v2/...` path duplication — the
URL identifies the *resource*, the negotiated version identifies the *representation/behavior*. A
request with no version selector resolves to the current default version, which is advertised in the
response.

### What bumps the version

- **Additive changes do NOT bump the version.** New optional request fields, new optional response
  fields, and new routes are backward-compatible and ship within the current version.
- **Only breaking changes increment** the negotiated version: removing/renaming a field, changing a
  type or a default, tightening validation, or changing semantics of an existing operation.

### Deprecation window

When a version is slated for removal, responses to that version carry deprecation signalling headers
so clients can migrate before the version is withdrawn:

```
Deprecation: true
Sunset: Wed, 30 Sep 2026 00:00:00 GMT
Link: <https://docs/.../migrate-v1-to-v2>; rel="deprecation"
```

### Example

```http
POST /v1/chat/complete
Accept: application/vnd.maistro.v2
Content-Type: application/json

{ "messages": [ ... ] }
```

```http
HTTP/1.1 200 OK
Content-Type: application/vnd.maistro.v2+json
Maistro-API-Version: 2
Maistro-API-Default: 2
```

(The `/v1` path segment here is the stable resource mount; the *behavioral* version is negotiated, not
taken from the path.)

### Canonical-surface principle

The HTTP API is the **canonical surface**. The TUI, web UI, and any other UI are **clients of it** —
the "thin wrapper" parity principle: every operation a UI can perform must be reachable through the
API. No UI gets a private side-channel or a capability the API does not expose. This keeps the API
complete and keeps every client at parity.

## Acceptance criteria

- [x] A client selects an API version via `Accept: application/vnd.maistro.vN` or an `api_version`
      body/query field; both forms resolve to the same negotiated version.
      *(Implemented and proven by the test files named above.)*
- [x] A single endpoint serves all versions; there is no `/vN/.../...` route duplication per version.
      *(Business routes stayed on their stable `/v1` mounts; the middleware serves the version axis.)*
- [x] An additive change (new optional field or new route) ships without incrementing the negotiated
      version and does not break a client requesting the prior version.
      *(This change itself is the exercised case: new response headers and a new negotiation layer
      shipped within version 1.)*
- [ ] A breaking change increments the negotiated version, and the prior version keeps working until
      its sunset.
      *(Mechanism in place — a version table with deprecation metadata — but no v2 exists yet to
      exercise it.)*
- [x] A request omitting a version selector resolves to the advertised default version, and the
      response states which version served it.
      *(Proven: `Maistro-API-Version` / `Maistro-API-Default` on every negotiated response.)*
- [x] A deprecated version's responses carry `Deprecation` / `Sunset` / `Link` headers naming the
      migration path.
      *(Proven against a fixture version; nothing is deprecated today, so no live traffic carries
      them.)*
- [ ] Every operation exposed in any UI (TUI, web) is reachable through the HTTP API (parity check).
      *(A standing property of the canonical-surface principle, not a property the negotiation layer
      can prove; tracked by that principle, not closed here.)*

## Consequences

- The URL space stays stable as the API evolves; version skew lives in negotiation, not in forked
  routes, halving the route/test surface relative to path-versioning.
- Clients opt into breaking changes deliberately by raising the version they request; silence keeps
  them on a known version until sunset.
- The canonical-surface rule forces feature completeness at the API layer and prevents UI-private
  capabilities from accreting.
- Handlers must branch on the negotiated version internally; this concentrates compatibility logic in
  one place rather than across parallel route trees.

## Out of scope

- The internal mechanism for dispatching a request to per-version handler logic (middleware vs
  decorator vs resolver) — an implementation detail.
- Versioning of non-HTTP surfaces (A2A, MCP, event bus).
- Authentication and authorization on the surface (ADR-068) — orthogonal to version negotiation.
- The default-version rollover policy (when the advertised default advances to a newer version).
