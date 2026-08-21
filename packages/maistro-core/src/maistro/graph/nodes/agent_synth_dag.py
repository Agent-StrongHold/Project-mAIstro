"""`agent.synth_dag` — synthesize a DAG at runtime and execute it as a sub-graph.

An orchestrating node takes a natural-language objective, delegates to the
injected `DagSynthesizer` to produce a `GraphConfig`, then runs that config
as a sub-graph via `run_graph()`. This is the "deep agent" pattern: instead of
a pre-wired static topology, the node *writes* the graph at runtime based on
what the task requires.

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

With no `llm_call` injected the node synthesizes but skips execution (useful
for topology inspection and dry-run tests). With an `llm_call` the approved
DAG runs in-process and the result is returned.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.graph.depth import can_spawn, get_role
from maistro.graph.synth import DagSynthesizer, RuleDagSynthesizer, SynthRequest, SynthResult
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
    # True only when the sub-graph was actually dispatched via `run_graph` --
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
    ) -> None:
        self._synthesizer: DagSynthesizer = synthesizer or RuleDagSynthesizer()
        self._llm_call = llm_call
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

        if self._llm_call is None:
            return SynthDagOut(
                success=True,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                run_output="dag synthesized — no llm_call provided, execution skipped",
            )

        from maistro.graph.executor import run_graph
        from maistro.graph.types import GraphTask

        task = GraphTask(
            description=inputs.objective,
            workspace=str(ctx.run_id),
            graph_config=synth.graph_config,
        )
        output = await run_graph(task, self._llm_call)
        return SynthDagOut(
            success=output.success,
            dispatched=True,
            synthesized_nodes=synthesized_kinds,
            rationale=synth.rationale,
            run_output=output.final_answer or "",
            error=None if output.success else "sub-graph execution failed",
        )
