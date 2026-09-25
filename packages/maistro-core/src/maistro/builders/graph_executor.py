"""Graph-aware builder pipeline executor.

Drives a :class:`~maistro.builders.graph.PipelineGraph` to completion:
find ready nodes → check skip → dispatch the whole wave concurrently →
store outputs → evaluate gates → repeat until no ready nodes remain.

Differences from the Stronghold Epic-15 executor it recreates:

- Dispatch is a direct ``await`` against a :class:`PipelineDispatcher`
  protocol instead of an engine poll loop; timeouts use ``asyncio.timeout``.
- Independent ready nodes execute concurrently (Epic-15 modelled the
  parallelism but ran the ready set sequentially).
- A failed gate triggers a bounded verify-and-revise loop: the revise
  target and every completed descendant are cleared and re-executed with
  the gating node's output injected as ``<node>_feedback``.
- Every node execution consumes from a shared
  :class:`~maistro.graph.node.IterationBudget` (ADR-062); exhaustion halts
  the run gracefully.

Failure still halts the run before any *new* node starts (Epic-15 INV-07,
relaxed to wave granularity), and a timed-out node never runs its
``on_complete`` hook (INV-09).

This module also hosts the canonical execution adapter (#734):
:class:`CanonicalGraphPipelineExecutor` translates a ``PipelineGraph`` into
a canonical ``Graph`` and drives it through the public durable
Run/NodeRun/Attempt spine, keeping Builders prompts, context, skip
predicates, gates, revision feedback, hooks and result projection as domain
state. Builders production entrypoints use the canonical adapter below; the
pre-convergence private executor and its parity tests were removed once the
adapter's own behavioral coverage stood on its own.
The adapter lives in this module rather than one of its own because a new
module identity would register as new unreachable-module debt against the
trusted-base reachability ratchet, and #734 defers reachability bookkeeping
to #49; it already shares this module's private dispatch helpers.

A post-merge audit of #734/#744 (2026-09-07) found 4 concrete parity defects
between the canonical adapter and the legacy semantics above; #1067 fixes
all 4:

1. A same-wave revision now folds *after* the whole frontier settles
   (:class:`_RevisionLedger`), matching legacy's "gather everything, then
   apply gate failures" ordering, instead of mutating ``run.context``
   synchronously inside the failing node's own coroutine while a slower
   sibling in the same ``asyncio.gather`` batch could still be running.
   A follow-up review (2026-09-21) found the ledger's own ``flush()`` was
   still being called from inside each stage's ``_execute()`` -- safe only
   if every stage in a wave suspends before another one finishes, which an
   immediate/fast dispatcher does not guarantee. ``flush()`` now runs once
   per frontier, from the canonical node resolver (see :func:`_resolver`),
   which is only ever invoked by the durable walk's synchronous per-frontier
   prep loop -- strictly after the previous frontier's whole
   ``asyncio.gather`` batch has returned, and strictly before any member of
   the new one starts executing. The same review also found the transient
   "stale guard" skip marker was never cleared before a stage's real
   redispatch, so a stage that failed for real after an earlier stale defer
   was misreported as SKIPPED instead of FAILED (:func:`_project_stage`
   reads ``run.skipped_stages`` before consulting NodeRun status); the
   marker is now cleared as soon as a stage passes the stale guard, before
   any real work is attempted.
2. A gated node with ``revise_target=None`` revises itself (already fixed
   on ``develop`` before this audit landed, by an unrelated commit —
   ``target = node.revise_target or node.name`` here and in
   :func:`_revision_edges`).
3. :meth:`CanonicalGraphPipelineExecutor.execute` now derives the durable
   walk's step bound from Builders' own admitted pipeline size and
   iteration policy (:func:`_derived_max_steps`) instead of silently
   inheriting the durable executor's generic 256-step default.
4. The compatibility receipt (:func:`_project_canonical_record`) now
   derives the failed stage *and* its message together from canonical's
   own selected failure (the first exhausted failure in frontier order),
   instead of a reversed ``NodeRun`` scan paired with a separately, and
   racily, mutated ``run.failed_stage_error``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, run_durable_graph
from maistro.graph.node import IterationBudget
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import RunStatus

if TYPE_CHECKING:
    from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.runs.store import RunStore

logger = logging.getLogger("maistro.builders.graph_executor")

_DEFAULT_EXECUTIONS_PER_NODE = 3


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of dispatching one node to an agent."""

    ok: bool
    output: str = ""
    error: str = ""


