---
id: ADR-061
title: "maistro-design — composable design skills + design systems package"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-29
substrate:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-041
related:
  - maistro-engine#ADR-033
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
ac-modules:
  AC-1: maistro_design.trust
  AC-2: maistro_design.trust
  AC-3: maistro_design.skills.registry
  AC-4: maistro_design.engine
  AC-5: maistro_design.engine
  AC-6: maistro_design.engine
  AC-7: maistro_design.nodes
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Implemented
---

# ADR-061 — maistro-design: composable design skills + design systems

## Context

`maistro-canvas` provides pixel-level composition primitives (layers, PIL compositor,
image generation). It has no concept of *design intent* — what kind of artifact to
create, what brand vocabulary to apply, or how to gather structured input before
generating. This gap produces costly redirect loops: the agent generates something,
the user says "wrong style", the agent regenerates.

`open-design` (nexu-io/open-design) solves this with two primitives:

1. **Skills** — atomic design capabilities, each with a discovery form that must be
   completed before generation. Structured upfront input eliminates redirect loops.
2. **Design Systems** — portable brand/style specifications (DESIGN.md + tokens.css +
   manifest.json) that ground every generation in a consistent visual vocabulary.

`maistro-design` brings these primitives into the maistro runtime, backed by the
engine's security (Warden), trust model, DAG node registry, and A2A delegation.

## Decision

### 1. Separate package, not an extension of canvas

`maistro-design` is a new package that depends on `maistro-core` and `maistro-canvas`.
Canvas remains a pure pixel compositor. Design is the skill/system/workflow layer above it.

### 2. DesignEngine builds artifacts; it does not call an LLM directly

The engine builds a prompt stack and creates canvas/A2A artifacts. The caller routes
the prompt stack to the maistro-core conduit/orchestrator. This preserves the
protocol-driven DI philosophy: no concrete LLM client dependency inside the package.

### 3. Trust contamination is per-session, monotonically decreasing

`TrustTier` ordering: `t0 > t1 > t2 > t3 > skull`.
One `DesignEngine` instance per session. `context_trust_tier` starts at `t0` and can
only decrease as components (skill, design system, discovery responses) are evaluated.
Discovery responses are always `t3` by default (untrusted user input).

### 4. All user input flows through Warden; decisions are async

Every discovery response is scanned by Warden before trust tier assignment. The engine
proceeds immediately at the assigned tier (non-blocking). A `TrustReviewRecord` is
queued for async admin review. Admin decides: keep / upgrade / improve+upgrade / banish.

### 5. RLPHD feedback loop

Admin decisions are the human preference signal for Warden's trust policy
(**RLPHD** — Reinforcement Learning for Policy via Human Decisions, pronounced
"Ralphed"). Banished patterns feed into `TrustBanishList` and auto-block future
similar content. Each upgrade teaches Warden what clears the bar.

### 6. Engine registers as a DAG node

`DesignOrchestrateNode` registers under kind `"design.orchestrate"` via
`@register_node`. This makes design workflows composable inside any maistro DAG.

## Acceptance criteria

```gherkin
@AC-1
Scenario: TrustTier.min() is monotonically decreasing
  Given TrustTier.T0
  When min(T2) is applied then min(T0) is applied
  Then result is T2

@AC-2
Scenario: skull is always the lowest tier
  Given any TrustTier value
  When min(SKULL) is applied
  Then result is SKULL

@AC-3
Scenario: t0 built-in skill cannot be overwritten by t2 install
  Given a registry containing "login-flow" at trust_tier=T0
  When DesignSkill(slug="login-flow", trust_tier=T2) is registered
  Then registry still holds the original T0 skill

@AC-4
Scenario: Discovery response contaminates engine context to t3
  Given a DesignEngine with context_trust_tier=T0
  When generate() is called with a DiscoveryResult (trust_tier=T3)
  Then engine.context_trust_tier == T3
  And DesignProject.trust_tier == T3

@AC-5
Scenario: Warden-blocked content raises TrustBannedError
  Given a banish list containing pattern "rm -rf"
  When a discovery response containing "rm -rf" is submitted
  Then TrustBannedError is raised

@AC-6
Scenario: Image-mode skill without image_gen raises SkillModeError
  Given a DesignEngine with image_gen=None
  When generate() is called for a skill with mode=IMAGE
  Then SkillModeError is raised

@AC-7
Scenario: DesignOrchestrateNode is registered in the DAG registry
  When the maistro_design.nodes module is imported
  Then "design.orchestrate" is present in the node registry
```

## Consequences

**Positive:**
- Discovery forms eliminate redirect loops for all downstream products.
- Design systems decouple brand vocabulary from skill logic — systems are portable DESIGN.md files.
- RLPHD trust loop continuously tightens Warden's policy from real admin signal.
- DAG node registration lets design workflows compose with any maistro graph.

**Negative:**
- Adding a Warden scan per discovery field adds latency to the generation path.
- Admin review queue requires UI surface (not in scope for this ADR).
- No bundled design systems — callers must register their own.

## Out of scope

- Admin panel UI for trust review decisions.
- Mutmut configuration (deferred to ADR-033 template rollout).
- LLM call inside the engine (caller's responsibility).
- ~~Bundled design systems (registry + loader infrastructure only).~~ Addressed by
  ADR-100: a Tier-1 bundled set (`load_bundled()`, `T1`) plus a Tier-2 one-click
  catalog (`import_from_catalog()`, `T2`), both sourced from Open Design's
  Apache-2.0 `design-systems/` corpus behind a content scan.
- Cross-tenant design system sharing (Stronghold concern).
