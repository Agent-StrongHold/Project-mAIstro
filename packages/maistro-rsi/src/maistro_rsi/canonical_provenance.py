"""RSI campaigns and cycles on the canonical Run -> NodeRun -> Attempt spine.

Epic #552 / child #50: an RSI campaign is ordinary work, and work has exactly
one execution identity — ``Goal -> Graph -> Run -> NodeRun -> Attempt``
(ADR-081226-a66b). Before this module, the only "runner" identity an RSI
cycle carried was its own private ``RsiCycleResult.run_id``; nothing in the
engine could answer "which canonical Run was this cycle?".

This adapter (modeled on Canvas's ``canonical_execution.py``) closes that gap
without moving authority anywhere:

* **admit_cycle** files one Run per cycle in an already-authorized
  Workspace/Project scope, with the campaign id, the cycle's work-source
  provenance, and the operator's budget in ``Run.provenance``;
* **run_cycle** executes the cycle callable *through* the canonical Runtime —
  the cycle's body becomes one physical Attempt whose terminal evidence is
  durable in the public RunStore, not in an RSI-private ledger;
* **record_completed_cycle** is the receipt path for drivers that already ran
  the physical work themselves (the local loop): it admits and terminalizes
  the same canonical identity from the cycle's observed outcome, so both RSI
  drivers leave the same trail.

The seam never schedules, never retries, never authorizes, and never becomes
a second execution lifecycle: statuses come from ``maistro.runs``, and the
caller still owns when (and whether) a cycle runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.service import RunExecutionService
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

logger = structlog.get_logger()

#: ``Run.provenance[ADMISSION_SOURCE]`` value for work RSI admitted (#50).
RSI_ADMISSION_SOURCE = "rsi"

#: The node kind of an RSI cycle. Not registered in the node catalog on
#: purpose: RSI owns its executor (the cycle callable), exactly like Canvas
#: owns ``canvas.*`` stages — admission through ``runs.admission`` is for
#: work the generic dispatcher will run, which is not what an RSI cycle is.
RSI_CYCLE_NODE_TYPE = "rsi.cycle"

#: ``executor_id`` stamped on every RSI cycle Attempt.
RSI_CYCLE_EXECUTOR_ID = "rsi_cycle"

#: Provenance keys this seam writes; exported so callers/tests read them by
#: the same spelling the adapter wrote them with.
RSI_CAMPAIGN_ID_KEY = "rsi_campaign_id"
RSI_CYCLE_ID_KEY = "rsi_cycle_id"
RSI_BUDGET_KEY = "rsi_budget"
RSI_WORK_ITEM_ID_KEY = "rsi_work_item_id"


class RsiProvenanceError(RuntimeError):
    """The canonical identity for an RSI cycle could not be established."""


@dataclass(frozen=True)
class CanonicalCycleRecord:
    """The canonical identity one RSI cycle left behind, and its outcome."""

    campaign_id: str
    cycle_id: str
    run_id: str
    node_run_id: str
    attempt_id: str
    run_status: str
    node_run_status: str
    attempt_status: str

    @property
    def completed(self) -> bool:
        return self.run_status == RunStatus.COMPLETED.value


def _require_non_empty(value: str, field: str) -> str:
    if not value.strip():
        raise RsiProvenanceError(f"{field} must be a non-empty string")
    return value


def cycle_graph(
    *,
    workspace_id: str,
    project_id: str,
    campaign_id: str,
    cycle_id: str,
    objective: str,
    parameters: dict[str, Any] | None = None,
) -> Graph:
    """The one-node Graph one RSI cycle admits under.

    The objective (and any extra cycle parameters) ride the node definition,
    so the Run's immutable Graph snapshot alone says what this cycle was
    asked to do — not just what an RSI-private log says it did.
    """
    return Graph(
        graph_id=f"rsi:{campaign_id}:{cycle_id}",
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"RSI cycle {cycle_id}",
        description=objective,
        nodes=[
            Node(
                node_id=f"rsi:{campaign_id}:{cycle_id}",
                node_type=RSI_CYCLE_NODE_TYPE,
                name=f"RSI cycle {cycle_id}",
                parameters={"objective": objective, **(parameters or {})},
            )
        ],
        edges=[],
        metadata={"rsi_campaign_id": campaign_id, "rsi_cycle_id": cycle_id},
    )


class RsiCycleProvenance:
    """Record RSI cycles as canonical Runs in one bound Workspace/Project.

    The scope bindings are constructor arguments supplied by the caller after
    authorization — this adapter never derives a Workspace or Project from an
    RSI-owned identity, and never grants one.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        workspace_id: str,
        project_id: str,
        runtime: ExecutionRuntime | None = None,
    ) -> None:
        _require_non_empty(workspace_id, "workspace_id")
        _require_non_empty(project_id, "project_id")
        self._runs = run_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
        )

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def project_id(self) -> str:
        return self._project_id

    async def find_cycle(self, campaign_id: str, cycle_id: str) -> Run | None:
        """The Run an earlier call already admitted for this cycle, if any.

        Idempotent admission's read half: a retried campaign re-admits the
        same identity instead of leaving orphaned duplicates behind.
        """
        for status in RunStatus:
            runs = await self._runs.list_by_status(
                status,
                limit=10_000,
                project_id=self._project_id,
                admission_source=RSI_ADMISSION_SOURCE,
            )
            for run in runs:
                if (
                    run.provenance.get(RSI_CAMPAIGN_ID_KEY) == campaign_id
                    and run.provenance.get(RSI_CYCLE_ID_KEY) == cycle_id
                ):
                    return run
        return None

    async def admit_cycle(
        self,
        *,
        campaign_id: str,
        cycle_id: str,
        objective: str,
        actor_principal_id: str,
        parameters: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        work_item_id: str | None = None,
        goal_id: str | None = None,
        goal_revision: int | None = None,
    ) -> Run:
        """Admit one RSI cycle as a canonical Run (idempotent per cycle id).

        ``actor_principal_id`` is required: a Run is attributable work, and an
        unattributable self-improvement cycle is exactly what provenance
        exists to prevent. The Goal binding, when given, is the already
        authorized pair (#1572) — this seam records it, never resolves it.
        """
        _require_non_empty(campaign_id, "campaign_id")
        _require_non_empty(cycle_id, "cycle_id")
        _require_non_empty(objective, "objective")
        _require_non_empty(actor_principal_id, "actor_principal_id")
        existing = await self.find_cycle(campaign_id, cycle_id)
        if existing is not None:
            return existing
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: RSI_ADMISSION_SOURCE,
            RSI_CAMPAIGN_ID_KEY: campaign_id,
            RSI_CYCLE_ID_KEY: cycle_id,
        }
        if budget is not None:
            provenance[RSI_BUDGET_KEY] = dict(budget)
        if work_item_id is not None:
            _require_non_empty(work_item_id, "work_item_id")
            provenance[RSI_WORK_ITEM_ID_KEY] = work_item_id
        graph = cycle_graph(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            campaign_id=campaign_id,
            cycle_id=cycle_id,
            objective=objective,
            parameters=parameters,
        )
        # The store (not the service wrapper) is the one create_run surface
        # that accepts the #1572 Goal binding; the service adds nothing here
        # and would silently drop it.
        if (goal_id is None) != (goal_revision is None):
            raise RsiProvenanceError(
                "goal binding is both-or-neither: set goal_id and goal_revision together"
            )
        return await self._runs.create_run(
            graph,
            actor_principal_id=actor_principal_id,
            provenance=provenance,
            goal_id=goal_id,
            goal_revision=goal_revision,
        )

    async def run_cycle(
        self,
        run: Run,
        cycle: Callable[[], Awaitable[Any]],
        *,
        timeout_s: float | None = None,
    ) -> CanonicalCycleRecord:
        """Execute one already-admitted cycle through the canonical spine.

        The cycle callable runs as the Attempt's executor: its return value
        becomes the Attempt's durable result; an exception becomes the
        Attempt's durable failure. Either way the physical evidence lands in
        the RunStore, and the Run is closed explicitly afterwards (the spine
        settles the single NodeRun, and this seam — the domain here — owns
        the Run's disposition, exactly as Canvas's stage adapter does).
        """
        node_id = run.graph.materialize().nodes[0].node_id
        await self._resume_for_execution(run)

        async def _execute(_work_item: object, _context: object) -> Any:
            return await cycle()

        context = {
            "run_id": run.run_id,
            "campaign_id": run.provenance.get(RSI_CAMPAIGN_ID_KEY),
            "cycle_id": run.provenance.get(RSI_CYCLE_ID_KEY),
        }
        try:
            node_run, _attempt = await self._service.execute_node(
                run.run_id,
                node_id,
                None,
                context,
                executor=_execute,
                executor_id=RSI_CYCLE_EXECUTOR_ID,
                timeout_s=timeout_s,
            )
        except BaseException as exc:
            # The spine terminalized the Attempt (the physical evidence) but
            # parks the logical NodeRun in WAITING: the failure projection is
            # the domain's decision, and this seam — the domain here — makes
            # it. Settle NodeRun then Run to FAILED before re-raising, so the
            # failure propagates to the caller exactly as it did before this
            # seam, with the canonical trail already terminal.
            await self._fail_run(run.run_id, error=str(exc))
            raise
        return await self._close_run_from_node(run.run_id, node_run.node_run_id)

    async def _fail_run(self, run_id: str, *, error: str) -> None:
        """Project a failed cycle onto NodeRun and Run (Canvas's fail path)."""
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return
        for node_run in await self._runs.list_node_runs(run_id):
            current = node_run
            if current.status in TERMINAL_RUN_STATUSES:
                continue
            for status in transition_path(current.status, RunStatus.FAILED):
                current = await self._runs.transition_node_run(
                    current.node_run_id,
                    status,
                    error=error if status is RunStatus.FAILED else None,
                )
        run = await self._require_run(run_id)
        for status in transition_path(run.status, RunStatus.FAILED):
            run = await self._runs.transition_run(
                run_id, status, error=error if status is RunStatus.FAILED else None
            )

    async def record_completed_cycle(
        self,
        *,
        campaign_id: str,
        cycle_id: str,
        objective: str,
        actor_principal_id: str,
        outcome: dict[str, Any],
        failed: bool = False,
        error: str | None = None,
        budget: dict[str, Any] | None = None,
        work_item_id: str | None = None,
    ) -> CanonicalCycleRecord:
        """Record a cycle the caller already executed, as canonical work.

        The receipt path for sync drivers (the local loop): the physical work
        is done and its outcome is observed, so the Run admits, runs, and
        terminalizes in one recorded sequence whose evidence is the observed
        outcome — never a fabricated success.
        """
        run = await self.admit_cycle(
            campaign_id=campaign_id,
            cycle_id=cycle_id,
            objective=objective,
            actor_principal_id=actor_principal_id,
            budget=budget,
            work_item_id=work_item_id,
        )
        node_id = run.graph.materialize().nodes[0].node_id
        await self._resume_for_execution(run)
        node_run = await self._runs.create_node_run(run.run_id, node_id=node_id)
        # The logical NodeRun must be RUNNING before its Attempt can complete
        # (the spine's reconciliation requirement): walk it there the way the
        # scheduler would, so the recorded receipt is a legal lifecycle, not a
        # shortcut the store would refuse.
        for status in transition_path(node_run.status, RunStatus.RUNNING):
            node_run = await self._runs.transition_node_run(node_run.node_run_id, status)
        attempt = await self._runs.create_attempt(
            node_run.node_run_id,
            runtime_id="python",
            executor_id=RSI_CYCLE_EXECUTOR_ID,
            lease_holder=RSI_CYCLE_EXECUTOR_ID,
        )
        token = (
            attempt.execution_lease.fencing_token if attempt.execution_lease is not None else None
        )
        await self._runs.transition_attempt(
            attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token
        )
        terminal = AttemptStatus.FAILED if failed else AttemptStatus.COMPLETED
        attempt = await self._runs.transition_attempt(
            attempt.attempt_id,
            terminal,
            result=None if failed else outcome,
            error=error,
            fencing_token=token,
        )
        if failed:
            await self._fail_recorded_cycle(run, node_run, error=error)
        else:
            await self._service.accept_outcome(
                AcceptedNodeOutcome(
                    node_run_id=node_run.node_run_id,
                    attempt_result=AttemptResult.from_attempt(attempt),
                    logical_status=RunStatus.COMPLETED,
                )
            )
        return await self._close_run_from_node(run.run_id, node_run.node_run_id)

    async def _fail_recorded_cycle(self, run: Run, node_run: NodeRun, *, error: str | None) -> None:
        """Project a failed recorded cycle onto its NodeRun and Run."""
        current = await self._runs.get_node_run(node_run.node_run_id)
        assert current is not None
        for status in transition_path(current.status, RunStatus.FAILED):
            current = await self._runs.transition_node_run(
                node_run.node_run_id,
                status,
                error=error if status is RunStatus.FAILED else None,
            )
        run = await self._require_run(run.run_id)
        for status in transition_path(run.status, RunStatus.FAILED):
            run = await self._runs.transition_run(
                run.run_id, status, error=error if status is RunStatus.FAILED else None
            )

    def record_completed_cycle_sync(self, **kwargs: Any) -> CanonicalCycleRecord:
        """Sync facade over :meth:`record_completed_cycle` for sync drivers.

        Refuses to run inside a live event loop rather than silently nesting
        one — a driver that is itself async must call the async method.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.record_completed_cycle(**kwargs))
        raise RsiProvenanceError(
            "record_completed_cycle_sync cannot run inside a live event loop; "
            "await record_completed_cycle instead"
        )

    def wrap_executor(
        self,
        executor: Callable[..., Awaitable[Any]],
        *,
        campaign_id: str,
        actor_principal_id: str,
        budget: dict[str, Any] | None = None,
        records: list[CanonicalCycleRecord] | None = None,
        timeout_s: float | None = None,
    ) -> Callable[..., Awaitable[Any]]:
        """Wrap one campaign executor so every call is one canonical cycle.

        The autorun coordinator's executor seam is "one call = one cycle":
        this decorator admits a Run per call (idempotent by cycle id), runs
        the wrapped executor as that Run's single Attempt, and appends the
        canonical record to ``records`` when a list is supplied — the campaign
        driver keeps its behavior and gains canonical provenance. The wrapped
        executor's report is returned unchanged: canonical ids travel on the
        records, not by mutating the report.
        """

        async def _canonical(context: Any) -> Any:
            run = await self.admit_cycle(
                campaign_id=campaign_id,
                cycle_id=_cycle_identity(context),
                objective=_cycle_objective(context),
                actor_principal_id=actor_principal_id,
                budget=budget,
            )
            record = await self.run_cycle(run, lambda: executor(context), timeout_s=timeout_s)
            if records is not None:
                records.append(record)
            return await executor_result(self._runs, record)

        return _canonical

    async def _resume_for_execution(self, run: Run) -> Run:
        """Advance an admitted Run to RUNNING (Canvas's resume discipline)."""
        current = await self._runs.get_run(run.run_id)
        if current is None:
            raise RsiProvenanceError(f"Run {run.run_id!r} disappeared from the store")
        if current.status in TERMINAL_RUN_STATUSES:
            raise RsiProvenanceError(
                f"Run {run.run_id!r} is already terminal ({current.status.value}); "
                "a cycle may not execute under it"
            )
        if current.status is RunStatus.CREATED:
            await self._runs.transition_run(run.run_id, RunStatus.QUEUED)
            current = await self._runs.get_run(run.run_id)
            assert current is not None
        if current.status in {RunStatus.QUEUED, RunStatus.WAITING}:
            await self._runs.transition_run(run.run_id, RunStatus.RUNNING)
        return await self._require_run(run.run_id)

    async def _require_run(self, run_id: str) -> Run:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise RsiProvenanceError(f"Run {run_id!r} disappeared from the store")
        return run

    async def _close_run_from_node(self, run_id: str, node_run_id: str) -> CanonicalCycleRecord:
        """Close the Run from its single NodeRun's observed disposition."""
        node_run = await self._runs.get_node_run(node_run_id)
        if node_run is None:
            raise RsiProvenanceError(f"NodeRun {node_run_id!r} disappeared from the store")
        attempts = await self._runs.list_attempts(node_run_id)
        if not attempts:
            raise RsiProvenanceError(
                f"NodeRun {node_run_id!r} has no Attempt; a cycle without physical "
                "evidence cannot be recorded"
            )
        attempt = attempts[-1]
        run = await self._require_run(run_id)
        if run.status not in TERMINAL_RUN_STATUSES:
            target = (
                RunStatus.COMPLETED
                if node_run.status is RunStatus.COMPLETED
                else (
                    RunStatus.FAILED if node_run.status is RunStatus.FAILED else RunStatus.RUNNING
                )
            )
            if target is not RunStatus.RUNNING:
                await self._runs.transition_run(run_id, target)
            run = await self._require_run(run_id)
        return CanonicalCycleRecord(
            campaign_id=str(run.provenance.get(RSI_CAMPAIGN_ID_KEY, "")),
            cycle_id=str(run.provenance.get(RSI_CYCLE_ID_KEY, "")),
            run_id=run.run_id,
            node_run_id=node_run.node_run_id,
            attempt_id=attempt.attempt_id,
            run_status=run.status.value,
            node_run_status=node_run.status.value,
            attempt_status=attempt.status.value,
        )


def _cycle_identity(context: Any) -> str:
    """The cycle id for one executor call: the hypothesis node's id."""
    node = getattr(context, "node", None)
    node_id = getattr(node, "id", None)
    return str(node_id) if node_id else f"cycle-{id(context):x}"


def _cycle_objective(context: Any) -> str:
    """The objective text for one executor call: its hypothesis."""
    node = getattr(context, "node", None)
    hypothesis = getattr(node, "hypothesis", None)
    if isinstance(hypothesis, str) and hypothesis.strip():
        return hypothesis
    return "RSI cycle"


async def executor_result(runs: RunStore, record: CanonicalCycleRecord) -> Any:
    """The wrapped executor's durable report, read back from its Attempt.

    The canonical Attempt is the record: rather than double-holding the
    report in memory, this reads the terminal Attempt's result so callers
    and tests see exactly the evidence the spine persisted.
    """
    attempts = await runs.list_attempts(record.node_run_id)
    return attempts[-1].result if attempts else None
