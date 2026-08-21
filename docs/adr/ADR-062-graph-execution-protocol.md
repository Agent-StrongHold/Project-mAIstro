---
id: ADR-062
title: Graph Execution Protocol
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-19
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-19
  - status: Accepted
    date: 2026-05-19
---

# ADR-062: Graph Execution Protocol

**Status:** Accepted
**Date:** 2026-05-19
**Tranche:** T4
**Depends on:** IMP-001 (error classifier, `maistro/resilience/classifier.py`)

---

## Context

The graph executor (`maistro/graph/executor.py`, 630 LOC) is a single async function
(`run_graph`) with module-level state (global circuit breaker) and switch-statement
dispatch on `AgentRole` enums. It has three structural problems:

1. **No per-node observability.** `GraphNodeResult` captures `success: bool`, `output:
   str`, and `tokens_used: int`. There is no record of what input a node received, what
   raw LLM response it produced, how long it took, what errors occurred on retries, or
   what classified error category caused failure. Without this data the evolution engine
   cannot correlate input→output quality per-node and cannot optimize prompts, model
   selection, or topology.

2. **No lifecycle enforcement.** `run_graph` can raise `LLMProviderError` (non-retryable
   errors escape `asyncio.gather`), has no cancellation handling, no phase tracking, and
   no guaranteed terminal state. A cancelled or crashed run leaves no trace.

3. **Node behavior is scattered.** Prompt construction, output parsing, scoring, and
   state update logic live as if/elif chains and dict lookups in the executor. Adding a
   new node type or evolving node behavior requires modifying the executor itself.

## Decision

Introduce a three-layer execution protocol:

| Layer | Class | Responsibility |
|-------|-------|----------------|
| **Orchestrator** | `GraphRun` | Phase machine, iteration budget, cancellation, guaranteed completion |
| **Executor** | `NodeRun` | Per-node lifecycle, retry, circuit breaker, timing, full I/O recording |
| **Behavior** | `NodeStrategy` (protocol) | Role-specific prompt building, output parsing, scoring, state update |

Beam search is an evolvable parameter on `NodeRun`, not a separate dispatch path.

**What we are building:**
- `GraphPhase` and `NodePhase` enums
- `NodeStrategy` protocol with 5 built-in implementations
- `NodeRun` dataclass — both executor and audit record
- `GraphRun` class — orchestrator with phase machine
- `IterationBudget` — shared counter across parent + subgraphs
- Full per-node telemetry: input, output, raw response, timing, error classifications

**What we are NOT porting:**
- No persistent execution log (future ADR)
- No subgraph nesting enforcement (IMP-023, separate)
- No WebSocket streaming (stays in hive-conductor, consumes events)
- No checkpoint/rollback (IMP-046, separate)

## Interface (spec)

### Phases

```python
class NodePhase(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

class GraphPhase(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
```

### NodeStrategy protocol

```python
class NodeStrategy(Protocol):
    role: AgentRole
    output_type: type[BaseModel]

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str: ...

    def score_output(self, output: BaseModel) -> float: ...

    def update_blackboard(
        self,
        output: BaseModel,
        blackboard: GraphBlackboard,
    ) -> GraphBlackboard: ...
```

Five built-in strategies: `PlannerStrategy`, `CoderStrategy`, `ReviewerStrategy`,
`ScoutStrategy`, `ConductorStrategy`. Registered in `STRATEGY_REGISTRY:
dict[AgentRole, NodeStrategy]`.

### NodeRun

```python
@dataclass
class NodeRun:
    # Identity
    run_id: str
    node_id: str
    role: AgentRole
    strategy: NodeStrategy
    beam_width: int = 1

    # Config snapshot
    model: str = "default"
    temperature: float | None = None
    system_prompt: str = ""
    user_prompt: str = ""
    blackboard_snapshot: GraphBlackboard | None = None

    # Lifecycle
    phase: NodePhase = NodePhase.PENDING
    phase_log: list[tuple[NodePhase, float]] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3

    # Telemetry
    started_at: float | None = None
    completed_at: float | None = None
    duration_s: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    error_classifications: list[ClassifiedError] = field(default_factory=list)

    # Beam search
    beam_candidates: list[BeamCandidate] = field(default_factory=list)
    beam_selected: int = -1

    # Output
    raw_response: str | None = None
    parsed_output: BaseModel | None = None
    parse_error: str | None = None
    score: float = 0.0
    classified_error: ClassifiedError | None = None

    # Circuit breaker (per-node)
    circuit: CircuitBreaker = field(default_factory=lambda: CircuitBreaker())

    # Execution
    async def execute(
        self,
        llm_call: Callable[..., Awaitable[str]],
        timeout: float = 120.0,
        backoff_config: BackoffConfig | None = None,
    ) -> None:
        """
        Execute the node. Guaranteed to transition to SUCCEEDED, FAILED,
        or CANCELLED. Never raises.
        """
        ...

    def cancel(self) -> None:
        """Request cancellation. Phase transitions to CANCELLED."""
        ...

    def to_result(self) -> GraphNodeResult:
        """Convert to wire format for API responses."""
        ...
```