class PipelineDispatcher(Protocol):
    """Seam between the executor and whatever runs the agents."""

    def supports(self, agent_name: str, node_name: str) -> bool:
        """Whether this dispatcher can execute the named agent for this node."""
        ...

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        """Execute one node and return its outcome."""
        ...


def _build_prompt(template: str, context: RunContext) -> str:
    class _Default(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_Default(context))
    except (ValueError, KeyError):
        return template


# --- Canonical execution adapter (#734) -------------------------------------
# Translated from the branch's standalone canonical_execution module into the
# executor module it already shares helpers with; see the module docstring.

_STAGE_KIND = "builders.pipeline_stage"
_START_KIND = "builders.frontier_start"
_STAGE_PREFIX = "builders-stage:"
_START_NODE_ID = "builders-frontier-start"
_ADMISSION_SOURCE = "builders"


class _StageInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _StageOutput(BaseModel):
    stage_name: str
    text: str = ""
    skipped: bool = False
    route: Literal["proceed", "revise"] = "proceed"


class _StartOutput(BaseModel):
    ready: bool = True


class _StartNode(BaseNode[_StageInput, _StartOutput]):
    kind: ClassVar[str] = _START_KIND
    input_schema: ClassVar[type[BaseModel]] = _StageInput
    output_schema: ClassVar[type[BaseModel]] = _StartOutput
    display_name: ClassVar[str] = "Start Builders ready frontier"
    description: ClassVar[str] = "Fan out to independent Builders root stages."

    async def _execute(self, inputs: _StageInput, ctx: NodeContext) -> _StartOutput:
        return _StartOutput()


@dataclass(frozen=True)
class _GateDecision:
    route: Literal["proceed", "revise"]
    halt_error: str | None = None


def _stage_node_id(stage_name: str) -> str:
    return f"{_STAGE_PREFIX}{stage_name}"


def _stage_name(node_id: str) -> str | None:
    if not node_id.startswith(_STAGE_PREFIX):
        return None
    return node_id[len(_STAGE_PREFIX) :]


def _mark_skipped(run: Any, stage_name: str) -> None:
    if stage_name not in run.skipped_stages:
        run.skipped_stages.append(stage_name)


def _unmark_skipped(run: Any, stage_name: str) -> None:
    if stage_name in run.skipped_stages:
        run.skipped_stages.remove(stage_name)


