---
id: SPEC-208
title: Foreign harness adapter — HarnessRunner slot and agent/skill format adapters
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-15
accepted: 2026-06-16
implemented: 2026-07-04
substrate:
  - maistro-engine#ADR-061526-f383
  - maistro-engine#SPEC-184
  - maistro-engine#ADR-058
  - maistro-engine#ADR-062
implements:
  - maistro-engine#ADR-061526-f383
related:
  - maistro-engine#ADR-083
  - maistro-engine#ADR-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/capabilities/test_harness_runner.py
  - packages/maistro-core/tests/capabilities/test_harness_manager.py
  - packages/maistro-core/tests/graph/test_harness_node.py
  - packages/maistro-core/tests/portability/test_portability.py
  - packages/maistro-core/tests/policy/test_sequence_policy.py
  - packages/maistro-core/tests/tools/test_microvm_sandbox.py
  - packages/hive-conductor/backend/tests/test_harness_routes.py
  - packages/maistro-core/tests/harness/test_harness_slot.py
  - packages/maistro-core/tests/harness/test_harness_guard.py
  - packages/maistro-core/tests/harness/test_importers.py
  - packages/maistro-core/tests/harness/test_export.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-15
  - status: Accepted
    date: 2026-06-16
  - status: Implemented
    date: 2026-07-04
---

# SPEC-208: Foreign harness adapter

**Implements:** ADR-061526-f383. ADR-061526-f383 decides *that* maistro wraps foreign agent harnesses behind a
`harness_runner` slot, can be wrapped the same way by other orchestrators, and adopts an
import-wide/export-narrow posture for agent and skill formats. This spec defines *how*: the slot
and protocol shapes, the safety wrapper, the import adapter catalog, the export artifact, and the
hierarchical-orchestration wiring.

---

## Context

SPEC-184 establishes `CapabilitySlot` / `CapabilityProvider` / `CapabilityRegistry`
(`packages/maistro-core/src/maistro/capabilities/`) as the one abstraction for installable,
toggleable, swappable capabilities, with a declared `FallbackPolicy` per slot
(`capabilities/types.py:9-14`). This spec adds one new slot, `harness_runner`, and the adapter
machinery around it.

## Decision

### 1. The `harness_runner` slot and the `HarnessRunner` protocol

```python
# capabilities/types.py — slot declaration
SlotSpec(name="harness_runner", fallback_policy=FallbackPolicy.SAFE_NOOP)
```

```python
# capabilities/protocols.py (new) — session protocol, layered on CapabilityProvider
@runtime_checkable
class HarnessRunner(CapabilityProvider, Protocol):
    """Adapter over a foreign agent harness's session/process API."""

    async def start_session(self, agent_spec: AgentConfig, *, workdir: str) -> str:
        """Start (or attach to) a harness session; returns a session_id."""
        ...

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """One turn: send messages, return the harness's response envelope."""
        ...

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Stream incremental events (tokens, tool calls, status) for a session."""
        ...

    async def stop(self, session_id: str) -> None:
        """Terminate the underlying process/session."""
        ...
```

`HarnessRunner.send()` returns the same response shape the `Conduit` already normalizes at
`conduit.py:130-133` (a dict, or a string coerced via `_stop_response`), so a session-backed agent
is dispatched identically to a native one — the `Conduit`'s call to `agent.handle(...)`
(`conduit.py:120`) does not change; what changes is that `agent.handle` for a harness-backed
`AgentConfig` delegates to `registry.resolve("harness_runner")` and calls `send()`.

Multiple `HarnessRunner` providers may be registered (one per foreign harness — `pi`, `openclaw`,
`claude_code`, `codex`, `opencode`); `CapabilityRegistry.activate("harness_runner", name)` selects
which one an `AgentConfig` binds to, same as any other slot.

**As-built.** The slot + `HarnessRunner` Protocol ship in
`capabilities/slots/harness_runner.py` (which also defines `HarnessInputBlocked`); the
`SlotSpec(name="harness_runner", fallback_policy=SAFE_NOOP)` is registered in
`capabilities/bootstrap.py`. The first reference provider is `SubprocessHarnessRunner`
(`capabilities/providers/subprocess_harness.py`) over an injected `SandboxExec` seam — which a
`MicroVMSandbox` (SPEC-205) satisfies, so a real harness can be run OS-isolated against a
pointed-at repo/workdir.