### BeamCandidate

```python
@dataclass
class BeamCandidate:
    index: int
    raw_response: str
    parsed_output: BaseModel | None
    parse_error: str | None
    score: float
    tokens_used: int
    duration_s: float
    error: Exception | None = None
```

### IterationBudget

```python
class IterationBudget:
    def __init__(self, max_iterations: int) -> None: ...
    def consume(self, count: int = 1) -> bool: ...
        """Returns True if budget remains, False if exhausted."""
    @property
    def remaining(self) -> int: ...
    @property
    def exhausted(self) -> bool: ...
```

### GraphRun

```python
class GraphRun:
    # Identity
    run_id: str
    task: GraphTask
    config: GraphConfig

    # Lifecycle
    phase: GraphPhase = GraphPhase.IDLE
    phase_log: list[tuple[GraphPhase, float]] = field(default_factory=list)

    # Shared state
    blackboard: GraphBlackboard
    iteration_budget: IterationBudget

    # All node executions (append-only audit trail)
    node_runs: list[NodeRun]

    # Accumulated state
    plan: PlanOutput | None = None
    code: CodeOutput | None = None
    review: ReviewOutput | None = None

    # Final result (set after completion)
    result: HyperagentOutput | None = None
    classified_error: ClassifiedError | None = None

    # Events (for WebSocket streaming, logging, etc.)
    event_callbacks: list[Callable[[GraphEvent], Awaitable[None]]] = field(default_factory=list)

    # Execution
    async def start(
        self,
        llm_call: Callable[..., Awaitable[str]],
        model: str = "default",
        temperature: float | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_config: BackoffConfig | None = None,
    ) -> HyperagentOutput:
        """
        Execute the graph. Guaranteed to return HyperagentOutput (never raises).
        Sets self.result and transitions to COMPLETED or FAILED.
        """
        ...

    async def cancel(self) -> None:
        """
        Cancel all in-flight NodeRuns. Transitions to CANCELLING, then
        to COMPLETED or FAILED once all nodes finish.
        """
        ...

    # Queries
    def node_runs_for_role(self, role: AgentRole) -> list[NodeRun]: ...
    def latest_node_run(self, role: AgentRole) -> NodeRun | None: ...
    def duration_s(self) -> float: ...
    def total_tokens(self) -> int: ...
    def success_rate(self) -> float: ...
```

### GraphEvent

```python
class GraphEvent(BaseModel):
    # Past-tense per the ADR-037 naming convention (matches the emitted code names).
    type: str  # "graph_started", "node_started", "node_completed", "node_retrying", "node_failed", "graph_completed", "graph_failed"
    run_id: str
    node_id: str | None = None
    role: AgentRole | None = None
    phase: str | None = None
    timestamp: float
    detail: dict[str, Any] = Field(default_factory=dict)
```

### Top-level API (replaces `run_graph`)

```python
async def run_graph(
    task: GraphTask,
    llm_call: Callable[..., Awaitable[str]],
    *,
    model: str = "default",
    max_retries: int = 3,
    timeout: float = 120.0,
    backoff_config: BackoffConfig | None = None,
    parallel_generations: int = 1,
    temperature: float | None = None,
    run_id: str | None = None,
    event_callbacks: list[Callable[[GraphEvent], Awaitable[None]]] | None = None,
) -> HyperagentOutput:
    """Create and execute a GraphRun. Returns HyperagentOutput (never raises)."""
    ...
```

Signature is backward-compatible. `parallel_generations` maps to `beam_width` on
each `NodeRun`. `event_callbacks` is new and optional.

## Acceptance criteria

- [ ] `run_graph` never raises — all errors captured in `HyperagentOutput(success=False)`
- [ ] Every `NodeRun` records: input prompts, raw response, parsed output, timing,
      error classifications, retry history, beam candidates