@dataclass
class _RevisionLedger:
    """Per-run bookkeeping that folds a same-wave revision after the wave settles.

    Legacy ``GraphPipelineExecutor`` dispatched a whole ready wave concurrently,
    gathered every outcome, recorded same-wave completions, and only *then*
    applied gate failures -- so a revision's invalidation of its stale
    descendants always landed after every sibling in that wave had already
    written its result (see the graph_executor module docstring's #734 entry
    and issue #1067). The canonical adapter's per-node ``_StageNode._execute``
    used to apply that invalidation eagerly, inside the *failing* node's own
    coroutine, while a slower sibling dispatched in the very same
    ``asyncio.gather`` batch (see ``attempt_executor._execute_frontier``)
    could still be running and write its own (now stale) output back into the
    just-cleared ``run.context`` afterward -- and the generic durable fold
    would then route that sibling's ordinary successor forward in the very
    same frontier as the revision, before the revision target had a chance to
    redo the work the sibling's output actually depended on.

    This ledger fixes both halves without teaching Builders to re-implement
    canonical traversal:

    * A failed gate's invalidation is *queued*, not applied, by
      :func:`_gate_decision`. :meth:`flush` applies every queued
      invalidation exactly once, from :func:`_resolver`'s ``resolve``
      closure -- the canonical durable walk's ``node_resolver`` callback,
      which ``attempt_executor._execute_frontier`` calls synchronously, once
      per frontier member, in a plain loop that runs entirely *before* that
      frontier's ``asyncio.gather`` batch is even created (see
      ``_execute_frontier``'s ``prepared`` loop). Walk steps are themselves
      sequential (``_walk_until_settled`` awaits one ``_walk_frontier`` call
      to completion before starting the next), so by the time ``resolve``
      is invoked for a frontier, every coroutine from the *previous*
      frontier's ``asyncio.gather`` has already returned -- nothing more can
      write to the entries a flush is about to clear. Flushing from
      ``resolve`` instead of from each stage's own ``_execute`` matters
      because two stages *in the same wave* both go through ``_execute``
      too, and with a fast/immediate dispatcher one can run to completion --
      including queuing its own gate failure -- before a sibling dispatched
      in the very same ``asyncio.gather`` batch has even started; a flush
      called from inside ``_execute`` would then apply that invalidation to
      a wave-mate that hasn't been dispatched yet, failing it out of the
      wave instead of giving it the dispatch legacy semantics require every
      admitted wave member to receive. Flushing once per frontier from
      ``resolve`` reproduces legacy's "gather everything, then apply gate
      failures" ordering at true frontier granularity instead of node
      granularity.
    * :attr:`satisfied` mirrors legacy's ``completed | skipped`` set.
      :meth:`ready` answers the same question legacy's own ``ready()``
      asked before ever dispatching a node: are this node's dependencies
      *genuinely* done. A stage the canonical fold routed to only because a
      stale sibling's ordinary (unconditioned) edge fired in the same
      frontier as the revision finds its own dependency missing from
      ``satisfied`` and defers instead of running against missing or stale
      input; canonical's ordinary edges re-offer it for real, with a fresh
      NodeRun, once its true predecessor genuinely re-completes.
    """

    satisfied: set[str] = field(default_factory=set)
    _pending: list[tuple[frozenset[str], str, str]] = field(default_factory=list)

    def mark_satisfied(self, name: str) -> None:
        self.satisfied.add(name)

    def ready(self, node: PipelineNode) -> bool:
        return all(dep in self.satisfied for dep in node.depends_on)

    def queue_revision(self, stale: frozenset[str], feedback_key: str, feedback: str) -> None:
        self._pending.append((stale, feedback_key, feedback))

    def flush(self, run: Any) -> None:
        if not self._pending:
            return
        for stale, feedback_key, feedback in self._pending:
            self.satisfied -= stale
            run.skipped_stages[:] = [name for name in run.skipped_stages if name not in stale]
            for name in stale:
                run.context.pop(name, None)
            run.context[feedback_key] = feedback
        self._pending.clear()


def _gate_decision(
    graph: PipelineGraph,
    node: PipelineNode,
    run: Any,
    ledger: _RevisionLedger,
) -> _GateDecision:
    """Apply Builders gate domain semantics without owning canonical lifecycle."""
    used = int(run.revisions.get(node.name, 0))
    if used >= node.max_revisions:
        if node.gate_exhausted == "continue":
            if node.name not in run.gate_exhausted:
                run.gate_exhausted.append(node.name)
            return _GateDecision(route="proceed")
        error = f"Gate failed after {used} revisions"
        run.failed_stage_error = error
        return _GateDecision(route="proceed", halt_error=error)

    run.revisions[node.name] = used + 1
    # A gate without an explicit target revises its own evaluation.  The
    # canonical graph therefore gets a real conditional back-edge instead of
    # silently treating the failed gate as terminal.
    target = node.revise_target or node.name
    stale = frozenset({target} | set(graph.descendants(target)))
    feedback = run.context.get(node.name, "")
    # Queued, not applied: see _RevisionLedger.
    ledger.queue_revision(stale, f"{node.name}_feedback", feedback)
    return _GateDecision(route="revise")


def _stale_guard_output(
    node: PipelineNode,
    run: Any,
    ledger: _RevisionLedger,
) -> _StageOutput | None:
    """Defer a stage the fold routed to before its own dependency truly settled.

    Only reachable once a revision has actually invalidated one of this
    node's dependencies (see ``_RevisionLedger``); on every ordinary
    dispatch ``ledger.ready`` is vacuously true. Deliberately does *not*
    mark the node satisfied -- it must stay eligible for this same check on
    its own downstream dependents, and for a genuine re-dispatch once its
    real predecessor re-completes.
    """
    if ledger.ready(node):
        return None
    _mark_skipped(run, node.name)
    return _StageOutput(stage_name=node.name, skipped=True)


