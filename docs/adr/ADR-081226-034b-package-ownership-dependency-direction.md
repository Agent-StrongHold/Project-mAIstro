---
id: ADR-081226-034b
title: Package Ownership and Dependency Direction
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: Foundation
owners: ['@BlakeMatthews-dev']
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
---

# ADR-081226-034b: Package Ownership and Dependency Direction

## Decision

`maistro-core` is authoritative for reusable product-domain semantics and generic platform mechanisms. Product and specialized packages depend inward on core contracts. Core does not import outward packages to define canonical semantics.

`maistro-server` is an API/transport surface. `hive-conductor` is a product/application surface. Canvas, Design, Turing, RSI and Evolve remain specialized packages that extend canonical Workspace/Graph/Run services rather than owning competing universal lifecycles.

`maistro-bootstrap` owns installation, detection, planning, materialization and environment/provider initialization. User-work execution currently mixed into bootstrap migrates toward canonical Runtime/Binding owners after parity tests.

The current architecture/spec registry is governance tooling. Its semantic target is `maistro-arch-governance`, import `maistro_arch_governance`, CLI `maistro-arch`; the physical rename is deferred to an isolated migration.

Core discovers specialized behavior through public extension contracts. Physical moves and renames follow semantic convergence, compatibility planning and behavior/reachability tests.