### 2. Safety wrapping

Every `HarnessRunner` provider implementation is required to compose three existing primitives —
no new trust-boundary type is introduced:

| Layer | Existing primitive | Applied to |
|---|---|---|
| Process isolation | `maistro.tools.sandbox` (incl. `MicroVMSandbox`, SPEC-205) | the foreign harness's subprocess: filesystem + network access |
| Inbound scan | `maistro.security.warden.detector` (Warden) | every `messages` payload before `send()` |
| Outbound policy | `SafeHarnessRunner` + an `ActionGate` (Sentinel-shaped) | every tool-call/action the harness reports in its response/stream, before maistro acts on it or relays it |
| Degradation | `capabilities/registry.py` resolution order | unhealthy/crashed harness → `SAFE_NOOP` → typed `Unavailable` (`capabilities/types.py`) |

**As-built.** The three layers are composed by `SafeHarnessRunner`
(`capabilities/providers/harness_safety.py`), which wraps any inner `HarnessRunner`:

- `_scan_inbound` runs Warden over every `send()`/`stream()` payload and raises
  `HarnessInputBlocked` (not a silent drop) when `verdict.clean` is false.
- `_filter_actions` gates outbound actions through an injected `ActionGate` — both the
  top-level `actions` list and any `choices[].message.tool_calls` — so a gate-denied action
  never reaches maistro or the caller. The default gate is `AllowAllGate`; supplying a
  `SequencePolicyEngine` (SPEC-203) yields a `PolicyActionGate` that enforces stateful,
  sequence-aware policy (budgets, after-count, forbidden pairs, velocity) per session.

`HarnessSessionManager` (`capabilities/harness_manager.py`) is the glue: it resolves the
slot, wraps the provider in `SafeHarnessRunner` (with a `PolicyActionGate` keyed by
`session_id` when a policy is given), and degrades to `Unavailable` instead of raising.

A `HarnessRunner` provider's `requires()` declares the binary or SDK the foreign harness needs
plus the sandbox profile; `healthcheck()` checks both the binary's presence and the sandbox's
reachability.

### 3. Import adapter catalog

```python
# maistro.agents.importers / maistro.skills.importers (new subpackages)
class AgentImporter(Protocol):
    format: str                       # "pi" | "openclaw" | "claude_code" | "codex" | "openai_assistant"
    def detect(self, source: dict | str) -> bool: ...
    def to_agent_config(self, source: dict | str) -> AgentConfig: ...

class SkillImporter(Protocol):
    format: str                       # "claude_code_skill" | "mcp_manifest" | "openai_tool"
    def detect(self, source: dict | str) -> bool: ...
    def to_skill_definitions(self, source: dict | str) -> list[SkillDefinition]: ...
```

| Source format | Importer | Target |
|---|---|---|
| Pi agent/task config | `agents.importers.pi` | `AgentConfig` (binds to `harness_runner="pi"`) |
| OpenClaw agent config | `agents.importers.openclaw` | `AgentConfig` (binds to `harness_runner="openclaw"`) |
| Claude Code `SKILL.md` / `.claude/agents/*.md` | `skills.importers.claude_code` | `SkillDefinition` — thin wrapper, `skills/parser.py` already parses this frontmatter shape |
| Codex CLI / `AGENTS.md` | `agents.importers.codex` | `AgentConfig` (binds to `harness_runner="codex"`) |
| OpenAI Assistants / Agent SDK spec | `agents.importers.openai_assistant` | `AgentConfig` + `skills.importers.openai_tool` for its tool list |
| MCP server/tool manifest | `skills.importers.mcp` | `list[SkillDefinition]` via `merge_into_tools()` (`skills/loader.py:88-99`) |

