---
id: SPEC-276
title: "Adapter port and protocol ownership classification"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-264
  - maistro-engine#SPEC-271
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-276: Adapter Port Ownership

## Finding addressed

Dead-code scanning reported protocol and adapter classes such as task backends, telemetry ports, and middleware seams. The currently scanned adapter seams are now classified as intentional public/internal extension points with package exports, docstrings, and smoke tests. Future vulture-reported adapter seams should follow the same classify-or-delete rule.

## Design

1. Inventory every newly vulture-reported protocol, adapter, middleware, and port class.
2. Classify each as public extension point, internal seam with tests, planned implementation, or removable dead code.
3. For public extension points, ensure the symbol is exported intentionally and has a docstring describing the contract.
4. For internal seams, add a smoke test or integration fixture proving the seam is exercised.
5. Delete stale abstractions rather than allowlisting them indefinitely.

## Acceptance criteria

- [x] Every currently scanned port/protocol class has an owner and classification.
- [x] Public extension points have docstrings and stable exports.
- [x] Internal seams have at least one test exercising the adapter boundary.
- [ ] Planned implementations have linked specs or issues.
- [ ] Removable dead code is deleted before the vulture baseline becomes blocking.
