---
id: SPEC-070226-b624
title: "General task planner & orchestration: SuperPlanner waves as Repertoire ensemble"
repo: maistro-engine
kind: spec
status: In Progress
created: 2026-07-02
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-062
  - maistro-engine#ADR-070
  - maistro-engine#ADR-071
  - maistro-engine#SPEC-184
implements:
  - maistro-engine#ADR-071
related:
  - maistro-engine#ADR-052
  - maistro-engine#ADR-056
  - maistro-engine#ADR-066
  - maistro-engine#SPEC-070226-b624
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/orchestrator/waves/test_ensemble.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-02
  - status: In Progress
    date: 2026-07-29
---

# SPEC-070226-b624: General task planner & orchestration — SuperPlanner waves as Repertoire ensemble

## Context

ADR-071 specifies SuperPlanner as a general-purpose task planner that orchestrates agent waves
(parallel branches of execution) using the Repertoire pattern (ADR-070). A wave is a set of
concurrent, mutually-isolated sub-agents attempting the same task in parallel; only the best
result (per a comparator) is retained, and the rest are discarded.

SuperPlanner exists as a skeleton; this SPEC completes its implementation: wave provisioning,
parallel execution with isolation, result aggregation, and integration with the graph executor
(ADR-062) and crash recovery (ADR-056).

## Goals

- SuperPlanner orchestrates waves (parallel agent teams) via the Repertoire pattern.
- Each wave is a `GraphRun` with isolated context (no shared state between wave branches).
- After all waves finish (or timeout), SuperPlanner compares results and returns the best.
- Waves are checkpointed (ADR-056) so a crash mid-wave can resume without rerunning all agents.
- SuperPlanner itself is a graph node strategy (ADR-062), callable from any graph.

## Non-goals

- MCTS/Monte-Carlo tree search (ADR-071 follow-up for later).
- Speculative execution (defer to Phase 2).
- Reconciliation/voting across wave results (Phase 2; for now: comparator picks single winner).

## Decision

### Wave definition and SuperPlanner structure

```python
@dataclass
class Wave:
    """A parallel branch with one or more sub-agents."""
    id: str
    agent_ids: list[str]  # agents in this wave (executed in sequence within the wave)
    context: AgentContext  # isolated context for this wave
    timeout_ms: int = 30000
    priority: int = 0  # execution priority (0=normal, higher=run first)

@dataclass
class SuperPlannerConfig:
    """Configuration for wave orchestration."""
    max_waves: int = 3  # max parallel waves
    result_comparator: Callable[[list[TaskResult]], TaskResult]  # pick best result
    timeout_ms: int = 60000  # total orchestration timeout
    checkpoint_interval_ms: int = 5000
    recovery_strategy: Literal["resume", "restart"] = "resume"

class SuperPlanner(NodeStrategy):
    """Execute a task via multiple waves, return the best result."""
    
    async def execute(
        self,
        task: Task,
        context: AgentContext,
        config: SuperPlannerConfig
    ) -> TaskResult:
        """
        1. Partition the task into waves (via an expander agent or config).
        2. Execute waves in parallel.
        3. Checkpoint after each wave completes.
        4. Compare results, return best.
        """
        waves = self.expand_to_waves(task, config.max_waves)
        
        # Checkpoint: record initial wave plan
        checkpoint = Checkpoint(
            task_id=task.id,
            state="waves_planned",
            waves=waves
        )
        await self.checkpoint_store.save(checkpoint)
        
        # Execute waves in parallel
        wave_results = await asyncio.gather(
            *[self._run_wave(wave) for wave in waves],
            return_exceptions=True
        )
        
        # Checkpoint: record completion
        await self.checkpoint_store.save(Checkpoint(
            task_id=task.id,
            state="waves_complete",
            results=wave_results
        ))
        
        # Compare and return best
        best_result = config.result_comparator(
            [r for r in wave_results if not isinstance(r, Exception)]
        )
        return best_result
    
    async def _run_wave(self, wave: Wave) -> TaskResult:
        """Execute a single wave (sequence of agents in parallel isolation)."""
        graph_run = GraphRun(nodes=[...], context=wave.context)
        executor = GraphExecutor(graph_run, checkpoint_store=self.checkpoint_store)
        
        try:
            return await executor.run(timeout_ms=wave.timeout_ms)
        except Exception as e:
            # Wave failed; log and return error
            emit("wave.failed", wave_id=wave.id, error=str(e))
            raise
```

### Wave expansion and provisioning

```python
class WaveExpander(Protocol):
    """Expand a task into waves (parallel branches)."""
    async def expand(self, task: Task, max_waves: int) -> list[Wave]:
        """Return a list of waves that collectively solve the task."""
        ...

# Example: multi-strategy wave expansion
class MultiStrategyExpander(WaveExpander):
    """Create waves that use different reasoning strategies."""
    strategies = [
        "chain_of_thought",
        "tree_of_thought",
        "self_critique"
    ]
    
    async def expand(self, task: Task, max_waves: int) -> list[Wave]:
        waves = []
        for i, strategy in enumerate(self.strategies[:max_waves]):
            wave = Wave(
                id=f"wave_{i}",
                agent_ids=[f"agent_{strategy}"],
                context=AgentContext(
                    **task.context,
                    reasoning_strategy=strategy  # isolated config
                )
            )
            waves.append(wave)
        return waves
```

### Result aggregation and comparison