def _skip_output(
    node: PipelineNode,
    run: Any,
    dispatcher: PipelineDispatcher,
    ledger: _RevisionLedger,
) -> _StageOutput | None:
    should_skip = node.skip_if is not None and node.skip_if(run.context)
    if not should_skip and dispatcher.supports(node.agent_name, node.name):
        return None
    _mark_skipped(run, node.name)
    ledger.mark_satisfied(node.name)
    return _StageOutput(stage_name=node.name, skipped=True)


def _reserve_iteration(run: Any, budget: IterationBudget) -> None:
    if budget.consume():
        return
    error = "iteration budget exhausted"
    run.failed_stage_error = error
    raise RuntimeError(error)


async def _dispatch_stage(
    node: PipelineNode,
    run: Any,
    dispatcher: PipelineDispatcher,
    ctx: NodeContext,
) -> Any:
    prompt = _build_prompt(node.prompt_template, run.context)
    try:
        async with asyncio.timeout(node.timeout_seconds):
            result = await dispatcher.run(
                run_id=ctx.run_id,
                node_name=node.name,
                agent_name=node.agent_name,
                prompt=prompt,
                context=run.context,
            )
    except TimeoutError as exc:
        error = f"Stage timed out after {node.timeout_seconds:.0f}s"
        run.failed_stage_error = error
        raise RuntimeError(error) from exc

    if not result.ok:
        run.failed_stage_error = result.error
        raise RuntimeError(result.error or f"{node.name} failed")
    return result


async def _commit_stage_result(node: PipelineNode, run: Any, result: Any) -> None:
    run.context[node.name] = result.output
    if node.on_complete is not None:
        await node.on_complete(run, result.output)
    if str(run.status).startswith("failed at "):
        raise RuntimeError(run.failed_stage_error or f"{node.name} failed")


def _route_stage_result(
    graph: PipelineGraph,
    node: PipelineNode,
    run: Any,
    result: Any,
    ledger: _RevisionLedger,
) -> _StageOutput:
    if node.gate is None or node.gate(run.context):
        _unmark_skipped(run, node.name)
        ledger.mark_satisfied(node.name)
        return _StageOutput(stage_name=node.name, text=result.output)

    decision = _gate_decision(graph, node, run, ledger)
    if decision.halt_error is not None:
        raise RuntimeError(decision.halt_error)
    if decision.route == "proceed":
        # gate_exhausted == "continue": the gate never passed, but the run
        # moves on as if it had.
        _unmark_skipped(run, node.name)
        ledger.mark_satisfied(node.name)
    return _StageOutput(
        stage_name=node.name,
        text=result.output,
        route=decision.route,
    )


