---
id: ADR-061526-f383
title: Foreign harness adapters, hierarchical orchestration, and agent/skill portability
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-06-15
substrate:
  - maistro-engine#ADR-058
  - maistro-engine#ADR-062
  - maistro-engine#SPEC-184
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-068
  - maistro-engine#ADR-083
  - maistro-engine#ADR-085
  - maistro-engine#ADR-086
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
    date: 2026-06-15
---

# ADR-061526-f383: Foreign harness adapters, hierarchical orchestration, and agent/skill portability

> Renumbered from `ADR-100` (2026-06-20): that ID collided with `ADR-100-bundled-open-design-systems.md`,
> assigned in a concurrent PR. See `ADR-062026-9b30-date-based-adr-spec-ids.md` for why new IDs are now
> date-based instead of sequential.

## Context

maistro-core's agent runtime is built around the assumption that agents run *on* the maistro
runtime: an agent is data (rows + YAML, `maistro.agents`), and the `Conduit` dispatches every
request to `agent.handle(...)` (`packages/maistro-core/src/maistro/conduit.py:120`). Two existing
mechanisms extend this runtime outward:

- **ADR-058 (A2A delegation protocol)** lets one maistro/Conductor instance delegate a *task* to
  another — either a local `AgentCard` (in-process) or a federated peer reached over HTTP
  (`packages/maistro-core/src/maistro/a2a/guest_peers.py`, `GuestPeerManager.delegate()`). Both
  ends speak the A2A protocol — `A2ATask`, `DelegationMode`, `TaskStatus`
  (`packages/maistro-core/src/maistro/a2a/delegate.py`).
- **SPEC-184 (modular capability platform)** lets any capability — tool, integration, MCP bridge,
  LLM provider — be installed, toggled, and swapped behind a typed `Protocol`, registered in the
  `CapabilityRegistry` (`packages/maistro-core/src/maistro/capabilities/registry.py`) with a
  declared `FallbackPolicy` (`BASELINE | SAFE_NOOP | HARD_REQUIRED`,
  `packages/maistro-core/src/maistro/capabilities/types.py:9-14`).

Neither covers a third case the project intends to support: **driving an agent that runs in
someone else's harness** — a Pi session, an OpenClaw agent, a Claude Code or Codex CLI subprocess
— under maistro's own safety controls, and **being driven** as a subagent inside someone else's
orchestrator (a Master Orchestrator, or an external "meta-harness" such as Databricks' Omnigent,
which wraps Claude Code / Codex / Pi / OpenAI & Claude Agent SDKs behind one Runner API with
stateful policy and sandboxing). A2A assumes both ends speak A2A; the capability framework assumes
a provider is a library call, not an interactive agent session with its own turn loop, tool calls,
and process lifecycle.

Separately, `maistro.skills` parses exactly one definition format — `SKILL.md` frontmatter +
markdown (`packages/maistro-core/src/maistro/skills/parser.py`), loaded by
`FilesystemSkillLoader` (`skills/loader.py:23-66`) — and the marketplace connectors
(`skills/connectors.py`) surface metadata from external catalogs but do not translate foreign
agent/skill definitions into maistro's internal types. There is no defined *export* path either.

## Decision

### 1. A `harness_runner` capability slot wraps foreign agent harnesses

Add a new slot, `harness_runner`, to the SPEC-184 framework —
`SlotSpec(name="harness_runner", fallback_policy=FallbackPolicy.SAFE_NOOP)`, so a missing or
unhealthy harness degrades to a typed `Unavailable` and never breaks the host run
(`capabilities/types.py:34-39`). Each `HarnessRunner` provider implements `CapabilityProvider`
(`capabilities/protocols.py:11-31`) plus a minimal session protocol:

```python
class HarnessRunner(CapabilityProvider, Protocol):
    async def start_session(self, agent_spec: AgentConfig, *, workdir: str) -> str: ...
    async def send(self, session_id: str, messages: list[dict]) -> dict: ...
    async def stream(self, session_id: str) -> AsyncIterator[dict]: ...
    async def stop(self, session_id: str) -> None: ...
```

