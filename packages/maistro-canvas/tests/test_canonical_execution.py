"""Behavioral proof that Canvas physical work uses canonical execution (#735)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro_canvas.canvas.canonical_execution import (
    CanvasCanonicalExecution,
    canonical_run_id,
    correlate_run,
)
from maistro_canvas.types import GenerationJobRecord, JobStatus

pytestmark = pytest.mark.asyncio


class _QueueTransitionFailingRunStore(InMemoryRunStore):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.deleted_runs: list[str] = []

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        **kwargs: Any,
    ):
        if target is RunStatus.QUEUED:
            raise RuntimeError("queue transition failed")
        return await super().transition_run(run_id, target, **kwargs)

    async def delete_run(self, run_id: str) -> bool:
        self.deleted_runs.append(run_id)
        return await super().delete_run(run_id)


async def _adapter() -> tuple[CanvasCanonicalExecution, InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    runs = InMemoryRunStore(project_store=projects)
    return (
        CanvasCanonicalExecution(
            runs,
            workspace_id="workspace-1",
            project_id=root.project_id,
        ),
        runs,
        root.project_id,
    )


async def _seed_active_attempt(
    runs: InMemoryRunStore,
    run_id: str,
    node_id: str,
):
    await runs.transition_run(run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(run_id, node_id=node_id)
    await runs.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await runs.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await runs.create_attempt(
        node_run.node_run_id,
        executor_id="dead-canvas-worker",
        lease_holder="dead-canvas-worker",
    )
    assert attempt.execution_lease is not None
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return node_run, attempt


async def test_scope_binding_requires_explicit_non_empty_authorized_scope() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    runs = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError, match="workspace_id"):
        CanvasCanonicalExecution(runs, workspace_id=" ", project_id=root.project_id)
    with pytest.raises(ValueError, match="project_id"):
        CanvasCanonicalExecution(runs, workspace_id="workspace-1", project_id=" ")


async def test_admission_is_queued_in_the_single_canonical_write() -> None:
    """There is no post-admission queue transition left to crash between."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    runs = _QueueTransitionFailingRunStore(project_store=projects)
    adapter = CanvasCanonicalExecution(
        runs,
        workspace_id="workspace-1",
        project_id=root.project_id,
    )

    run_id = await adapter.admit(
        job_id="job-admission-rollback",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    admitted = await runs.get_run(run_id)
    assert admitted is not None
    assert admitted.status is RunStatus.QUEUED
    assert runs.deleted_runs == []


async def test_admission_creates_one_scoped_run_with_stage_graph() -> None:
    adapter, runs, project_id = await _adapter()

    run_id = await adapter.admit(
        job_id="job-1",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    run = await runs.get_run(run_id)
    assert run is not None
    assert run.workspace_id == "workspace-1"
    assert run.project_id == project_id
    assert run.actor_principal_id == "user-1"
    assert run.status is RunStatus.QUEUED
    graph = run.graph.materialize()
    assert [(node.node_id, node.node_type) for node in graph.nodes] == [
        ("canvas:job-1:generate", "canvas.generate"),
    ]


async def test_successful_stage_is_one_completed_node_run_and_attempt() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-1",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    result = await adapter.execute_stage(
        run_id,
        "generate",
        lambda: _result(["image://one"]),
    )

    assert result == ["image://one"]
    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.COMPLETED
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_failed_stage_retry_keeps_both_attempts_under_same_node_run() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-retry",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    async def fail() -> list[str]:
        raise RuntimeError("provider 503")

    with pytest.raises(RuntimeError, match="provider 503"):
        await adapter.execute_stage(run_id, "generate", fail)

    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    first_attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in first_attempts] == [AttemptStatus.FAILED]

    result = await adapter.execute_stage(
        run_id,
        "generate",
        lambda: _result(["image://retry-success"]),
    )

    assert result == ["image://retry-success"]
    node_runs_after = await runs.list_node_runs(run_id)
    assert [node_run.node_run_id for node_run in node_runs_after] == [node_runs[0].node_run_id]
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [
        AttemptStatus.FAILED,
        AttemptStatus.COMPLETED,
    ]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_reclaimed_worker_attempt_is_fenced_before_retry() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-reclaim",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, abandoned = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-reclaim:generate",
    )
    calls = 0

    async def operation() -> list[str]:
        nonlocal calls
        calls += 1
        return ["image://replacement"]

    result = await adapter.execute_stage(run_id, "generate", operation)

    assert result == ["image://replacement"]
    assert calls == 1
    attempts = await runs.list_attempts(node_run.node_run_id)
    assert [attempt.status for attempt in attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert attempts[0].attempt_id == abandoned.attempt_id
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_requested_cancel_fences_active_attempt_and_cancels_logical_identity() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cancel",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, active = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-cancel:generate",
    )

    await adapter.cancel(run_id)

    attempt = await runs.get_attempt(active.attempt_id)
    assert attempt is not None
    assert attempt.status is AttemptStatus.CANCELLED
    settled_node = await runs.get_node_run(node_run.node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.CANCELLED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


async def test_cancel_after_failed_attempt_terminalizes_parked_node() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cancel-parked",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    async def fail() -> list[str]:
        raise RuntimeError("provider 503")

    with pytest.raises(RuntimeError, match="provider 503"):
        await adapter.execute_stage(run_id, "generate", fail)

    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.WAITING
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.FAILED]

    await adapter.cancel(run_id)

    settled_node = await runs.get_node_run(node_runs[0].node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.CANCELLED
    attempts_after = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts_after] == [AttemptStatus.FAILED]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


