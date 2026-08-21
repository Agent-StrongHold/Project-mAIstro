"""Builders pipeline as a DAG with gated verify-and-revise loops.

Implements SPEC-070226-82ea (which implements ADR-099) on top of the two
layers that already exist:

- :mod:`maistro.builders.graph` / :mod:`maistro.builders.graph_executor` —
  the Epic-15 pipeline graph and its wave executor with executor-level
  revision (SPEC-201). This module does **not** re-implement stage
  execution; it *describes* a builders pipeline (stages, edges, gates,
  loop-back targets) and lowers that description onto the existing
  :class:`~maistro.builders.graph.PipelineGraph` +
  :class:`~maistro.builders.graph_executor.GraphPipelineExecutor`.
- :mod:`maistro.graph` — the ADR-062 graph execution protocol.
  :func:`builders_dag_to_graph` converts a :class:`BuildersDAG` into the
  ADR-062 graph description (``GraphConfig``, exposed here under the SPEC's
  ``GraphSpec`` name) so the same pipeline can run as a
  :class:`~maistro.graph.run.GraphRun`.

Loop-back control flow
----------------------
ADR-099: "the dependency graph itself stays acyclic; revision is an
executor-level re-offer, not a graph cycle." A gated stage therefore loops
back to an *ancestor* (its ``loop_target``); the executor clears the target
and all completed descendants, injects ``<stage>_feedback`` into the run
context, and re-offers them — bounded by the gate's ``max_iterations`` and
the run's shared :class:`~maistro.graph.node.IterationBudget`. The SPEC's
``review → revise → test`` loop is realized by placing the ``revise`` stage
as a *skippable ancestor* of ``test`` (skipped on the first pass, executed
on every revision pass), which keeps the dependency edges acyclic.

Gate exhaustion
---------------
When a gate still fails after ``max_iterations`` loop-backs, its
``exhausted`` policy decides the outcome — ``"fail"`` fails the run
explicitly (the safe default per ADR-099's ``gate_exhausted`` policy) and
``"continue"`` force-forwards past the gate (the SPEC's ``apply_gate``
pseudo-code; used by the built-in review gate so a downstream cleanup /
human-escalation stage remains reachable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import GraphPipelineExecutor, PipelineDispatcher
from maistro.graph.node import IterationBudget
from maistro.graph.types import AgentRole, GraphConfig, GraphEdge, NodeConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

# The ADR-062 graph description type. The SPEC calls this ``GraphSpec``;
# maistro.graph's canonical name is ``GraphConfig`` — alias, don't fork.
GraphSpec = GraphConfig

GateExhaustedPolicy = Literal["fail", "continue"]
FailureKind = Literal["invalid_graph", "stage_failed", "gate_exhausted", "budget_exhausted"]

#: Default coverage threshold (percent) for :func:`coverage_gate`. A default,
#: not a constant of nature — callers inject their own threshold.
DEFAULT_COVERAGE_THRESHOLD = 80.0
DEFAULT_GATE_MAX_ITERATIONS = 3

_CLEAN_REVIEW_SIGNALS = ("no violations", "lgtm", "approved", "all checks pass", "clean")


@dataclass(frozen=True)
class StageResult:
    """What a :class:`Gate` predicate sees after a stage completes.

    ``output`` is the stage's own output text; ``context`` is the full run
    context (stage outputs keyed by stage name, run parameters, metrics
    written by dispatchers/hooks, and ``<stage>_feedback`` entries).
    ``iterations`` counts prior evaluations of this gate in this run
    (0 on the first pass).
    """

    stage: str
    output: str
    context: Mapping[str, Any]
    iterations: int = 0


@dataclass(frozen=True)
class Gate:
    """A verifiable acceptance predicate evaluated after a stage completes.

    ``predicate`` returns True when the stage passed the gate (continue to
    the next stage) and False to loop back to the DAG's ``loop_target`` for
    this stage. ``max_iterations`` is the safety valve: the number of
    loop-backs permitted before the ``exhausted`` policy applies —
    ``"fail"`` fails the run explicitly, ``"continue"`` force-forwards.

    ``graph_condition`` is the optional ADR-062 condition-string equivalent
    of the predicate (e.g. ``"review.approved is False"``), used by
    :func:`builders_dag_to_graph` to express the loop-back edge in a
    ``GraphSpec``. Gates without one (e.g. coverage over runtime metrics
    the blackboard does not carry) simply have no conditional edge in the
    converted graph.
    """

    name: str
    predicate: Callable[[StageResult], bool]
    max_iterations: int = DEFAULT_GATE_MAX_ITERATIONS
    exhausted: GateExhaustedPolicy = "fail"
    graph_condition: str | None = None


def coverage_gate(
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    *,
    key: str = "coverage",
    max_iterations: int = DEFAULT_GATE_MAX_ITERATIONS,
    exhausted: GateExhaustedPolicy = "fail",
) -> Gate:
    """Gate that passes when ``context[key] >= threshold``.

    The coverage figure is written into the run context by whatever runs the
    tests (dispatcher or ``on_complete`` hook). A missing or non-numeric
    value passes the gate — no measurement means nothing verifiable to gate
    on, and blocking on absent tooling would make the gate mandatory.
    """

    def predicate(result: StageResult) -> bool:
        value = result.context.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return True
        return float(value) >= threshold

    return Gate(
        name=f"{key}>={threshold:g}",
        predicate=predicate,
        max_iterations=max_iterations,
        exhausted=exhausted,
    )


def review_gate(
    *,
    key: str = "approved",
    max_iterations: int = DEFAULT_GATE_MAX_ITERATIONS,
    exhausted: GateExhaustedPolicy = "continue",
) -> Gate:
    """Gate that passes when the review approved the change.

    Prefers an explicit boolean ``context[key]`` (written by a dispatcher or
    hook); otherwise falls back to scanning the review output for clean
    signals (APPROVED / LGTM / "no violations" / …). Defaults to
    ``exhausted="continue"`` so a downstream cleanup stage stays reachable
    as the escalation path (ADR-099's default for the review stage).
    """

    def predicate(result: StageResult) -> bool:
        value = result.context.get(key)
        if isinstance(value, bool):
            return value
        lowered = result.output.lower()
        return any(signal in lowered for signal in _CLEAN_REVIEW_SIGNALS)

    return Gate(
        name=f"review.{key}",
        predicate=predicate,
        max_iterations=max_iterations,
        exhausted=exhausted,
        graph_condition="review.approved is False",
    )


@dataclass(frozen=True)
class StageSpec:
    """One stage of a builders DAG.

    ``role`` maps the stage onto an ADR-062 :class:`AgentRole` for
    :func:`builders_dag_to_graph`; execution via :func:`run_builders_dag`
    dispatches by ``agent_name`` through the existing
    :class:`~maistro.builders.graph_executor.PipelineDispatcher` seam, so
    stage logic is whatever the injected dispatcher already implements.
    """

    name: str
    agent_name: str
    prompt_template: str
    role: AgentRole = AgentRole.CODER
    skip_if: Callable[[RunContext], bool] | None = None
    timeout_seconds: float = 600.0
    on_complete: Callable[[Any, str], Awaitable[None]] | None = None


@dataclass(frozen=True)
class BuildersDAG:
    """Declarative description of a builders pipeline.

    ``edges`` are forward control-flow edges (must be acyclic); ``gates``
    maps a stage name to the :class:`Gate` evaluated after it completes;
    ``loop_targets`` maps each gated stage to the ancestor stage a gate
    failure loops back to. Loop-back is executor-level re-offer, so it never
    introduces a cycle into ``edges``.
    """

    stages: tuple[StageSpec, ...]
    edges: tuple[tuple[str, str], ...]
    gates: Mapping[str, Gate] = field(default_factory=dict)
    loop_targets: Mapping[str, str] = field(default_factory=dict)

    def stage(self, name: str) -> StageSpec:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)

    def terminal_stages(self) -> tuple[str, ...]:
        """Stages with no outgoing forward edge, in declaration order."""
        sources = {a for a, _ in self.edges}
        return tuple(s.name for s in self.stages if s.name not in sources)

    def validate(self) -> list[str]:
        """Return error strings; empty means the DAG is valid.

        Checks name uniqueness, edge/gate/loop-target referential integrity,
        and gate↔loop-target pairing here; cycle and ancestor checks are
        delegated to :meth:`PipelineGraph.validate` on the lowered graph.
        """
        names = [s.name for s in self.stages]
        known = set(names)
        errors: list[str] = [] if len(known) == len(names) else ["Duplicate stage names"]
        errors.extend(
            f"Edge references undeclared stage {endpoint!r}"
            for a, b in self.edges
            for endpoint in (a, b)
            if endpoint not in known
        )
        errors.extend(self._validate_gates(known))
        if errors:
            return errors
        # Cycles + "loop target must be an ancestor" via the lowered graph.
        return to_pipeline_graph(self).validate()

    def _validate_gates(self, known: set[str]) -> list[str]:
        errors: list[str] = []
        for gated in self.gates:
            if gated not in known:
                errors.append(f"Gate on undeclared stage {gated!r}")
            elif gated not in self.loop_targets:
                errors.append(f"Gated stage {gated!r} has no loop_target")
        for gated, target in self.loop_targets.items():
            if gated not in self.gates:
                errors.append(f"loop_target on ungated stage {gated!r}")
            if target not in known:
                errors.append(f"loop_target of {gated!r} references undeclared stage {target!r}")
        return errors


def _wrap_gate(stage_name: str, gate: Gate) -> Callable[[RunContext], bool]:
    evaluations = [0]

    def check(ctx: RunContext) -> bool:
        result = StageResult(
            stage=stage_name,
            output=str(ctx.get(stage_name, "")),
            context=ctx,
            iterations=evaluations[0],
        )
        evaluations[0] += 1
        return gate.predicate(result)

    return check


def to_pipeline_graph(dag: BuildersDAG) -> PipelineGraph:
    """Lower a :class:`BuildersDAG` onto the existing Epic-15 pipeline graph.

    Forward edges become ``depends_on``; gates become the graph's
    ``gate``/``revise_target``/``max_revisions``/``gate_exhausted`` fields,
    so the existing :class:`GraphPipelineExecutor` provides the bounded
    verify-and-revise loop unchanged.
    """
    incoming: dict[str, list[str]] = {s.name: [] for s in dag.stages}
    for a, b in dag.edges:
        if b in incoming:
            incoming[b].append(a)

    nodes: list[PipelineNode] = []
    for stage in dag.stages:
        gate = dag.gates.get(stage.name)
        nodes.append(
            PipelineNode(
                name=stage.name,
                agent_name=stage.agent_name,
                prompt_template=stage.prompt_template,
                depends_on=tuple(incoming.get(stage.name, ())),
                skip_if=stage.skip_if,
                timeout_seconds=stage.timeout_seconds,
                on_complete=stage.on_complete,
                gate=_wrap_gate(stage.name, gate) if gate is not None else None,
                revise_target=dag.loop_targets.get(stage.name),
                max_revisions=gate.max_iterations if gate is not None else 2,
                gate_exhausted=gate.exhausted if gate is not None else "fail",
            )
        )
    return PipelineGraph(nodes)


def _lower_edges(dag: BuildersDAG, role_of: dict[str, AgentRole]) -> tuple[list[GraphEdge], int]:
    """Lower forward edges + conditional gate loop-backs onto role-level edges."""
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str | None]] = set()

    def _add(from_role: AgentRole, to_role: AgentRole, condition: str | None) -> None:
        key = (from_role.value, to_role.value, condition)
        if from_role is not to_role and key not in seen:
            seen.add(key)
            edges.append(GraphEdge(from_role=from_role, to_role=to_role, condition=condition))

    for a, b in dag.edges:
        _add(role_of[a], role_of[b], None)
    max_gate_iterations = 0
    for gated, gate in dag.gates.items():
        max_gate_iterations = max(max_gate_iterations, gate.max_iterations)
        target = dag.loop_targets.get(gated)
        if gate.graph_condition is not None and target is not None:
            _add(role_of[gated], role_of[target], gate.graph_condition)
    return edges, max_gate_iterations


def builders_dag_to_graph(dag: BuildersDAG) -> GraphSpec:
    """Convert a :class:`BuildersDAG` into an ADR-062 ``GraphSpec``.

    The ADR-062 executor (:class:`~maistro.graph.run.GraphRun`) dispatches
    by :class:`AgentRole` strategy, so stages sharing a role are merged into
    one node (e.g. test/implement/revise all lower onto CODER). Loop-back
    edges are emitted for gates that declare a ``graph_condition``; the
    bounded-iteration property maps onto ``max_cycles``.
    """
    roles: list[AgentRole] = []
    role_of: dict[str, AgentRole] = {}
    for stage in dag.stages:
        role_of[stage.name] = stage.role
        if stage.role not in roles:
            roles.append(stage.role)

    edges, max_gate_iterations = _lower_edges(dag, role_of)

    targets = {b for _, b in dag.edges}
    entry = next((s.name for s in dag.stages if s.name not in targets), dag.stages[0].name)
    return GraphConfig(
        nodes=list(roles),
        edges=edges,
        entry=role_of[entry],
        max_cycles=min(max(1 + max_gate_iterations, 1), 20),
        # One NodeConfig per role; the first stage declaring a role names it.
        node_configs={
            stage.role.value: NodeConfig(role=stage.role, name=stage.name)
            for stage in reversed(dag.stages)
        },
    )


# ── Default builders DAG (SPEC-070226-82ea stage set) ────────────────────────


def _revise_skip_if(ctx: RunContext) -> bool:
    """Skip revise on the first pass — it only runs when a gate looped back."""
    return not any(key.endswith("_feedback") for key in ctx)


def default_builders_dag(
    *,
    coverage: Gate | None = None,
    review: Gate | None = None,
) -> BuildersDAG:
    """The SPEC's design → test → implement → review pipeline with a revise
    loop. ``revise`` sits between design and test as a skippable stage: it is
    skipped on the first pass and executed on every gate-triggered revision
    pass, realizing the SPEC's ``review → revise → test`` loop without a
    dependency cycle. Both gates are injectable — pass your own thresholds.
    """
    coverage = coverage if coverage is not None else coverage_gate()
    review = review if review is not None else review_gate()
    stages = (
        StageSpec(
            name="design",
            agent_name="quartermaster",
            role=AgentRole.PLANNER,
            prompt_template=(
                "Design the implementation for: {title}\n\n"
                "Produce a spec with acceptance criteria and file paths."
            ),
        ),
        StageSpec(
            name="revise",
            agent_name="mason",
            role=AgentRole.CODER,
            skip_if=_revise_skip_if,
            prompt_template=(
                "Revise the previous attempt for: {title}\n\n"
                "Latest code:\n{implement}\n\n"
                "Reviewer feedback (fix everything listed, if any):\n{review_feedback}\n\n"
                "Coverage feedback (add tests for anything listed, if any):\n{test_feedback}\n\n"
                "Output the revised code and a change summary."
            ),
        ),
        StageSpec(
            name="test",
            agent_name="mason",
            role=AgentRole.CODER,
            prompt_template=(
                "Write failing tests for: {title}\n\n"
                "Design:\n{design}\n\n"
                "Revisions so far (if any):\n{revise}\n\n"
                "Cover every acceptance criterion; report coverage."
            ),
        ),
        StageSpec(
            name="implement",
            agent_name="mason",
            role=AgentRole.CODER,
            prompt_template=(
                "Implement: {title}\n\n"
                "Design:\n{design}\n\nTests to satisfy:\n{test}\n\n"
                "Write the minimum code to make the tests pass."
            ),
        ),
        StageSpec(
            name="review",
            agent_name="auditor",
            role=AgentRole.REVIEWER,
            prompt_template=(
                "Review the implementation of: {title}\n\n"
                "Code:\n{implement}\n\n"
                "Reply APPROVED, or list each violation."
            ),
        ),
    )
    return BuildersDAG(
        stages=stages,
        edges=(
            ("design", "revise"),
            ("revise", "test"),
            ("test", "implement"),
            ("implement", "review"),
        ),
        gates={"test": coverage, "review": review},
        loop_targets={"test": "revise", "review": "revise"},
    )


# ── Entry point ───────────────────────────────────────────────────────────────


@dataclass
class DagRun:
    """Mutable run record driven by the pipeline executor."""

    id: str
    status: str = "pending"
    context: RunContext = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)
    failed_stage_error: str = ""
    revisions: dict[str, int] = field(default_factory=dict)
    gate_exhausted: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildersDagFailure:
    """Typed failure: what went wrong, where, and why."""

    kind: FailureKind
    stage: str
    detail: str


@dataclass(frozen=True)
class BuildersDagResult:
    """Outcome of :func:`run_builders_dag` — final output or typed failure."""

    ok: bool
    run: DagRun
    output: str = ""
    failure: BuildersDagFailure | None = None


def _classify_failure(run: DagRun) -> BuildersDagFailure:
    status = run.status
    if status.startswith("invalid graph"):
        return BuildersDagFailure(kind="invalid_graph", stage="", detail=status)
    if status.startswith("halted at "):
        stage = status[len("halted at ") :].split(":", 1)[0]
        return BuildersDagFailure(kind="budget_exhausted", stage=stage, detail=status)
    stage = status[len("failed at ") :] if status.startswith("failed at ") else ""
    kind: FailureKind = (
        "gate_exhausted" if run.failed_stage_error.startswith("Gate failed") else "stage_failed"
    )
    return BuildersDagFailure(kind=kind, stage=stage, detail=run.failed_stage_error or status)


def _default_budget(dag: BuildersDAG) -> IterationBudget:
    """Bound total stage executions: every stage may run once per pass, and
    each gate contributes up to ``max_iterations`` revision passes."""
    passes = 1 + sum(gate.max_iterations for gate in dag.gates.values())
    return IterationBudget(max_iterations=passes * len(dag.stages))


async def run_builders_dag(
    dag: BuildersDAG,
    dispatcher: PipelineDispatcher,
    *,
    params: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    budget: IterationBudget | None = None,
) -> BuildersDagResult:
    """Run a :class:`BuildersDAG` to completion via the existing pipeline
    executor and return the terminal stage's output or a typed failure.

    Never raises for run failures; total stage executions never exceed the
    iteration budget (default: ``(1 + sum of gate.max_iterations) * len(stages)``).
    """
    run = DagRun(id=run_id or f"builders-dag-{uuid4().hex[:8]}")
    run.context.update(dict(params or {}))

    errors = dag.validate()
    if errors:
        run.status = f"invalid graph: {'; '.join(errors)}"
        return BuildersDagResult(ok=False, run=run, failure=_classify_failure(run))

    graph = to_pipeline_graph(dag)
    executor = GraphPipelineExecutor(dispatcher, budget=budget or _default_budget(dag))
    await executor.execute(graph, run)

    if run.status != "completed":
        return BuildersDagResult(ok=False, run=run, failure=_classify_failure(run))

    output = ""
    for name in dag.terminal_stages():
        text = str(run.context.get(name, ""))
        if text:
            output = text
            break
    return BuildersDagResult(ok=True, run=run, output=output)
