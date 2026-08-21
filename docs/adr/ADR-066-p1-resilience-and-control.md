---
id: ADR-066
title: P1 Resilience and Control
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-20
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-062
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
ac-modules:
  AC-1: maistro.graph.depth
  AC-2: maistro.graph.depth
  AC-3: maistro.graph.depth
  AC-4: maistro.graph.depth
  AC-5: maistro.graph.depth
  AC-6: maistro.graph.depth
  AC-7: maistro.graph.depth
  AC-8: maistro.graph.depth
  AC-9: maistro.graph.compaction
  AC-10: maistro.graph.compaction
  AC-11: maistro.graph.compaction
  AC-12: maistro.graph.compaction
  AC-13: maistro.graph.compaction
  AC-14: maistro.graph.compaction
  AC-15: maistro.graph.compaction
  AC-16: maistro.graph.steering
  AC-17: maistro.graph.steering
  AC-18: maistro.graph.steering
  AC-19: maistro.graph.steering
  AC-20: maistro.graph.steering
  AC-21: maistro.graph.steering
  AC-22: maistro.graph.steering
  AC-23: maistro.resilience.rate_coordination
  AC-24: maistro.resilience.rate_coordination
  AC-25: maistro.resilience.rate_coordination
  AC-26: maistro.resilience.rate_coordination
  AC-27: maistro.resilience.rate_coordination
  AC-28: maistro.resilience.rate_coordination
  AC-29: maistro.resilience.rate_coordination
  AC-30: maistro.resilience.rate_coordination
  AC-31: maistro.resilience.retry_policy
  AC-32: maistro.resilience.retry_policy
  AC-33: maistro.resilience.retry_policy
  AC-34: maistro.resilience.retry_policy
  AC-35: maistro.resilience.retry_policy
  AC-36: maistro.resilience.retry_policy
  AC-37: maistro.resilience.retry_policy
  AC-38: maistro.resilience.context_probe
  AC-39: maistro.resilience.context_probe
  AC-40: maistro.resilience.context_probe
  AC-41: maistro.resilience.context_probe
  AC-42: maistro.resilience.context_probe
  AC-43: maistro.resilience.context_probe
  AC-44: maistro.resilience.context_probe
  AC-45: maistro.resilience.context_probe
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-20
---

# ADR-066: P1 Resilience and Control

**Status:** Proposed
**Date:** 2026-05-20
**Tranche:** T5
**Depends on:** ADR-038 (reliability taxonomy), ADR-062 (graph execution protocol)

---

## Context

ADR-062 introduced `GraphRun`, `NodeRun`, `NodeStrategy`, and `IterationBudget` as the
graph execution protocol. It deliberately excluded several operational concerns to separate
mechanical correctness from resilience and control. Six P1 improvements from the competitive
analysis fill those gaps:

1. **Infinite DAG recursion** — nothing prevents a subgraph from spawning subgraphs ad
   infinitum. IMP-023 adds a hierarchical depth/role system to enforce a finite bound.

2. **Context bloat in long-running DAGs** — the blackboard accumulates indefinitely.
  IMP-044 compresses it via iterative LLM summarization when it exceeds a threshold.

3. **No mid-run control** — once `GraphRun.start()` is called, the caller cannot alter
   course without cancelling and restarting. IMP-025 adds non-interrupting steering.

4. **Thundering herd on rate limits** — concurrent processes sharing one API key all hit
   the same rate limit and all retry simultaneously. IMP-008 coordinates via shared state.

5. **One-size-fits-all retry** — a transient read failure and a failed write have identical
   retry behaviour. IMP-009 introduces per-operation-stage retry policies.

6. **Unknown model context lengths** — calling an unfamiliar model risks silent truncation
   or an immediate overflow. IMP-016 probes context length with tiered requests.

These are grouped into this single ADR because they share a common theme (keeping
long-running, multi-node graph executions alive and under control) and because their
packages are tightly coupled: depth gating triggers compaction, compaction triggers
context probing, rate coordination feeds retry policies, and steering reads compacted
context.

---

## Decision

Six sub-decisions, one per IMP. Each introduces a new public package under
`maistro.graph` or `maistro.resilience`.

---

### Sub-decision 1: IMP-023 — Hierarchical Depth/Role System for Subgraphs

**Package:** `maistro.graph.depth` (new)

A subgraph invocation boundary assigns a **role** to each subgraph based on its nesting
depth:

| Role | Depth | `can_spawn` | `control_scope` | Purpose |
|------|-------|-------------|-----------------|---------|
| `root` | 0 | Yes | Full graph | Entry point; owns `IterationBudget` |
| `orchestrator` | 1 .. max-1 | Yes | Subtree only | Intermediate coordinator |
| `leaf` | max | No | Own node only | Terminal executor |

**Mechanism:**

- `max_depth` is a configurable integer (default: 3, minimum: 1).
- Each `GraphRun` carries a `depth: int` field. The top-level run has `depth=0`.
- When a `NodeStrategy` (or any node) invokes a subgraph, it creates a child `GraphRun`
  with `depth = parent.depth + 1`.
- `DepthRole(role, depth, max_depth)` is computed at subgraph creation time and stored on
  the child `GraphRun`.
- If `depth > max_depth`, the subgraph invocation raises `DepthExceededError` (subclass of
  `GraphError`) and the parent `NodeRun` records a `ClassifiedError` with category
  `PERMANENT`.

**Enforcement boundary:** The check happens at the subgraph invocation boundary — the
point where a parent `GraphRun` creates a child `GraphRun`. This is the only place depth
is incremented, so it is the natural chokepoint.

**Control scope semantics:**

- `root` can cancel any node or child graph, read the full blackboard, and steer.
- `orchestrator` can cancel its own subtree's nodes, read/write its subtree's blackboard
  partition, and steer within its subtree.