async def test_terminal_run_cancel_and_fail_are_idempotent_noops() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-terminal-noop",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    await adapter.execute_stage(run_id, "generate", lambda: _result(["image://done"]))

    await adapter.cancel(run_id)
    await adapter.fail(run_id, "ignored")

    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.error is None


async def test_reference_operation_has_four_distinct_canonical_stages() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-ref",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="reference",
        actor_principal_id="user-1",
    )

    for stage in (
        "reference.hero",
        "reference.side",
        "reference.back",
        "reference.three-quarter",
    ):
        await adapter.execute_stage(run_id, stage, lambda stage=stage: _result([stage]))

    node_runs = await runs.list_node_runs(run_id)
    assert {node_run.node_id for node_run in node_runs} == {
        "canvas:job-ref:reference.hero",
        "canvas:job-ref:reference.side",
        "canvas:job-ref:reference.back",
        "canvas:job-ref:reference.three-quarter",
    }
    for node_run in node_runs:
        attempts = await runs.list_attempts(node_run.node_run_id)
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.COMPLETED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_empty_reference_hero_short_circuits_without_fabricating_stages() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-empty-ref",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="reference",
        actor_principal_id="user-1",
    )
    calls = 0

    async def no_hero() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    first = await adapter.execute_stage(run_id, "reference.hero", no_hero)
    second = await adapter.execute_stage(run_id, "reference.hero", no_hero)

    assert first == second == []
    assert calls == 1
    node_runs = await runs.list_node_runs(run_id)
    assert [node_run.node_id for node_run in node_runs] == ["canvas:job-empty-ref:reference.hero"]
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.COMPLETED]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.result == []


async def test_reference_short_circuit_rejects_non_running_non_completed_run() -> None:
    adapter, _runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-ref-invalid-short-circuit",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="reference",
        actor_principal_id="user-1",
    )

    with pytest.raises(RunIntegrityError, match="cannot complete Run"):
        await adapter._project_stage_result(run_id, "reference.hero", [])


async def test_completed_stage_reuses_attempt_evidence_without_reexecuting_provider() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cache",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    calls = 0

    async def operation() -> list[str]:
        nonlocal calls
        calls += 1
        return ["image://stable"]

    first = await adapter.execute_stage(run_id, "generate", operation)
    second = await adapter.execute_stage(run_id, "generate", operation)

    assert first == second == ["image://stable"]
    assert calls == 1
    node_runs = await runs.list_node_runs(run_id)
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1