class _StageNode(BaseNode[_StageInput, _StageOutput]):
    kind: ClassVar[str] = _STAGE_KIND
    input_schema: ClassVar[type[BaseModel]] = _StageInput
    output_schema: ClassVar[type[BaseModel]] = _StageOutput
    display_name: ClassVar[str] = "Execute Builders pipeline stage"
    description: ClassVar[str] = "Run one Builders stage under canonical Attempt evidence."
    # Replay policy lives only in the inherited ReplaySemantics contract
    # (PURE here); the former dead `idempotent: ClassVar[bool]` flag was a
    # lying second source of truth (#1194 residual).
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        *,
        graph: PipelineGraph,
        node: PipelineNode,
        run: Any,
        dispatcher: PipelineDispatcher,
        budget: IterationBudget,
        ledger: _RevisionLedger,
    ) -> None:
        self._graph = graph
        self._node = node
        self._run = run
        self._dispatcher = dispatcher
        self._budget = budget
        self._ledger = ledger

    async def _execute(self, inputs: _StageInput, ctx: NodeContext) -> _StageOutput:
        # Ledger invalidation is flushed once per frontier from _resolver's
        # `resolve` closure, not here -- see _RevisionLedger's docstring for
        # why a per-task flush inside _execute is unsafe against a
        # fast/immediate dispatcher.
        guard = _stale_guard_output(self._node, self._run, self._ledger)
        if guard is not None:
            return guard

        # Past the stale guard: this is a genuine attempt at this stage's
        # real terminal work (a real skip, or a real dispatch), not another
        # transient defer. Clear the transient marker now, before that real
        # work is attempted, not only after it succeeds -- otherwise a stage
        # that hit the guard earlier and then genuinely fails here (dispatch
        # error, timeout, budget exhaustion, a failing on_complete hook)
        # never reaches _route_stage_result's _unmark_skipped, and
        # _project_stage -- which checks run.skipped_stages before NodeRun
        # status -- reports it SKIPPED even though it canonically FAILED.
        # _skip_output immediately re-marks it if this stage genuinely does
        # skip, so this is never a false negative.
        _unmark_skipped(self._run, self._node.name)

        skipped = _skip_output(self._node, self._run, self._dispatcher, self._ledger)
        if skipped is not None:
            return skipped

        _reserve_iteration(self._run, self._budget)
        result = await _dispatch_stage(self._node, self._run, self._dispatcher, ctx)
        await _commit_stage_result(self._node, self._run, result)
        return _route_stage_result(self._graph, self._node, self._run, result, self._ledger)


def _roots(graph: PipelineGraph) -> list[PipelineNode]:
    return [node for node in graph if not node.depends_on]


def _fanout_edges(
    source: str,
    targets: list[str],
    *,
    condition: str | None = None,
) -> list[Edge]:
    """Encode one canonical ready wave as one sequential edge plus parallel siblings."""
    return [
        Edge(
            from_node=source,
            to_node=target,
            condition=condition,
            metadata={"parallel": True} if index else {},
        )
        for index, target in enumerate(targets)
    ]


def _canonical_stage_nodes(graph: PipelineGraph) -> list[Node]:
    return [
        Node(
            node_id=_stage_node_id(node.name),
            node_type=_STAGE_KIND,
            name=node.name,
            metadata={"builders_stage": node.name},
            policies={"max_attempts": 1},
        )
        for node in graph
    ]


def _dependency_edges(graph: PipelineGraph) -> list[Edge]:
    by_name = {node.name: node for node in graph}
    successors: dict[str, list[str]] = {node.name: [] for node in graph}
    for node in graph:
        for dependency in node.depends_on:
            successors[dependency].append(node.name)

    edges: list[Edge] = []
    for predecessor_name, successor_names in successors.items():
        predecessor = by_name[predecessor_name]
        edges.extend(
            _fanout_edges(
                _stage_node_id(predecessor_name),
                [_stage_node_id(name) for name in successor_names],
                condition="route == 'proceed'" if predecessor.gate is not None else None,
            )
        )
    return edges


def _revision_edges(graph: PipelineGraph) -> list[Edge]:
    return [
        Edge(
            from_node=_stage_node_id(node.name),
            to_node=_stage_node_id(node.revise_target or node.name),
            condition="route == 'revise'",
            metadata={"builders_revision": True},
        )
        for node in graph
        if node.gate is not None
    ]


def _entry_frontier(graph: PipelineGraph) -> tuple[str, list[Node], list[Edge]]:
    roots = _roots(graph)
    if len(roots) == 1:
        return _stage_node_id(roots[0].name), [], []

    control_node = Node(
        node_id=_START_NODE_ID,
        node_type=_START_KIND,
        name="Builders ready frontier",
        policies={"max_attempts": 1},
        metadata={"builders_control": True},
    )
    control_edges = _fanout_edges(
        _START_NODE_ID,
        [_stage_node_id(root.name) for root in roots],
    )
    return _START_NODE_ID, [control_node], control_edges


def _canonical_graph(
    graph: PipelineGraph,
    *,
    run: Any,
    workspace_id: str,
    project_id: str,
) -> Graph:
    entry, control_nodes, control_edges = _entry_frontier(graph)
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"Builders pipeline #{run.issue_number}",
        description=str(run.title),
        nodes=[*control_nodes, *_canonical_stage_nodes(graph)],
        edges=[*_dependency_edges(graph), *_revision_edges(graph), *control_edges],
        metadata={
            "entry_node": entry,
            "execution_owner": "canonical_run",
            "product": "builders",
            "pipeline_id": str(run.id),
        },
    )