A `HarnessRunner` provider is a thin adapter over a foreign harness's own session/process API (Pi,
OpenClaw, Claude Code, Codex CLI, OpenAI/Claude Agent SDK sessions). The `Conduit` dispatches to it
exactly as it dispatches to a native agent at `conduit.py:120` — for a session-backed agent,
`agent.handle(...)` becomes `harness_runner.send(session_id, messages)`.

**Safety wrapping is mandatory, not optional** — this is what makes wrapping a foreign harness
"safe-ish to operate":

- The foreign harness process runs inside the existing sandbox boundary (`maistro.tools.sandbox`);
  its filesystem/network access is whatever the sandbox grants, not whatever the harness would
  otherwise claim.
- Every inbound message to the harness passes through `Warden`
  (`maistro.security.warden.detector`) before `send()`, and every tool-call/action the harness
  reports back passes through `Sentinel` policy evaluation before maistro acts on it (e.g. before
  relaying a "wants to run `git push`" action to the user).
- `healthcheck()` reports process liveness; an unhealthy or crashed harness degrades via the
  existing resolution order (`capabilities/registry.py:91-128`) — `SAFE_NOOP`, never an exception.

### 2. Hierarchical orchestration: the `HarnessRunner` protocol is bidirectional

Formalize what was previously only implied: a maistro instance can be **a node inside another
orchestrator's graph**, and a foreign harness can be **a node inside maistro's own graph**
(ADR-062) — using the *same* `HarnessRunner` protocol in each direction:

