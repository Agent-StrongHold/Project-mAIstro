---
id: SPEC-070226-c4f8
title: "Hierarchical orchestration: agent/skill portability across harnesses"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-02
substrate:
  - maistro-engine#ADR-058
  - maistro-engine#ADR-061526-f383
  - maistro-engine#ADR-101
  - maistro-engine#SPEC-208
implements:
  - maistro-engine#ADR-101
related:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-070
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/orchestrator/test_hierarchy.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-c4f8: Hierarchical orchestration — agent/skill portability across harnesses

## Context

ADR-101 specifies portability: an agent built for one harness (e.g., Claude Code Conductor) can be
exported and run on another harness (e.g., Pi, OpenClaw). Hierarchical orchestration means a parent
harness can spawn sub-agents on foreign harnesses and collect results.

SPEC-208 (foreign harness adapter) exports agents. This SPEC completes the hierarchical part:
parent orchestrator discovers available foreign harnesses, selects one, spawns agents, and
aggregates results.

## Goals

- Agent export from one harness in a portable format (MCP manifest).
- Foreign harness discovery and capability advertisement.
- Hierarchical delegation: parent harness spawns agents on sub-harnesses.
- Result aggregation and error handling.

## Non-goals

- Cross-tenant orchestration (Stronghold).
- Peer-to-peer harness mesh (Phase 2).

## Decision

Implemented in `packages/maistro-core/src/maistro/orchestrator/hierarchy.py` (exported from
`maistro.orchestrator`). Placement: `orchestrator/` rather than `a2a/` — this is
result-aggregation over harness nodes (the Repertoire/wave pattern), not A2A task delegation
between maistro peers.

### Harness registry and discovery

```python
@dataclass(frozen=True)
class HarnessAdvertisement:
    harness_id: str  # "pi-0", "openclaw-1"
    endpoint: str  # "https://pi.local:8000"
    capabilities: tuple[str, ...] = ()  # ("agent:run", "skill:import")
    agent_roster: tuple[str, ...] = ()  # agent names available on this harness
    cost_multiplier: float = 1.0  # relative cost vs. local
    latency_multiplier: float = 1.0

class HarnessRegistry(Protocol):
    async def list_harnesses(self) -> list[HarnessAdvertisement]:
        """Discover all connected foreign harnesses."""

    async def get_harness(self, harness_id: str) -> HarnessAdvertisement:
        """Raises HarnessUnavailableError if unknown."""
```

`InMemoryHarnessRegistry` is the reference implementation (register/unregister/list/get).

### Hierarchical delegation