- `leaf` can only execute its own `NodeRun`. It cannot spawn children, steer, or modify
  blackboard outside its own output.

```python
from enum import StrEnum
from dataclasses import dataclass

class DepthRole(StrEnum):
    ROOT = "root"
    ORCHESTRATOR = "orchestrator"
    LEAF = "leaf"

@dataclass(frozen=True)
class DepthDescriptor:
    role: DepthRole
    depth: int
    max_depth: int

    @property
    def can_spawn(self) -> bool:
        return self.role != DepthRole.LEAF

    @property
    def control_scope(self) -> str:
        if self.role == DepthRole.ROOT:
            return "full"
        if self.role == DepthRole.ORCHESTRATOR:
            return "subtree"
        return "node"

def compute_role(depth: int, max_depth: int) -> DepthDescriptor:
    if depth == 0:
        return DepthDescriptor(DepthRole.ROOT, depth, max_depth)
    if depth >= max_depth:
        return DepthDescriptor(DepthRole.LEAF, depth, max_depth)
    return DepthDescriptor(DepthRole.ORCHESTRATOR, depth, max_depth)
```

---

### Sub-decision 2: IMP-044 — Iterative Context Compaction

**Package:** `maistro.graph.compaction` (new)

When the blackboard's serialized size exceeds a configurable threshold (default: 80% of
the model's known context window), the compaction engine compresses it via LLM
summarization.

**Algorithm:**

1. `CompactionEngine` checks `blackboard.serialized_size()` before each node execution.
2. If size exceeds `threshold_bytes`, the engine invokes an LLM summarization call with a
   structured prompt template.
3. The prompt template has six sections: **Goal**, **Constraints**, **Progress**,
   **Key Decisions**, **Next Steps**, **Critical Context**.
4. The engine stores `_previous_summary` on the blackboard and generates an iterative
   update (not a full re-summarization) on subsequent compactions.
5. The compacted context replaces the verbose blackboard content. Original entries are
   marked `compacted=True` and retained for audit but excluded from the next node's input.

**Prompt template structure:**

```
You are summarizing the execution context of a multi-step agent graph.

## Goal
{task_description}

## Constraints
{constraints_from_task}

## Progress So Far
{previous_summary_or_original_progress}

## Key Decisions Made
{accumulated_decisions}

## Next Steps
{pending_nodes_description}

## Critical Context (must preserve)
{items_marked_critical}

Produce a concise summary preserving all facts needed for remaining nodes.
```

```python
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class CompactionResult:
    summary: str
    previous_summary: str | None
    bytes_before: int
    bytes_after: int
    entries_compacted: int
    preserved_critical: list[str]

class CompactionThreshold(Protocol):
    def should_compact(self, serialized_size: int, context_window: int) -> bool: ...

@dataclass
class PercentageThreshold:
    percentage: float = 0.8
    def should_compact(self, serialized_size: int, context_window: int) -> bool:
        return serialized_size > context_window * self.percentage

class CompactionEngine:
    def __init__(
        self,
        threshold: CompactionThreshold,
        llm_call: Callable[..., Awaitable[str]],
        model: str = "default",
    ) -> None: ...

    async def compact(
        self,
        blackboard: GraphBlackboard,
        task: GraphTask,
    ) -> CompactionResult | None:
        """
        Compact if threshold exceeded. Returns None if no compaction needed.
        Iterative: uses _previous_summary if present.
        """
        ...

    def _build_prompt(
        self,
        blackboard: GraphBlackboard,
        task: GraphTask,
        previous_summary: str | None,
    ) -> str: ...
```

**Integration with GraphRun:** The `GraphRun` calls `compaction_engine.compact()`
before each `NodeRun.execute()`. If a `CompactionResult` is returned, the compacted
summary is injected into the next node's context via the `NodeStrategy.build_user_prompt`
method.

---

### Sub-decision 3: IMP-025 — Steering / Mid-Run Guidance

**Package:** `maistro.graph.steering` (new)

A `steer(guidance: str)` method on `GraphRun` that appends mid-run guidance to the
current execution context without restarting or interrupting in-flight nodes.

**Mechanism:**

- `GraphRun` has an internal `SteeringQueue`: an async-safe list of guidance strings.
- `steer(guidance)` appends to the queue. This is safe to call from any coroutine or
  thread at any time.
- Between node completions (after one `NodeRun` finishes, before the next starts),
  `GraphRun` drains the steering queue and injects all accumulated guidance into the
  blackboard under a `_steering_guidance` key.
- The next node's `NodeStrategy.build_user_prompt` includes any steering guidance present
  on the blackboard.
- Steering is non-interrupting: an in-flight `NodeRun` is unaffected. Guidance appears in
  the next node's context.
- Steering respects `control_scope`: a leaf role's steering is ignored. An orchestrator
  can only steer within its subtree.

```python
import asyncio
from dataclasses import dataclass, field

@dataclass
class SteeringEntry:
    guidance: str
    timestamp: float
    source_depth: int

class SteeringQueue:
    def __init__(self) -> None:
        self._entries: list[SteeringEntry] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    async def append(self, guidance: str, source_depth: int) -> None:
        async with self._lock:
            self._entries.append(SteeringEntry(
                guidance=guidance,
                timestamp=time.monotonic(),
                source_depth=source_depth,
            ))

    async def drain(self) -> list[SteeringEntry]:
        async with self._lock:
            entries = self._entries.copy()
            self._entries.clear()
            return entries

@dataclass
class SteeringGuidance:
    entries: list[SteeringEntry]
    injected_at: float
```

**Integration with GraphRun:**

