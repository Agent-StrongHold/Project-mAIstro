---
id: SPEC-177
title: Hyperagent graph execution (legacy port)
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-05-13
accepted: 2026-06-02
implemented: 2026-06-02
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-004
implements: []
related:
  - maistro-engine#SPEC-178
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/agents/test_graph_execution.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Accepted
    date: 2026-06-02
  - status: AC Defined
    date: 2026-06-02
---

# SPEC-177: Hyperagent graph execution

## Context

The **product** meta-spec for the hyperagent graph runtime (`specs/conductor/S-145-hyperagent-graph-runtime.md` in the sibling product repository — keep `Project_mAIstro` updated) names nodes, edges, and contracts at the **conductor** layer. **SPEC-177** is the **substrate** port into `packages/maistro-core`: shared types, graph executor, and task `ExecutionMode` must remain **compatible** with that contract where they overlap; extend S-145 first if the product runtime adds new primitives.

Before the monorepo split, a **directed-graph orchestration** mode (“hyperagent”) lived beside the single-pass conductor: multiple **Pydantic AI** sub-agents (planner, coder, reviewer, optional scout/conductor routing), **fan-out** execution, **beam search** when tier parallelism > 1, **edge conditions** on accumulated state, a shared **blackboard**, optional **SCOUT** pre-pass, and a **GraphOptimizer** that rewrote weak node prompts using traces persisted through **`WorkingMemoryProtocol`**.

`packages/maistro-core` today ships **single-pass** `run_conductor` only (`TaskCreate` has no `execution_mode` / `graph_config`). The **curated reference bundle** under `potential-dead-code/code-worth-implementing-from-legacy/` (and the full tree under `potential-dead-code/legacy-maistro-site/`) preserves the last known-good layout for a spec-first port.

## Decision

Reintroduce **GRAPH** execution as an **optional path** controlled explicitly by the task/API contract:

1. **Types** — Extend `maistro.agents.types` (or add `maistro.agents.types_graph`) with: `ExecutionMode`, graph/blackboard/optimizer models (`GraphEdge`, `GraphBlackboard`, `GraphConfig`, `GraphNodeResult`, `HyperagentOutput`, `OptimizationSignal`, `NodePerformanceMetrics`, `ScoutContext`, `ScoutOutput`, `NodeConfig`, `ConductorRoutingOutput`, etc.) aligned with the reference bundle.
2. **Working memory** — Add `WorkingMemoryProtocol` under `maistro.memory` or `maistro.protocols` with async methods: `save_trace` / `load_traces`, `save_signal` / `load_signals`, `save_node_config` / `load_node_configs` (see reference `memory/working_memory_protocol.py`).
3. **Task model** — Extend `TaskCreate` with `execution_mode: ExecutionMode` defaulting to current behavior (`WORKFLOW` or equivalent) and `graph_config: GraphConfig | None` **required** when `execution_mode == GRAPH`.
4. **Graph engine** — Port `run_graph_task` (and helpers) from reference `agents/graph.py`: cycle-based activation, concurrent dispatch (`asyncio.gather`), sequential vs parallel edges, terminal edges (`to_role is None`), `max_cycles`, tier-driven beam search, JSON-mode fallbacks per role, integration with circuit breaker / metrics / tracing consistent with existing conductor.
5. **SCOUT** — Optional pre-pass when `GraphConfig.run_scout` is true; populates `GraphBlackboard.scout_context`.
6. **GraphOptimizer** — Optional follow-on in the same epic or a child spec: meta-prompt rewrite of weakest node, persistence via `WorkingMemoryProtocol`; must not block graph execution if memory is `None`/noop.
7. **Conductor dispatch** — `run_conductor` (or a thin router used by `TaskRunner`) branches on `execution_mode == GRAPH` to call the graph executor with resolved model/tier/json_mode parity with single-pass mode.
8. **HTTP** — When `maistro-server` exposes `POST /tasks`, validate `graph_config` when mode is GRAPH; reject with **422** and a stable error body if missing/invalid.

### Out of scope (v1 of this spec)

