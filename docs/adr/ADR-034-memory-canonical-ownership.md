---
id: ADR-034
title: Memory Canonical Ownership
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-013
  - maistro-engine#ADR-014
  - maistro-engine#ADR-015
  - maistro-engine#ADR-016
  - maistro-engine#ADR-017
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-030
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-034: Memory Canonical Ownership

## Context

Memory architecture is currently described in three places:

- `maistro-engine` ADRs 011–017 (engine, types, protocols, learning store, episodic store, outcome store)
- `AgentTuring` `turing-dossier`, `turing-memory-consolidator`, `turing-notebook-live-vault`, `turing-obsidian-store`, and `epic-12-memory-v2`
- `Project_mAIstro` `S-008` (session-summarisation), `S-009` (episodic-memory-bridge), `S-032` (episodic-memory), `S-033` (memory-evolution)

Three teams describing overlapping memory subsystems is the highest drift risk in the four-repo system. The inventory (`docs/INVENTORY-ADRS-SPECS.md`) flagged this explicitly.

## Decision

### 1. Canonical owner

`maistro-engine` is the canonical owner of memory architecture. ADRs 011–017 define:

- **Stores** — learning, episodic, outcome, session
- **Types** — memory record, scope, decay function
- **Protocols** — `MemoryStore`, `EpisodicStore`, `OutcomeStore`, `LearningStore`
- **Persistence** — pgvector + Postgres via SQLAlchemy async

No product redefines these. Architectural changes to memory happen in engine ADRs.

### 2. Product specs become parameterisations

Product memory specs do not redefine architecture. They specify:

1. **Tenancy / scoping** — per-user (`Project_mAIstro`), continuous-singleton (`AgentTuring`), tenant-isolated (`stronghold`)
2. **UX / surface area** — what the user sees (Turing's dossier, mAIstro's profile, stronghold's audit view)
3. **Product-specific stores** — Turing's `obsidian-store` is a product-specific *adapter* over engine's `MemoryStore` protocol, not a redefinition of the protocol

Every product memory spec MUST have `substrate:` cross-refs to the engine ADRs it parameterises. Specs without `substrate:` cross-refs are migration debt and are flagged as `gap-spec` in the inventory.

### 3. Migration

| Product spec | Treatment |
|---|---|
| `AgentTuring/turing-dossier` | Recast as `substrate: [maistro-engine#ADR-016]` — dossier is the autonoetic UX over episodic memory |
| `AgentTuring/turing-memory-consolidator` | Recast as `substrate: [maistro-engine#ADR-016, maistro-engine#ADR-017]` — consolidator is the autonoetic-loop-driven decay/promotion job |
| `AgentTuring/turing-notebook-live-vault` | Recast as `substrate: [maistro-engine#ADR-011]` — vault is a Turing-specific store implementing `MemoryStore` |
| `AgentTuring/turing-obsidian-store` | Recast as `substrate: [maistro-engine#ADR-014]` — Obsidian backing implementing memory protocols |
| `AgentTuring/epic-12-memory-v2` (stub) | Promote to engine ADR if it changes the architecture; otherwise close as duplicate |
| `Project_mAIstro/S-008 session-summarization` | Recast as `substrate: [maistro-engine#ADR-018]` (task-record-persistence) |
| `Project_mAIstro/S-009 episodic-memory-bridge` | Recast as `substrate: [maistro-engine#ADR-016]` |
| `Project_mAIstro/S-032 episodic-memory` | Recast as `substrate: [maistro-engine#ADR-016]` |
| `Project_mAIstro/S-033 memory-evolution` | Recast as `substrate: [maistro-engine#ADR-017]` |

### 4. Memory v2

If a product needs memory architecture that engine ADRs 011–017 don't support, the path is:

1. Open an engine ADR proposing the change
2. Engine ADR is accepted (possibly superseding 011–017 or part of them)
3. Product spec then `substrate:`-cites the new engine ADR

Products do not silently extend the memory model.

## Consequences

- Three-way drift becomes detectable. Any product memory spec without `substrate:` is a CI warning during the rollout window and a hard failure after (per ADR-031).
- Turing's autonoetic memory is no longer architecturally distinct — it is the engine's memory, scoped to a continuous-singleton, with autonoetic-specific *adapters* and *jobs* on top.
- mAIstro's memory specs become much shorter (they describe per-user scoping, not memory itself).
- A future memory-v2 in engine that breaks the protocols requires explicit downstream migration in each product. The cost is visible.

## Out of scope

- Memory-v2 design — separate engine ADR if proposed.
- Backup / export semantics — separate engine ADR.
- Per-product retention policies — product specs.
