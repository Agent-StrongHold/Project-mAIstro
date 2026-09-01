---
id: SPEC-070226-8239
title: "maistro-server /v2/canvas capability boundary and consumer cutover"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-02
substrate:
  - maistro-engine#ADR-045
  - maistro-engine#ADR-076
  - maistro-engine#SPEC-229
implements:
  - maistro-engine#ADR-045
related:
  - maistro-engine#ADR-042
  - maistro-engine#SPEC-183
  - maistro-engine#SPEC-184
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-02
---

# SPEC-070226-8239: maistro-server /v2/canvas capability boundary and consumer cutover

## Current interpretation

This specification remains **Proposed** because the server-side Canvas boundary
is only partially wired and the product-consumer cutover is incomplete. Older
revisions called the consumer "Canvas Studio" and treated it as a separate
product. That product framing is retired: **Design Studio** is the parent
creative-production surface and **Canvas** is a capability/tool boundary within
that product.

The live contract retained here is the mounted `maistro-server` `/v2/canvas`
surface and its migration role for product consumers. It must not be interpreted
as authorization for a separate Canvas Studio lifecycle, storage authority,
execution system, or frontend product.

## Context

Canvas has lower-level capability routes and storage/rendering services, while
product consumers need a stable server boundary that does not require importing
or calling package-private Canvas internals. `maistro-server` therefore exposes
`/v2/canvas/*` routes that wrap injected Canvas dependencies.

The proxy surface exists today, but the default shipped service does not inject
`app.state.canvas_store`; data routes consequently return `503`. Optional
compositor/event/asset providers are likewise unavailable when not configured.
That is truthful partial implementation, not a completed Design Studio cutover.

Design Studio migration is owned by #95 under #286. Legacy direct Canvas routes
may coexist until parity and supported deployment wiring are proven.

## Goals

- Maintain `/v2/canvas/*` as the server-facing Canvas capability boundary for
  operations it actually implements.
- Make product consumers, including Design Studio, use governed server/Canvas
  capability seams rather than package-private or separate-product side paths.
- Preserve Canvas as the owner of Canvas domain/storage/rendering semantics.
- Fail visibly when required Canvas dependencies are absent.
- Preserve backward compatibility during the migration window without treating
  legacy routes as a second canonical product surface.
- Keep content-negotiation behavior explicit and limited to what the current
  server actually implements; ADR-076 remains the general API-versioning
  authority.

## Non-goals

- Recreating a standalone Canvas Studio product.
- Rewriting Canvas ability internals.
- Defining Design Studio Goal/CreativeBrief/artifact-control state.
- Creating a second Run/job lifecycle.
- Multi-tenant Stronghold policy.
- Claiming that publish/export is available when providers are not configured.

## Current API surface (`/v2/canvas/*`)

The currently registered `maistro-server` handlers are:

```text
GET    /v2/canvas/designs
POST   /v2/canvas/designs
GET    /v2/canvas/designs/{design_id}
PUT    /v2/canvas/designs/{design_id}
DELETE /v2/canvas/designs/{design_id}
POST   /v2/canvas/designs/{design_id}/publish
GET    /v2/canvas/designs/{design_id}/export/{format}
GET    /v2/canvas/assets
```

There are currently **no** `/thumbnail` or `/generate-ai` handlers on this
server boundary. Future generation, thumbnail, or refinement endpoints must be
added explicitly and proven before being listed as reachable API surface.

`packages/maistro-server/src/maistro_server/api/canvas.py` is authoritative for
current reachability until this proposal is fully accepted. This spec constrains
that boundary behavior; it does not turn a `501` stub or an unconfigured provider
into an available product effect.

### Dependency injection

The server composes Canvas capability dependencies through app state. At
minimum:

- `app.state.canvas_store` is required for Canvas data operations. When absent,
  affected routes return `503` rather than an empty or simulated result.
- `app.state.canvas_compositor` is optional; export/render operations that need
  it report unsupported/unavailable behavior when absent.
- `app.state.canvas_events` is optional and does not imply a second event bus.
- `app.state.canvas_asset_registry` is optional for asset discovery.

The composition layer may depend on Canvas protocols without taking ownership
of Canvas persistence or execution semantics.

### Authentication and authorization

The server Canvas surface uses the same governed authentication/authorization
boundary as other server routes. Design Studio does not gain a privileged
in-process bypass. A future product mount must bind the authorized
Workspace/Project context required by the canonical product hierarchy.

### Content negotiation

The current Canvas server surface may support its narrow Canvas media-type
behavior. It must not be described as implementation of the repository-wide
ADR-076 negotiation scheme unless the general server actually implements that
scheme. API version and package version remain independent.

## Consumer cutover

### Phase 1 — Server boundary exists, dependencies may be unconfigured

`maistro-server` mounts the Canvas router and has tests that exercise behavior
against injected fakes. This phase is **partial** in the shipped deployment
because required Canvas dependencies are not wired by default. Those existing
tests are not yet registered as contract evidence for this spec because they do
not carry the contract markers required by ADR-032.

