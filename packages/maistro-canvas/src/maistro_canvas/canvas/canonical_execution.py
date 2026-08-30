"""Canonical Graph/Run execution adapter for Canvas generation jobs (#735).

Canvas owns generation requests, image paths, selected variants, layers, and
user-facing receipts. Universal execution lifecycle belongs to the canonical
Run/NodeRun/Attempt spine. This module maps one generation receipt to one Run
and lets the public durable Graph executor own physical execution and retries.

The canonical Run id is stored inside the existing ``params`` JSONB payload
under a reserved key. That keeps restart correlation durable without adding a
Canvas column or repository migration, both outside #735's collision boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, run_durable_graph
from maistro.graph.nodes.base import BaseNode, NodeContext, NodeResult
from maistro.runs.model import RunStatus

from maistro_canvas.canvas.executor import _sanitise_error
from maistro_canvas.types import GenerationJobRecord, JobStatus

if TYPE_CHECKING:
    from maistro.graph.durable_runs.protocol import DurableRunStore
    from maistro.runs.store import RunStore
    from maistro_canvas.canvas.executor import CanvasExecutor

_CANVAS_STAGE_KIND = "canvas.generation"
_CANVAS_STAGE_ID = "canvas-generation"
_ADMISSION_SOURCE = "canvas"
_CANONICAL_RUN_PARAM = "_canonical_run_id"


class _GenerationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _GenerationOutput(BaseModel):
    result_paths: list[str] = Field(default_factory=list)


def canonical_run_id(job: GenerationJobRecord) -> str | None:
    """Return the canonical Run bound to this Canvas receipt, if one exists."""
    value = str(job.params.get(_CANONICAL_RUN_PARAM) or "")
    return value or None


def _bind_canonical_run(job: GenerationJobRecord, run_id: str) -> None:
    existing = canonical_run_id(job)
    if existing is not None and existing != run_id:
        raise ValueError(
            f"Canvas job {job.id!r} is already bound to canonical Run {existing!r}"
        )
    job.params[_CANONICAL_RUN_PARAM] = run_id


def public_job_params(job: GenerationJobRecord) -> dict[str, Any]:
    """Return provider/user parameters without Canvas' internal Run correlation."""
    return {key: value for key, value in job.params.items() if key != _CANONICAL_RUN_PARAM}


class _GenerationNode(BaseNode[_GenerationInput, _GenerationOutput]):
    kind: ClassVar[str] = _CANVAS_STAGE_KIND
    input_schema: ClassVar[type[BaseModel]] = _GenerationInput
    output_schema: ClassVar[type[BaseModel]] = _GenerationOutput
    display_name: ClassVar[str] = "Execute Canvas generation"
    description: ClassVar[str] = "Run one Canvas provider generation under canonical Attempt evidence."
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True

    def __init__(self, *, executor: CanvasExecutor, job: GenerationJobRecord) -> None:
        self._executor = executor
        self._job = job

    async def _execute(
        self,
        inputs: _GenerationInput,
        ctx: NodeContext,
    ) -> _GenerationOutput:
        # The provider body may contain credentials, internal URLs, or storage
        # paths. Canonical evidence is inspectable, so sanitize before the
        # exception crosses into NodeResult/Attempt persistence.
        try:
            await self._executor._execute_claimed(self._job)
        except Exception as exc:
            raise RuntimeError(_sanitise_error(exc)) from None
        return _GenerationOutput(result_paths=list(self._job.result_paths))


def _canonical_graph(
    job: GenerationJobRecord,
    *,
    workspace_id: str,
    project_id: str,
) -> Graph:
    node = Node(
        node_id=_CANVAS_STAGE_ID,
        node_type=_CANVAS_STAGE_KIND,
        name=f"Canvas {job.action}",
        policies={"max_attempts": max(1, int(job.max_attempts))},
        metadata={
            "canvas_job_id": job.id,
            "canvas_id": job.canvas_id,
            "layer_id": job.layer_id,
            "action": str(job.action),
            "model_id": job.model_id,
        },
    )
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"Canvas {job.action} for layer {job.layer_id}",
        nodes=[node],
        edges=[],
        metadata={
            "entry_node": _CANVAS_STAGE_ID,
            "execution_owner": "canonical_run",
            "product": "canvas",
            "canvas_job_id": job.id,
        },
    )


