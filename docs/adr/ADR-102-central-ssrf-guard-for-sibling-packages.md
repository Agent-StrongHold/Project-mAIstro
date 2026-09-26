---
id: ADR-102
title: "Sibling packages use maistro-core's central outbound HTTP guard"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-14
accepted: 2026-09-14
implemented: 2026-09-14
substrate:
  - maistro-engine#ADR-082326-5386
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - tests/test_check_security_inventory.py::test_repo_constructor_census_has_no_unpooled_production_clients
  - packages/maistro-rsi/tests/test_free_router.py::test_explicit_gateway_base_cannot_allowlist_a_private_target
ac-modules:
  AC-1: maistro.security.outbound
  AC-2: maistro_registry.linker
  AC-3: maistro.security.outbound
  AC-4: maistro.security.outbound
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Accepted
    date: 2026-09-14
---

# ADR-102: Sibling packages use the central outbound HTTP guard

## Context

The outbound HTTP census found direct `httpx` calls in `maistro-registry`,
`maistro-bootstrap`, and `maistro-evolve`, which did not previously declare a
`maistro-core` dependency. `maistro-rsi` and `maistro-design` already depend on
core, but their direct clients also bypassed ADR-082326-5386's guarded seam.
Vendoring a second SSRF validator into the standalone packages would recreate
the duplicate-control drift that ADR-082326-5386 retired.

The registry linker is the highest-risk case: repository and artifact metadata
can influence documentation URLs. Its request must be restricted to the
GitHub Contents API's HTTPS origin; those inputs may affect only quoted path
segments, never the scheme or host.

## Decision

All five packages use the existing `maistro-core` HTTP seam rather than a
vendored guard:

- `maistro-registry`, `maistro-bootstrap`, and `maistro-evolve` declare
  `maistro-core>=0.9.0` and use `sync_client` or `shared_client`. This is an
  intentional dependency: the security control is centralized, maintained,
  and tested once, while the added dependency is smaller than the risk and
  maintenance cost of a second implementation.
- `maistro-rsi` and `maistro-design` use the same seam already available from
  their existing core dependency.
- Operator-configured origins are registered through the existing exact-origin
  `OutboundPolicy`; the transport still refuses every non-allowlisted private,
  malformed, or unresolvable destination with `OutboundBlockedError`.
- The registry linker pins `https://api.github.com` explicitly and quotes
  owner/repository path segments before any HTTP client is created. It does not
  allow a caller-influenced value to select a scheme or network origin.

No package creates a competing policy, validator, exception type, or transport.
The canonical path remains `Goal -> Graph -> Run -> NodeRun -> Attempt`; this
connectivity decision introduces no execution authority.

## Consequences

The standalone registry, bootstrap, and evolve distributions now install the
central core security seam as a direct dependency. They gain the same policy
updates and `OutboundBlockedError` contract as the engine, at the cost of core's
runtime dependency footprint. A future package that cannot accept that footprint
must propose a new architecture decision; it may not copy the guard silently.

Configured local gateways and daemons remain reachable because only their exact
origins are allowlisted. The registry's public GitHub endpoint is likewise
explicitly pinned, while path data remains untrusted.

## Acceptance criteria

Retrofitted at acceptance from the behaviour this change already shipped, in
the same shape as ADR-082326-5386: each criterion is bound to a test that
proves it, and each anchor names the module that carries the decision's
runtime consequence.

- [x] **AC-1** Every outbound network call in the five sibling packages
  (`maistro-registry`, `maistro-bootstrap`, `maistro-evolve`, `maistro-rsi`,
  `maistro-design`) resolves through the guarded core seam; the sibling census
  reports no direct `httpx` network call in their source trees.
- [x] **AC-2** The registry linker pins the `https://api.github.com` origin and
  quotes owner/repository path segments before any client is created;
  caller-influenced values can never choose the scheme or network origin, and
  the fetch runs on `maistro.http.sync_client`'s guarded transports.
- [x] **AC-3** The dependency choice is recorded here and declared in package
  metadata: `maistro-registry`, `maistro-bootstrap` and `maistro-evolve`
  declare `maistro-core>=0.9.0` rather than vendoring a second guard.
- [x] **AC-4** The repo-wide constructor census covers the sibling source roots
  and reports no unguarded `httpx.Client`/`httpx.AsyncClient` construction in
  production code outside the central seam.