def _resolver(
    graph: PipelineGraph,
    *,
    run: Any,
    dispatcher: PipelineDispatcher,
    budget: IterationBudget,
) -> Callable[[str, Graph], BaseNode[Any, Any]]:
    stages = {node.name: node for node in graph}
    start = _StartNode()
    # One ledger shared by every stage of this run: revision invalidation and
    # dependency-readiness are properties of the whole wave, not one node.
    ledger = _RevisionLedger()
    stage_nodes = {
        name: _StageNode(
            graph=graph,
            node=node,
            run=run,
            dispatcher=dispatcher,
            budget=budget,
            ledger=ledger,
        )
        for name, node in stages.items()
    }

    def resolve(node_id: str, _canonical_graph: Graph) -> BaseNode[Any, Any]:
        # `attempt_executor._execute_frontier` calls this once per frontier
        # member, synchronously, for the *whole* frontier, before creating
        # that frontier's `asyncio.gather` batch -- and only after the
        # previous frontier's own batch has fully returned (walk steps are
        # sequential). That makes this the one place a same-wave revision's
        # queued invalidation can be applied without a race against a
        # still-running (or not-yet-started) wave-mate: see
        # _RevisionLedger's docstring.
        ledger.flush(run)
        if node_id == _START_NODE_ID:
            return start
        name = _stage_name(node_id)
        if name is None or name not in stage_nodes:
            raise KeyError(f"unknown Builders canonical node {node_id!r}")
        return stage_nodes[name]

    return resolve


def _latest_stage_runs(record: DurableRunRecord) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for node_run in record.node_runs:
        name = _stage_name(node_run.node_id)
        if name is not None:
            latest[name] = node_run
    return latest


#: Every Builders stage failure path -- dispatch failure, timeout, gate
#: exhaustion, iteration-budget exhaustion, and a status-setting on_complete
#: hook -- raises ``RuntimeError(message)`` (see _dispatch_stage,
#: _gate_decision, _reserve_iteration, _commit_stage_result). BaseNode.run
#: captures that uniformly as ``error_code=type(exc).__name__`` and
#: ``error_message=str(exc)``, and canonical's own logical fold then stores
#: ``f"{error_code}: {error_message}"`` on the NodeRun (see
#: authoritative_fold._logical_outcome). Stripping this fixed, always-present
#: prefix recovers the exact domain message Builders raised.
_RUNTIME_ERROR_PREFIX = "RuntimeError: "


def _stage_failure_message(node_run: Any) -> str:
    """Recover the bare Builders failure message from canonical NodeRun evidence."""
    error = str(node_run.error or "")
    if error.startswith(_RUNTIME_ERROR_PREFIX):
        return error[len(_RUNTIME_ERROR_PREFIX) :]
    return error


def _failed_stage(record: DurableRunRecord) -> tuple[str, str] | None:
    """The stage name and message canonical Run itself selected as authoritative.

    Canonical's own ``first_exhausted_failure`` (see
    ``durable_runs.executor``) picks the *first* exhausted failure in
    frontier order -- every Builders stage policy is ``max_attempts: 1`` (see
    ``_canonical_stage_nodes``), so every stage failure is exhausted
    immediately and this is always the failure that terminalized the Run.
    Scanning ``record.node_runs`` forward (not reversed) for the first
    failure, and reading its own error text rather than the separately
    mutated ``run.failed_stage_error``, is what makes the projected stage
    name and its error come from the *same* selected failure instead of two
    different concurrent dispatchers' writes (issue #1067).
    """
    for node_run in record.node_runs:
        name = _stage_name(node_run.node_id)
        if name is not None and node_run.status is RunStatus.FAILED:
            return name, _stage_failure_message(node_run)
    return None


