---
id: ADR-030
title: Four-Repo Governance — Substrate + Three Templated Products
repo: maistro-engine
kind: adr
status: Superseded
created: 2026-05-07
accepted: 2026-05-07
substrate: [maistro-engine#ADR-019]
implements: []
related:
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-033
  - maistro-engine#ADR-034
  - maistro-engine#ADR-035
supersedes: []
superseded-by:
  - maistro-engine#ADR-019
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
  - status: Superseded
    date: 2026-05-07
---

# ADR-030: Four-Repo Governance — Substrate + Three Templated Products

> **⚠️ SUPERSEDED (2026-05-30) by the monorepo consolidation.** The four-repo / templated-peers
> model below is **no longer current**. `maistro-engine` is now a single **consolidation
> monorepo** that *contains* the Agent Conductor app (`packages/hive-conductor`) and the canvas
> ability (`packages/maistro-canvas`); **Stronghold** and the **Canvas book-maker POC** are
> downstream products that *import* the engine. `Project_mAIstro` and `AgentTuring` were absorbed
> into this repo (their substance lives in `packages/` and `docs/`), not maintained as separate
> templated peers. See `docs/archive/CONSOLIDATION-PLAN.md`, ADR-019, and `CLAUDE.md` for the current
> structure. This ADR is retained as historical record; do not cite it as the live model.

## Context

Four repositories share an architecture but have drifted in shape and purpose:

- `BlakeMatthews-dev/maistro-engine` — Python runtime library (the substrate)
- `BlakeMatthews-dev/Project_mAIstro` — single-tenant secure multi-user product (91 numbered specs)
- `BlakeMatthews-dev/AgentTuring` — autonoetic / self-aware experimental agent
- `agent-stronghold/stronghold` — enterprise multi-tenant variant

Today `AgentTuring` and `stronghold` are blob-identical at the spec/ADR level (mirror fork). Memory architecture is described in three places. Enterprise Kubernetes deployment ADRs (`ADR-K8S-*`) live in `AgentTuring` even though they describe stronghold's mission. ADR-019 established `maistro-engine` as the canonical source for shared Python subsystems but did not specify the relationship between the three downstream products.

## Decision

### 1. Roles and dominant constraints

| Repo | Role | Dominant constraint |
|---|---|---|
| `maistro-engine` | Substrate library + canonical ADRs + registry CI host | n/a — it is the substrate |
| `Project_mAIstro` | Single-tenant secure multi-user product | **Ease of self-hosting** |
| `AgentTuring` | Autonoetic experimental agent | **Continuity of self** |
| `stronghold` | Multi-tenant enterprise product | **Multi-tenant isolation** |

READMEs and ROADMAPs for the three products are framed by their dominant constraint. Features that don't serve the dominant constraint are deferred or rejected.

### 2. Substrate–product relationship

All three products are **Copier-templated peers** rebasing from templates owned by `maistro-engine` (see ADR-033). They are equal peers, not a hierarchy.

The substrate (`maistro-engine`) owns:

- The Python runtime library
- The canonical ADRs (memory, catalog, orchestration, security, etc.)
- The registry CI tooling (front-matter validator, link checker, registry generator — see ADR-031)
- The Copier templates that scaffold the three products (ADR-033)

Each product owns:

- Product-specific specs (`<repo>#SPEC-NNN`) that parameterise engine ADRs via `substrate:` cross-refs
- Product-specific ADRs only for decisions that are genuinely local (e.g., stronghold's K8s deployment topology)
- Its own README and ROADMAP framed by its dominant constraint

### 3. Autonoetic loop is Turing-only

The continuous self-aware processing loop (mood, HEXACO drives, dream loop, self-talk, dossier, memory consolidator) is the defining experimental mission of `AgentTuring`. `Project_mAIstro` and `stronghold` explicitly **do not** run an autonoetic loop. This is a hard product boundary, not a feature flag.

### 4. K8S-* ADRs migrate to stronghold

The 31 `ADR-K8S-*` records currently in `AgentTuring/docs/adr/` describe enterprise multi-tenant Kubernetes deployment topology. They migrate to `stronghold/docs/adr/` and are renumbered to the unified scheme on touch (see ADR-031).

### 5. v1.0 dominant-constraint MVPs (3-month horizon)

| Product | v1.0 = |
|---|---|
| `Project_mAIstro` | Multi-user with hard per-user isolation + setup wizard (`Project_mAIstro#SPEC-139`) |
| `AgentTuring` | Self-consistency-as-tests — autonoesis is *measurable* via property tests asserting "the same self that started the run finishes it" |
| `stronghold` | Compliance-first — on-prem + cloud, OPA/Cedar policy authoring, OWASP Agentic Top 10 mapping shipped |

v2.0 (12-month horizon) drains the existing inventory of accepted ADRs and specs.

### 6. Per-repo branching

Each repo keeps `main` as the integration branch. Active work happens on `claude/<topic>-<slug>` branches (see ADR-001). Cross-repo coordinated work uses the same branch name across repos when feasible.

## Consequences

- `AgentTuring` and `stronghold` stop being mirrors. Each evolves through the engine template (`copier update`).
- The "ADR in the wrong repo" problem becomes detectable: any ADR whose `layer:` is enterprise/multi-tenant but whose `repo:` is `AgentTuring` is an inventory bug.
- `Project_mAIstro` having zero ADRs is acceptable so long as its specs `substrate:`-cite engine ADRs for architectural choices.
- The substrate becomes a coordination point: changes that affect all three products must land in engine first, then ripple via `copier update`. ADR-033 covers the template update workflow.

## Supersedure

Extends ADR-019 (canonical-source-split). ADR-019 remains correct on the `maistro-core` vs `Stronghold` split rule; this ADR adds `AgentTuring` and `Project_mAIstro` to the picture and formalises the templated-product relationship.

## Out of scope

- Front-matter schema and registry CI — ADR-031.
- Acceptance-criteria contract layers — ADR-032.
- Copier template mechanics — ADR-033.
- Memory and catalog ownership specifics — ADR-034 and ADR-035.
