"""Live-PostgreSQL proof that the admission binding and the Run are one commit (#1845).

The seam tests (``test_pg_root_admission_coordinator.py``) pin the
coordinator's decisions against a fake pool; these run the production wiring —
``PgTaskIdempotencyStore``, ``TaskRunAdmitter.prepare_run``,
``PgRunStore.insert_prepared_run`` — against a real server, gated on
``MAISTRO_TEST_PG_DSN`` like the other durable tiers. The issue's own evidence
standard calls the SQLite reproduction failure-class only; this is the PG half
of that class, short of a process-kill harness: commit atomicity, replay
honesty after the commit, and joint rollback on a refused insert.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.admission import direct_work_graph
from maistro.runs.model import RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.tasks.admission import TASK_ID_KEY, TASK_QUEUE_SOURCE, TaskRunAdmitter
from maistro.tasks.idempotency import (
    DERIVED_KEY_PREFIX,
    TASK_SUBMIT_ACTION,
    AdmissionRecord,
    Claimed,
    PgTaskIdempotencyStore,
    Replayed,
    admission_scope_key,
    request_fingerprint,
)
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus
from maistro.tasks.pg_admission import AdmissionBound, PgRootAdmissionCoordinator


async def _wired(
    pg_pool: Any,
) -> tuple[
    str, str, PgTaskIdempotencyStore, PgRunStore, TaskRunAdmitter, PgRootAdmissionCoordinator
]:
    """The production composition on one Workspace: PG claims, PG Run store,
    the routed admitter's prepare half, and the coordinator over the shared
    pool — exactly what `wire_execution_spine` builds on the PG tier. Returns
    the Workspace, a real Project id under it, and the four wired halves."""
    workspace = f"issue-1845-{uuid4().hex}"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Atomic admission"
    )
    runs = PgRunStore(pg_pool, project_store=projects)
    claims = PgTaskIdempotencyStore(pg_pool)
    coordinator = PgRootAdmissionCoordinator(pool=pg_pool, insert_run=runs.insert_prepared_run)
    admitter = TaskRunAdmitter(
        runs,
        workspace_id=workspace,
        project_id=project.project_id,
        project_store=projects,
        coordinator=coordinator,
    )
    return workspace, project.project_id, claims, runs, admitter, coordinator


def _request() -> TaskCreate:
    return TaskCreate(description="reconcile me", user_id="user-1")


def _scope_key(workspace: str, request: TaskCreate) -> str:
    return admission_scope_key(
        principal="user-1",
        workspace_id=workspace,
        action=TASK_SUBMIT_ACTION,
        key=f"{DERIVED_KEY_PREFIX}{request_fingerprint(request)}",
    )


def _task(now: datetime, workspace: str) -> TaskResponse:
    return TaskResponse(
        task_id=TaskResponse.new_id(),
        status=TaskStatus.QUEUED,
        description="reconcile me",
        workspace=workspace,
        user_id="user-1",
        tier=2,
        created_at=now,
    )


def _claim(rows: list[AdmissionRecord | None]) -> AdmissionRecord:
    record = rows[0]
    assert record is not None and not record.admitted
    return record


async def _canonical_run_count(pg_pool: Any, workspace: str) -> int:
    conn: Any
    async with pg_pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM canonical_runs WHERE workspace_id = $1", workspace
            )
        )


@pytest.mark.asyncio
async def test_the_joint_commit_is_live_and_replay_honest(pg_pool: Any) -> None:
    """Admit once, then reread as a crashed process would: the binding is
    durable, the claim flow replays it, and nothing mints a second Run."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    workspace, _project_id, claims, runs, admitter, coordinator = await _wired(pg_pool)
    request = _request()
    now = datetime.now(UTC)
    scope_key = _scope_key(workspace, request)
    request_json = json.dumps(request.model_dump(mode="json"))

    outcome = await claims.claim(
        scope_key, fingerprint=request_fingerprint(request), request=request_json, now=now
    )
    assert isinstance(outcome, Claimed)
    claim = _claim([await claims.get(scope_key)])

    task = _task(now, workspace)
    bound = await coordinator.bind_admission(
        scope_key=scope_key,
        claim=claim,
        task_id=task.task_id,
        prepare_run=lambda: admitter.prepare_run(task),
    )
    assert isinstance(bound, AdmissionBound)

    # The Run is canonically QUEUED with the admission evidence the legacy
    # path stamps: the entry-point source and the receipt correlation keys.
    run = await runs.get_run(bound.run_id)
    assert run is not None
    assert run.status is RunStatus.QUEUED
    assert run.provenance[ADMISSION_SOURCE] == TASK_QUEUE_SOURCE
    assert run.provenance[TASK_ID_KEY] == task.task_id

    # The binding is durable in the same commit: a fresh reread — the state a
    # process restarted after the commit observes — finds it admitted.
    row = await claims.get(scope_key)
    assert row is not None
    assert row.admitted
    assert row.task_id == task.task_id
    assert row.run_id == bound.run_id

    # The resubmit-after-death experiment, through the public claim flow: the
    # bound row replays instead of being taken over, and no second Run exists
    # for the Workspace.
    replay = await claims.claim(
        scope_key, fingerprint=request_fingerprint(request), request=request_json, now=now
    )
    assert isinstance(replay, Replayed)
    assert replay.record.run_id == bound.run_id
    assert await _canonical_run_count(pg_pool, workspace) == 1