- **Outbound** — a `HarnessRunner` provider wraps Pi/OpenClaw/Claude Code/etc.; maistro's
  `MasterOrchestrator` (`packages/maistro-core/src/maistro/orchestrator/master.py`) or graph
  executor (ADR-062's `GraphRun`/`NodeRun`) can place that provider as a graph node alongside
  native `NodeStrategy` implementations (PlannerStrategy, CoderStrategy, ReviewerStrategy, etc.).
- **Inbound** — a maistro instance exposes a small adapter server implementing the *same*
  `HarnessRunner` session protocol (`start_session` / `send` / `stream` / `stop`) over HTTP. Any
  orchestrator that speaks `HarnessRunner` — another maistro's `MasterOrchestrator`, or an
  external meta-harness like Omnigent — can then drive this maistro instance as one of its
  subagents, without needing to understand A2A, the Conduit, or maistro's internal types.

This is **distinct from ADR-058's A2A federation**, which operates one layer up: A2A delegates a
*task* between peers that both understand `A2ATask` / `DelegationMode` / budgets / trust
(`a2a/delegate.py`, `a2a/guest_peers.py`), with the receiving side remaining a full maistro /
Conductor instance in its own right. `HarnessRunner` operates at the *session* layer — "drive this
process's turn loop" — and is intentionally protocol-minimal so non-maistro harnesses can
implement it too. A maistro instance may simultaneously be an A2A peer to some callers and a
`HarnessRunner` node to others; the two surfaces are not mutually exclusive, and a fully-featured
remote maistro instance should expose both.

### 3. Agent & skill portability: import wide, export narrow

Adapters that translate foreign agent/skill definitions into maistro's internal `AgentConfig`
(`maistro.types`) and `SkillDefinition` (`maistro.skills`) are added **per source format**, with no
change to the internal representation:

| Source format | Adapter target |
|---|---|
| Pi agent/task config | `AgentConfig` (+ `HarnessRunner` session if Pi remains the executor) |
| OpenClaw agent config | `AgentConfig` / `HarnessRunner` session |
| Claude Code `SKILL.md` / `.claude/agents/*.md` subagents | `SkillDefinition` (near 1:1 — maistro's `SKILL.md` parser, `skills/parser.py`, is already this format) |
| Codex CLI / `AGENTS.md` | `AgentConfig` |
| OpenAI Assistants / Agent SDK specs | `AgentConfig` + tool list → `SkillDefinition[]` |
| MCP server/tool manifests | `SkillDefinition[]` (already the closest fit — `skills/loader.py` + `merge_into_tools()`) |

New formats are added by writing a new adapter module (e.g. under `maistro.skills.importers` /
`maistro.agents.importers`); the marketplace connectors (`skills/connectors.py`) gain an
`import_format` hint so a catalog entry routes to the right adapter.

**Export is the opposite of import: pick one widely-compatible target, not N.** maistro publishes
an agent or skill as:

1. an **MCP server manifest** exposing the agent's capabilities as MCP tools — the broadest
   cross-harness target today (consumable by Claude Code, Codex, OpenAI/Claude Agent SDKs, and any
   `HarnessRunner`-speaking orchestrator via an MCP bridge), and
2. a **`SKILL.md`** alongside it, since maistro already speaks this format natively
   (`skills/parser.py`) and it is the convention multiple harnesses (including Claude Code)
   already read.

maistro does **not** maintain bespoke exporters for Pi/OpenClaw/etc. native formats — a consumer in
one of those harnesses that wants a maistro-defined agent or skill consumes it via MCP, the same as
everyone else. The adapter surface stays asymmetric on purpose: N import adapters, 1 export
target.

## Follow-ups (tracked, not decided here)

**Stateful, sequence-aware policy engine.** ADR-085 (cost/quota/rate-limiting) is reactive/veto at
a single call; ADR-086 (events/triggers/reactor) delivers events but defines no stateful approval
workflow. A policy engine that reasons over a *session's action history* — "pause after $100
cumulative spend," "require approval for `git push` only if a package was installed earlier this
session" — is a natural generalization of both, and becomes more valuable once `HarnessRunner`
sessions (Section 1) exist, since those sessions are exactly where this kind of policy matters
most. Not designed here; tracked for a future SPEC.

**Session co-ownership / real-time collaboration.** "Invite someone to view, comment on, or send
commands to a running session" — raised as a place competing agent UIs currently win — likely
needs a core primitive (a session-event stream multiple viewers can attach to), with the
collaborative UI itself (presence, comments, permissions) living in Stronghold. Not designed here.

**Omnibox-style OS-level sandbox / network interception.** A per-session sandbox that intercepts
network requests (stronger than Warden's input-side scanning) is a Stronghold-layer hardening of
the sandbox boundary `HarnessRunner` providers already run inside (Section 1). Not designed here.

## Consequences

- New `harness_runner` slot + `HarnessRunner` protocol in `maistro.capabilities`, following the
  SPEC-184 pattern exactly — no new registry or discovery machinery.
- New `maistro.skills.importers` / `maistro.agents.importers` adapter modules; `SkillMetadata`
  (`skills/connectors.py`) gains an `import_format` field.
- ADR-058's A2A protocol is unchanged; `HarnessRunner` is a separate, additive integration path at
  a different layer (session vs. task).
- Every foreign-harness adapter is reviewed under ADR-083's trust-tier model before it can reach
  `active` in the registry — a `HarnessRunner` provider is exactly the kind of "untrusted
  third-party code at a trust boundary" the Warden/Sentinel pair and ADR-083 exist for.
- Stronghold (ADR-019, ADR-068) inherits `HarnessRunner` and the import/export adapters as-is; it
  may add stricter trust tiers or disable specific foreign-harness providers per its security
  posture, but needs no separate implementation.

## References

- [ADR-058: A2A delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [ADR-062: Graph execution protocol](ADR-062-graph-execution-protocol.md)
- [ADR-083: Skills and MCP gateway trust](ADR-083-skills-mcp-trust.md)
- [ADR-085: Cost, quota, and rate limiting](ADR-085-cost-quota-rate-limiting.md)
- [ADR-086: Events, triggers, and the reactor](ADR-086-events-triggers-reactor.md)
- [ADR-019: Canonical source split](ADR-019-canonical-source-split.md)
- [ADR-068: Unified authorization and elevation](ADR-068-unified-authorization-and-elevation.md)
- [SPEC-184: Modular capability platform](../specs/SPEC-184-modular-capability-platform.md)
- [SPEC-208: Foreign harness adapter](../specs/SPEC-208-foreign-harness-adapter.md)
- Seams: `conduit.py:120`, `capabilities/registry.py`, `capabilities/protocols.py`,
  `capabilities/types.py:9-39`, `a2a/delegate.py`, `a2a/guest_peers.py`, `skills/parser.py`,
  `skills/loader.py:23-66`, `skills/connectors.py`, `orchestrator/master.py`