- [ ] `GraphRun.phase` transitions are logged and append-only
- [ ] `NodeRun.phase` transitions are logged and append-only
- [ ] `IterationBudget` shared across all nodes in a run, consumes on each LLM call
- [ ] `asyncio.CancelledError` produces COMPLETED result with partial node data
- [ ] Per-node circuit breaker (not global)
- [ ] Error classification (IMP-001) used for retry/raise decisions
- [ ] Jittered backoff (IMP-003) used for retry delays
- [ ] Beam search produces `beam_candidates` list with scores, best selected
- [ ] `beam_width` is an evolvable parameter — can be set per-node via `NodeConfig`
- [ ] `NodeStrategy` protocol allows new node types without modifying executor
- [ ] All 5 built-in strategies produce identical behavior to current executor
- [ ] Existing tests pass without modification

## Test plan

| Test | Type | Covers |
|------|------|--------|
| `test_node_run_succeeds` | unit | NodeRun happy path: pending→running→succeeded |
| `test_node_run_retries_transient` | unit | Retries on transient error, succeeds on 2nd attempt |
| `test_node_run_fails_permanent` | unit | Permanent error → failed, no retry |
| `test_node_run_cancellation` | unit | Cancel mid-execution → cancelled phase |
| `test_node_run_beam_search` | unit | beam_width=3, best scored output selected |
| `test_node_run_records_input_output` | unit | system_prompt, user_prompt, raw_response, parsed_output all recorded |
| `test_node_run_timing` | unit | started_at, completed_at, duration_s set correctly |
| `test_node_run_error_classification` | unit | ClassifiedError recorded on each retry |
| `test_graph_run_happy_path` | integration | Full planner→coder→reviewer graph succeeds |
| `test_graph_run_cancellation` | integration | Cancel mid-graph, partial results preserved |
| `test_graph_run_iteration_budget` | integration | Budget exhaustion stops graph gracefully |
| `test_graph_run_node_failure_continues` | integration | One node fails, graph continues with other paths |
| `test_graph_run_phase_transitions` | integration | idle→running→completed, all logged |
| `test_graph_run_event_callbacks` | integration | Events emitted for each node start/complete |
| `test_graph_run_never_raises` | integration | Even on catastrophic error, returns HyperagentOutput |
| `test_backward_compat_run_graph` | integration | Existing run_graph signature works unchanged |
| `test_strategy_registry` | unit | All 5 roles have strategies, correct output_types |
| `test_planner_strategy` | unit | Prompt contains task description and constraints |
| `test_coder_strategy` | unit | Prompt contains plan and subtasks |
| `test_reviewer_strategy` | unit | Prompt contains code output and files changed |
| `test_scout_strategy` | unit | Prompt contains workspace and iteration |
| `test_custom_strategy` | unit | New strategy can be registered and used |

## Dependencies

- IMP-001 (`maistro/resilience/classifier.py`) — error classification
- IMP-003 (`maistro/resilience/backoff.py`) — jittered backoff

## Out of scope

- Persistent execution log / trajectory recording (IMP-048)
- Subgraph nesting depth limits (IMP-023)
- Orphaned run recovery (IMP-026)
- WebSocket streaming (hive-conductor concern, consumes GraphEvent)
- Configurable hooks before/after nodes (IMP-082)
- Steerable mid-run guidance (IMP-025)

## File layout

```
maistro/graph/
├── types.py          # Existing Pydantic models (extended: beam_width on NodeConfig)
├── phases.py         # GraphPhase, NodePhase enums
├── events.py         # GraphEvent model
├── strategy.py       # NodeStrategy protocol + 5 built-in + STRATEGY_REGISTRY
├── node.py           # NodeRun, BeamCandidate, IterationBudget
├── run.py            # GraphRun class
├── executor.py       # run_graph() thin wrapper around GraphRun
├── scout.py          # DELETED — merged into ScoutStrategy
└── optimizer.py      # Unchanged
```

## Source references

- `packages/maistro-core/src/maistro/graph/executor.py` — existing executor being replaced
- `packages/maistro-core/src/maistro/graph/scout.py` — merging into ScoutStrategy
- `packages/maistro-core/src/maistro/graph/types.py` — extended with beam_width
- `docs/analysis/COMPETITIVE-IMPROVEMENTS.md` — IMP-010, IMP-022, IMP-021, IMP-024
- Hermes `_dispatch_node_single` retry + circuit breaker pattern
- Pi `AgentHarness` phase machine pattern
- OpenClaw `SubgraphRegistry` lifecycle tracking pattern

## Links

- PR: (pending)
- Issue: (pending)
- Follow-up work (unwritten): persistent execution log; subgraph nesting
