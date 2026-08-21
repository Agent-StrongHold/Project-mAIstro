---
id: ADR-035
title: Catalog Ownership Split — Engine Simple, Stronghold Multi-Tenant
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-009
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-030
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-035: Catalog Ownership Split — Engine Simple, Stronghold Multi-Tenant

## Context

Catalogs (agents, skills, tools, recipes, MCP servers) are currently described in three places:

- `maistro-engine` ADR-006 (recipe-registry), ADR-009 (spawner)
- `AgentTuring` (mirrored in `stronghold`) `ADR-K8S-021` (tool-catalog), `ADR-K8S-022` (skill-catalog), `ADR-K8S-023` (resource-catalog), `ADR-K8S-027` (agent-catalog)
- `Project_mAIstro` `S-005` (agent-factory), `S-138` (agent-conductor)

The `K8S-*` catalog ADRs describe multi-tenant catalogs, but they live in `AgentTuring` — a product whose dominant constraint is continuity of self, not multi-tenancy.

## Decision

### 1. Two-tier catalog ownership

**Engine ships the simple form.** This is what `Project_mAIstro` and `AgentTuring` consume directly.

- Single in-process catalog
- Recipe registry (ADR-006)
- Spawner (ADR-009)
- No tenancy, no per-tenant access control, no namespace scoping

**`stronghold` owns the multi-tenant variant.** This extends the engine's simple form, it does not replace it.

- Tenant-scoped namespacing
- Per-tenant access policies (Casbin / OPA — see stronghold's policy-engine ADR)
- Cross-tenant catalog imports (with explicit tenant approval)
- Audit on every catalog mutation

The multi-tenant catalog is implemented as a wrapper that holds one engine simple-catalog instance per tenant plus the policy / audit layer above.

### 2. Migration

| Source artifact | Disposition |
|---|---|
| `AgentTuring/ADR-K8S-021 tool-catalog` | Move to `stronghold/docs/adr/`, renumber, set `substrate: [maistro-engine#ADR-006]`, scope reduced to multi-tenant additions only |
| `AgentTuring/ADR-K8S-022 skill-catalog` | Same |
| `AgentTuring/ADR-K8S-023 resource-catalog` | Same |
| `AgentTuring/ADR-K8S-027 agent-catalog` | Same; explicitly defines tenant-scoped agent visibility |
| `Project_mAIstro/S-005 agent-factory` | Recast as `substrate: [maistro-engine#ADR-009]` — factory is the user-facing wrapper over engine spawner |
| `Project_mAIstro/S-138 agent-conductor` | Recast as `substrate: [maistro-engine#ADR-005, maistro-engine#ADR-006, maistro-engine#ADR-009]` — conductor wires existing engine pieces |

### 3. Implication for AgentTuring

Turing has *no* multi-tenant catalog. It uses the engine's simple in-process form. Its agent / skill / tool catalogs are the engine's. Any Turing-specific extensions are autonoetic (e.g. a "self-talk-target" agent is a regular engine agent registered into the simple catalog).

The catalog ADRs leaving AgentTuring is the first concrete step toward AgentTuring's ADR set being focused on autonoesis only.

### 4. Cross-product portability

The two-tier split makes cross-product agent portability possible: an agent registered in `Project_mAIstro`'s simple catalog can be exported and imported into `stronghold`'s tenant catalog without recoding the agent itself. Only the catalog wrapper changes. The agent serialisation format is left to a separate engine ADR.

## Consequences

- The four `K8S-*` catalog ADRs leave `AgentTuring` permanently. AgentTuring's autonoetic ADR set becomes much smaller and more focused.
- Engine's simple catalog must remain fit for purpose for two of the three products. Multi-tenant features cannot leak into the engine simple form — they belong in stronghold's wrapper.
- Cross-product agent portability becomes a real possibility. This unlocks future scenarios (e.g. moving a household agent into an enterprise tenant, or running a Turing-trained agent as a stronghold tenant tool).

## Out of scope

- Stronghold's multi-tenant policy engine choice (OPA vs Cedar vs Sentinel) — separate stronghold ADR.
- Cross-product agent serialisation format — separate engine ADR.
- Catalog discovery semantics for offline / air-gapped deployments — separate engine ADR if needed.
