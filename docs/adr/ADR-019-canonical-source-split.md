---
id: ADR-019
title: Canonical Source Split — maistro-engine vs Stronghold
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-06
accepted: 2026-05-06
substrate: []
implements: []
related:
  - maistro-engine#ADR-030
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-06
  - status: Accepted
    date: 2026-05-06
---

# ADR-019: Canonical Source Split — maistro-engine vs Stronghold

**Context:** Three codebases share one Python runtime architecture. Need a rule for where new code lands.

~~Extended by [`engine#ADR-030`](ADR-030-four-repo-governance.md) (Four-Repo Governance)~~ —
**ADR-030 is now Superseded.** The four-repo / templated-peers model was reversed by the
**monorepo consolidation**: this repo *contains* the Conductor + canvas and is *imported* by
downstream products (Stronghold, Canvas book-maker); `Project_mAIstro` and `AgentTuring` were
absorbed here, not kept as separate peers. See `docs/archive/CONSOLIDATION-PLAN.md` and `CLAUDE.md`.

## Decision

`maistro-engine` is the canonical source for all shared Python subsystems. `Agent Stronghold` keeps only its multi-tenant layer.

### Split rule

| Goes in maistro-core (shared) | Goes in Stronghold only |
|-------------------------------|------------------------|
| Protocols (abstract interfaces) | Keycloak integration |
| Agent runtime (base, strategies, factory, roster) | Vaultwarden secrets backend |
| Memory (learnings, episodic, outcomes, scopes) | Postgres + pgvector as mandatory store |
| Security (Warden, Sentinel, gate, PII filter, trust tiers) | Redis caching layer (prompt cache, rate limiter, session store) |
| Classifier (keyword, LLM fallback, complexity, multi-intent) | K8s sandbox lifecycle (deployer, templates, budgets) |
| Router (scorer, selector, filter, scarcity, speed) | Tenant isolation middleware |
| Builders (pipeline, spec emission, verifier, coverage) | Helm charts / K8s manifests |
| A2A (delegation, lifecycle, guest peers) | AKS / cloud deployment configs |
| Skills (marketplace, forge, parser, registry, canary) | Agent pod discovery (multi-tenant) |
| Persistence (PostgreSQL stores) | Entra ID / Azure AD integration |
| Types (config, errors, intent, model, memory, security) | |
| Orchestrator (SuperPlanner, MasterOrchestrator) | |
| Auth (B2B service keys, JWT, middleware) | |
| Events (bus, handlers, recipes, triggers) | |
| Tools (sandbox Docker, git, browser) | |
| Config (settings, loader, model resolver) | |
| Observability (logging, metrics, tracing) | |
| Canvas protocols (CanvasStore, ImageGenClient, Compositor) | |
| Da Vinci agent definition | |

### Products

| Product | What it is | Relationship to maistro-engine |
|---------|-----------|-------------------------------|
| **Agent Conductor** | Household/personal product | Runs maistro-server + maistro-turing. SQLite + age-vault + Tailscale defaults. |
| **Agent Stronghold** | Enterprise/multi-tenant product | `pip install maistro-core` + its own multi-tenant layer. Postgres + Keycloak + Vaultwarden + K8s. |
| **Canvas Studio** | Standalone book builder | `pip install maistro-core` for canvas protocols. Own React app + Express API + P40 image gen server. |
| **Project Turing** | Autonoetic self-model extension | Lives in `maistro-turing` package. |

### Naming convention

- `AgentConfig`, `AgentError` — canonical names in maistro-core
- `MaistroConfig`, `MaistroError`, `StrongholdError` — backwards-compat aliases

### Enforcement

- Stronghold PRs that touch shared subsystems (security, memory, classifier, router, agents, etc.) should go into `maistro-core` first, then Stronghold imports from the released version.
- Stronghold-only code (Keycloak, K8s, Redis, tenant isolation) stays in the Stronghold repo.
- When in doubt, it goes in maistro-core. Multi-tenant concerns are the exception, not the rule.

### Scope vs. tenancy (amended by ADR-068)

The "no `org_id` in core" shorthand conflated **scope** with **tenancy**. Corrected: core
carries the *soft scope axes* `global > org > team > user > agent > session` (a user may be
in multiple teams/orgs); only the **hard `tenant` boundary** — fully segmented, one tenant
per user — is Stronghold-only. So `org`/`team` filters in maistro-core (ADR-013/015/016/017)
are legitimate scope, not tenancy. See ADR-068 for the full hierarchy and how it feeds the
authorization model.

## Consequences

- maistro-engine becomes the single source of truth for the Python runtime
- Stronghold's dependency on maistro-core is explicit (`pip install maistro-core`)
- Canvas Studio can ship independently without pulling in Conductor or Stronghold
- Future products (mobile app, CLI tool, etc.) get the same shared runtime

## Note on the four-repo system

The "Products" framing in this ADR was briefly extended by `engine#ADR-030` to four templated
peers (`Project_mAIstro`, `AgentTuring`, `stronghold`). **That model is Superseded:** the
consolidation made `maistro-engine` a single monorepo that *contains* the Conductor + canvas and
is *imported* by downstream products (Stronghold, Canvas book-maker); `Project_mAIstro` and
`AgentTuring` were absorbed into this repo's `packages/` and `docs/`. Current structure lives in
`CLAUDE.md`, `README.md`, and `docs/archive/CONSOLIDATION-PLAN.md`.