`HierarchicalOrchestrator` is protocol-driven DI (per core convention) rather than doing HTTP
inline: it takes a `HarnessRegistry`, a `HarnessTransport`, an `AgentSource` (resolves an agent
name to the `AgentIdentity` + `SkillDefinition` list that SPEC-208's `export_agent` consumes),
and an optional `HarnessResultComparator` (default: highest `metadata["quality_score"]`).

```python
class HierarchicalOrchestrator:
    async def export_agent(self, agent_name: str) -> ExportBundle:
        """SPEC-208 export: MCP manifest + SKILL.md."""

    async def spawn_on_harness(
        self, agent_name: str, harness_id: str, task: HarnessTask
    ) -> HarnessTaskResult:
        """registry.get_harness -> export_agent -> transport.spawn.
        A result envelope carrying an error raises ForeignHarnessError."""

    async def spawn_wave_across_harnesses(
        self, agents: list[str], harnesses: list[str], task: HarnessTask
    ) -> HarnessTaskResult:
        """asyncio.gather(return_exceptions=True); comparator picks the best;
        AllHarnessesFailedError (carrying the failures) when every spawn failed;
        CancelledError propagates (same rule as waves/ensemble.py)."""

    async def spawn_with_fallback(
        self, agent_name: str, harnesses: list[str], task: HarnessTask
    ) -> HarnessTaskResult:
        """Ordered preference list; only HarnessUnavailableError advances to the
        next harness — ForeignHarnessError propagates; NoAvailableHarnessError
        when the whole list is down."""
```

Transports (`HarnessTransport` protocol: `spawn(harness, bundle, task) -> HarnessTaskResult`):

- `LoopbackHarnessTransport` — in-memory per-harness handlers (tests/dev); a disconnected
  harness raises `HarnessUnavailableError`, mirroring a connection failure.
- `HTTPHarnessTransport` — httpx `POST {endpoint}/v1/harness/sessions` with
  `{"agent": {"mcp_manifest": ..., "skill_md": ...}, "task": task.to_dict()}` and a bearer
  `harness_token`. Transport errors and 502/503/504 map to `HarnessUnavailableError`; other
  non-2xx raise `ForeignHarnessError`.

### Agent portability via MCP manifest

The export format (from SPEC-208) is an MCP server manifest + agent config YAML:

```yaml
# agent-export.yaml
name: "research-agent"
version: "1.0.0"
description: "Research and summarization"
mcp_manifest: {...}  # MCP server spec
agent_config:
  prompt: "..."
  memory_type: "episodic"
  tools: [...]
```

Foreign harness imports and runs this like any native agent.

### Error handling and fallback

`spawn_with_fallback` (above) retries only on `HarnessUnavailableError`; a harness that *ran* the
task and failed propagates immediately (errors are never masked by fallback). Error hierarchy:
`HierarchyError` base; `HarnessUnavailableError`, `ForeignHarnessError`, `AllHarnessesFailedError`
(carries `failures: list[BaseException]`), `NoAvailableHarnessError` (carries `harness_ids`).

### Deviations from the original draft

- Types are named `HarnessTask` / `HarnessTaskResult` (no generic `Task`/`TaskResult` exists in
  core); `HarnessAdvertisement` is frozen with tuple fields.
- HTTP is behind the injected `HarnessTransport` protocol instead of inline `httpx` calls in the
  orchestrator (core's protocol-driven-DI convention); `HTTPHarnessTransport` implements the
  draft's exact wire shape.
- A foreign error envelope raises `ForeignHarnessError` rather than returning an error result —
  makes "propagated, not silent" structural.
- The waves `ResultComparator` protocol is mirrored (`HarnessResultComparator`) rather than
  imported: it is typed to `WaveResult` specifically, which fails mypy --strict for
  `HarnessTaskResult`. Semantics (max `quality_score`, ties keep input order) are identical.
- `AllHarnessesFailedError` receives only the exceptions (not raw gather results), and
  `CancelledError` is re-raised, matching `waves/ensemble.py`.

## Acceptance criteria

- [x] Harness registry returns all connected foreign harnesses.
- [x] Agent export produces a valid MCP manifest + agent config (SPEC-208 `export_agent`).
- [x] Hierarchical spawn succeeds: parent sends agent to foreign harness, foreign harness runs it,
      parent receives result.
- [x] Wave across harnesses: multiple agents on multiple harnesses, best result returned.
- [x] Fallback: if harness A unavailable, try harness B (property: at least one succeeds if any
      harness is up).
- [x] Error from foreign harness is propagated (not silent failure).

## Testing

`packages/maistro-core/tests/orchestrator/test_hierarchy.py` (22 tests):

- Registry list/get/unregister; unknown harness raises `HarnessUnavailableError`.
- Round-trip: exported agent reaches a fake (loopback) harness, result collected.
- Wave across 3 fake harnesses returns the highest-quality result; survives partial failures;
  all-failed raises `AllHarnessesFailedError` with the per-harness failures.
- Fallback: dead harness skipped, all-dead raises `NoAvailableHarnessError`, foreign errors are
  not masked.
- Property (Hypothesis over availability masks): fallback spawn succeeds iff at least one harness
  is available, and lands on the first available one.
- `HTTPHarnessTransport` against `httpx.MockTransport`: wire shape, bearer auth, connect-error and
  503 -> `HarnessUnavailableError`, 4xx -> `ForeignHarnessError`.

## References

- [ADR-101: Foreign harness adapters](../adr/ADR-101-foreign-harness-adapters-and-portability.md)
- [SPEC-208: Foreign harness adapter](SPEC-208-foreign-harness-adapter.md)