A registry (`ImporterRegistry`, mirroring `CapabilityRegistry`'s shape but unkeyed by slot) tries
each importer's `detect()` in registration order and applies the first match. The marketplace
connectors (`skills/connectors.py`) gain an `import_format: str | None` field on `SkillMetadata` so
a catalog entry can name its format explicitly and skip detection.

### 4. Export: one target format

```python
# maistro.agents.export (new)
def export_agent(agent: AgentConfig, skills: list[SkillDefinition]) -> ExportBundle:
    """Returns an MCP server manifest exposing `agent`'s skills as MCP tools,
    plus a SKILL.md describing the agent, for any MCP- or SKILL.md-aware harness."""
```

`ExportBundle` is `{mcp_manifest: dict, skill_md: str}`. There is exactly one export path,
regardless of how the agent was imported (native, Pi, OpenClaw, ...). A maistro-defined agent
consumed from Pi/OpenClaw/Codex goes through that harness's own MCP client — maistro does not
special-case the consumer.

### 5. Hierarchical orchestration mechanics

**Outbound (maistro drives a foreign harness).** A graph node's turn is executed by a foreign
harness instead of the LLM. This needs an *execution* seam, not a strategy: ADR-062's
`NodeStrategy` is a prompt/output **shaper** (`build_user_prompt` / `score_output` /
`update_blackboard`), so it cannot itself "run" a harness. The original sketch of a
`HarnessNodeStrategy.execute()` did not match that interface and was **not** built as such. The
as-built design instead adds a distinct seam:

- **`NodeExecutor` protocol** (`graph/node.py`) — a non-LLM execution backend. When a `NodeRun`
  carries an `executor`, `execute()` dispatches to `_execute_via_executor()`, which **reuses** the
  existing circuit-breaker, `IterationBudget`, retry, and success/failure/telemetry plumbing but
  replaces "call `llm_call`, parse text" with "call the executor, get a parsed output." The shared
  per-attempt guard (cancel/circuit/budget) is factored into `_preflight_stop()`, used by both the
  LLM and executor paths.
- **`HarnessStrategy`** (`graph/strategy.py`) — the shaper half: role `AgentRole.HARNESS`, output
  type `HarnessOutput`, registered in `STRATEGY_REGISTRY` so a DAG can schedule a harness node by
  role.
- **`HarnessOutput{summary, actions, raw}`** (`graph/types.py`) — the node output. `actions` stays
  untyped (`list[dict]`) because each foreign harness emits its own action shape.
- **`HarnessNodeExecutor`** (`graph/harness_executor.py`) — the `NodeExecutor` implementation that
  bridges to `HarnessSessionManager`: `start` → `send` (Warden-scanned, policy-gated) → `stop`,
  normalizing either envelope shape (OpenAI `choices` or flat `content`) into `HarnessOutput`, and
  raising `HarnessExecutionError` on `Unavailable` so the node's retry/circuit plumbing records it.
- **Wiring** — a per-role `node_executors: dict[str, NodeExecutor]` map is threaded through
  `GraphRun` and `run_graph()`; when a node's role matches, it runs via the executor. A foreign
  harness node thus cannot exceed the shared `IterationBudget` and records `NodeRun` telemetry
  identically to a native node.

**Inbound (maistro is driven by another orchestrator).** A `hive-conductor` route
(`routes/harness.py`) exposes the `HarnessRunner` HTTP shape: `POST /v1/harness/sessions`
(→ `session_id`), `POST /v1/harness/sessions/{id}/send`, `GET /v1/harness/sessions/{id}/stream`
(SSE), `DELETE /v1/harness/sessions/{id}`. As-built it is backed by a process-wide
`HarnessSessionManager` over the engine's capability registry + Warden — so the same Warden +
policy gating applies to inbound turns — rather than wrapping `Conduit.route_request()` directly.
It degrades to `503` when no `harness_runner` provider is active (SAFE_NOOP), `400` when Warden
refuses an inbound payload (`HarnessInputBlocked`), and `404` for an unknown session. Auth rides
the existing middleware; a dedicated `harness:session` service-key scope can gate the route.

## Acceptance Criteria

- [x] `harness_runner` `SlotSpec` defined with `FallbackPolicy.SAFE_NOOP`; `HarnessRunner` Protocol
      shipped in `capabilities/slots/harness_runner.py`, `mypy --strict` clean.
- [x] A `HarnessRunner` reference provider (`SubprocessHarnessRunner`) implements
      `start_session`/`send`/`stream`/`stop` over an injected `SandboxExec` seam (satisfiable by
      `MicroVMSandbox`); `healthcheck()` reflects binary presence + sandbox reachability.
- [x] Every `send()` call passes its `messages` through Warden before reaching the subprocess, and
      every action in the harness's response passes through the `ActionGate` before being surfaced
      — asserted via a fake harness that emits a flagged payload and a flagged action.
- [x] A crashed/unhealthy/disabled `HarnessRunner` provider degrades the slot to `SAFE_NOOP`
      (`Unavailable`); the calling agent/graph node receives the typed result, never an exception.
- [x] At least two `AgentImporter`/`SkillImporter` implementations exist (Claude Code / OpenAI
      agent formats; Claude Code `SKILL.md` / MCP manifest skill formats), each with `detect()` +
      `to_*()` round-tripped in a unit test (`portability/`).
- [x] `export_agent()` produces an MCP server manifest + a `SKILL.md` whose frontmatter
      `skills/parser.py` can re-parse — proving the import→export round trip.
- [x] A harness-backed graph node runs under ADR-062's `GraphRun` via the `NodeExecutor` seam
      (`HarnessNodeExecutor` + `HarnessStrategy`), recording `NodeRun` telemetry identically to a
      native node and respecting `IterationBudget`. *(Built as an executor seam, not a
      `NodeStrategy.execute()` — see §5 rationale.)*
- [x] `POST /v1/harness/sessions` (+ send/stream/stop) is reachable through the Conductor auth
      middleware, backed by `HarnessSessionManager` (same Warden + policy gating), returning
      `503`/`400`/`404` for no-provider / Warden-blocked / unknown-session.

## Testing

- Unit: each `AgentImporter`/`SkillImporter` `detect()`/`to_*()`; `export_agent()` MCP manifest +
  `SKILL.md` shape; `HarnessRunner` registry resolution (healthy / unhealthy / disabled →
  `SAFE_NOOP`).
- Contract: `HarnessRunner` Protocol conformance for each provider (boundary); Warden/Sentinel
  wrapping order is enforced regardless of provider (behavioral) — a fake provider cannot bypass
  the wrapper.
- Integration: outbound — a `HarnessNodeStrategy` node driving a stub `HarnessRunner` inside a
  `GraphRun`; inbound — `POST /v1/harness/sessions/.../send` round-tripping through
  `Conduit.route_request()` against an in-memory container.
- Property (formal/, per repo convention): "a `harness_runner` provider that is absent, disabled,
  or unhealthy never causes a graph node or `Conduit` call to raise" (extends the SPEC-184
  `safe_noop` invariant to this slot).

