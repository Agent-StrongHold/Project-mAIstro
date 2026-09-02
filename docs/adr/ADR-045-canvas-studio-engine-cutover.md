---
id: ADR-045
title: Canvas capability ↔ maistro-server /v2/canvas boundary
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-09
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
  - maistro-engine#ADR-042
  - maistro-engine#ADR-043
  - maistro-engine#ADR-044
  - maistro-engine#ADR-019
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-09
---

# ADR-045: Canvas capability ↔ maistro-server /v2/canvas boundary

## Current interpretation

This ADR remains **Proposed** because the Canvas server boundary and legacy-route
cutover are only partially complete. The historical name "Canvas Studio" in
older revisions described a separate application. The repository may still ship
or run a standalone/installable `maistro-canvas` package during convergence,
and legacy package/install documentation may continue to describe that package
shape. What is no longer canonical is treating that package/application as the
top-level creative-production **product authority** or as a peer lifecycle,
storage, Goal, or execution system. **Design Studio** is the parent
creative-production product surface, and **Canvas** is one
visual/fixed-page/rendering capability it consumes.

The live authority retained by this ADR is therefore the Canvas capability
boundary: `maistro-server` may expose governed `/v2/canvas/*` routes over Canvas
stores/services, and product consumers migrate to that boundary without
creating a second product state model or bypassing canonical execution and
tool semantics. Design Studio product integration is tracked by #95 under
#286.

The old separate-application Phase A/B/C migration described below is preserved
only as historical engineering context. It is not authority to recreate a
separate top-level Canvas Studio product. Keeping a standalone package runnable
for compatibility, testing, or migration does not make that package the
canonical product boundary.

## Context

The original Canvas book-maker POC had a local FastAPI/Node-facing surface and
legacy JSONB state, while `maistro-canvas` introduced typed Canvas capability
models and routes. That split established a real architectural need for a
stable server boundary even though the old separate-product framing is no
longer valid.

`maistro-server` now mounts a `/v2/canvas` proxy surface. In the default shipped
configuration it does **not** inject the required Canvas store, so data routes
fail closed with `503`; optional compositor and other providers likewise remain
unavailable when not configured. The existence of a mounted route is not proof
that Design Studio or a supported deployment is fully cut over.

## Decision

Use `maistro-server` as the HTTP boundary for Canvas capability operations that
are exposed to product consumers. The boundary wraps/injects Canvas services;
it does not own a second Canvas lifecycle, Design Studio state model, or
execution system.

The current migration obligation is:

1. keep the typed Canvas capability contract stable for callers that configure
   the required dependencies;
2. wire supported deployments truthfully rather than returning success-shaped
   placeholders;
3. move Design Studio and other product consumers onto the governed Canvas
   capability boundary under their owning convergence issues;
4. retire legacy/direct route paths only after behavioural parity and supported
   deployment wiring are proven.

### Dependency injection and truthful unavailability

`maistro-server` owns the HTTP composition layer, while Canvas remains the
capability implementation. Required dependencies must be injected explicitly.
A missing required store is a service-unavailable condition, not an empty
Canvas. Optional export/render/event providers may report unsupported behavior
when absent rather than fabricating results.

### Auth and policy

Canvas routes inherit the server's normal authentication/authorization and
policy boundaries. A product consumer does not gain a privileged direct path to
`maistro-canvas` merely because the same process can import it. External effects
such as publish/export remain governed capabilities and are not implied by
successful generation or persistence.

### Rollback and compatibility

Legacy routes and standalone package entry points may coexist while consumers
migrate, but coexistence is a compatibility window, not a second canonical
product surface. Removal requires behavioural parity evidence and must not
strand persisted Canvas state or downstream package users.

## Historical separate-application migration notes

Older revisions proposed three phases for the former standalone Canvas Studio
application: mirror reads, cut reads over to the engine, then cut writes over
and retire its separate Postgres. Those steps are not the current product plan.
Where the observations still match live code they may inform #95 or a legacy
route-retirement task, but they must be revalidated against the current Design
Studio/Canvas boundary before implementation.

## Cross-service contracts

The `/v2/canvas/*` server surface is a consumer-facing Canvas capability
contract. Request/response models, status-code semantics, auth behavior, and
configured dependency requirements are compatibility-sensitive. Adding a
required request field, removing a response field, or silently changing a
stable error mapping requires the normal API compatibility process.

The accepted lower-level Canvas asset route contract remains ADR-042. This ADR
covers the additional `maistro-server` composition/cutover boundary; it does
not supersede ADR-042 or make the server the owner of Canvas domain models.

## Boundary contracts

- Design Studio is the product; Canvas is a capability inside it.
- A runnable/installable standalone Canvas package is a compatibility/deployment
  form, not a second canonical product identity or state authority.
- `maistro-server` may compose Canvas dependencies but does not create a second
  Canvas or Design Studio lifecycle.
- Missing required Canvas dependencies fail visibly; they do not yield fake
  success or placeholder artifacts.
- Direct legacy routes may remain only as an explicitly transitional surface.
- Product cutover must preserve authorization, durable state, execution
  identity, cancellation semantics, and provenance owned by their canonical
  systems.

## Behavioural contracts

- Reads must not mutate Canvas state merely because they cross the proxy
  boundary.
- Mutations must report real persistence/provider failures.
- A configured server proxy and the underlying Canvas capability must agree on
  the stable wire semantics they both expose.
- A consumer refresh/reconnect must observe durable state rather than a new
  locally simulated operation once the production cutover is complete.

## Consequences

- The old "Canvas Studio" name may survive in filenames, package metadata,
  install guidance, and legacy migration notes while compatibility surfaces
  remain runnable; those references do not define a current peer product
  authority.
- `maistro-server` deployment wiring is part of whether the Canvas HTTP boundary
  is actually usable.
- Design Studio's #95 cutover can consume this boundary without owning Canvas
  internals or inventing a parallel API/runtime authority.
- Legacy database/route/package retirement remains separate work and requires
  parity evidence before deletion.

## Out of scope

- Defining Design Studio's Goal, CreativeBrief, artifact, or control model.
- Replacing canonical Run/NodeRun/Attempt execution semantics.
- Implementing publish/export providers.
- Multi-tenant Stronghold policy.
- Removing standalone `maistro-canvas` packaging solely to enforce product
  naming; package retirement requires its own compatibility evidence.
- Recreating the former standalone Canvas Studio application as a peer product
  authority.

## Source references

- `packages/maistro-server/src/maistro_server/api/canvas.py` — mounted server
  Canvas proxy surface.
- `packages/maistro-server/tests/api/test_canvas.py` — implementation exercise;
  contract-marker registration remains incomplete in SPEC-070226-8239.
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_routes.py` — accepted
  lower-level Canvas asset route surface (ADR-042).
- `packages/maistro-canvas/src/maistro_canvas/canvas/routes.py` — legacy Canvas
  route surface retained during convergence.

## Links