```python
class GraphRun:
    _steering_queue: SteeringQueue

    async def steer(self, guidance: str) -> None:
        """
        Append mid-run guidance. Appears in next node's context.
        No restart or interrupt. Respects depth role control_scope.
        """
        if self._depth_descriptor.control_scope == "node":
            return
        await self._steering_queue.append(guidance, self._depth_descriptor.depth)

    async def _drain_steering(self) -> None:
        """Called between node completions. Drains queue into blackboard."""
        entries = await self._steering_queue.drain()
        if entries:
            self.blackboard._steering_guidance = SteeringGuidance(
                entries=entries,
                injected_at=time.monotonic(),
            )
```

---

### Sub-decision 4: IMP-008 — Cross-Process Rate Limit Coordination

**Package:** `maistro.resilience.rate_coordination` (new)

A file-based coordination mechanism that concurrent processes (on the same host) check
before making API calls. When one process hits a rate limit, it writes the reset time;
others read it and back off.

**Design:**

- **State file:** A JSON file at a configurable path (default:
  `/tmp/maistro-rate-coordination.json`).
- **Schema:** `{ "<provider>": { "reset_at": <unix_timestamp>, "updated_at": <unix_timestamp>, "limit_type": "rpm|rpm_team|tpm" } }`
- **Read path:** Before an API call, the process reads the state file. If `reset_at` is in
  the future, the process sleeps until `reset_at` (or uses an async equivalent).
- **Write path:** On receiving a 429 response, the process parses the `Retry-After` header
  or error body, computes `reset_at = now + retry_after_seconds`, and writes it to the
  state file.
- **Atomicity:** Writes use `write-to-temp + rename` for atomic updates. Reads use a
  shared `fcntl.flock(LOCK_SH)` to avoid reading partial writes.
- **Staleness:** Entries older than `staleness_threshold` (default: 300s) are pruned on
  read. A stale entry (where `reset_at` has passed) is ignored.
- **Zero infrastructure:** No Redis, no database, no service. Just a file on disk.

```python
from dataclasses import dataclass
from pathlib import Path
import fcntl
import json
import time
from typing import Protocol

@dataclass(frozen=True)
class RateLimitState:
    provider: str
    reset_at: float
    updated_at: float
    limit_type: str

class RateCoordinationStore(Protocol):
    async def read(self, provider: str) -> RateLimitState | None: ...
    async def write(self, state: RateLimitState) -> None: ...
    async def clear(self, provider: str) -> None: ...

class FileRateCoordinationStore:
    def __init__(
        self,
        path: Path = Path("/tmp/maistro-rate-coordination.json"),
        staleness_threshold: float = 300.0,
    ) -> None: ...

    async def read(self, provider: str) -> RateLimitState | None:
        """
        Read state for provider. Returns None if no entry or entry is stale
        (reset_at in the past or updated_at older than staleness_threshold).
        Uses shared lock for concurrent reads.
        """
        ...

    async def write(self, state: RateLimitState) -> None:
        """
        Write state atomically (write-to-temp + rename).
        Uses exclusive lock.
        """
        ...

    async def clear(self, provider: str) -> None:
        """Remove entry for provider. Used when rate limit window passes."""
        ...

class RateCoordinator:
    def __init__(self, store: RateCoordinationStore) -> None: ...

    async def check_before_call(self, provider: str) -> float:
        """
        Returns seconds to wait before calling provider.
        Returns 0.0 if no rate limit is active.
        """
        state = await self._store.read(provider)
        if state is None:
            return 0.0
        wait = state.reset_at - time.monotonic()
        return max(0.0, wait)

    async def record_rate_limit(
        self,
        provider: str,
        retry_after_seconds: float,
        limit_type: str = "rpm",
    ) -> None:
        """Record that provider returned 429. Writes reset_at."""
        await self._store.write(RateLimitState(
            provider=provider,
            reset_at=time.monotonic() + retry_after_seconds,
            updated_at=time.monotonic(),
            limit_type=limit_type,
        ))
```

**Integration:** `NodeRun.execute()` calls `coordinator.check_before_call(provider)` before
each LLM call. On 429, it calls `coordinator.record_rate_limit()`. This is transparent to
`NodeStrategy` implementations.

---

### Sub-decision 5: IMP-009 — Stage-Aware Retry Policies

**Package:** `maistro.resilience.retry_policy` (new)

Per-operation-stage retry policies that replace the one-size-fits-all retry in ADR-038
with stage-appropriate behaviour.

**Stages:**

| Stage | Default Max Attempts | Default Backoff | Rationale |
|-------|---------------------|-----------------|-----------|
| `read` | 3 | 250ms fixed | Reads are idempotent and cheap; retry aggressively |
| `evaluate` | 2 | 1s exponential | Moderate cost; retry cautiously |
| `write` | 1 (no retry) | N/A | Writes are non-idempotent by default; require explicit opt-in |
| `llm_call` | 3 | Exponential (2s base) | Inherits ADR-038 LLM retry; handled by LiteLLM |

**Configuration:**

