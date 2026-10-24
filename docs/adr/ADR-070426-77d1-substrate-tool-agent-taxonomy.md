---
id: ADR-070426-77d1
title: Substrate/tool/agent taxonomy — light and heavy agent kinds
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-092
  - maistro-engine#ADR-070426-c4b2
  - maistro-engine#ADR-093
related:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-058
  - maistro-engine#SPEC-184
  - maistro-engine#ADR-088
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-77d1: Substrate/tool/agent taxonomy

## Context

Today every agent is the same shape: `AgentIdentity` (`types/agent.py`) carries a `tools` tuple
and a `trust_tier`, and `agents/factory.py` loads it without distinguishing *what kind* of thing an
agent is allowed to touch. In practice, agents fall into two very different roles — some exist
purely to reason and delegate (an Arbiter-shaped triage agent that calls other agents and never
touches a side effect directly), others exist to actually do something with side effects (write a
file, call an API, run a shell command). Nothing in the schema or the factory enforces this split;
a "reasoning-only" agent could accumulate a `file_write` tool over time with no structural
objection, and the only thing standing between "agent that only delegates" and "agent that can
also, incidentally, write to disk" is agent-author discipline.

This matters for the same reason ADR-092 states the control posture explicitly: **the constraint
is the product.** A security auditor's job of answering "where does every side effect in this
system originate" is currently a full-repository grep for tool registrations, not a structural
guarantee. ADR-070426-c4b2's `CapabilityProfile` needs a place to put "this agent has zero tools,
period" as a *verifiable* fact rather than an observed one, and ADR-093's sandbox isolation model
needs to know which agents actually need a container versus which are pure prompt+delegate
compositions that never should.

## Decision

### 1. Three tiers: substrate, tools, agents

- **Substrate** — LLM inference plus deterministic pure utilities (current time, UUID generation,
  hashing, in-memory formatting). Available to **every** agent, unconditionally, with **no
  permission check**. Substrate is the fabric agents reason within, not a resource they're granted
  — gating `get_current_time()` behind a tool-permission check would force a reasoning-only agent
  to delegate for trivia, which is pure overhead with no security benefit (nothing here can have a
  side effect by construction — see §3).
- **Tools** — permissioned, side-effecting capabilities (file I/O, network calls, process spawn,
  external API calls). Only **heavy** agents may hold tools (§2). Every tool call is exactly the
  kind of "untrusted action at a trust boundary" ADR-068's authorization and Sentinel's policy
  evaluation already exist for; this ADR does not change that enforcement, it changes *who is
  structurally eligible to attempt it*.
- **Agents** — callable units. Any agent, light or heavy, may call another agent it's permitted to
  call (the agent-call ACL is a separate, existing concern — this ADR only fixes *which agents may
  hold tools*, not who may call whom).

### 2. `kind: light | heavy` on `AgentIdentity`

```python
class AgentKind(StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"

@dataclass(frozen=True)
class AgentIdentity:
    ...
    kind: AgentKind = AgentKind.HEAVY   # default preserves every existing agent's behavior
```

- **Light agents structurally hold zero tools.** Not "zero tools by convention" — the factory
  (`agents/factory.py`) rejects loading any `agent.yaml` with `kind: light` and a non-empty `tools`
  list, and the runtime registration path rejects any attempt to attach a tool to an
  already-loaded light agent. This is what makes the security boundary **trivially verifiable**: to
  confirm a light agent cannot smuggle a side effect through minimal tool access, a security auditor
  checks one field — `tools == ()` — instead of auditing every tool's blast radius for
  under-the-radar misuse. A light agent that needs a side effect **calls a heavy agent** that has
  the tool; it never grows the tool itself.
