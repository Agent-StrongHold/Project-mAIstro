---
id: ADR-070426-c4b2
title: CapabilityProfile — per-agent (capability, intent_class) permission, skill, and cost model
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-092
  - maistro-engine#ADR-058
related:
  - maistro-engine#ADR-079
  - maistro-engine#SPEC-184
  - maistro-engine#ADR-068
  - maistro-engine#ADR-093
  - maistro-engine#ADR-088
implements: []
supersedes: []
blocks:
  - maistro-engine#SPEC-278
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-c4b2: CapabilityProfile — per-agent permission/skill/cost model

## Context

An agent today is `AgentIdentity` (`packages/maistro-core/src/maistro/types/agent.py`) — a flat
bag of `tools`, `skills`, `trust_tier`, `priority_tier`, `sub_agents`. That's enough for the
Conduit's classify → route → `agent.handle()` pipeline (`conduit.py:120`) and for the router's
model-level scoring (`quality^(qw*p)/cost^cw`, `router/scorer.py`), but it says nothing about
whether *this agent* is any good at *this kind of task*, or what it actually costs to run — only
whether it is wired up with a tool at all. Two consumers need exactly that finer signal and don't
have it yet:

- **A2A delegation** (ADR-058, `a2a/delegate.py`) decides whether to keep a task local or hand it
  to another agent, but has no per-capability competence signal to decide *which* agent, only
  `AgentCard` metadata and trust tier.
- **A future reasoning router** — self-execute vs. delegate vs. decline — needs, per
  `(capability, intent_class)` pair: is this allowed, is this agent actually good at it for *this*
  kind of request, and what does invoking it cost. None of the three exist as data today; they are
  folded into ad hoc heuristics or simply absent (a light-vs-heavy delegate/decline decision has no
  home; see ADR-070426-77d1).

Model-level routing (ADR-079) already separates quality and cost as scoring inputs, but at the
*model* level — it says nothing about a given *agent's* competence at a given *intent*, which is
a different axis (an agent using a strong model can still be bad at "terse changelog," good at
"long-form prose").

## Decision

### 1. `CapabilityProfile` — three orthogonal dimensions, keyed by `(capability, intent_class)`

```python
@dataclass(frozen=True)
class CostVector:
    """Measured, not estimated. Populated from observed calls, not declared once."""
    standing: dict[str, float] = field(default_factory=dict)   # cpu, mem, replicas_min (heavy agents)
    cold_start_ms: float = 0.0
    per_call_compute: float = 0.0   # normalized compute-seconds
    per_call_tokens: float = 0.0    # input+output tokens, EMA over recent calls
    tool_fees: float = 0.0          # metered third-party API cost, if any
    overhead: float = 0.0           # warden/sentinel/context-build cost attributable to the call

@dataclass(frozen=True)
class SkillScore:
    """Intent-conditional competence, EMA-updated from eval outcomes (SPEC-278)."""
    value: float          # 0.0-10.0
    sample_count: int = 0 # 0 = still the declared prior; never decayed in v1 (see SPEC-278)

class Permission(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class CapabilityEntry:
    capability: str        # e.g. "write_text", "run_shell", "call_agent:ranger"
    intent_class: str      # e.g. "summary", "report", "prose" — "*" for intent-agnostic capabilities
    permission: Permission
    skill: SkillScore
    cost: CostVector

@dataclass(frozen=True)
class CapabilityProfile:
    agent_name: str
    entries: tuple[CapabilityEntry, ...]

    def visible_entries(self) -> tuple[CapabilityEntry, ...]:
        """BLOCKED entries never leave this method — see Decision §3."""
        return tuple(e for e in self.entries if e.permission is Permission.ALLOWED)
```

Full schema, storage protocol, and the EMA updater are SPEC-278's job; this ADR fixes the shape and
the invariants around it.

### 2. The three dimensions answer three different questions, and none is derived from another

- **Permission** ("can you?") — binary, authority-derived. Composes with ADR-068's tiers and
  approver graph and with the taxonomy's agent-call ACLs (ADR-070426-77d1) — this ADR does not
  reimplement authorization, it *consumes* its verdict as one bit per `(capability, intent_class)`.