```python
from dataclasses import dataclass
from enum import StrEnum

class OperationStage(StrEnum):
    READ = "read"
    EVALUATE = "evaluate"
    WRITE = "write"
    LLM_CALL = "llm_call"

@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    exponential: bool
    idempotency_required: bool

DEFAULT_POLICIES: dict[OperationStage, RetryConfig] = {
    OperationStage.READ: RetryConfig(
        max_attempts=3, base_delay_s=0.25, max_delay_s=2.0,
        exponential=False, idempotency_required=False,
    ),
    OperationStage.EVALUATE: RetryConfig(
        max_attempts=2, base_delay_s=1.0, max_delay_s=8.0,
        exponential=True, idempotency_required=False,
    ),
    OperationStage.WRITE: RetryConfig(
        max_attempts=1, base_delay_s=0.0, max_delay_s=0.0,
        exponential=False, idempotency_required=True,
    ),
    OperationStage.LLM_CALL: RetryConfig(
        max_attempts=3, base_delay_s=2.0, max_delay_s=16.0,
        exponential=True, idempotency_required=False,
    ),
}

class StageAwareRetryPolicy:
    def __init__(
        self,
        policies: dict[OperationStage, RetryConfig] | None = None,
    ) -> None:
        self._policies = policies or DEFAULT_POLICIES

    def config_for(self, stage: OperationStage) -> RetryConfig:
        return self._policies[stage]

    def should_retry(
        self,
        stage: OperationStage,
        attempt: int,
        error: Exception,
        has_idempotency_key: bool = False,
    ) -> bool:
        cfg = self.config_for(stage)
        if attempt >= cfg.max_attempts:
            return False
        if cfg.idempotency_required and not has_idempotency_key:
            return False
        return self._is_transient(error)

    def delay_for(self, stage: OperationStage, attempt: int) -> float:
        cfg = self.config_for(stage)
        if cfg.exponential:
            delay = cfg.base_delay_s * (2 ** attempt)
            return min(delay, cfg.max_delay_s)
        return cfg.base_delay_s

    @staticmethod
    def _is_transient(error: Exception) -> bool:
        """Transient: network errors, 429, 5xx. Non-transient: 4xx (not 429)."""
        ...
```

**Integration:** `NodeRun.execute()` uses `StageAwareRetryPolicy` to decide whether to
retry a failed LLM call (stage=`llm_call`). Non-LLM IO within strategies (e.g., database
reads, MCP tool calls) uses the appropriate stage. The policy replaces the hardcoded
`max_retries` parameter on `NodeRun`.

---

### Sub-decision 6: IMP-016 — Context Length Probing

**Package:** `maistro.resilience.context_probe` (new)

When a model's maximum context length is unknown (not in the model registry), probe it
with progressively larger requests before using the model for real work.

**Algorithm:**

1. **Probe tiers:** `[4096, 16384, 65536, 131072, 204800]` tokens.
2. For each tier, send a request with a prompt padded to that size (using a simple
   repeated token pattern).
3. If the request succeeds, move to the next tier.
4. If the request fails with a context-length overflow error, parse the actual limit from
   the error response (most providers include `max_tokens` or `context_length` in the
   error body).
5. Cache the discovered limit in the model registry.
6. On subsequent calls, use the cached value. No re-probing.

**Error parsing:**

Provider-specific error parsing extracts the actual context limit:

- OpenAI: `error.message` contains "maximum context length" with a number.
- Anthropic: `error.message` contains "token limit" or `max_tokens` in the response.
- Google: `error.message` contains "exceeds" with a token count.
- Generic fallback: binary search between the last successful tier and the failing tier.

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

PROBE_TIERS: list[int] = [4096, 16384, 65536, 131072, 204800]

@dataclass(frozen=True)
class ProbeResult:
    model: str
    context_limit: int
    probed_at: float
    provider: str
    method: str  # "probe_success", "error_parse", "binary_search"

class ModelRegistry(Protocol):
    async def get_context_limit(self, model: str) -> int | None: ...
    async def set_context_limit(self, model: str, limit: int) -> None: ...