def _project_run_status(
    run: Any,
    record: DurableRunRecord,
    failure: tuple[str, str] | None,
) -> None:
    if record.run.status is RunStatus.COMPLETED:
        run.status = "completed"
    elif failure is not None:
        failed_stage, message = failure
        if "iteration budget exhausted" in message:
            run.status = f"halted at {failed_stage}: iteration budget exhausted"
        else:
            run.status = f"failed at {failed_stage}"
    else:
        run.status = record.run.status.value


def _project_stage(
    run: Any,
    stage: Any,
    node_run: Any,
    failure: tuple[str, str] | None,
) -> None:
    if stage.name in run.skipped_stages:
        stage.status = _stage_status("skipped")
    elif node_run is None:
        stage.status = _stage_status("pending")
    elif node_run.status is RunStatus.COMPLETED:
        stage.status = _stage_status("completed")
    elif node_run.status is RunStatus.RUNNING:
        stage.status = _stage_status("running")
    elif node_run.status in {
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }:
        stage.status = _stage_status("failed")
        if failure is not None and stage.name == failure[0]:
            stage.error = failure[1]


def _project_canonical_record(run: Any, record: DurableRunRecord) -> None:
    """Refresh the compatibility receipt from canonical execution evidence."""
    latest_by_stage = _latest_stage_runs(record)
    failure = _failed_stage(record)
    if failure is not None:
        # Overwrite whichever concurrently-dispatched stage last raced to set
        # this: the receipt's error must come from the same selected failure
        # as run.status, not from an unrelated stage's write (#1067).
        run.failed_stage_error = failure[1]
    _project_run_status(run, record, failure)
    for stage in getattr(run, "stages", ()):
        _project_stage(run, stage, latest_by_stage.get(stage.name), failure)


def _stage_status(value: str) -> Any:
    # Local import avoids a module cycle: pipeline imports this adapter.
    from maistro.builders.pipeline import StageStatus

    return StageStatus(value)


def _derived_max_steps(graph: PipelineGraph, budget: IterationBudget) -> int:
    """Bound the durable walk by what Builders' own iteration policy allows.

    ``run_durable_graph`` counts walk *steps* (frontiers), not node
    dispatches, and its generic default (256) is a ceiling picked for
    callers with no domain-specific bound of their own -- not one derived
    from a Builders pipeline's own size or iteration policy (#1067's defect
    3). A real dispatch always consumes exactly one unit of ``budget``
    (``_reserve_iteration``), so ``budget.max_iterations`` alone already
    bounds every step that does real work.

    A skip-only frontier -- a ``skip_if`` node, the multi-root fan-out
    control frontier (``_entry_frontier``), or a revision target settling
    back through its own stale descendants (``_stale_guard_output``) --
    does not consume the budget, but it is *not* bounded at one free step
    per graph node for the whole run the way an earlier version of this
    function assumed. Every gated node's own revision loop (``_gate_decision``
    / ``max_revisions``) can re-walk its ``revise_target``'s entire stale
    chain -- target plus every descendant up to the gate itself -- once per
    failed attempt, and a real dispatch check (``_reserve_iteration``) only
    ever happens once that whole chain has re-settled. So each of the
    (at most) ``budget.max_iterations`` real dispatches the budget allows can
    be preceded by up to ``len(graph) - 1`` free frontiers replaying that
    chain -- not by one free frontier total. A 100-node pipeline with a
    single always-skipped root, one always-failing gated child revising it,
    and 98 unrelated always-skipped roots demonstrates the gap concretely:
    with the old ``budget.max_iterations + len(graph) + 1`` formula and the
    default ``max_iterations=300`` the derived bound was 401, but the walk
    needs roughly ``2 * 300`` steps (one free root-settle frontier
    alternating with one budget-consuming gate frontier) to legitimately
    exhaust the 300-iteration budget -- so it hit ``StepBudgetExhausted``
    after only ~200 real dispatches instead of reaching genuine budget
    exhaustion.

    Bounding by ``budget.max_iterations * len(graph)`` instead is sound
    for any topology: every step is either one of the (at most)
    ``budget.max_iterations`` budget-consuming dispatches, or a free
    settle-frontier for some node revisited by a revision -- and a single
    uninterrupted stretch of free frontiers between two real dispatches can
    touch each of the graph's own nodes at most once (a node cannot be
    revisited a second time without an intervening gated dispatch, since
    only a gate's own failure re-queues an invalidation), so it is bounded
    by ``len(graph)``. ``+ len(graph) + 1`` covers the initial free settle
    before the first real dispatch and the multi-root control frontier.
    ``max()`` against the durable executor's own default keeps small,
    non-revising pipelines exactly as bounded as before.
    """
    from maistro.graph.durable_runs import DEFAULT_MAX_STEPS

    size = len(graph)
    return max(DEFAULT_MAX_STEPS, budget.max_iterations * size + size + 1)