Done when:

- the mounted routes have stable, registered contract evidence for
  request/response/error behavior;
- missing required dependencies fail explicitly and that behavior is registered
  as contract evidence;
- configured dependencies are exercised without bypassing Canvas protocols;
- no success-shaped placeholder substitutes for unavailable work;
- optional event-delivery failure cannot turn an already-persisted mutation into
  an ambiguous failure response unless event delivery is itself part of the
  governed effect contract.

### Phase 2 — Design Studio and supported deployments bind the capability

Under #95, Design Studio reaches the Canvas capability through an authorized
Workspace/Project-bound composition and consumes real durable job/Run state.
The product must be able to cancel, refresh/reconnect, and observe terminal
success/failure without local timers or fake `/canvas/eval` behavior.

Done when the #95 acceptance criteria are met through public/canonical seams,
not by moving Canvas internals into the Design Studio page.

### Phase 3 — Retire redundant direct/legacy paths

Legacy direct Canvas paths may be removed only after supported consumers have
migrated and behavioral parity is demonstrated. Retirement must not delete the
only path to persisted data or break downstream importers without an explicit
compatibility decision.

## Boundary contracts

- Design Studio is the product; Canvas is a capability.
- Server proxying does not create a second Canvas lifecycle or storage owner.
- Required dependency absence is explicit (`503` or another documented
  unavailable response), never fabricated success.
- Publish/export/generation effects are available only when their real governed
  providers are configured.
- Stable request/response/status semantics are compatibility-sensitive.
- Product consumers may not side-channel Canvas providers around canonical
  authorization, execution, or Invocation policy.

## Behavioral contracts

- Reads are side-effect free unless an endpoint explicitly documents otherwise.
- Mutations report real persistence failures and do not acknowledge success
  before the underlying persistence operation has succeeded at the contract
  boundary.
- Soft-delete and update semantics remain consistent with the server models and
  tests for the mounted routes.
- A configured export returns the documented media type; an unconfigured export
  reports unsupported/unavailable behavior rather than placeholder bytes.
- **Not yet satisfied:** the current `_emit()` path propagates a configured
  `canvas_events` callback failure after create/update/delete persistence has
  already succeeded. Until isolated or governed transactionally, a client can
  receive `500` after a successful mutation and may retry ambiguous work.
- Target behavior is that optional event emission does not change the success
  semantics of the primary persisted mutation unless that event is part of the
  governed effect contract.

## Acceptance criteria

- [x] `maistro-server` mounts a `/v2/canvas` router.
- [ ] Route behavior is registered as contract evidence with ADR-032-compatible
      `boundary`/`behavioral` markers.
- [ ] Missing required Canvas store behavior is registered as contract evidence
      rather than only existing as an unregistered implementation test.
- [ ] Optional `canvas_events` callback failure cannot turn an already-persisted
      mutation into an ambiguous failure response unless event delivery is part
      of the governed transaction/effect contract.
- [ ] A supported shipped deployment injects the required Canvas dependencies.
- [ ] Design Studio consumes the authorized Canvas capability boundary under
      #95 without direct/package-private side channels.
- [ ] Generation/refinement exposes canonical Run identity, real state,
      cancellation, refresh/reconnect restoration, persisted artifact linkage,
      and truthful terminal success/failure.
- [ ] Publish/export effects are backed by real governed providers where the
      product advertises them.
- [ ] Redundant legacy/direct routes are retired only after parity evidence.

## Testing

- Existing implementation exercise: `packages/maistro-server/tests/api/test_canvas.py`
  covers route behavior against injected fakes, including missing-store handling,
  but it is **not** listed in front matter as contract evidence until the tests
  carry the contract markers required by ADR-032.
- Auth: Canvas server routes use the same required bearer/session boundary as
  the surrounding server surface.
- Compatibility: stable wire fields and status mappings remain covered when
  handlers change.
- Product E2E: #95 proves Design Studio uses the real boundary without local
  execution simulation.
- Export/publish E2E: #94 proves configured effects are real before the product
  advertises them.

## Historical note

The original spec described a separate Canvas Studio frontend migrating from
localhost/direct Canvas routes to `maistro-server` in three phases. That
consumer-specific plan is historical only. The useful server-boundary contract
has been retained here and rewritten around the current Design Studio → Canvas
capability architecture.

## References

- [ADR-045: Canvas capability ↔ maistro-server /v2/canvas boundary](../adr/ADR-045-canvas-studio-engine-cutover.md)
- [ADR-042: Canvas Asset HTTP Routes](../adr/ADR-042-canvas-asset-routes.md)
- [ADR-076: HTTP API Versioning via content negotiation](../adr/ADR-076-http-api-versioning.md)
- [SPEC-229: Canvas asset compositor](SPEC-229-canvas-asset-compositor.md)
- `packages/maistro-server/src/maistro_server/api/canvas.py`
- `packages/maistro-server/tests/api/test_canvas.py`
- Design Studio cutover: #95 under #286.