async def test_terminal_canvas_failure_settles_stranded_physical_attempt_first() -> None:
    """Final worker lease loss cannot leave a RUNNING Attempt under a FAILED Run."""
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-worker-loss",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, attempt = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-worker-loss:generate",
    )

    await adapter.fail(run_id, "Generation failed: worker lease expired.")

    settled_attempt = await runs.get_attempt(attempt.attempt_id)
    assert settled_attempt is not None
    assert settled_attempt.status is AttemptStatus.CANCELLED
    settled_node = await runs.get_node_run(node_run.node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.FAILED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error == "Generation failed: worker lease expired."


async def test_integrity_guards_reject_invalid_terminalization_and_missing_identity() -> None:
    adapter, runs, _project_id = await _adapter()

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await adapter._require_run("missing-run")

    run_id = await adapter.admit(
        job_id="job-integrity",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    with pytest.raises(RunIntegrityError, match="expected exactly one"):
        await adapter.execute_stage(run_id, "not-a-stage", lambda: _result([]))
    with pytest.raises(ValueError, match="failed or cancelled"):
        await adapter._terminalize_observed_nodes(
            run_id,
            RunStatus.COMPLETED,
            error="invalid",
        )

    node_id = "canvas:job-integrity:generate"
    first = await runs.create_node_run(run_id, node_id=node_id)
    second = await runs.create_node_run(run_id, node_id=node_id)
    assert first.node_run_id != second.node_run_id
    with pytest.raises(RunIntegrityError, match="duplicate NodeRuns"):
        await adapter._node_run(run_id, node_id)


async def test_abandoned_attempt_integrity_requires_persisted_attempt_and_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, runs, _project_id = await _adapter()

    missing = Attempt(node_run_id="missing-node-run", ordinal=1, executor_id="worker")
    with pytest.raises(RunIntegrityError, match="disappeared"):
        await adapter._settle_abandoned_attempt(
            missing,
            error="worker disappeared",
            cancellation=CancellationCause.RECOVERED,
        )

    run_id = await adapter.admit(
        job_id="job-no-attempt-lease",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    await runs.transition_run(run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(run_id, node_id="canvas:job-no-attempt-lease:generate")
    await runs.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await runs.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    unleased = await runs.create_attempt(node_run.node_run_id, executor_id="worker")
    assert unleased.execution_lease is None

    async def no_cancel(_attempt_id: str) -> None:
        return None

    monkeypatch.setattr(adapter._service, "cancel_attempt", no_cancel)
    with pytest.raises(RunIntegrityError, match="no execution lease"):
        await adapter._settle_abandoned_attempt(
            unleased,
            error="worker disappeared",
            cancellation=CancellationCause.RECOVERED,
        )


class _ReceiptStore:
    """Minimal Canvas receipt store double for admission recovery proofs.

    Satisfies exactly the contract ``_reconcile_admission`` needs from the
    Canvas package: read, insert, and update receipts scoped by org.
    """

    def __init__(self) -> None:
        self.jobs: dict[tuple[str, str], GenerationJobRecord] = {}
        self.fail_next_create = False
        #: Keys whose first read reports missing, modelling the window in
        #: which another worker's insert has not yet become visible.
        self.missing_on_first_read: set[tuple[str, str]] = set()
        self.updates: list[GenerationJobRecord] = []

    async def get_job(self, job_id: str, *, org_id: str) -> GenerationJobRecord | None:
        key = (job_id, org_id)
        if key in self.missing_on_first_read:
            self.missing_on_first_read.discard(key)
            return None
        return self.jobs.get(key)

    async def create_job(self, job: GenerationJobRecord, *, org_id: str) -> GenerationJobRecord:
        if self.fail_next_create:
            self.fail_next_create = False
            raise RuntimeError("receipt insert lost the race")
        self.jobs[(job.id, org_id)] = job
        return job

    async def update_job(self, job: GenerationJobRecord, *, org_id: str) -> GenerationJobRecord:
        self.jobs[(job.id, org_id)] = job
        self.updates.append(job)
        return job


def _generation_receipt() -> dict[str, Any]:
    return {
        "action": "generate",
        "model_id": "draft-model",
        "prompt": "a safe landscape",
        "params": {},
        "org_id": "org-1",
    }


async def _admit_with_receipt(
    adapter: CanvasCanonicalExecution,
    job_id: str,
    *,
    receipt: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> str:
    return await adapter.admit(
        job_id=job_id,
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
        operation_id=operation_id,
        receipt=receipt if receipt is not None else _generation_receipt(),
    )


def _correlated_job(job_id: str, run_id: str, **overrides: Any) -> GenerationJobRecord:
    params: dict[str, Any] = {}
    correlate_run(params, run_id)
    return GenerationJobRecord(
        id=job_id,
        layer_id="layer-1",
        canvas_id="canvas-1",
        model_id="draft-model",
        prompt="a safe landscape",
        params=params,
        org_id="org-1",
        **overrides,
    )


def _service_run_graph(project_id: str, node_id: str, node_type: str) -> Graph:
    return Graph(
        graph_id=f"graph:{node_id}",
        workspace_id="workspace-1",
        project_id=project_id,
        name="recovery",
        nodes=[Node(node_id=node_id, node_type=node_type)],
        edges=[],
    )


async def _non_canvas_run(
    adapter: CanvasCanonicalExecution, project_id: str, job_claim: str
) -> str:
    """A task-queue Run whose provenance falsely claims a canvas job id."""
    run = await adapter._service.create_run(
        _service_run_graph(project_id, f"other:{job_claim}:generate", "other.generate"),
        actor_principal_id="user-1",
        provenance={
            ADMISSION_SOURCE: "task_queue",
            "canvas_job_id": job_claim,
        },
        initial_status=RunStatus.QUEUED,
    )
    return run.run_id


async def _receiptless_canvas_run(
    adapter: CanvasCanonicalExecution,
    project_id: str,
    job_id: str,
    *,
    receipt: dict[str, Any] | None = None,
) -> str:
    """A canvas-source Run that carries a job claim and org, with no receipt
    unless one is handed in (for races where the receipt outlived the job)."""
    provenance: dict[str, Any] = {
        ADMISSION_SOURCE: "canvas_generation",
        "canvas_job_id": job_id,
        "canvas_org_id": "org-1",
    }
    if receipt is not None:
        provenance["canvas_receipt"] = receipt
    run = await adapter._service.create_run(
        _service_run_graph(project_id, f"canvas:{job_id}:generate", "canvas.generate"),
        actor_principal_id="user-1",
        provenance=provenance,
        initial_status=RunStatus.QUEUED,
    )
    return run.run_id


async def test_admission_retry_with_different_receipt_inputs_is_an_integrity_error() -> None:
    adapter, _runs, _project = await _adapter()
    await _admit_with_receipt(adapter, "job-receipt-change")

    changed = {**_generation_receipt(), "prompt": "a different landscape"}
    with pytest.raises(RunIntegrityError, match="retried with different inputs"):
        await _admit_with_receipt(adapter, "job-receipt-change", receipt=changed)


async def test_admission_matches_operation_identity_across_job_ids() -> None:
    adapter, runs, _project = await _adapter()
    first = await _admit_with_receipt(adapter, "job-first-attempt", operation_id="operation-1")

    # The durable operation identity, not the ephemeral receipt id, names the
    # admission: a retry presenting the same operation under a different
    # receipt id rejoins the original Run instead of admitting a second one.
    rejoined = await adapter.admit(
        job_id="job-retried-elsewhere",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
        operation_id="operation-1",
    )

    assert rejoined == first
    assert await runs.get_run(first) is not None


async def test_admission_ignores_non_canvas_runs_claiming_the_same_job() -> None:
    adapter, runs, project = await _adapter()
    impostor = await _non_canvas_run(adapter, project, "job-usurped")

    admitted = await _admit_with_receipt(adapter, "job-usurped")

    assert admitted != impostor
    canvas_run = await runs.get_run(admitted)
    assert canvas_run is not None
    assert canvas_run.provenance[ADMISSION_SOURCE] == "canvas_generation"


async def test_reconcile_admissions_rejects_non_positive_limit() -> None:
    adapter, _runs, _project = await _adapter()

    with pytest.raises(ValueError, match="limit must be positive"):
        await adapter.reconcile_admissions(_ReceiptStore(), limit=0)


async def test_reconcile_skips_non_canvas_admissions() -> None:
    adapter, _runs, project = await _adapter()
    await _non_canvas_run(adapter, project, "job-other-source")
    store = _ReceiptStore()

    assert await adapter.reconcile_admissions(store) == []
    assert store.jobs == {}


async def test_reconcile_ignores_canvas_run_without_recovery_payload() -> None:
    adapter, _runs, _project = await _adapter()
    # A receiptless admission (crash before the receipt was persisted, with no
    # idempotency key) carries a job id but no org to read the receipt with.
    await adapter.admit(
        job_id="job-legacy",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    store = _ReceiptStore()

    assert await adapter.reconcile_admissions(store) == []
    assert store.jobs == {}


async def test_reconcile_ignores_missing_job_without_recoverable_receipt() -> None:
    adapter, _runs, project = await _adapter()
    await _receiptless_canvas_run(adapter, project, "job-gone")
    store = _ReceiptStore()

    assert await adapter.reconcile_admissions(store) == []
    assert store.jobs == {}


async def test_reconcile_recreates_failed_receipt_from_canonical_provenance() -> None:
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-failed-recreate")
    await runs.transition_run(run_id, RunStatus.RUNNING)
    await runs.transition_run(run_id, RunStatus.FAILED, error="provider exploded")
    store = _ReceiptStore()

    repaired = await adapter.reconcile_admissions(store)

    assert len(repaired) == 1
    recreated = repaired[0]
    assert recreated.status == JobStatus.FAILED
    assert recreated.error_message == "provider exploded"
    assert canonical_run_id(recreated.params) == run_id
    assert store.updates == []


async def test_reconcile_recreates_cancelled_receipt_from_canonical_provenance() -> None:
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-cancelled-recreate")
    await runs.transition_run(run_id, RunStatus.CANCELLED)
    store = _ReceiptStore()

    repaired = await adapter.reconcile_admissions(store)

    assert len(repaired) == 1
    assert repaired[0].status == JobStatus.CANCELLED


async def test_reconcile_missing_receipt_after_completion_projects_failed() -> None:
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-vanished-receipt")
    await runs.transition_run(run_id, RunStatus.RUNNING)
    await runs.transition_run(run_id, RunStatus.COMPLETED)
    store = _ReceiptStore()

    repaired = await adapter.reconcile_admissions(store)

    assert len(repaired) == 1
    recreated = repaired[0]
    assert recreated.status == JobStatus.FAILED
    assert recreated.error_message == ("Canvas receipt was missing after canonical completion")
    assert canonical_run_id(recreated.params) == run_id


async def test_reconcile_lost_insert_race_reattaches_to_winning_receipt() -> None:
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-race-winner")
    store = _ReceiptStore()
    winner = _correlated_job("job-race-winner", run_id)
    store.jobs[("job-race-winner", "org-1")] = winner
    store.missing_on_first_read.add(("job-race-winner", "org-1"))
    store.fail_next_create = True

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [winner]
    assert winner.status == JobStatus.PENDING
    assert store.updates == []


async def test_reconcile_lost_insert_race_without_winner_reraises() -> None:
    adapter, _runs, project = await _adapter()
    # The receipt survived in provenance but the job insert never became
    # durable: the recreate insert raises and the re-read finds no winner.
    await _receiptless_canvas_run(adapter, project, "job-race-lost", receipt=_generation_receipt())
    store = _ReceiptStore()
    store.fail_next_create = True

    with pytest.raises(RuntimeError, match="receipt insert lost the race"):
        await adapter.reconcile_admissions(store)


async def test_reconcile_rejects_receipt_correlated_to_different_run() -> None:
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-usurped-receipt")
    store = _ReceiptStore()
    store.jobs[("job-usurped-receipt", "org-1")] = _correlated_job(
        "job-usurped-receipt", "run-claimed-by-other"
    )
    assert await runs.get_run(run_id) is not None

    with pytest.raises(RunIntegrityError, match="correlates"):
        await adapter.reconcile_admissions(store)


async def test_recovery_projects_completed_evidence_to_done_and_stamps_terminal_fields() -> None:
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-completed-evidence")
    store = _ReceiptStore()
    job = _correlated_job("job-completed-evidence", run_id)
    job.leased_by = "worker-1"
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    store.jobs[("job-completed-evidence", "org-1")] = job

    await adapter.execute_stage(run_id, "generate", lambda: _result(["image://one"]))
    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.DONE
    assert job.result_paths == ["image://one"]
    assert job.completed_at is not None
    assert job.leased_by is None
    assert job.lease_expires_at is None
    assert store.updates == [job]


async def test_recovery_completed_run_without_attempt_evidence_projects_failed() -> None:
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-no-evidence")
    await runs.transition_run(run_id, RunStatus.RUNNING)
    await runs.transition_run(run_id, RunStatus.COMPLETED)
    store = _ReceiptStore()
    store.jobs[("job-no-evidence", "org-1")] = _correlated_job("job-no-evidence", run_id)

    repaired = await adapter.reconcile_admissions(store)

    assert repaired[0].status == JobStatus.FAILED
    assert repaired[0].error_message == (
        "Canonical completion has no completed Canvas Attempt evidence"
    )
    assert repaired[0].completed_at is not None


async def test_recovery_requires_completed_attempt_with_string_path_results() -> None:
    async def scalar_result() -> Any:
        return "not-a-path-list"

    async def non_string_members() -> list[Any]:
        return [123]

    for name, stage_operation in (
        ("job-attempt-failed", None),
        ("job-scalar-result", scalar_result),
        ("job-non-string-paths", non_string_members),
    ):
        adapter, runs, _project = await _adapter()
        run_id = await _admit_with_receipt(adapter, name)
        store = _ReceiptStore()
        store.jobs[(name, "org-1")] = _correlated_job(name, run_id)
        if stage_operation is None:
            with pytest.raises(RuntimeError, match="stage exploded"):
                await adapter.execute_stage(run_id, "generate", _failing_stage)
            # The failed Attempt leaves the Run WAITING; a later recovery pass
            # observes the Run after it has been completed by its supervisor.
            run = await runs.get_run(run_id)
            assert run is not None
            if run.status is RunStatus.WAITING:
                await runs.transition_run(run_id, RunStatus.RUNNING)
            await runs.transition_run(run_id, RunStatus.COMPLETED)
        else:
            await adapter.execute_stage(run_id, "generate", stage_operation)
        repaired = await adapter.reconcile_admissions(store)
        assert len(repaired) == 1, name
        assert repaired[0].status == JobStatus.FAILED, name
        assert repaired[0].error_message == (
            "Canonical completion has no completed Canvas Attempt evidence"
        ), name


async def test_recovery_returns_running_job_with_queued_run_to_pending() -> None:
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-lease-orphan")
    store = _ReceiptStore()
    job = _correlated_job(
        "job-lease-orphan",
        run_id,
        status=JobStatus.RUNNING,
        leased_by="lost-worker",
    )
    store.jobs[("job-lease-orphan", "org-1")] = job

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.PENDING
    # A non-terminal requeue keeps the receipt claimable by a live worker; the
    # lease fields are only cleared when the canonical side reaches a terminal.
    assert job.leased_by == "lost-worker"
    assert job.completed_at is None


async def test_recovery_leaves_a_live_leased_running_receipt_alone() -> None:
    """A worker's live RUNNING lease survives even a momentarily-QUEUED Run.

    With multiple runners, one can hold a valid RUNNING lease on its receipt
    while the canonical Run is still QUEUED -- the narrow window just before
    `_execute_stage` advances it. Reconciliation must not flip that receipt
    back to PENDING: `claim_next_pending` selects by status and would
    immediately re-claim it, dispatching the provider a second time. Compare
    against `test_recovery_returns_running_job_with_queued_run_to_pending`,
    whose job carries no `lease_expires_at` and is correctly requeued --
    only a *live*, unexpired lease is protected.
    """
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-live-lease")
    store = _ReceiptStore()
    job = _correlated_job(
        "job-live-lease",
        run_id,
        status=JobStatus.RUNNING,
        leased_by="live-worker",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    store.jobs[("job-live-lease", "org-1")] = job

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.RUNNING
    assert job.leased_by == "live-worker"
    assert store.updates == []


async def test_recovery_requeues_a_running_receipt_whose_lease_expired() -> None:
    """An *expired* lease is not live: recovery may still requeue it.

    Only the lease reaper decides a worker is lost in the ordinary case; this
    proves the fix is a liveness check, not a blanket "never touch RUNNING".
    """
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-expired-lease")
    store = _ReceiptStore()
    job = _correlated_job(
        "job-expired-lease",
        run_id,
        status=JobStatus.RUNNING,
        leased_by="dead-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store.jobs[("job-expired-lease", "org-1")] = job

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.PENDING


async def test_recovery_leaves_an_exhausted_expired_lease_for_the_reaper() -> None:
    """Recovery must not requeue a receipt that has spent its retry budget.

    `claim_next_pending` bumps `attempts` without checking `max_attempts`;
    only the lease reaper enforces that ceiling. Reconciliation runs every
    poll tick, roughly 30x as often as the reaper, so it usually reaches an
    expired lease first. If it requeued an exhausted receipt whose worker
    died before `execute_stage` moved the Run out of QUEUED, each claim would
    dispatch the provider again, with no limit. The receipt must stay
    RUNNING so the reaper fails it canonically.
    """
    adapter, runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-exhausted")
    store = _ReceiptStore()
    job = _correlated_job(
        "job-exhausted",
        run_id,
        status=JobStatus.RUNNING,
        attempts=3,
        max_attempts=3,
        leased_by="dead-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store.jobs[("job-exhausted", "org-1")] = job

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.RUNNING
    assert job.attempts == 3
    assert store.updates == []
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.QUEUED


async def test_recovery_marks_an_exhausted_unleased_receipt_reapable() -> None:
    """With no lease at all, the reaper would never see the receipt.

    `reap_expired_leases` only matches a non-null, past `lease_expires_at`.
    Leaving an exhausted, unleased RUNNING receipt as it is would strand it:
    it could not be claimed and could not be reaped. Recovery stamps an
    already-expired lease so the next reaper sweep fails it, and leaves the
    budget decision to the reaper.
    """
    adapter, _runs, _project = await _adapter()
    run_id = await _admit_with_receipt(adapter, "job-exhausted-unleased")
    store = _ReceiptStore()
    job = _correlated_job(
        "job-exhausted-unleased",
        run_id,
        status=JobStatus.RUNNING,
        attempts=3,
        max_attempts=3,
    )
    store.jobs[("job-exhausted-unleased", "org-1")] = job
    before = datetime.now(UTC)

    repaired = await adapter.reconcile_admissions(store)

    assert repaired == [job]
    assert job.status == JobStatus.RUNNING
    assert job.lease_expires_at is not None
    assert before <= job.lease_expires_at <= datetime.now(UTC)
    assert store.updates == [job]

    # Once stamped, the receipt is simply "exhausted with an expired lease";
    # a second pass must not requeue it or rewrite it again.
    await adapter.reconcile_admissions(store)
    assert job.status == JobStatus.RUNNING
    assert store.updates == [job]


async def test_reconcile_admissions_pages_past_the_first_batch_of_healthy_canvas_runs() -> None:
    """A missing receipt behind a full first page must still be reached.

    Before the fix, one bounded `list_by_status(status, limit=N)` call read
    only the oldest `N` rows of a status and never paged further: a status
    with more than `N` already-healthy Canvas admissions ahead of a broken
    one left the broken one permanently unreconciled on every future tick.
    """
    adapter, _runs, _project = await _adapter()
    store = _ReceiptStore()
    for i in range(3):
        healthy_run_id = await _admit_with_receipt(adapter, f"job-healthy-{i}")
        store.jobs[(f"job-healthy-{i}", "org-1")] = _correlated_job(
            f"job-healthy-{i}", healthy_run_id
        )
    # Admitted after (and so ordered after) all three healthy rows above, and
    # its receipt was never persisted -- the same crash shape every other
    # reconciliation test in this module exercises.
    await _admit_with_receipt(adapter, "job-starved")

    repaired = await adapter.reconcile_admissions(store, limit=2)

    assert "job-starved" in {job.id for job in repaired}


async def test_reconcile_admissions_ignores_a_matching_job_id_in_another_status() -> None:
    """The `admission_source` filter is pushed into the query, not merely
    applied after it -- a page must never be crowded out by non-Canvas rows
    sharing the same status."""
    adapter, _runs, project = await _adapter()
    for i in range(3):
        await _non_canvas_run(adapter, project, f"job-other-{i}")
    await _admit_with_receipt(adapter, "job-real")
    store = _ReceiptStore()

    repaired = await adapter.reconcile_admissions(store, limit=2)

    assert {job.id for job in repaired} == {"job-real"}


async def test_concurrent_admission_race_adopts_the_winner_instead_of_orphaning_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two admitters racing the same idempotency key end up with one Run.

    Simulates the race by admitting the winner first, then forcing a second
    admit's *own* pre-admission lookup to miss it -- exactly what a second
    worker's concurrent scan would do before either insert lands. What
    prevents a second, orphaned Run is the durable `canvas_job_id` claim
    (migration 039 / `InMemoryRunStore`'s mirror of it) refusing the second
    insert, not the scan: the loser's `create_run` raises, and `admit`
    re-reads to adopt the winner instead of leaving its own Run behind.
    """
    adapter, runs, _project = await _adapter()
    winner_run_id = await _admit_with_receipt(adapter, "job-race", operation_id="op-race")

    original_find_admitted = adapter._find_admitted
    calls = 0

    async def racy_find_admitted(*, job_id: str, operation_id: str | None) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            # The racing worker's own lookup, which ran before the winner's
            # insert was visible to it.
            return None
        return await original_find_admitted(job_id=job_id, operation_id=operation_id)

    monkeypatch.setattr(adapter, "_find_admitted", racy_find_admitted)

    loser_run_id = await adapter.admit(
        job_id="job-race",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
        operation_id="op-race",
        receipt=_generation_receipt(),
    )

    assert loser_run_id == winner_run_id
    assert calls == 2
    all_canvas_runs = [
        run
        for status in RunStatus
        for run in await runs.list_by_status(
            status, limit=100, admission_source="canvas_generation"
        )
    ]
    assert len(all_canvas_runs) == 1


async def test_concurrent_admission_race_with_different_inputs_still_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine race does not launder a conflicting retry.

    The recovery path taken when the durable claim refuses a concurrent
    insert must apply the same receipt-fingerprint comparison as the
    ordinary pre-admission lookup, not skip it.
    """
    adapter, _runs, _project = await _adapter()
    await _admit_with_receipt(adapter, "job-race-conflict", operation_id="op-race-conflict")

    original_find_admitted = adapter._find_admitted
    calls = 0

    async def racy_find_admitted(*, job_id: str, operation_id: str | None) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return await original_find_admitted(job_id=job_id, operation_id=operation_id)

    monkeypatch.setattr(adapter, "_find_admitted", racy_find_admitted)
    changed_receipt = {**_generation_receipt(), "prompt": "a different landscape"}
    with pytest.raises(RunIntegrityError, match="retried with different inputs"):
        await adapter.admit(
            job_id="job-race-conflict",
            canvas_id="canvas-1",
            layer_id="layer-1",
            action="generate",
            actor_principal_id="user-1",
            operation_id="op-race-conflict",
            receipt=changed_receipt,
        )


async def test_admission_fingerprint_rejects_a_different_resource_under_the_same_key() -> None:
    """The persisted admission fingerprint must name its own resource.

    If admission crashed before the Canvas job was inserted and the same
    org/key is retried for a *different* canvas or layer with otherwise
    identical generation inputs, the deterministic job id still finds the
    original Run -- so the fingerprint compared against the retry must
    include `canvas_id`/`layer_id`, or two different resources correlate to
    one Run whose graph and provenance still name the first.
    """
    adapter, _runs, _project = await _adapter()
    await adapter.admit(
        job_id="job-cross-resource",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
        operation_id="op-cross-resource",
        receipt={**_generation_receipt(), "canvas_id": "canvas-1", "layer_id": "layer-1"},
    )

    with pytest.raises(RunIntegrityError, match="retried with different inputs"):
        await adapter.admit(
            job_id="job-cross-resource",
            canvas_id="canvas-2",
            layer_id="layer-2",
            action="generate",
            actor_principal_id="user-1",
            operation_id="op-cross-resource",
            receipt={**_generation_receipt(), "canvas_id": "canvas-2", "layer_id": "layer-2"},
        )


async def _failing_stage() -> list[str]:
    raise RuntimeError("stage exploded")


async def _result(value: list[str]) -> list[str]:
    return value