- **Skill** ("should you?") — continuous 0–10, **intent-conditional**: the same capability can
  score differently per intent class (`{summary: 4, report: 8, prose: 2}`), because competence is
  not a property of the capability alone. Declared once (agent author's prior, in `agent.yaml`),
  then **converges toward empirical reality** via EMA over eval outcomes (SPEC-278) — the profile
  is not a static declaration, it is a prior with a measured trajectory.
- **Cost** ("what does it consume?") — composite and **measured**, not estimated once at authoring
  time: standing cost (container reservation, relevant for heavy agents per the taxonomy ADR),
  cold-start latency, per-call compute and tokens, third-party tool fees, and warden/context-build
  overhead. A cheap-looking agent with high standing cost or a large cold-start penalty is not
  actually cheap for bursty traffic — the vector, not a scalar, is the point.

Collapsing these into one scalar (as a single "confidence" or "cost-adjusted quality" number would)
throws away exactly the information a delegate/self-execute/decline decision needs: an agent can be
permitted, unskilled, and cheap (fine for a low-stakes retry) or permitted, skilled, and expensive
(fine for a high-stakes one-shot) — those are different decisions, and a scalar can't distinguish
them.

### 3. Blocked capabilities are omitted from surfaced options — not masked, not scored zero

`CapabilityProfile.visible_entries()` filters out `Permission.BLOCKED` entries entirely before
anything downstream sees them. A capability the agent isn't allowed to use is not represented as
"skill 0" or "cost infinite" in the surfaced set — it isn't in the set. This closes an injection
surface: a reasoning agent (or an adversarial prompt steering it) never sees a blocked capability
named, described, or scored, so there is nothing to attempt to argue around, socially engineer, or
misinterpret as "technically zero but let's try anyway." This mirrors the existing principle that
Warden-scanned/Sentinel-denied actions don't get explained to the untrusted side of the boundary —
here applied to the option set itself, before an LLM ever reasons over it.

### 4. Consumed by, not implemented as, a reasoning router

This ADR defines the data model. A future reasoning router that reads `CapabilityProfile.entries`
to decide self-execute vs. delegate vs. decline is out of scope here — SPEC-278 stops at schema +
updater + surfacing rules. The router is a separate, follow-on spec once the profile has real data
behind it (chicken-and-egg: you can't design a good router against a profile that's never been
populated from actual outcomes).

### 5. Distinct from SPEC-184's capability slots — different axis entirely

SPEC-184's `CapabilitySlot`/`CapabilityProvider` framework (llm_gateway, web_search, smart_home,
…) answers **"which implementation fills this seam right now"** — install/toggle/swap, with a
fallback policy for when nothing is installed. `CapabilityProfile` answers **"is this agent
permitted, competent, and affordable at this task"** — a per-agent scoring/authorization record,
not an installable/swappable unit. An agent can be built entirely on installed SPEC-184 slots and
still need a `CapabilityProfile` to describe how well it uses them for a given intent; the two are
orthogonal and neither subsumes the other. Do not conflate "provider" with "capability" from this
ADR's perspective — a SPEC-184 provider is infrastructure; a `CapabilityProfile` entry is a claim
about an agent's competence and cost using that infrastructure.

## Alternatives considered

- **Single scalar score per agent.** Rejected — collapses permission/skill/cost into one number,
  losing exactly the distinctions a delegate/self-execute/decline decision needs (§2).
- **Skill score without intent-conditioning.** Rejected — Scribe-at-prose vs. Scribe-at-changelog
  is the whole point; an intent-agnostic skill score is a worse prior than no prior, since it
  actively misleads on the cases where competence varies most.
- **Fold this into SPEC-184's provider metadata.** Rejected — providers are a fill-the-seam
  concern; profiles are a per-agent competence/cost concern. Conflating them would make every
  provider swap also a profile edit, and vice versa, for no shared invariant.
- **Cost as declared config rather than measured telemetry.** Rejected — a declared cost estimate
  drifts from reality the moment traffic patterns or provider pricing change; measuring is the only
  way the vector stays honest, mirroring why skill converges from outcomes rather than staying a
  static prior.
- **Mask blocked capabilities with a score instead of omitting them.** Rejected — see §3; scoring
  a blocked capability still names it to the reasoning surface, which is the injection risk this
  ADR closes.

## Consequences

- New `maistro.capabilities.profile` (or `maistro.agents.profile` — SPEC-278 decides the module
  home) types: `CapabilityProfile`, `CapabilityEntry`, `SkillScore`, `CostVector`, `Permission`.
- `AgentIdentity` gains no new required field from this ADR alone — a profile is looked up by
  `agent_name`, not embedded in the identity record, so existing agents keep working with an
  empty/default profile until SPEC-278's updater has outcomes to work from.
- A2A delegation (ADR-058) and the taxonomy's light-agent delegate path (ADR-070426-77d1) become
  the first two consumers once a router exists to read profiles; this ADR does not wire either
  consumer, it makes the data available to be wired.
- Establishes a pattern maistro-evolve (ADR-088) can plausibly reuse: skill score's EMA-from-
  outcomes shape is structurally similar to fitness update across generations, though this ADR
  does not couple the two — evolve's genome fitness stays evolve-scoped unless a follow-up spec
  says otherwise.
- Stronghold (ADR-019, ADR-068) inherits `CapabilityProfile` as-is; per-org profile isolation, if
  ever needed, is a Stronghold-layer scoping concern, not a change to the schema itself.

## Non-goals

- Implementing the reasoning router that consumes profiles (§4) — future work.
- Skill-score decay in the absence of outcomes — SPEC-278 fixes this at "no decay in v1"; a decay
  policy is a follow-up once there's production evidence to justify one (per the constant-
  tunability ladder, ADR-062226-674b).
- Replacing or subsuming SPEC-184's slot/provider framework (§5).
- Defining new permission semantics — permission here is a read of ADR-068's/the taxonomy's
  authorization verdict, not a new authorization mechanism.

## References

- [ADR-092: Capability-vs-control posture](ADR-092-capability-vs-control-posture.md)
- [ADR-058: A2A delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [ADR-079: LLM provider/model registry, routing, and embeddings](ADR-079-model-registry-routing-embeddings.md)
- [SPEC-184: Modular capability platform](../specs/SPEC-184-modular-capability-platform.md)
- [ADR-068: Unified authorization and elevation](ADR-068-unified-authorization-and-elevation.md)
- [ADR-093: Sandbox isolation model](ADR-093-sandbox-isolation-model.md)
- [ADR-088: maistro-evolve — experimental genome optimiser](ADR-088-maistro-evolve-experimental.md)
- [ADR-070426-77d1: Substrate/tool/agent taxonomy](ADR-070426-77d1-substrate-tool-agent-taxonomy.md)
- [SPEC-278: CapabilityProfile schema and updater](../specs/SPEC-278-capability-profile-schema-and-updater.md)
- Seams: `types/agent.py` (`AgentIdentity`), `conduit.py:120`, `router/scorer.py`, `a2a/delegate.py`,
  `capabilities/types.py` (`FallbackPolicy`, `SlotSpec` — the SPEC-184 shape this ADR is distinct
  from)