def _resolver(*, executor: CanvasExecutor, job: GenerationJobRecord):
    generation = _GenerationNode(executor=executor, job=job)

    def resolve(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
        if node_id != _CANVAS_STAGE_ID:
            raise KeyError(f"unknown Canvas canonical node {node_id!r}")
        return generation

    return resolve


def _latest_physical_error(record: DurableRunRecord) -> str:
    for attempt in reversed(record.attempts):
        if attempt.result is None:
            continue
        try:
            result = NodeResult.model_validate(attempt.result)
        except (TypeError, ValueError):
            continue
        if not result.success:
            return result.error_message or "Generation failed: provider error. Please try again."
    return "Generation failed: provider error. Please try again."


def _project_receipt(job: GenerationJobRecord, record: DurableRunRecord) -> None:
    """Project canonical terminal evidence back onto the Canvas domain receipt."""
    job.attempts = len(record.attempts)
    if record.node_runs:
        job.started_at = record.node_runs[0].started_at
    job.completed_at = record.run.finished_at

    if record.run.status is RunStatus.COMPLETED:
        job.status = JobStatus.DONE
        job.error_message = None
        if record.node_runs:
            result = record.node_runs[-1].result
            if isinstance(result, dict):
                paths = result.get("result_paths")
                if isinstance(paths, list):
                    job.result_paths = [str(path) for path in paths]
        return

    if record.run.status is RunStatus.CANCELLED:
        job.status = JobStatus.CANCELLED
        return

    job.status = JobStatus.FAILED
    job.error_message = _latest_physical_error(record)


class CanvasCanonicalExecution:
    """Admit and execute Canvas generation work on the canonical durable spine."""

    def __init__(
        self,
        *,
        run_store: RunStore,
        durable_store: DurableRunStore,
        workspace_id: str,
        project_id: str,
        actor_principal_id: str | None = None,
    ) -> None:
        self._run_store = run_store
        self._durable_store = durable_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._actor_principal_id = actor_principal_id

    async def admit(self, job: GenerationJobRecord) -> str:
        """Create one queued canonical Run and bind its id to the Canvas receipt."""
        existing = canonical_run_id(job)
        if existing is not None:
            run = await self._run_store.get_run(existing)
            if run is None:
                raise ValueError(
                    f"Canvas job {job.id!r} references missing canonical Run {existing!r}"
                )
            return existing

        graph = _canonical_graph(
            job,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        )
        admitted = await self._run_store.create_run(
            graph,
            actor_principal_id=self._actor_principal_id,
            provenance={
                "admission_source": _ADMISSION_SOURCE,
                "product": "canvas",
                "canvas_job_id": job.id,
                "canvas_id": job.canvas_id,
                "layer_id": job.layer_id,
            },
            initial_status=RunStatus.QUEUED,
        )
        _bind_canonical_run(job, admitted.run_id)
        return admitted.run_id

    async def abandon_admission(self, job: GenerationJobRecord) -> None:
        """Compensate a receipt write that failed before any physical work began."""
        run_id = canonical_run_id(job)
        if run_id is None:
            return
        run = await self._run_store.get_run(run_id)
        if run is not None and run.status in {RunStatus.CREATED, RunStatus.QUEUED}:
            await self._run_store.delete_run(run_id)
        job.params.pop(_CANONICAL_RUN_PARAM, None)

    async def execute(
        self,
        job: GenerationJobRecord,
        *,
        executor: CanvasExecutor,
    ) -> DurableRunRecord:
        """Execute an admitted Canvas Run and refresh the Canvas receipt projection."""
        run_id = canonical_run_id(job)
        if run_id is None:
            run_id = await self.admit(job)

        graph = _canonical_graph(
            job,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        )
        provenance = {
            "admission_source": _ADMISSION_SOURCE,
            "product": "canvas",
            "canvas_job_id": job.id,
            "canvas_id": job.canvas_id,
            "layer_id": job.layer_id,
        }
        record = await run_durable_graph(
            graph,
            store=self._durable_store,
            node_resolver=_resolver(executor=executor, job=job),
            actor_principal_id=self._actor_principal_id,
            run_id=run_id,
            provenance=provenance,
            run_store=self._run_store,
        )
        _project_receipt(job, record)
        return record


__all__ = [
    "CanvasCanonicalExecution",
    "canonical_run_id",
    "public_job_params",
]