class ContextLengthProber:
    def __init__(
        self,
        llm_call: Callable[..., Awaitable[str]],
        registry: ModelRegistry,
        probe_tiers: list[int] | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._registry = registry
        self._probe_tiers = probe_tiers or PROBE_TIERS

    async def probe(self, model: str, provider: str) -> ProbeResult:
        """
        Probe context length for model. Returns the discovered limit.
        Caches result in registry.
        """
        cached = await self._registry.get_context_limit(model)
        if cached is not None:
            return ProbeResult(
                model=model, context_limit=cached,
                probed_at=time.monotonic(), provider=provider,
                method="cached",
            )

        last_success = 0
        for tier in self._probe_tiers:
            prompt = self._make_probe_prompt(tier)
            try:
                await self._llm_call(
                    model=model, prompt=prompt, max_tokens=1,
                )
                last_success = tier
            except ContextOverflowError as e:
                parsed = self._parse_limit_from_error(e, provider)
                if parsed:
                    await self._registry.set_context_limit(model, parsed)
                    return ProbeResult(
                        model=model, context_limit=parsed,
                        probed_at=time.monotonic(), provider=provider,
                        method="error_parse",
                    )
                limit = await self._binary_search(
                    model, last_success, tier,
                )
                await self._registry.set_context_limit(model, limit)
                return ProbeResult(
                    model=model, context_limit=limit,
                    probed_at=time.monotonic(), provider=provider,
                    method="binary_search",
                )

        await self._registry.set_context_limit(model, self._probe_tiers[-1])
        return ProbeResult(
            model=model, context_limit=self._probe_tiers[-1],
            probed_at=time.monotonic(), provider=provider,
            method="probe_success",
        )

    async def _binary_search(
        self, model: str, low: int, high: int, tolerance: int = 1024,
    ) -> int:
        """Binary search between low and high to find exact limit."""
        ...

    def _parse_limit_from_error(
        self, error: ContextOverflowError, provider: str,
    ) -> int | None:
        """Provider-specific error parsing."""
        ...

    @staticmethod
    def _make_probe_prompt(size_tokens: int) -> str:
        """Generate a padding prompt of approximately size_tokens tokens."""
        ...
```

**Integration:** `CompactionEngine` calls `prober.probe(model, provider)` before computing
the compaction threshold. `NodeRun.execute()` calls it on first use of an unknown model.
The probed limit feeds back into `CompactionThreshold.should_compact()` and
`CompactionEngine` threshold calculation.

---

## Consequences

**Positive:**

- **Infinite recursion eliminated.** `DepthDescriptor` at the subgraph boundary guarantees
  finite DAG depth. A misconfigured graph fails fast with `DepthExceededError` instead of
  consuming unbounded resources.

- **Long-running DAGs stay alive.** Iterative compaction keeps the blackboard within model
  context limits, enabling graphs that run for hundreds of iterations (e.g., multi-hour
  code generation or research tasks).

- **Human-in-the-loop control.** Steering allows operators to correct course mid-run
  without losing progress. This is critical for expensive long-running jobs.

- **Coordinated back-off.** Cross-process rate coordination prevents thundering-herd
  retries when multiple processes share an API key, reducing 429 errors by spreading
  load.

- **Appropriate retry aggressiveness.** Stage-aware policies mean reads recover quickly,
  writes don't duplicate work, and evaluation retries are conservative — matching the
  cost profile of each operation type.

- **Unknown models become usable.** Context probing eliminates a hard blocker for using
  new or custom models whose limits aren't documented in the registry.

**Negative / risks:**

- **Compaction information loss.** LLM summarization is lossy. Critical context may be
  dropped. Mitigated by the "Critical Context" section in the prompt template and by
  retaining compacted entries for audit.

- **File-based rate coordination is host-local.** Processes on different machines cannot
  coordinate. This is acceptable for single-host deployments (current architecture) but
  will need a Redis-based store for multi-node deployments.

- **Probing costs tokens.** Each probe tier consumes tokens. Mitigated by tiered probing
  (4K before 16K before 64K) and caching results in the model registry.

- **Steering timing is best-effort.** Guidance appears at node boundaries, not mid-node.
  A long-running LLM call will not see steering until it completes. This is inherent to
  the non-interrupting design.

- **Six new packages increase surface area.** Each package has its own types, protocols,
  and integration points. Mitigated by small, focused packages and by colocating related
  features (depth + compaction + steering are all in `maistro.graph.*`).

---

## File layout

```
maistro/
├── graph/
│   ├── depth/
│   │   ├── __init__.py        # DepthRole, DepthDescriptor, compute_role
│   │   └── errors.py          # DepthExceededError
│   ├── compaction/
│   │   ├── __init__.py        # CompactionEngine, CompactionResult
│   │   ├── threshold.py       # PercentageThreshold, CompactionThreshold protocol
│   │   └── prompt.py          # Structured prompt template
│   └── steering/
│       ├── __init__.py        # SteeringQueue, SteeringEntry, SteeringGuidance
│       └── integration.py     # GraphRun.steer(), _drain_steering()
├── resilience/
│   ├── rate_coordination/
│   │   ├── __init__.py        # RateCoordinator, RateLimitState
│   │   └── file_store.py      # FileRateCoordinationStore
│   ├── retry_policy/
│   │   ├── __init__.py        # StageAwareRetryPolicy, RetryConfig, OperationStage
│   │   └── defaults.py        # DEFAULT_POLICIES
│   └── context_probe/
│       ├── __init__.py        # ContextLengthProber, ProbeResult
│       ├── registry.py        # ModelRegistry protocol
│       └── parsers.py         # Provider-specific error parsing
```

---

## Dependencies

- ADR-038 (reliability taxonomy) — retry policies extend ADR-038 primitives
- ADR-062 (graph execution protocol) — depth, compaction, steering integrate with
  `GraphRun` and `NodeRun`
- ADR-037 (observability taxonomy) — metrics for compaction, rate coordination, probing

## Out of scope

- Distributed rate coordination (Redis-based) — future ADR for multi-node
- Persistent steering history — future ADR
- Compaction strategy evolution (learning what to keep) — future ADR
- Checkpoint/rollback (IMP-046) — separate ADR
- Subgraph DAG validation (static analysis) — future ADR

---

## Gherkin Acceptance Criteria

> **Measurement note (2026-08-19).** These 45 scenarios are tagged `@AC-N` and
> measured by `scripts/check-ac-state.py`. Sixteen are bound to existing tests
> and pass; the other twenty-nine describe design this ADR proposes that is not
> yet built to this contract (`control_scope`, `DepthDescriptor`,
> `CompactionResult` with byte accounting, steering timestamps and role
> scoping, `check_before_call` wait-seconds, `limit_type`, idempotency-keyed
> and custom retry policies, the `llm_call` stage, error-parse and
> binary-search probing, and every executor-integration clause). A test is
> bound only when it proves *every* behavioural clause of its scenario —
> partial proof stays `declared`, because a binding that claims more than its
> test shows is the falsehood this measurement exists to end.
>
> Every bound criterion caps at `passing`, not `reachable`, and that is the
> load-bearing finding: all six implementing modules — `graph.depth`,
> `graph.compaction`, `graph.steering`, `resilience.rate_coordination`,
> `resilience.retry_policy`, `resilience.context_probe` — sit in
> `quality/reachability-baseline.json`. The whole P1 resilience layer is
> built and green and wired into no entry point. The executor runs without
> depth enforcement, without compaction, without steering, without rate
> coordination, without stage-aware retries, and without context probing.

### Feature: IMP-023 — Hierarchical Depth/Role System

```gherkin
Feature: Hierarchical depth/role system for subgraphs
  As a graph executor
  I want depth-based roles enforced at subgraph boundaries
  So that infinite DAG recursion is prevented and control scope is bounded

  Background:
    Given a GraphConfig with max_depth set to 3
    And a root GraphRun at depth 0

  @AC-1
  Scenario: Root role assigned at depth 0
    Given a GraphRun at depth 0
    When the depth role is computed
    Then the role shall be "root"
    And can_spawn shall be true
    And control_scope shall be "full"

  @AC-2
  Scenario: Orchestrator role assigned at intermediate depth
    Given a GraphRun at depth 1
    When the depth role is computed
    Then the role shall be "orchestrator"
    And can_spawn shall be true
    And control_scope shall be "subtree"

  @AC-3
  Scenario: Leaf role assigned at max depth
    Given a GraphRun at depth 3
    When the depth role is computed
    Then the role shall be "leaf"
    And can_spawn shall be false
    And control_scope shall be "node"

  @AC-4
  Scenario: Subgraph invocation at depth exceeding max raises DepthExceededError
    Given a parent GraphRun at depth 2 with max_depth 3
    When a subgraph is invoked creating a child at depth 3
    Then the child shall have role "leaf"
    And the child shall not be able to spawn further subgraphs
    And when the child attempts to spawn a subgraph at depth 4
    Then a DepthExceededError shall be raised

  @AC-5
  Scenario: Depth role computed for max_depth of 1
    Given a GraphConfig with max_depth set to 1
    And a root GraphRun at depth 0
    When the root spawns a subgraph at depth 1
    Then the child shall have role "leaf"
    And can_spawn shall be false

  @AC-6
  Scenario: Orchestrator at depth 2 can spawn children within its subtree
    Given a GraphRun at depth 1 with max_depth 3 and role "orchestrator"
    When it spawns a child at depth 2
    Then the child shall have role "orchestrator"
    And the child can_spawn shall be true

  @AC-7
  Scenario: Leaf node attempting subgraph invocation is blocked
    Given a GraphRun at depth 3 with role "leaf"
    When the leaf node attempts to create a child GraphRun
    Then a DepthExceededError shall be raised
    And the parent NodeRun shall record a ClassifiedError with category PERMANENT

  @AC-8
  Scenario: Depth descriptor is frozen and immutable
    Given a DepthDescriptor with role "orchestrator" at depth 1
    When any code attempts to modify the depth or role fields
    Then a FrozenInstanceError shall be raised
```

### Feature: IMP-044 — Iterative Context Compaction

```gherkin
Feature: Iterative context compaction
  As a long-running graph executor
  I want my blackboard context compacted when it exceeds a threshold
  So that the graph stays within model context limits without losing critical information

  Background:
    Given a CompactionEngine with percentage threshold of 0.8
    And a model context window of 128000 tokens
    And a GraphTask with goal "Refactor the authentication module"

  @AC-9
  Scenario: No compaction when blackboard is under threshold
    Given a blackboard with serialized size of 50000 bytes
    And a context window of 128000 tokens
    When compaction is checked
    Then no compaction shall occur
    And the blackboard shall remain unchanged

  @AC-10
  Scenario: Compaction triggered when blackboard exceeds 80% of context window
    Given a blackboard with serialized size of 110000 bytes
    And a context window of 128000 tokens
    When compaction is invoked
    Then the LLM summarization prompt shall include six sections: Goal, Constraints, Progress, Key Decisions, Next Steps, Critical Context
    And a CompactionResult shall be returned with bytes_after less than bytes_before
    And entries_compacted shall be greater than 0

  @AC-11
  Scenario: Iterative compaction uses previous summary
    Given a blackboard that has been compacted once with _previous_summary "Initial progress: auth module analyzed"
    And the blackboard grows to exceed the threshold again
    When compaction is invoked a second time
    Then the summarization prompt shall include the _previous_summary as "Progress So Far"
    And the new summary shall be an incremental update, not a full re-summarization
    And _previous_summary shall be updated to the new summary

  @AC-12
  Scenario: Critical context is preserved through compaction
    Given a blackboard with entries marked as critical: ["API key rotation scheduled for Tuesday", "Database migration in progress"]
    And the blackboard exceeds the compaction threshold
    When compaction is invoked
    Then the CompactionResult preserved_critical list shall contain "API key rotation scheduled for Tuesday"
    And the CompactionResult preserved_critical list shall contain "Database migration in progress"
    And the summarized context shall include both critical entries

  @AC-13
  Scenario: Compaction result is injected into next node's context
    Given a GraphRun that has just compacted the blackboard
    And the compaction produced summary "Auth refactor 60% complete, OAuth2 flow implemented"
    When the next NodeRun executes
    Then the NodeStrategy.build_user_prompt shall receive the compacted blackboard
    And the prompt shall include the compaction summary
    And the original verbose entries shall be excluded from the prompt

  @AC-14
  Scenario: Original entries retained for audit after compaction
    Given a blackboard with 50 entries before compaction
    When compaction is invoked and produces a summary
    Then all 50 original entries shall be marked compacted=True
    And all 50 entries shall be retained in the blackboard for audit
    And only the summary shall appear in subsequent node contexts

  @AC-15
  Scenario: Compaction handles empty blackboard gracefully
    Given a blackboard with serialized size of 0 bytes
    When compaction is checked
    Then no compaction shall occur
    And no LLM call shall be made
```

### Feature: IMP-025 — Steering / Mid-Run Guidance

```gherkin
Feature: Steering and mid-run guidance
  As a graph operator
  I want to inject guidance into a running graph without interruption
  So that I can correct course without losing progress on expensive long-running jobs

  Background:
    Given a GraphRun with phase "running"
    And the GraphRun has a SteeringQueue

  @AC-16
  Scenario: Steering appends guidance to the queue
    Given a running GraphRun
    When steer("Focus on the database schema next") is called
    Then the SteeringQueue shall contain one entry with guidance "Focus on the database schema next"
    And the entry timestamp shall be within 1 second of the current time

  @AC-17
  Scenario: Guidance appears in next node's context after current node completes
    Given a running GraphRun with Node A currently executing
    When steer("Skip the review step") is called while Node A is in-flight
    Then Node A shall complete execution unaffected
    And the steering queue shall be drained before the next node starts
    And the next node's context shall include guidance "Skip the review step"

  @AC-18
  Scenario: Multiple steering calls accumulate and drain atomically
    Given a running GraphRun
    When steer("Use Python 3.12 features") is called
    And steer("Prefer async/await over threads") is called
    And steer("Add type hints everywhere") is called
    Then the SteeringQueue shall contain three entries
    And when the drain occurs between nodes
    Then all three entries shall be drained as a single SteeringGuidance
    And the next node's context shall include all three guidance strings

  @AC-19
  Scenario: Steering does not interrupt in-flight node
    Given a running GraphRun with Node B currently in RUNNING phase
    When steer("Change approach to iterative") is called
    Then Node B's phase shall remain RUNNING
    And Node B's execution shall continue without any change
    And the guidance shall only appear after Node B completes

  @AC-20
  Scenario: Leaf role ignores steering
    Given a GraphRun at depth 3 with role "leaf" and control_scope "node"
    When steer("Do something different") is called
    Then the steering call shall return without appending to the queue
    And the SteeringQueue shall remain empty

  @AC-21
  Scenario: Orchestrator can steer within its subtree only
    Given a root GraphRun at depth 0 with child orchestrator at depth 1
    When the orchestrator calls steer("Prioritize subgraph A")
    Then the guidance shall appear in nodes within the orchestrator's subtree
    And the guidance shall NOT appear in sibling subtrees at the same depth
    And the guidance shall NOT appear in the root's direct nodes

  @AC-22
  Scenario: Steering on a completed graph is a no-op
    Given a GraphRun with phase "completed"
    When steer("Post-completion guidance") is called
    Then the SteeringQueue shall remain empty
    And no error shall be raised
```

### Feature: IMP-008 — Cross-Process Rate Limit Coordination

```gherkin
Feature: Cross-process rate limit coordination
  As a concurrent process making API calls
  I want to coordinate rate limit back-off with other processes via a shared file
  So that we avoid thundering-herd retries on shared API keys

  Background:
    Given a FileRateCoordinationStore at path "/tmp/maistro-rate-coordination.json"
    And a RateCoordinator using that store

  @AC-23
  Scenario: No wait when no rate limit is active
    Given a provider "openai" with no entry in the rate coordination file
    When check_before_call is called for "openai"
    Then it shall return 0.0
    And the process shall proceed with the API call immediately

  @AC-24
  Scenario: Process waits when another process recorded a rate limit
    Given a RateLimitState for "openai" with reset_at 60 seconds in the future
    And the state is written to the coordination file
    When check_before_call is called for "openai"
    Then it shall return approximately 60.0 seconds to wait
    And the process should delay its API call accordingly

  @AC-25
  Scenario: Recording a rate limit from a 429 response
    Given a process receives a 429 response from "anthropic" with Retry-After of 30 seconds
    When record_rate_limit is called with provider "anthropic" and retry_after_seconds 30
    Then the coordination file shall contain an entry for "anthropic"
    And reset_at shall be approximately 30 seconds from now
    And limit_type shall be "rpm"

  @AC-26
  Scenario: Stale entries are pruned on read
    Given a RateLimitState for "openai" with reset_at 10 seconds ago
    And the state is written to the coordination file
    When check_before_call is called for "openai"
    Then it shall return 0.0
    And the stale entry shall be removed from the coordination file

  @AC-27
  Scenario: Concurrent reads do not block each other
    Given a coordination file with an entry for "openai"
    When process A calls check_before_call for "openai"
    And process B calls check_before_call for "openai" simultaneously
    Then both reads shall succeed using shared locks
    And neither read shall block the other

  @AC-28
  Scenario: Write uses atomic file replacement
    Given a coordination file with existing entries for "openai" and "anthropic"
    When process A records a rate limit for "google"
    Then the write shall use write-to-temp-and-rename
    And the existing entries for "openai" and "anthropic" shall be preserved
    And the new entry for "google" shall be added

  @AC-29
  Scenario: Different providers tracked independently
    Given a RateLimitState for "openai" with reset_at 30 seconds from now
    And no entry for "anthropic"
    When check_before_call is called for "anthropic"
    Then it shall return 0.0
    And the "openai" entry shall remain unaffected

  @AC-30
  Scenario: Staleness threshold prunes very old entries
    Given a RateLimitState for "openai" with updated_at 400 seconds ago
    And a staleness_threshold of 300 seconds
    When check_before_call is called for "openai"
    Then the entry shall be considered stale and ignored
    And the entry shall be pruned from the coordination file
```

### Feature: IMP-009 — Stage-Aware Retry Policies

```gherkin
Feature: Stage-aware retry policies
  As a graph executor performing different types of operations
  I want retry behaviour tailored to the operation stage
  So that reads retry aggressively, evaluations retry cautiously, and writes do not retry by default

  Background:
    Given a StageAwareRetryPolicy with default policies

  @AC-31
  Scenario: Read stage retries up to 3 times with 250ms fixed delay
    Given a read operation that fails with a transient network error
    When should_retry is called with stage "read" and attempt 0
    Then it shall return true
    And delay_for shall return 0.25 seconds
    When should_retry is called with stage "read" and attempt 1
    Then it shall return true
    And delay_for shall return 0.25 seconds
    When should_retry is called with stage "read" and attempt 2
    Then it shall return true
    When should_retry is called with stage "read" and attempt 3
    Then it shall return false

  @AC-32
  Scenario: Evaluate stage retries up to 2 times with exponential backoff
    Given an evaluate operation that fails with a transient error
    When should_retry is called with stage "evaluate" and attempt 0
    Then it shall return true
    And delay_for shall return 1.0 seconds
    When should_retry is called with stage "evaluate" and attempt 1
    Then it shall return true
    And delay_for shall return 2.0 seconds
    When should_retry is called with stage "evaluate" and attempt 2
    Then it shall return false

  @AC-33
  Scenario: Write stage does not retry by default
    Given a write operation that fails with a transient error
    When should_retry is called with stage "write" and attempt 0
    Then it shall return false
    And no retry shall occur

  @AC-34
  Scenario: Write stage retries with explicit idempotency key
    Given a write operation that fails with a transient error
    And the operation has an idempotency key
    When should_retry is called with stage "write", attempt 0, and has_idempotency_key true
    Then it shall return false
    # ...because the default write max_attempts is 1 even with an idempotency key
    And a custom policy with max_attempts greater than 1 would return true

  @AC-35
  Scenario: Non-transient errors are never retried regardless of stage
    Given a read operation that fails with a 401 Unauthorized error
    When should_retry is called with stage "read" and attempt 0
    Then it shall return false
    And no retry shall occur

  @AC-36
  Scenario: Custom policies override defaults per stage
    Given a StageAwareRetryPolicy with a custom write policy of max_attempts 2
    And the custom write policy has idempotency_required true
    When a write operation fails with a transient error and has an idempotency key
    Then should_retry shall return true for attempt 0
    And should_retry shall return false for attempt 1

  @AC-37
  Scenario: LLM call stage uses exponential backoff matching ADR-038
    Given an LLM call operation that fails with a 429 rate limit error
    When should_retry is called with stage "llm_call" and attempt 0
    Then it shall return true
    And delay_for shall return 2.0 seconds
    When delay_for is called with stage "llm_call" and attempt 2
    Then it shall return 8.0 seconds
    And the delay shall be capped at max_delay_s of 16.0 seconds
```

### Feature: IMP-016 — Context Length Probing

```gherkin
Feature: Context length probing
  As a graph executor using an unfamiliar model
  I want to probe the model's maximum context length with tiered requests
  So that I can size prompts and compaction thresholds accurately

  Background:
    Given a ContextLengthProber with probe tiers [4096, 16384, 65536, 131072, 204800]
    And a model registry with no cached limit for "newmodel-v1"

  @AC-38
  Scenario: Probing returns cached limit without making API calls
    Given a model registry with a cached context limit of 32768 for "known-model"
    When probe is called for "known-model"
    Then the ProbeResult context_limit shall be 32768
    And method shall be "cached"
    And no LLM API call shall be made

  @AC-39
  Scenario: Probing succeeds at all tiers and returns maximum tier
    Given a model "newmodel-v1" that accepts all prompt sizes up to 204800 tokens
    When probe is called for "newmodel-v1"
    Then the prober shall send requests at each tier: 4K, 16K, 64K, 128K, 200K
    And all requests shall succeed
    And the ProbeResult context_limit shall be 204800
    And method shall be "probe_success"
    And the limit shall be cached in the model registry

  @AC-40
  Scenario: Probing parses actual limit from overflow error
    Given a model "newmodel-v1" that accepts 4K but fails at 16K with error "maximum context length is 8192 tokens"
    When probe is called for "newmodel-v1"
    Then the prober shall succeed at 4K
    And the prober shall fail at 16K
    And the prober shall parse 8192 from the error message
    And the ProbeResult context_limit shall be 8192
    And method shall be "error_parse"
    And 8192 shall be cached in the model registry

  @AC-41
  Scenario: Probing uses binary search when error parsing fails
    Given a model "newmodel-v1" that accepts 4K but fails at 16K with unparseable error
    When probe is called for "newmodel-v1"
    Then the prober shall succeed at 4K
    And the prober shall fail at 16K
    And error parsing shall return None
    And the prober shall binary search between 4096 and 16384
    And the ProbeResult method shall be "binary_search"
    And the discovered limit shall be cached in the model registry

  @AC-42
  Scenario: Probing stops at first failure and does not attempt higher tiers
    Given a model "small-model" that fails at 4096 tokens with error "context length is 2048"
    When probe is called for "small-model"
    Then the prober shall attempt only the first tier (4K)
    And shall NOT attempt 16K, 64K, 128K, or 200K
    And the ProbeResult context_limit shall be 2048
    And method shall be "error_parse"

  @AC-43
  Scenario: Probed limit feeds into compaction threshold calculation
    Given a probed context limit of 8192 tokens for "newmodel-v1"
    And a PercentageThreshold of 0.8
    When the compaction threshold is calculated
    Then the compaction threshold shall be 6553 tokens (8192 * 0.8)
    And compaction shall trigger when the blackboard exceeds 6553 tokens

  @AC-44
  Scenario: Concurrent probes for the same model use cached result
    Given two concurrent calls to probe for "newmodel-v1"
    And the model registry has no cached limit
    When both calls execute
    Then only one probe sequence shall actually run
    And the second call shall use the cached result from the first
    And the ProbeResult for both calls shall have the same context_limit

  @AC-45
  Scenario: Probe prompt is approximately the target token count
    Given a probe tier of 65536 tokens
    When the prober generates a probe prompt
    Then the prompt shall contain approximately 65536 tokens
    And the prompt shall be a repeatable padding pattern (not random noise)
    And the prompt shall request max_tokens of 1 to minimize waste
```

---

## Source references

- `packages/maistro-core/src/maistro/graph/executor.py` — existing executor (ADR-062 target)
- `packages/maistro-core/src/maistro/resilience/` — existing resilience module (ADR-038)
- `docs/analysis/COMPETITIVE-IMPROVEMENTS.md` — IMP-008, IMP-009, IMP-016, IMP-023, IMP-025, IMP-044
- Hermes `SubgraphRegistry` — depth-based role assignment pattern
- Pi `ContextManager` — iterative summarization pattern
- OpenClaw `RateLimiter` — cross-process coordination pattern

## Links

- PR: (pending)
- Issue: (pending)
- Follow-up ADRs: ADR-047 (distributed rate coordination), ADR-048 (persistent execution log)