## Open questions

- **Per-harness session lifecycle limits** (DEFERRED to Phase 2): idle timeout, max concurrent
  sessions per host — resource-management policy belongs with the follow-up stateful policy engine
  (ADR-061526-f383 follow-ups).
- **HarnessNodeStrategy priority tier interaction** (DEFERRED to implementation): whether it needs
  its own `priority_tier` interaction with `determine_execution_tier` when a foreign harness
  reports its own cost/latency profile — likely emerges during wiring.
- **MCP manifest versioning** (DEFERRED with pinned baseline): `export_agent()` targets a pinned
  MCP schema version with a documented upgrade path; exact compatibility story as MCP spec evolves
  is a follow-up.

## References

- [ADR-061526-f383: Foreign harness adapters, hierarchical orchestration, and agent/skill portability](../adr/ADR-061526-f383-foreign-harness-adapters-and-portability.md)
- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md)
- [ADR-058: A2A delegation protocol](../adr/ADR-058-a2a-delegation-protocol.md)
- [ADR-062: Graph execution protocol](../adr/ADR-062-graph-execution-protocol.md)
- [ADR-083: Skills and MCP gateway trust](../adr/ADR-083-skills-mcp-trust.md)
- Seams: `capabilities/protocols.py:11-31`, `capabilities/registry.py:91-128`,
  `capabilities/types.py:9-39`, `conduit.py:24-33,68,120,130-133`, `skills/parser.py`,
  `skills/loader.py:23-66,88-99`, `skills/connectors.py`, `a2a/delegate.py`, `a2a/guest_peers.py`
