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

Execution is canonical or the node fails (#520, #1193). An approved DAG whose
kinds are all registered nodes dispatches through `run_durable_graph` as a
**child Run** of the Run that synthesized it — parent linkage from the
NodeContext, canonical NodeRun/Attempt records for every subgraph node,
recursion depth threaded into the child's blackboard. Every path that
dispatches nothing — the depth cap, a shape review that does not approve, a
config the registry cannot execute (AgentRole placeholders, unregistered,
disallowed or duplicated kinds), a missing durable store — and a child Run that
ends FAILED, CANCELLED or TIMED_OUT raises instead of returning, so the
NodeRun ends FAILED with the reason recorded and the parent Run cannot report
success for work that never happened. A `success=False` flag inside a
COMPLETED node's output is not an outcome this node produces. The previous
fallback — re-entering the ephemeral `GraphRun` executor from *inside* a
durable Run, leaving the whole subtree without canonical records — was exactly
the second execution universe ADR-081226-69ee retires.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from maistro.graph.depth import can_spawn, get_role
from maistro.graph.synth import DagSynthesizer, RuleDagSynthesizer, SynthRequest, SynthResult
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
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
from .base import BaseNode, NodeCompositionError, NodeContext, ReplaySemantics

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime import would cycle
    from maistro.graph.definitions import Graph
    from maistro.graph.durable_runs.attempt_executor import NodeResolver
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.graph.types import GraphConfig
    from maistro.runs.store import RunStore
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
    # Only ever returned for a dispatched child that COMPLETED or is parked
    # WAITING/PAUSED; every other outcome raises `SynthDagFailed` (#1193), so
    # `success` is always True and `error` always None on a returned output.
    success: bool = True
    synthesized_nodes: list[str] = Field(default_factory=list)
    rationale: str = ""
    run_output: str = ""
    error: str | None = None
    # The canonical child Run executing the synthesized subgraph (#520) — the
    # handle that makes the subtree inspectable through the same Run model as
    # everything else.
    child_run_id: str = ""
    # True on every returned output: a node that declined to spawn raises
    # instead. Consumed by the durable executor's `_actually_spawned` for
    # recursion-depth accounting.
    dispatched: bool = False


class SynthDagFailed(RuntimeError):
    """The node dispatched nothing, or its child Run did not complete (#1193).

    `BaseNode.run` turns this into a failed NodeResult, so the canonical NodeRun
    ends FAILED with the reason — naming the child Run when there is one —
    rather than COMPLETED with a flag saying the work did not happen. A child
    that was dispatched is also carried in the result's metadata: it still
    spent a recursion level, and the durable fold charges it even though the
    node failed, so a retry or a `continue_on_failure` successor cannot spawn
    again at the same depth.
    """

    def __init__(self, reason: str, *, child_run_id: str = "") -> None:
        self.reason = reason
        self.child_run_id = child_run_id
        self.result_metadata: dict[str, Any] = (
            {"dispatched": True, "child_run_id": child_run_id} if child_run_id else {}
        )
        super().__init__(f"child run {child_run_id}: {reason}" if child_run_id else reason)


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


def _requires_inputs(kind: str) -> bool:
    """Whether this kind's entry schema demands a field nothing here can supply.

    A synthesized `GraphConfig` carries no per-node inputs — `NodeConfig` has
    no such field — so a child whose entry node requires one is a Run created
    to fail validation. Declining is the honest answer; inventing a value
    would be worse.
    """
    try:
        schema = get_node(kind).input_schema
    except KeyError:  # pragma: no cover - callers check `_registered` first
        return False
    return any(field.is_required() for field in schema.model_fields.values())


def _undispatchable_reason(
    config: GraphConfig, ctx: NodeContext, available_kinds: list[str]
) -> str | None:
    """Why an approved config cannot execute canonically, or None when it can.

    Node ids in the child graph are the kinds themselves, so a config the
    registry cannot construct, or one whose edges could not name their nodes
    unambiguously, is reported rather than half-run. AgentRole placeholders
    land in the first bucket by construction: roles are strategies of the
    retired GraphRun executor, not registered node kinds.
    """
    names = [str(node) for node in config.nodes]
    return (
        _unusable_kinds_reason(names, available_kinds)
        or _unaddressable_topology_reason(names, config)
        or _unscoped_reason(ctx)
    )


def _unusable_kinds_reason(names: list[str], available_kinds: list[str]) -> str | None:
    """Kinds the registry cannot build, or the caller never allowed.

    The allowlist is a boundary, not a hint: `available_kinds` is only ever
    *described* to the synthesizer — `LLMDagSynthesizer` puts it in a prompt —
    so a malformed or prompt-injected response can name any registered kind,
    including external-I/O and delegation nodes, while the shape review
    upstream judges width and cost rather than identity. An empty list means
    the caller named no restriction and the registry is the only bound.
    """
    unregistered = sorted({name for name in names if not _registered(name)})
    if unregistered:
        return f"synthesized kinds are not registered nodes: {', '.join(unregistered)}"
    if not available_kinds:
        return None
    allowed = set(available_kinds)
    outside = sorted({name for name in names if name not in allowed})
    if outside:
        return f"synthesized kinds outside the requested allowlist: {', '.join(outside)}"
    return None


def _unaddressable_topology_reason(names: list[str], config: GraphConfig) -> str | None:
    """A shape whose entry cannot be named, reached, or invoked."""
    if len(set(names)) != len(names):
        return "duplicate node kinds cannot be addressed unambiguously by edges"
    entry = str(config.entry)
    if entry not in names:
        return f"entry node {entry} is not among the synthesized nodes"
    if _requires_inputs(entry):
        return f"entry node {entry} requires inputs a synthesized config cannot supply"
    return None


def _unscoped_reason(ctx: NodeContext) -> str | None:
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
    # The two stores are what turn an approved config into a canonical child
    # Run: the canonical RunStore admits it, the durable graph store runs it.
    # Both declared required so the production resolver can never hand this
    # node `run_store=None` and let it answer "success" for a sub-graph
    # nothing ran (#1193). The wired resolver is optional: the child's nodes
    # get the caller's dependencies when there is one.
    required_authorities: ClassVar[Mapping[str, str]] = {
        "run_store": "graph_run_store",
        "canonical_run_store": "run_store",
    }
    optional_authorities: ClassVar[Mapping[str, str]] = {"node_resolver": "node_resolver"}
    kind_category: ClassVar = "composite"
    input_schema: ClassVar[type[BaseModel]] = SynthDagIn
    output_schema: ClassVar[type[BaseModel]] = SynthDagOut
    cost_hint: ClassVar[float] = 8.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.NON_RETRYABLE
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Agent: synthesize DAG"
    description: ClassVar[str] = (
        "Turn a natural-language objective into a GraphConfig at runtime, "
        "then execute the synthesized sub-graph."
    )

    def __init__(
        self,
        synthesizer: DagSynthesizer | None = None,
        *,
        warden: Warden | None = None,
        sentinel: Sentinel | None = None,
        principal: Principal | None = None,
        proportionality_judge: ProportionalityJudge | None = None,
        max_depth: int = _DEFAULT_MAX_DEPTH,
        run_store: DurableRunStore | None = None,
        canonical_run_store: RunStore | None = None,
        runtime: ExecutionRuntime | None = None,
        node_resolver: NodeResolver | None = None,
    ) -> None:
        self._synthesizer: DagSynthesizer = synthesizer or RuleDagSynthesizer()
        self._run_store = run_store
        self._canonical_run_store = canonical_run_store
        self._runtime = runtime
        self._node_resolver = node_resolver
        self._warden = warden or Warden()
        # Fail-closed by the shared Sentinel semantics (ADR-072726-0d6b,
        # #1165): with no governed permission source wired, the empty table
        # DENIES every ``authorize`` lookup, so a bare-constructed node refuses
        # to approve (and therefore dispatch) synthesized sub-graphs instead of
        # granting the synth action by omission. A deployment that wants
        # governed synth_dag authority wires an explicit Sentinel whose table
        # grants it; the compatibility escape hatch (allow_on_miss=True) is
        # deliberately not offered here -- production construction sites do not
        # get to re-arm allow-all.
        self._sentinel = sentinel or Sentinel(warden=self._warden, permission_table={})
        self._principal = principal or DEFAULT_PRINCIPAL
        self._proportionality_judge: ProportionalityJudge = (
            proportionality_judge or RuleProportionalityJudge()
        )
        self._max_depth = max_depth

    async def _admit_child(
        self,
        graph: Graph,
        ctx: NodeContext,
        *,
        provenance: dict[str, Any],
        blackboard_metadata: dict[str, Any],
    ) -> str | None:
        """Admit the child on the canonical spine before its first checkpoint.

        The Container's durable graph store is a projection of the canonical
        spine: it refuses to checkpoint a Run that `RunStore` has not admitted,
        and `run_durable_graph` against a canonical store consumes an admitted,
        still-QUEUED Run whose launch snapshot it re-reads (#1193). So admission
        is one durable write here, carrying the launch metadata, filed under the
        parent Run and NodeRun the way `agent.delegate_remote` files its child.
        Without a canonical store — an in-memory durable store in tests — the
        executor mints the Run itself, as it always did.
        """
        if self._canonical_run_store is None:
            return None
        from maistro.graph.durable_runs.launch import durable_graph_launch_provenance

        admitted = await self._canonical_run_store.create_run(
            graph,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id or None,
            actor_principal_id=ctx.user_id,
            provenance={
                **provenance,
                **durable_graph_launch_provenance(blackboard_metadata=blackboard_metadata),
            },
            initial_status=RunStatus.QUEUED,
        )
        return admitted.run_id

    def _child_resolver(self) -> NodeResolver:
        """The resolver the child graph builds its nodes with.

        The caller's wired one when there is one. `build_node_resolver` is
        where `agent.spawn_harness` gets its adapters, `agent.delegate_remote`
        its delegator and RunStore, and `rsi.quota_pace_trigger` the real usage
        log; constructing those from the bare registry passes `_registered`
        and then fails or computes against empty state inside the child. The
        bare fallback keeps a node built with no wiring behaving as it did.
        """
        if self._node_resolver is not None:
            return self._node_resolver
        return lambda node_id, graph: get_node(_node_kind(graph, node_id))()

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
            raise SynthDagFailed(
                f"recursion depth cap reached (depth={depth}, "
                f"max_depth={self._max_depth}) — refusing to spawn further sub-graphs"
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
            raise SynthDagFailed(_verdict_error(verdict))

        return await self._dispatch_or_decline(synth, synthesized_kinds, inputs, ctx, depth)

    async def _dispatch_or_decline(
        self,
        synth: SynthResult,
        synthesized_kinds: list[str],
        inputs: SynthDagIn,
        ctx: NodeContext,
        depth: int,
    ) -> SynthDagOut:
        """Run the approved config as a canonical child Run, or fail saying why (#520)."""
        if self._run_store is None:
            # This used to answer `success=True` with "execution skipped" —
            # a Graph node reporting success for work it did not do, in the
            # production resolver's own generic construction (#1193). The
            # in-process GraphRun path is retired (#520) and there is no
            # other way to run the sub-graph, so a node built without the
            # store fails as the node, loudly, rather than completing.
            raise NodeCompositionError(self.kind, missing=("graph_run_store", "run_store"))

        undispatchable = _undispatchable_reason(synth.graph_config, ctx, inputs.available_kinds)
        if undispatchable is not None:
            raise SynthDagFailed(f"dag synthesized — not executed: {undispatchable}")

        from maistro.graph.durable_runs import run_durable_graph

        child_graph = _child_graph(synth.graph_config, inputs.objective, ctx)
        provenance = {
            "admission_source": "agent.synth_dag",
            "objective": inputs.objective[:200],
        }
        # The child starts one level deeper than the node that spawned it,
        # so a nested agent.synth_dag inside it hits the same hard cap.
        blackboard_metadata = {"synth_depth": depth + 1}
        child = await run_durable_graph(
            child_graph,
            store=self._run_store,
            node_resolver=self._child_resolver(),
            actor_principal_id=ctx.user_id,
            run_id=await self._admit_child(
                child_graph, ctx, provenance=provenance, blackboard_metadata=blackboard_metadata
            ),
            run_store=self._canonical_run_store,
            # Deliberately NOT `self._runtime`. `ExecutionRuntime.execute`
            # holds a semaphore slot for the whole executor call, so the
            # parent Attempt is holding one while this awaits the child. On a
            # runtime with `max_concurrency=1` that is a guaranteed deadlock,
            # and on any bound a frontier of synth nodes can occupy every slot
            # while each waits for a child that cannot get one. The child gets
            # its own runtime and its own budget; sharing one would make
            # dispatch depend on capacity its own caller is consuming.
            runtime=None,
            parent_run_id=ctx.run_id,
            parent_node_run_id=ctx.node_run_id or None,
            provenance=provenance,
            blackboard_metadata=blackboard_metadata,
        )
        # A child parked WAITING or PAUSED has not failed — it is a wait or a
        # HITL pause the subgraph is entitled to, and calling it a failure
        # would put `sub-graph execution failed` on a Run that is still live.
        # A child that settled anywhere but COMPLETED is the parent's failure.
        if child.status in TERMINAL_RUN_STATUSES and child.status is not RunStatus.COMPLETED:
            raise SynthDagFailed(
                f"sub-graph execution {child.status.value}", child_run_id=child.run_id
            )
        return SynthDagOut(
            dispatched=True,
            synthesized_nodes=synthesized_kinds,
            rationale=synth.rationale,
            run_output=f"child run {child.run_id} {child.status.value}",
            child_run_id=child.run_id,
        )