class CanonicalGraphPipelineExecutor:
    """Execute a Builders ``PipelineGraph`` on the canonical durable spine."""

    def __init__(
        self,
        dispatcher: PipelineDispatcher,
        *,
        run_store: RunStore | None = None,
        durable_store: DurableRunStore | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        actor_principal_id: str | None = None,
        budget: IterationBudget | None = None,
    ) -> None:
        if (run_store is None) != (durable_store is None):
            raise ValueError("run_store and durable_store must be supplied together")
        if run_store is not None and (workspace_id is None or project_id is None):
            raise ValueError("workspace_id and project_id are required with explicit stores")
        if run_store is None and project_id is not None:
            raise ValueError("project_id requires explicit canonical stores")
        self._dispatcher = dispatcher
        self._run_store = run_store
        self._durable_store = durable_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._actor_principal_id = actor_principal_id
        self._budget = budget

    async def _ensure_default_stores(self) -> None:
        """Build an isolated canonical owner for compatibility callers.

        Product callers should inject their wired stores. The fallback keeps the
        historical Builders entrypoints usable while still making the canonical
        spine authoritative for every execution.
        """
        if self._run_store is not None:
            return
        from maistro.graph.durable_runs import (
            CanonicalDurableRunStore,
            InMemoryGraphContinuationStore,
        )
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        workspace_id = self._workspace_id or "builders"
        project_store = InMemoryProjectScopeStore()
        project = await project_store.create_root(workspace_id)
        run_store = InMemoryRunStore(project_store=project_store)
        self._workspace_id = workspace_id
        self._project_id = project.project_id
        self._run_store = run_store
        self._durable_store = CanonicalDurableRunStore(
            run_store,
            InMemoryGraphContinuationStore(),
        )

    async def execute(self, graph: PipelineGraph, run: Any) -> DurableRunRecord:
        """Run one Builders pipeline as canonical Graph -> Run -> NodeRun -> Attempt work."""
        errors = graph.validate()
        if errors:
            raise ValueError(f"invalid Builders pipeline graph: {'; '.join(errors)}")

        await self._ensure_default_stores()
        assert self._run_store is not None
        assert self._durable_store is not None
        assert self._workspace_id is not None
        assert self._project_id is not None
        budget = self._budget or IterationBudget(
            max_iterations=_DEFAULT_EXECUTIONS_PER_NODE * len(graph)
        )
        canonical = _canonical_graph(
            graph,
            run=run,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        )
        provenance = {
            "admission_source": _ADMISSION_SOURCE,
            "product": "builders",
            "pipeline_id": str(run.id),
            "issue_number": int(run.issue_number),
        }
        admitted = await self._run_store.create_run(
            canonical,
            actor_principal_id=self._actor_principal_id,
            provenance=provenance,
            initial_status=RunStatus.QUEUED,
        )
        run.canonical_run_id = admitted.run_id
        # Compatibility projection only. Canonical Run/NodeRun/Attempt remain
        # authoritative for lifecycle; legacy hooks may still inspect this receipt.
        run.status = "running"
        record = await run_durable_graph(
            canonical,
            store=self._durable_store,
            node_resolver=_resolver(
                graph,
                run=run,
                dispatcher=self._dispatcher,
                budget=budget,
            ),
            actor_principal_id=self._actor_principal_id,
            run_id=run.canonical_run_id,
            provenance=provenance,
            run_store=self._run_store,
            max_steps=_derived_max_steps(graph, budget),
        )
        _project_canonical_record(run, record)
        return record