@pytest.mark.asyncio
async def test_a_refused_insert_rolls_the_binding_back_with_it(pg_pool: Any) -> None:
    """The joint commit fails jointly: a Run the canonical table refuses (a
    duplicate run_id, a real server-side constraint violation) leaves the
    claim unbound — retryable, never half-admitted."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    workspace, project_id, claims, runs, _admitter, coordinator = await _wired(pg_pool)
    request = _request()
    now = datetime.now(UTC)
    scope_key = _scope_key(workspace, request)
    request_json = json.dumps(request.model_dump(mode="json"))

    outcome = await claims.claim(
        scope_key, fingerprint=request_fingerprint(request), request=request_json, now=now
    )
    assert isinstance(outcome, Claimed)
    claim = _claim([await claims.get(scope_key)])

    # A Run whose id is already canonically taken: the INSERT hits the
    # primary key, the transaction aborts, and the binding dies with it.
    seed = await runs.create_run(
        direct_work_graph(
            workspace_id=workspace,
            project_id=project_id,
            node_type="llm.summarize",
            name="seed",
            description="seed",
        ),
        actor_principal_id="user-1",
        initial_status=RunStatus.QUEUED,
    )
    graph = direct_work_graph(
        workspace_id=workspace,
        project_id=project_id,
        node_type="llm.summarize",
        name="duplicate",
        description="duplicate",
    )
    prepared = await runs.prepare_run(
        graph, actor_principal_id="user-1", initial_status=RunStatus.QUEUED
    )
    prepared = prepared.model_copy(update={"run_id": seed.run_id})

    async def refuses_mid_write() -> Any:
        return prepared

    with pytest.raises(Exception, match="duplicate key"):
        await coordinator.bind_admission(
            scope_key=scope_key,
            claim=claim,
            task_id="t-rollback-1845",
            prepare_run=refuses_mid_write,
        )
    row = await claims.get(scope_key)
    assert row is not None
    assert row.task_id is None and row.run_id is None  # rolled back together
    assert await _canonical_run_count(pg_pool, workspace) == 1  # only the seed

    # The claim is intact and unbound: the retry admits fresh.
    async def retries_fresh() -> Any:
        return await runs.prepare_run(
            graph, actor_principal_id="user-1", initial_status=RunStatus.QUEUED
        )

    retry = await coordinator.bind_admission(
        scope_key=scope_key,
        claim=row,
        task_id="t-retry-1845",
        prepare_run=retries_fresh,
    )
    assert isinstance(retry, AdmissionBound)
    assert await _canonical_run_count(pg_pool, workspace) == 2
