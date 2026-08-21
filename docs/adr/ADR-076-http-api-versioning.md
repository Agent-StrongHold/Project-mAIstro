---
id: ADR-076
title: "HTTP API Versioning via content negotiation"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
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
---

# ADR-076: HTTP API Versioning via content negotiation

**Status:** Accepted
**Date:** 2026-06-10
**Fixes the HTTP surface contract** so the API can evolve without forking the URL space, and so every
client (TUI, web, third-party) talks to one canonical, fully-featured surface.

**Implementation status (D2/#290, 2026-07-29):** the decision is Accepted, but no
code implements this content-negotiation scheme. `maistro-server` and
`hive-conductor` mount every business route under a plain `/v1` path prefix
(`main.py` in each), not the `Accept: application/vnd.maistro.vN` / `api_version`
mechanism described below. The only content-negotiation code anywhere in the
tree is `maistro-server`'s `/v2/canvas` route, which checks a narrow,
canvas-specific `application/vnd.canvas+json;version=2` media type — unrelated
to this ADR's general scheme. None of the acceptance criteria below are met.
Tracked as a v1.1 deferral in [KNOWN-GAPS.md](../../KNOWN-GAPS.md#http-api-content-negotiation).

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

- [ ] A client selects an API version via `Accept: application/vnd.maistro.vN` or an `api_version`
      body/query field; both forms resolve to the same negotiated version.
- [ ] A single endpoint serves all versions; there is no `/vN/.../...` route duplication per version.
- [ ] An additive change (new optional field or new route) ships without incrementing the negotiated
      version and does not break a client requesting the prior version.
- [ ] A breaking change increments the negotiated version, and the prior version keeps working until
      its sunset.
- [ ] A request omitting a version selector resolves to the advertised default version, and the
      response states which version served it.
- [ ] A deprecated version's responses carry `Deprecation` / `Sunset` / `Link` headers naming the
      migration path.
- [ ] Every operation exposed in any UI (TUI, web) is reachable through the HTTP API (parity check).

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
