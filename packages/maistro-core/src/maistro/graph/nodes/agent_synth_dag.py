"""`agent.synth_dag` — synthesize a DAG at runtime and execute it as a child Run.

An orchestrating node takes a natural-language objective, delegates to the
injected `DagSynthesizer` to produce a `GraphConfig`, then projects that config
onto the canonical Graph definition and dispatches it through the durable
Run/NodeRun/Attempt spine. This is the "deep agent" pattern without a nested
execution lifecycle: the synthesized subtree is an inspectable child Run.

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

`GraphConfig` still permits the legacy AgentRole vocabulary. Those role nodes
are adapted *inside* canonical child Attempts: the adapter reuses the existing
role strategies and model callback, but it does not create legacy GraphRun or
legacy NodeRun objects. Registered modern node kinds fall through to the
parent durable resolver unchanged.

With no `llm_call` injected the node synthesizes but skips execution (useful
for topology inspection and dry-run tests). With an `llm_call`, durable
execution must inject `NodeContext.child_graph_runner`; there is deliberately
no fallback to the ephemeral `run_graph` path.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.concurrency import llm_call_permit
from maistro.graph.definitions import Edge, Graph, Node as GraphNode
from maistro.graph.depth import can_spawn, get_role
from maistro.graph.strategy import get_strategy
from maistro.graph.synth import DagSynthesizer, RuleDagSynthesizer, SynthRequest, SynthResult
from maistro.graph.types import (
    DEFAULT_SYSTEM_PROMPTS,
    JSON_OUTPUT_SCHEMAS,
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphConfig,
    GraphTask,
    NodeConfig,
    PlanOutput,
    ReviewOutput,
    ScoutContext,
)
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

# Absolute substrate backstop only (mirrors fan_out.MAX_PARALLEL_CEILING) — the
# real width gate is `evaluate_dag_shape`, not this number. Raised well past
# the old default-8 ceiling since a justified DAG can legitimately be large.
_MAX_NODE_CEILING = 64
_DEFAULT_MAX_DEPTH = 3
_SYNTHETIC_ROLE_KIND = "agent.synthetic_role"


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
    child_run_id: str | None = None
    error: str | None = None
    # True only when a canonical child Run was actually created. This
    # distinguishes "child Run failed" from "declined to spawn" for recursion
    # accounting in the durable executor.
    dispatched: bool = False


class _SyntheticRoleIn(BaseModel):
    """Open input envelope for a compatibility AgentRole node."""

    model_config = ConfigDict(extra="allow")


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


def _node_key(value: AgentRole | str) -> str:
    return value.value if isinstance(value, AgentRole) else str(value)


def _agent_role(value: AgentRole | str) -> AgentRole | None:
    if isinstance(value, AgentRole):
        return value
    try:
        return AgentRole(value)
    except ValueError:
        return None


def _node_config(config: GraphConfig, node_id: str) -> NodeConfig:
    return config.node_configs.get(node_id, NodeConfig(role=node_id))


def _canonical_child_graph(
    config: GraphConfig,
    *,
    objective: str,
    workspace_id: str,
    project_id: str,
) -> Graph:
    """Project the synthesizer facade onto the canonical Graph definition."""
    nodes: list[GraphNode] = []
    for value in config.nodes:
        node_id = _node_key(value)
        node_config = _node_config(config, node_id)
        role = _agent_role(value)
        if role is not None:
            node_type = _SYNTHETIC_ROLE_KIND
            metadata = {
                "agent_role": role.value,
                "node_config": node_config.model_dump(mode="json"),
            }
        else:
            node_type = node_config.kind or node_id
            metadata = {"node_config": node_config.model_dump(mode="json")}
        nodes.append(
            GraphNode(
                node_id=node_id,
                node_type=node_type,
                name=node_config.name or node_id,
                metadata=metadata,
            )
        )

    edges = [
        Edge(
            from_node=_node_key(edge.from_role),
            to_node=_node_key(edge.to_role) if edge.to_role is not None else "",
            condition=edge.condition,
            metadata={"parallel": edge.parallel},
        )
        for edge in config.edges
        if edge.to_role is not None
    ]
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"Synthesized: {objective}"[:200],
        description=objective,
        nodes=nodes,
        edges=edges,
        metadata={
            "entry_node": _node_key(config.entry),
            "synthesized": True,
            "source": "agent.synth_dag",
            "max_cycles": config.max_cycles,
        },
    )


def _strip_json_block(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _read_usage(value: Any) -> tuple[int, int]:
    if isinstance(value, Mapping):
        return (
            int(value.get("prompt_tokens") or value.get("input_tokens") or 0),
            int(value.get("completion_tokens") or value.get("output_tokens") or 0),
        )
    return (
        int(getattr(value, "prompt_tokens", 0) or getattr(value, "input_tokens", 0) or 0),
        int(
            getattr(value, "completion_tokens", 0)
            or getattr(value, "output_tokens", 0)
            or 0
        ),
    )


def _normalize_llm_result(result: Any) -> tuple[str, int, int]:
    if isinstance(result, str):
        return result, 0, 0
    if isinstance(result, tuple) and len(result) == 2:
        text, usage = result
        tokens_in, tokens_out = _read_usage(usage)
        return str(text), tokens_in, tokens_out
    if isinstance(result, Mapping):
        text = result.get("text") or result.get("content") or ""
        usage = result.get("usage")
    else:
        text = getattr(result, "text", None) or getattr(result, "content", None) or ""
        usage = getattr(result, "usage", None)
    tokens_in, tokens_out = _read_usage(usage)
    return str(text), tokens_in, tokens_out


def _typed_metadata(
    metadata: Mapping[str, Any],
) -> tuple[PlanOutput | None, CodeOutput | None, ReviewOutput | None]:
    def restore(key: str, model: type[BaseModel]) -> BaseModel | None:
        value = metadata.get(key)
        if not isinstance(value, Mapping):
            return None
        try:
            return model.model_validate(value)
        except Exception:
            return None

    plan = restore("plan", PlanOutput)
    code = restore("code", CodeOutput)
    review = restore("review", ReviewOutput)
    return (
        plan if isinstance(plan, PlanOutput) else None,
        code if isinstance(code, CodeOutput) else None,
        review if isinstance(review, ReviewOutput) else None,
    )


def _blackboard_for_role(ctx: NodeContext, objective: str) -> GraphBlackboard:
    if isinstance(ctx.blackboard, GraphBlackboard):
        blackboard = ctx.blackboard
    else:
        blackboard = GraphBlackboard(
            task_objective=objective,
            workspace=ctx.workspace_id or "",
        )
    scout = blackboard.metadata.get("scout_context")
    if isinstance(scout, Mapping):
        try:
            blackboard = blackboard.model_copy(
                update={"scout_context": ScoutContext.model_validate(scout)}
            )
        except Exception:
            pass
    return blackboard


class _SyntheticRoleNode(BaseNode[_SyntheticRoleIn, BaseModel]):
    """Compatibility adapter that executes one AgentRole inside a canonical Attempt."""

    kind: ClassVar[str] = _SYNTHETIC_ROLE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = _SyntheticRoleIn
    output_schema: ClassVar[type[BaseModel]] = BaseModel
    cost_hint: ClassVar[float] = 1.0
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Synthesized role"
    description: ClassVar[str] = "Compatibility AgentRole executed inside canonical Run state."

    def __init__(
        self,
        *,
        role: AgentRole,
        node_config: NodeConfig,
        objective: str,
        constraints: list[str],
        graph_config: GraphConfig,
        llm_call: Callable[..., Awaitable[Any]],
    ) -> None:
        self._role = role
        self._node_config = node_config
        self._objective = objective
        self._constraints = constraints
        self._graph_config = graph_config
        self._llm_call = llm_call

    async def _execute(self, inputs: _SyntheticRoleIn, ctx: NodeContext) -> BaseModel:
        strategy = get_strategy(self._role)
        blackboard = _blackboard_for_role(ctx, self._objective)
        plan, code, review = _typed_metadata(blackboard.metadata)
        task = GraphTask(
            description=self._objective,
            workspace=ctx.workspace_id or "",
            constraints=self._constraints,
            graph_config=self._graph_config,
        )
        system_prompt = (
            self._node_config.system_prompt or DEFAULT_SYSTEM_PROMPTS.get(self._role, "")
        ) + JSON_OUTPUT_SCHEMAS.get(self._role, "")
        user_prompt = strategy.build_user_prompt(task, blackboard, plan, code, review)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        async with llm_call_permit():
            result = await asyncio.wait_for(
                self._llm_call(
                    messages,
                    model=self._node_config.model or "default",
                    temperature=self._node_config.temperature,
                    response_schema=strategy.output_type.model_json_schema(),
                ),
                timeout=120.0,
            )
        raw, _tokens_in, _tokens_out = _normalize_llm_result(result)
        try:
            output = strategy.output_type.model_validate(json.loads(_strip_json_block(raw)))
        except Exception as exc:
            raise ValueError(f"failed to parse synthesized {self._role.value} output") from exc

        updated = strategy.update_blackboard(output, blackboard)
        metadata = dict(updated.metadata)
        slot = {
            AgentRole.PLANNER: "plan",
            AgentRole.CODER: "code",
            AgentRole.REVIEWER: "review",
        }.get(self._role)
        if slot is not None:
            metadata[slot] = output.model_dump(mode="json")
        if updated.scout_context is not None:
            metadata["scout_context"] = updated.scout_context.model_dump(mode="json")
        ctx.blackboard = updated.model_copy(update={"metadata": metadata})
        return output


@register_node
class AgentSynthDagNode(BaseNode[SynthDagIn, SynthDagOut]):
    """Synthesize a GraphConfig from an objective, then run it as a child Run."""

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
        "then execute the synthesized sub-graph as a canonical child Run."
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

    def _child_node_override(
        self,
        objective: str,
        constraints: list[str],
        config: GraphConfig,
    ) -> Callable[[str, Graph], BaseNode[Any, Any] | None]:
        assert self._llm_call is not None

        def resolve(node_id: str, graph: Graph) -> BaseNode[Any, Any] | None:
            spec = next((node for node in graph.nodes if node.node_id == node_id), None)
            if spec is None or spec.node_type != _SYNTHETIC_ROLE_KIND:
                return None
            role = _agent_role(str(spec.metadata.get("agent_role") or ""))
            if role is None:
                raise KeyError(f"synthesized role node {node_id!r} has no valid agent_role")
            return _SyntheticRoleNode(
                role=role,
                node_config=_node_config(config, node_id),
                objective=objective,
                constraints=constraints,
                graph_config=config,
                llm_call=self._llm_call,
            )

        return resolve

    async def _execute(self, inputs: SynthDagIn, ctx: NodeContext) -> SynthDagOut:
        # Recursion depth: hard, structural, unconditional — no rationale
        # unlocks more. The durable child-run launcher carries synth_depth + 1
        # into each child Run, so recursive synthesis cannot reset at a Run
        # boundary.
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

        synthesized_kinds = [_node_key(n) for n in synth.graph_config.nodes]

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

        if ctx.child_graph_runner is None:
            return SynthDagOut(
                success=False,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                error="canonical child-run capability unavailable; refusing ephemeral subgraph execution",
            )
        if not ctx.workspace_id or not ctx.project_id:
            return SynthDagOut(
                success=False,
                synthesized_nodes=synthesized_kinds,
                rationale=synth.rationale,
                error="canonical child-run scope unavailable",
            )

        child_graph = _canonical_child_graph(
            synth.graph_config,
            objective=inputs.objective,
            workspace_id=ctx.workspace_id,
            project_id=ctx.project_id,
        )
        child = await ctx.child_graph_runner(
            child_graph,
            {"objective": inputs.objective},
            self._child_node_override(inputs.objective, inputs.constraints, synth.graph_config),
        )
        child_run_id = str(child.run_id)
        child_success = child.run.status is RunStatus.COMPLETED
        final_result = next(
            (
                node_run.result
                for node_run in reversed(child.node_runs)
                if node_run.status is RunStatus.COMPLETED and node_run.result is not None
            ),
            None,
        )
        run_output = json.dumps(final_result, sort_keys=True, default=str) if final_result else ""
        return SynthDagOut(
            success=child_success,
            dispatched=True,
            synthesized_nodes=synthesized_kinds,
            rationale=synth.rationale,
            run_output=run_output,
            child_run_id=child_run_id,
            error=None if child_success else child.run.error or "sub-graph execution failed",
        )