```python
class ResultComparator(Protocol):
    """Compare wave results and pick the best."""
    def compare(self, results: list[TaskResult]) -> TaskResult:
        ...

class QualityComparator(ResultComparator):
    """Pick the result with the highest quality score."""
    
    def compare(self, results: list[TaskResult]) -> TaskResult:
        # Assume each result has a quality_score (0-1)
        return max(results, key=lambda r: r.metadata.get("quality_score", 0))

class LLMJudgeComparator(ResultComparator):
    """Use an LLM to judge which result is better."""
    
    async def compare(self, results: list[TaskResult]) -> TaskResult:
        if len(results) == 1:
            return results[0]
        
        # Ask an LLM judge to score each result
        prompt = f"""
        The task was: {results[0].task}
        
        Option A: {results[0].output}
        Option B: {results[1].output}
        
        Which is better and why?
        """
        # Call LLM, parse score, return best
        ...
```

### Integration with graph executor (ADR-062)

```python
# SuperPlanner is a NodeStrategy in the graph:
@dataclass
class NodeSpec:
    id: str
    strategy: NodeStrategy  # can be SuperPlanner, DirectAgent, etc.
    inputs: dict[str, str]
    ...

graph = GraphSpec(
    nodes=[
        NodeSpec(id="plan", strategy=SuperPlanner(config=...)),
        NodeSpec(id="execute", strategy=DirectAgent(...), inputs={"task": "plan.output"})
    ]
)

executor = GraphExecutor(GraphRun(graph))
result = await executor.run()
```

### Checkpointing and crash recovery (ADR-056)

```python
# SuperPlanner writes checkpoints before and after wave execution:
#   state: "waves_planned" → (async execute) → "waves_complete"
#
# On resume (crash recovery):
#   1. If state is "waves_planned", resume from wave 1 (waves not started yet).
#   2. If state is "waves_complete", use the saved results (don't re-run).

async def recover_from_checkpoint(checkpoint: Checkpoint) -> TaskResult:
    if checkpoint.state == "waves_complete":
        # Waves already finished; just compare and return
        comparator = get_comparator(...)
        return comparator.compare(checkpoint.results)
    else:
        # Re-run from the checkpoint (waves_planned)
        return await super_planner.execute(...)
```

### Observability (ADR-037)

```python
emit("waves.planned", task_id=task.id, wave_count=len(waves))
emit("wave.started", wave_id=wave.id)
emit("wave.completed", wave_id=wave.id, quality_score=result.quality_score)
emit("waves.compared", task_id=task.id, winner=best_result.wave_id)
```

## Implementation status (corrected 2026-07-29)

Front matter was corrected from `Implemented` to `In Progress` (D2/#290):
`LLMJudgeComparator.compare` (`packages/maistro-core/src/maistro/orchestrator/waves/ensemble.py`)
unconditionally raises `NotImplementedError("LLMJudgeComparator is a Phase 2 stub
(SPEC-070226-b624)")` — deliberately, per its own docstring. It is exported from
the package's public surface but is not instantiated anywhere in production; the
comparator that ships is the deterministic `QualityComparator` in the same file.
No acceptance criterion below is checked off; none has been verified against
running code.

## Acceptance criteria

- [ ] SuperPlanner.expand() produces N waves (configurable, default 3) with isolated contexts
      (property: no state shared between waves).
- [ ] A single wave with one agent produces the same result as running that agent alone
      (baseline test; no parallelism overhead).
- [ ] Three waves with the same task and different strategies produce different outputs
      (stochasticity test; same seed in wave A produces same result in wave B).
- [ ] SuperPlanner compares results and returns exactly one (the best per comparator).
- [ ] A wave that times out (> 30s) is marked as failed; other waves continue.
- [ ] Checkpoint saved before wave execution; on crash recovery, waves are not re-run if
      checkpoint state is "waves_complete".
- [ ] SuperPlanner is a valid NodeStrategy in a GraphRun (types check, integrates with
      graph executor without special-case code).
- [ ] Emitted events (waves.planned, wave.started, waves.compared) follow ADR-037 format.

## Testing

- Unit: `MultiStrategyExpander.expand()` produces N waves with distinct configs (property:
  context.reasoning_strategy varies per wave).
- Unit: `QualityComparator.compare()` picks the highest-scoring result (deterministic).
- Integration: a graph with a SuperPlanner node + three DirectAgent nodes; SuperPlanner returns
  the best result and all waves complete without error.
- Integration: crash recovery — simulate a crash mid-wave, resume from checkpoint, confirm waves
  are not re-run.
- Property (formal/): "SuperPlanner with N=1 wave produces same result as DirectAgent" (use
  Hypothesis to generate tasks).
- Load test: 10 concurrent SuperPlanner invocations, each with 3 waves; verify no thread-safety
  or context-crossing issues.

## Open questions

- Should waves be constrained to use specific strategies, or is wave expansion a free-form search
  over the agent roster? (Leaning: specific strategies first, free-form search in Phase 2.)
- How does SuperPlanner interact with the Builders DAG (ADR-099)? Can a Builder use SuperPlanner
  as part of its pipeline? (Deferred to Phase 2; Builders and SuperPlanner are independent for now.)
- Should result comparison emit a detailed report (why option A vs B), or just the winner?
  (Emit winner only for Phase 1, report in Phase 2 for LLM observability.)

## References

- [ADR-071: General Task Planner & Orchestration](../adr/ADR-071-task-planner-orchestration.md)
- [ADR-070: Repertoire Pattern](../adr/ADR-070-repertoire-pattern.md)
- [ADR-062: Graph Execution Protocol](../adr/ADR-062-graph-execution-protocol.md)
- [ADR-056: Task crash recovery](../adr/ADR-056-task-crash-recovery.md)
- [ADR-052: Parallel agent waves](../adr/ADR-052-parallel-agent-waves.md)
