"""`agent.synth_dag` — synthesize a DAG at runtime and execute it as a sub-graph.

An orchestrating node takes a natural-language objective, delegates to the
injected `DagSynthesizer` to produce a `GraphConfig`, then runs that config
as a canonical **child Run** via `run_durable_graph()`. This is the "deep
agent" pattern: instead of a pre-wired static topology, the node *writes* the
graph at runtime based on what the task requires.

Two independent safety axes govern this, deliberately treated differently:

  - **Recursion depth** is a hard, structural cap (`maistro.graph.depth`).
    Recursion is easy to get wrong and easy to get expensively wrong, so it's
    enforced unconditionally on every invocation — no rationale can unlock
    more depth.
  - **Width** (node count) is *not* capped by a fixed number. A large DAG can
    be exactly the right shape — many small focused nodes standing in for
    one giant model — so width goes through `evaluate_dag_shape` (the
    security-review-team gate: Warden for safety, Sentinel/delegability for
    budget, a proportionality critic for need). A shape that falls short
    gets one bounded revision pass with concrete add/drop feedback rather
    than an outright refusal — a "blocked" wastes the tokens and turnaround
    already spent on synthesis; "almost, but drop X and add Y" gives the
    synthesizer a real chance to land it.

Execution is canonical or it is skipped (#520). An approved DAG whose kinds
are all registered nodes dispatches through `run_durable_graph` as a **child
Run** of the Run that synthesized it — parent linkage from the NodeContext,
canonical NodeRun/Attempt records for every subgraph node, recursion depth
threaded into the child's blackboard. Without a wired durable store, or for a
config the registry cannot execute (AgentRole placeholders, unregistered or
duplicated kinds), the node reports the synthesis and truthfully does not
execute: the previous behavior — re-entering the ephemeral `GraphRun`
executor from *inside* a durable Run, leaving the whole subtree without
canonical records — was exactly the second execution universe ADR-081226-69ee
retires.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from maistro.graph.depth import can_spawn, get_role
from maistro.graph.synth import DagSynthesizer, RuleDagSynthesizer, SynthRequest, SynthResult
from maistro.runs.model import RunStatus
from maistro.security.dag_shape import (
    DEFAULT_PRINCIPAL,
    DagShapeVerdict,
    ProportionalityJudge,
    ProposedDagShape,
    RuleProportionalityJudge,
    ShapeRevision,
    evaluate_dag_shape,
)
from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden

from . import get_node, register_node
from .base import BaseNode, NodeContext

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime import would cycle
    from maistro.graph.definitions import Graph
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.graph.types import GraphConfig
    from maistro.runtime import ExecutionRuntime

# Absolute substrate backstop only (mirrors fan_out.MAX_PARALLEL_CEILING) — the
# real width gate is `evaluate_dag_shape`, not this number. Raised well past
# the old default-8 ceiling since a justified DAG can legitimately be large.
_MAX_NODE_CEILING = 64
_DEFAULT_MAX_DEPTH = 3


class SynthDagIn(BaseModel):
    objective: str = Field(description="What the synthesized DAG should accomplish")
    constraints: list[str] = Field(
        default_factory=list, description="Hard constraints on DAG structure"
    )
    available_kinds: list[str] = Field(
        default_factory=list, description="Node kinds the synthesizer may use"
    )
    max_nodes: int = Field(
        default=8,
        ge=2,
        le=_MAX_NODE_CEILING,
        description="Substrate backstop, not the real width gate — see evaluate_dag_shape",
    )


class SynthDagOut(BaseModel):
    success: bool = True
    synthesized_nodes: list[str] = Field(default_factory=list)
    rationale: str = ""
    run_output: str = ""
    error: str | None = None
    # The canonical child Run executing the synthesized subgraph, when one was
    # dispatched (#520) — the handle that makes the subtree inspectable through
    # the same Run model as everything else. Empty when nothing executed.
    child_run_id: str = ""
    # True only when the sub-graph was actually dispatched as a child Run --
    # distinguishes "spawned but the sub-graph itself failed" (success=False,
    # dispatched=True) from "declined to spawn" (depth cap / security block /
    # dry-synthesis; success=False or True, dispatched=False). Consumed by
    # the durable executor's `_actually_spawned` to decide whether a real
    # spawn attempt occurred for recursion-depth accounting.
    dispatched: bool = False


def _revision_note(revision: ShapeRevision) -> str:
    parts: list[str] = []
    if revision.add:
        parts.append(f"must add node kinds: {', '.join(revision.add)}")
    if revision.drop:
        parts.append(f"must drop node kinds: {', '.join(revision.drop)}")
    if revision.reason:
        parts.append(f"reason: {revision.reason}")
    return "; ".join(parts) or "shape needs revision"


def _verdict_error(verdict: DagShapeVerdict) -> str:
    if verdict.status == "blocked":
        flags = ", ".join(verdict.safety_flags) or "policy"
        return f"blocked by security review: {flags}"
    if verdict.revision is not None:
        return f"not justified after revision pass: {_revision_note(verdict.revision)}"
    return "shape rejected by security review"


def _estimate_cost(node_kinds: list[str]) -> float:
    total = 0.0
    for kind in node_kinds:
        try:
            total += get_node(kind).cost_hint
        except KeyError:
            total += 1.0  # AgentRole values and unregistered kinds: unit cost
    return total


def _registered(kind: str) -> bool:
    try:
        get_node(kind)
    except KeyError:
        return False
    return True


def _undispatchable_reason(config: GraphConfig, ctx: NodeContext) -> str | None:
    """Why an approved config cannot execute canonically, or None when it can.

    Node ids in the child graph are the kinds themselves, so a config the
    registry cannot construct, or one whose edges could not name their nodes
    unambiguously, is reported rather than half-run. AgentRole placeholders
    land in the first bucket by construction: roles are strategies of the
    retired GraphRun executor, not registered node kinds.
    """
    names = [str(node) for node in config.nodes]
    unregistered = sorted({name for name in names if not _registered(name)})
    if unregistered:
        return f"synthesized kinds are not registered nodes: {', '.join(unregistered)}"
    if len(set(names)) != len(names):
        return "duplicate node kinds cannot be addressed unambiguously by edges"
    if str(config.entry) not in names:
        return f"entry node {config.entry!s} is not among the synthesized nodes"
    if not ctx.workspace_id or not ctx.project_id:
        return "execution context carries no Workspace/Project scope"
    return None


def _child_graph(config: GraphConfig, objective: str, ctx: NodeContext) -> Graph:
    """The canonical Graph snapshot the child Run carries: the synthesized work."""
    from maistro.graph.definitions import Edge, Graph, Node

    names = [str(node) for node in config.nodes]
    edges = [
        Edge(
            edge_id=f"{edge.from_node}-{edge.to_node}-{index}",
            from_node=str(edge.from_node),
            to_node=str(edge.to_node),
            condition=edge.condition,
            metadata={"parallel": True} if edge.parallel else {},
        )
        for index, edge in enumerate(config.edges, start=1)
        if edge.to_node is not None
    ]
    return Graph(
        workspace_id=str(ctx.workspace_id),
        project_id=str(ctx.project_id),
        name=objective or "synthesized sub-graph",
        nodes=[Node(node_id=name, node_type=name) for name in names],
        edges=edges,
        metadata={"entry_node": str(config.entry)},
    )


def _node_kind(graph: Graph, node_id: str) -> str:
    """Node ids in a synthesized child graph are their kinds; resolve defensively."""
    for node in graph.nodes:
        if node.node_id == node_id:
            return node.node_type
    raise KeyError(node_id)


@register_node
class AgentSynthDagNode(BaseNode[SynthDagIn, SynthDagOut]):
    """Synthesize a GraphConfig from an objective, then run it as a sub-graph."""

    kind: ClassVar[str] = "agent.synth_dag"
    kind_category: ClassVar = "composite"
    input_schema: ClassVar[type[BaseModel]] = SynthDagIn
    output_schema: ClassVar[type[BaseModel]] = SynthDagOut
    cost_hint: ClassVar[float] = 8.0
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Agent: synthesize DAG"
    description: ClassVar[str] = (
        "Turn a natural-language objective into a GraphConfig at runtime, "
        "then execute the synthesized sub-graph."
    )

    def __init__(
        self,
        synthesizer: DagSynthesizer | None = None,
        llm_call: Callable[..., Awaitable[Any]] | None = None,
        *,
        warden: Warden | None = None,
        sentinel: Sentinel | None = None,
        principal: Principal | None = None,
        proportionality_judge: ProportionalityJudge | None = None,
        max_depth: int = _DEFAULT_MAX_DEPTH,
        run_store: DurableRunStore | None = None,
        runtime: ExecutionRuntime | None = None,
    ) -> None:
        self._synthesizer: DagSynthesizer = synthesizer or RuleDagSynthesizer()
        self._llm_call = llm_call
        self._run_store = run_store
        self._runtime = runtime
        self._warden = warden or Warden()
        self._sentinel = sentinel or Sentinel(warden=self._warden, permission_table={})
        self._principal = principal or DEFAULT_PRINCIPAL
        self._proportionality_judge: ProportionalityJudge = (
            proportionality_judge or RuleProportionalityJudge()
        )
        self._max_depth = max_depth

    async def _judge(self, objective: str, synth: SynthResult) -> DagShapeVerdict:
        node_kinds = [str(n) for n in synth.graph_config.nodes]
        shape = ProposedDagShape(
            objective=objective,
            node_kinds=tuple(node_kinds),
            rationale=synth.rationale,
            estimated_cost=_estimate_cost(node_kinds),
        )
        return await evaluate_dag_shape(
            shape,
            warden=self._warden,
            sentinel=self._sentinel,
            principal=self._principal,
            proportionality_judge=self._proportionality_judge,
        )

    async def _execute(self, inputs: SynthDagIn, ctx: NodeContext) -> SynthDagOut:
        # Recursion depth: hard, structural, unconditional — no rationale
        # unlocks more. `synth_depth` is threaded through NodeContext.metadata
        # by whatever executor dispatches nested agent.synth_dag nodes. A node
        # at the depth ceiling is a LEAF (ADR depth taxonomy) and refuses to
        # spawn further sub-graphs, full stop.
        depth = int((ctx.metadata or {}).get("synth_depth", 0))
        if not can_spawn(get_role(depth, self._max_depth)):
            return SynthDagOut(
                success=False,
                error=(
                    f"recursion depth cap reached (depth={depth}, "
                    f"max_depth={self._max_depth}) — refusing to spawn further sub-graphs"
                ),
            )

        request = SynthRequest(
            objective=inputs.objective,
            constraints=inputs.constraints,
            available_kinds=inputs.available_kinds,
            max_nodes=inputs.max_nodes,
        )
        synth = await self._synthesizer.synthesize(request)
        verdict = await self._judge(inputs.objective, synth)

        if verdict.status == "needs_revision" and verdict.revision is not None:
            revised_request = SynthRequest(
                objective=inputs.objective,
                constraints=[*inputs.constraints, _revision_note(verdict.revision)],
                available_kinds=inputs.available_kinds,
                max_nodes=inputs.max_nodes,
            )
            synth = await self._synthesizer.synthesize(revised_request)
            verdict = await self._judge(inputs.objective, synth)

        synthesized_kinds = [str(n) for n in synth.graph_config.nodes]

        if verdict.status != "approved":
            return SynthDagOut(
                success=False,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                error=_verdict_error(verdict),
            )

        return await self._dispatch_or_decline(synth, synthesized_kinds, inputs, ctx, depth)

    async def _dispatch_or_decline(
        self,
        synth: SynthResult,
        synthesized_kinds: list[str],
        inputs: SynthDagIn,
        ctx: NodeContext,
        depth: int,
    ) -> SynthDagOut:
        """Run the approved config as a canonical child Run, or say why not (#520)."""
        if self._run_store is None:
            if self._llm_call is None:
                return SynthDagOut(
                    success=True,
                    synthesized_nodes=synthesized_kinds,
                    rationale=synth.rationale,
                    run_output="dag synthesized — no llm_call provided, execution skipped",
                )
            # An llm_call used to select the ephemeral GraphRun path here,
            # executing the subtree with no canonical records (#520). Declining
            # is the honest replacement: the synthesis stands, and the output
            # says exactly why nothing ran.
            return SynthDagOut(
                success=True,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                run_output=(
                    "dag synthesized — not executed: canonical dispatch requires "
                    "a durable run store; the in-process GraphRun path is retired (#520)"
                ),
            )

        undispatchable = _undispatchable_reason(synth.graph_config, ctx)
        if undispatchable is not None:
            return SynthDagOut(
                success=True,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                run_output=f"dag synthesized — not executed: {undispatchable}",
            )

        from maistro.graph.durable_runs import run_durable_graph

        child = await run_durable_graph(
            _child_graph(synth.graph_config, inputs.objective, ctx),
            store=self._run_store,
            node_resolver=lambda node_id, graph: get_node(_node_kind(graph, node_id))(),
            actor_principal_id=ctx.user_id,
            runtime=self._runtime,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id or None,
            provenance={
                "admission_source": "agent.synth_dag",
                "objective": inputs.objective[:200],
            },
            # The child starts one level deeper than the node that spawned it,
            # so a nested agent.synth_dag inside it hits the same hard cap.
            blackboard_metadata={"synth_depth": depth + 1},
        )
        succeeded = child.status is RunStatus.COMPLETED
        return SynthDagOut(
            success=succeeded,
            dispatched=True,
            synthesized_nodes=synthesized_kinds,
            rationale=synth.rationale,
            run_output=f"child run {child.run_id} {child.status.value}",
            error=None if succeeded else "sub-graph execution failed",
            child_run_id=child.run_id,
        )