- **Heavy agents declare container/tool/scaling profile.** A heavy agent's `CapabilityProfile`
  (ADR-070426-c4b2) cost vector's `standing` dimension is exactly its container reservation (cpu,
  mem, replicas_min/max) — the taxonomy and the profile share this data point on purpose, so
  deployment topology planning (which agents need a pod, which don't) and cost attribution read
  from the same source.
- **Legacy defaults to heavy.** Every `agent.yaml` written before this ADR has no `kind` field;
  the factory defaults missing `kind` to `AgentKind.HEAVY`, so no existing agent's tool access
  changes on upgrade. Light is opt-in, chosen deliberately at authoring time for agents that are
  genuinely orchestration-only (Arbiter-shaped triage/delegation compositions).

### 3. Substrate-purity validation at registration

A substrate utility registry (new, alongside the existing `ToolRegistry` protocol,
`protocols/tools.py:26-44`) validates every candidate at *registration* time, not at call time:

- Static/runtime checks reject registration if the callable performs network I/O, file I/O, or
  process spawning — these are, by definition, side effects, and a side-effecting function is a
  **tool**, never substrate, no matter how small or "basically free" it looks (an HTTP call to a
  geocoding API is exactly as rejected as a call to `subprocess.run` — network I/O is still I/O).
- This is a **registration-time gate**, mirroring the same "validate before it can reach `active`"
  discipline SPEC-184 already applies to capability providers and ADR-083 applies to skills — the
  cost of getting this wrong is paid once, at the point someone tries to add a new substrate
  utility, not repeatedly at every call.
- A substrate utility that later needs a side effect does not get "upgraded in place" — it is
  re-registered as a tool, on a heavy agent, same as any other tool. Substrate and tool are not
  points on a spectrum an entry can slide along; they are disjoint categories decided once, at
  registration.

### 4. Relationship to existing mechanisms

- **Not a replacement for trust tiers (ADR-068) or Warden/Sentinel.** `kind` answers "can this
  agent structurally hold a tool at all"; trust tier and Sentinel policy answer "which specific
  tool calls does this particular heavy agent's specific trust tier permit, right now." A light
  agent needs no additional trust-tier reasoning for tools it structurally cannot have; a heavy
  agent still goes through the full existing authorization path for every tool call it makes.
- **Composes with A2A (ADR-058).** A light agent delegating to a heavy agent for a side effect is
  the same delegation primitive A2A already defines (`A2ATask`, `a2a/delegate.py`) — this ADR adds
  no new delegation mechanism, it gives A2A delegation a structural reason to exist for a whole
  class of agents (light agents *always* delegate for side effects, never occasionally).
- **Feeds ADR-070426-c4b2's `CapabilityProfile`.** A light agent's profile has an always-empty
  tool-cost surface by construction — its `entries` for any tool-shaped capability are simply
  absent (not present-and-BLOCKED, genuinely absent, since the agent cannot register one). Its
  `agents` dimension reflects whatever it's permitted to call. This is a stronger, structural
  version of the profile's "blocked capabilities omitted" rule (ADR-070426-c4b2 §3) — for a light
  agent, there is nothing to block because there is nothing to have.
- **Sandbox isolation (ADR-093) applies to heavy agents' tool execution**, not to light agents —
  a light agent that never runs a tool has nothing that needs hardware-VM isolation; this narrows
  which agents actually need the sandbox boundary at all, which is useful input to ADR-093's own
  deployment-cost tradeoffs (not re-litigated here).
- **maistro-evolve (ADR-088) mutates agent genomes**; `kind` becomes one more field a genome
  mutation could touch. This ADR does not decide whether evolve is allowed to flip `kind` on a
  mutated candidate — that's an evolve-scoped guard rail, tracked as an open question below, not
  decided here.

## Alternatives considered

- **Trust-tier-only enforcement (no `kind` field).** Rejected — trust tier already answers "which
  tools may this agent use," not "may this agent have tools at all." Overloading trust tier to also
  mean "structurally toolless" would make trust tier do two jobs and make the toolless guarantee
  depend on tier *assignment* discipline rather than a schema-level structural fact.
- **Runtime-only tool-attachment check (no registration-time substrate-purity gate).** Rejected —
  a call-time-only check means an impure "substrate" utility could sit unregistered-as-a-tool for
  a long time before its first side-effecting call is ever exercised in a test, which is exactly
  the kind of latent risk a registration-time gate is meant to close early.
- **Let light agents keep a small, "safe" tool allowlist (e.g., read-only tools).** Rejected — this
  reintroduces the audit burden this ADR exists to remove: "structurally zero tools" is trivially
  verifiable; "zero tools except this allowlisted safe set" requires re-auditing the allowlist every
  time a new "obviously safe" tool is proposed for it. Zero is a much easier invariant to keep true.
- **Make `kind` a continuum or additional tiers beyond light/heavy.** Rejected for v1 — the
  Hyperagents precedent (`EV-HYPERAGENTS-01`) that motivates this taxonomy is a two-tier split
  (meta-agent vs. task-agent); a richer tier system is more speculative complexity than the current
  evidence supports, and can be added later without breaking the light/heavy boundary (a new tier
  would sit alongside, not replace, "does this agent have zero tools").

## Consequences

- `AgentIdentity.kind: AgentKind = AgentKind.HEAVY` — additive, backward compatible; no existing
  `agent.yaml` needs edits.
- `agents/factory.py` gains a validation step: `kind: light` + non-empty `tools` is a load-time
  `ConfigError`, not a silent acceptance.
- New `maistro.capabilities.substrate` (or `maistro.tools.substrate` — implementation spec
  decides the module home) registry with registration-time purity validation, distinct from
  `ToolRegistry`.
- Security audits of "where can side effects originate" become a structural grep (`kind: heavy`
  agents with non-empty `tools`) instead of a full behavioral review of every agent.
- Stronghold (ADR-019, ADR-068) inherits `kind` as-is; it may add stricter enforcement (e.g.,
  refusing to deploy a `kind: heavy` agent without a declared container spec) as part of its own
  posture, without needing a different taxonomy.

## Non-goals

- Deciding whether maistro-evolve may mutate an agent's `kind` field during genome evolution — an
  evolve-scoped open question, not resolved here.
- A richer-than-two-tier kind system (e.g., a "read-only tools" middle tier) — see Alternatives.
- Runtime promotion of a light agent to heavy, or vice versa — `kind` is fixed at authoring time in
  this ADR; a promotion path, if ever needed, is a follow-up spec with its own audit-trail
  requirements (a light-to-heavy promotion is exactly the kind of change a security auditor needs
  to see happen, not infer after the fact).
- Redefining trust tiers, Sentinel policy, or the sandbox boundary — this ADR narrows *who is
  eligible to reach* those mechanisms, it does not change what they do once reached.

## Open questions

- Can maistro-evolve (ADR-088) mutate `kind` on a candidate genome, and if so, does a light→heavy
  flip require the same review gate as any other capability-granting mutation?
- Does the substrate-purity validator need an explicit allowlist for utilities that look
  side-effecting but are actually safe (e.g., reading a value from an in-process cache) — or is
  "in-process, no I/O boundary crossed" already a sufficient, mechanically-checkable rule?

## References

- [ADR-092: Capability-vs-control posture](ADR-092-capability-vs-control-posture.md)
- [ADR-070426-c4b2: CapabilityProfile](ADR-070426-c4b2-capability-profile.md)
- [ADR-093: Sandbox isolation model](ADR-093-sandbox-isolation-model.md)
- [ADR-068: Unified authorization and elevation](ADR-068-unified-authorization-and-elevation.md)
- [ADR-058: A2A delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [SPEC-184: Modular capability platform](../specs/SPEC-184-modular-capability-platform.md)
- [ADR-088: maistro-evolve — experimental genome optimiser](ADR-088-maistro-evolve-experimental.md)
- Seams: `types/agent.py` (`AgentIdentity`), `agents/factory.py`, `protocols/tools.py:26-44`,
  `capabilities/types.py`, `a2a/delegate.py`