- Persisted **Obsidian** / **PgVector** stores: specify **InMemory** + protocol mocks in tests; concrete vault/pg stores are follow-up specs or ADRs.
- Changing default behavior for existing clients (default mode remains non-GRAPH).
- Product-gateway TypeScript parity (see `potential-dead-code/code-worth-implementing-from-Project-mAIstro/gateway-ts-snapshot/` when present — not a port target in SPEC-177).

## Behavioral contract

### Graph execution

- **Deterministic topology:** `GraphConfig.nodes`, `edges`, `entry`, `hyperagent`, `max_cycles` are honored; unknown roles or edges referencing missing nodes fail fast with a typed error before any LLM call.
- **Cycle cap:** Execution stops when `max_cycles` is reached; final `HyperagentOutput` records `total_cycles` and `success` reflects whether a terminal state was reached (define: at least one node completed and no further non-terminal edges fire, or explicit policy in implementation PR).
- **Fan-out / gather:** All active nodes in a cycle complete (or fail) before edge evaluation; failures on one branch do not silent-skip observability (log + metric + structured failure on output).
- **Beam search:** When `TierConfig.parallel_generations > 1`, multiple completions run, scored, and one winner is selected; `GraphNodeResult` exposes `candidates` / `selected_candidate` / `parallel_group` as in the reference model.
- **LLM routing:** When `use_llm_routing` is true, hyperagent routing uses an LLM call with structured or JSON fallback consistent with per-role agents.

### Optimizer (if shipped in same PR)

- **Idempotent persistence:** Repeated optimization with the same traces must not corrupt store schema; tests use in-memory protocol fake.
- **Non-blocking:** Optimizer failures log at **warning** and return the input `GraphConfig` unchanged (same spirit as SPEC-175 webhook).

## Acceptance Criteria

- **AC-1**: In-memory graph run completes for a minimal triangle topology (planner → coder → reviewer) with mocked LLM responses.
- **AC-2**: Default `TaskCreate` without graph fields behaves exactly as today (existing tests unchanged).
- **AC-3**: `execution_mode=GRAPH` without `graph_config` raises validation error at Pydantic boundary.
- **AC-4**: Dispatch with `GRAPH` mode reaches graph module (can short-circuit LLM with stub).
- **AC-5**: Spec appendix stays in sync with target module paths in the implementation PR.

## Appendix A — Reference bundle → target paths

| Reference file (`potential-dead-code/code-worth-implementing-from-legacy/`) | Intended destination |
|--------------------------------------------------------|-------------------------|
| `agents/types_graph_and_execution.py` | `packages/maistro-core/src/maistro/agents/types.py` (merge or `types_graph.py`) |
| `memory/working_memory_protocol.py` | `packages/maistro-core/src/maistro/memory/protocol.py` or `maistro/protocols/memory_working.py` |
| `tasks/task_create_with_graph.py` | Merge into `packages/maistro-core/src/maistro/tasks/models.py` |
| `agents/graph.py` | `packages/maistro-core/src/maistro/agents/graph.py` |
| `agents/scout.py` | `packages/maistro-core/src/maistro/agents/scout.py` |
| `agents/optimizer.py` | `packages/maistro-core/src/maistro/agents/optimizer.py` |
| `agents/prompts.py` (delta) | Extend `packages/maistro-core/src/maistro/agents/prompts.py` (e.g. `SCOUT_SYSTEM`, routing strings) |
| `agents/conductor_with_graph_branch.py` | Merge dispatch into `packages/maistro-core/src/maistro/agents/conductor.py` |

Full legacy tree (API, `main.py`, duplicate memory) remains **diff-only** context under `potential-dead-code/legacy-maistro-site/`; do not bulk-copy.

## Appendix B — Archive deletion (after this spec is Implemented)

SPEC-177 is **Implemented** — graph execution ships under `packages/maistro-core/src/maistro/graph/` (`executor.py`, `dag_registry.py`, `node.py`, `nodes/`, `durable_runs/`, …). The entire `potential-dead-code/` tree — the legacy hyperagent bundle, the full-site duplicates, and the sibling snapshots — was **removed** per [SPEC-178](./SPEC-178-legacy-snapshot-retention.md); provenance lives in git history and the live sibling repos.
