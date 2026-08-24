"""One suite, three Run stores (#132).

`InMemoryRunStore`, `SqliteRunStore` and `PgRunStore` all claim the `RunStore`
protocol. Until now each had its own tests with its own assertions, which means
"same protocol" was three separate beliefs rather than one checked fact — the
shape that let `PgStrikeTracker` carry the same claim while being unsubstitutable
(#134).

The concurrency section is the part that only matters here. SQLite serialises
writers at the database, so its integrity constraints never fire and a
check-then-insert cannot race. PostgreSQL admits concurrent writers, so the same
code *is* a race, and these are the cases that distinguish a store that holds
from one that has merely never been asked.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope import ProjectNotEmpty
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import (
    ActiveAttemptExists,
    AttemptNotFound,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
)
from maistro.testing.postgres import postgres_dsn


def _graph(workspace: str, project_id: str, *, node_ids: tuple[str, ...] = ("node-1",)) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Durable graph",
        nodes=[Node(node_id=node_id, node_type="agent") for node_id in node_ids],
    )


async def _run(spine: Any) -> Any:
    store, workspace, project_id = spine
    return await store.create_run(_graph(workspace, project_id))


async def _node_run(spine: Any) -> Any:
    """A NodeRun under a fresh Run — what most of the Attempt tests need."""
    store, _workspace, _project_id = spine
    run = await _run(spine)
    return await store.create_node_run(run.run_id, node_id="node-1")


# ── identity round-trips ──────────────────────────────────────────


async def test_a_created_run_reloads_with_its_relationships(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await _run(spine)

    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.run_id == run.run_id
    assert reloaded.workspace_id == workspace
    assert reloaded.project_id == project_id
    assert reloaded.status is RunStatus.CREATED


async def test_the_graph_snapshot_survives_the_round_trip(spine: Any) -> None:
    """The snapshot is what a resume replays against; a Run whose graph came
    back different would resume as different work."""
    store, workspace, project_id = spine
    graph = _graph(workspace, project_id, node_ids=("node-1", "node-2"))

    run = await store.create_run(graph)
    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    materialized = reloaded.graph.materialize()
    assert [node.node_id for node in materialized.nodes] == ["node-1", "node-2"]
    assert reloaded.graph.content_hash == graph.content_hash


async def test_provenance_and_actor_survive(spine: Any) -> None:
    store, workspace, project_id = spine

    run = await store.create_run(
        _graph(workspace, project_id),
        actor_principal_id="user-1",
        provenance={"admission_source": "task_queue", "task_id": "t-1"},
    )
    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.actor_principal_id == "user-1"
    assert reloaded.provenance == {"admission_source": "task_queue", "task_id": "t-1"}


async def test_an_unknown_run_is_none_not_an_error(spine: Any) -> None:
    store, _workspace, _project_id = spine

    assert await store.get_run("no-such-run") is None
    assert await store.get_node_run("no-such-node-run") is None
    assert await store.get_attempt("no-such-attempt") is None


# ── scope integrity ───────────────────────────────────────────────


async def test_a_graph_in_an_unknown_project_is_refused(spine: Any) -> None:
    store, workspace, _project_id = spine

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await store.create_run(_graph(workspace, "no-such-project"))


async def test_a_node_id_outside_the_snapshot_is_refused(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)

    with pytest.raises(RunIntegrityError, match="not present"):
        await store.create_node_run(run.run_id, node_id="node-99")


async def test_a_node_run_under_a_terminal_run_is_refused(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.CANCELLED)

    with pytest.raises(RunIntegrityError, match="terminal Run"):
        await store.create_node_run(run.run_id, node_id="node-1")


async def test_a_child_run_cannot_cross_workspaces(spine: Any) -> None:
    store, _workspace, project_id = spine
    parent = await _run(spine)

    with pytest.raises(RunIntegrityError, match="Workspace"):
        await store.create_run(
            _graph("some-other-workspace", project_id), parent_run_id=parent.run_id
        )


async def test_a_parent_node_run_requires_a_parent_run(spine: Any) -> None:
    store, workspace, project_id = spine

    with pytest.raises(RunIntegrityError, match="requires parent_run_id"):
        await store.create_run(_graph(workspace, project_id), parent_node_run_id="nr-1")


# ── lifecycle ─────────────────────────────────────────────────────


async def test_a_run_advances_and_the_change_is_durable(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)

    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.status is RunStatus.RUNNING


async def test_a_terminal_run_records_its_outcome(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    await store.transition_run(run.run_id, RunStatus.FAILED, error="it broke")
    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.error == "it broke"
    assert reloaded.finished_at is not None


async def test_transitioning_an_unknown_run_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine

    with pytest.raises(RunNotFound):
        await store.transition_run("no-such-run", RunStatus.QUEUED)


async def test_transitioning_an_unknown_node_run_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine

    with pytest.raises(NodeRunNotFound):
        await store.transition_node_run("no-such-node-run", RunStatus.QUEUED)


async def test_transitioning_an_unknown_attempt_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine

    with pytest.raises(AttemptNotFound):
        await store.transition_attempt("no-such-attempt", AttemptStatus.RUNNING)


# ── ordinals ──────────────────────────────────────────────────────


async def test_node_run_ordinals_are_dense_and_ordered(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id, node_ids=("node-1", "node-2", "node-3"))
    )

    for node_id in ("node-1", "node-2", "node-3"):
        await store.create_node_run(run.run_id, node_id=node_id)

    assert [nr.ordinal for nr in await store.list_node_runs(run.run_id)] == [1, 2, 3]


async def test_attempt_ordinals_are_dense(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)

    for _ in range(3):
        attempt = await store.create_attempt(node_run.node_run_id)
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.FAILED, error="retry")

    assert [a.ordinal for a in await store.list_attempts(node_run.node_run_id)] == [1, 2, 3]


# ── one active Attempt ────────────────────────────────────────────


async def test_a_second_attempt_while_one_is_active_is_refused(spine: Any) -> None:
    """The constraint the whole retry model rests on."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    await store.create_attempt(node_run.node_run_id)

    with pytest.raises(ActiveAttemptExists):
        await store.create_attempt(node_run.node_run_id)


async def test_a_new_attempt_is_allowed_once_the_last_one_ended(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    first = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(first.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(first.attempt_id, AttemptStatus.FAILED, error="retry")

    second = await store.create_attempt(node_run.node_run_id)

    assert second.ordinal == 2


# ── execution fence ───────────────────────────────────────────────


async def test_a_leased_attempt_rejects_an_unfenced_write(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)


async def test_a_leased_attempt_rejects_the_wrong_token(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            attempt.attempt_id, AttemptStatus.RUNNING, fencing_token="worker-b-token"
        )


async def test_the_lease_holder_may_write(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    assert attempt.execution_lease is not None

    updated = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )

    assert updated.status is AttemptStatus.RUNNING


# ── concurrency: the part SQLite never had to answer ──────────────


async def test_only_one_of_many_concurrent_workers_starts_an_attempt(spine: Any) -> None:
    """Ten workers race to start the same node. Nine must lose.

    Under SQLite the database serialises them and the application check is
    enough; under PostgreSQL they run genuinely at once, and the difference
    between a store that holds and one that has merely never been asked shows
    up exactly here.
    """
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)

    results = await asyncio.gather(
        *(store.create_attempt(node_run.node_run_id, lease_holder=f"w{i}") for i in range(10)),
        return_exceptions=True,
    )

    started = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, ActiveAttemptExists)]
    unexpected = [
        r
        for r in results
        if isinstance(r, BaseException) and not isinstance(r, ActiveAttemptExists)
    ]

    assert unexpected == [], f"losers must be refused cleanly, not crash: {unexpected}"
    assert len(started) == 1
    assert len(refused) == 9


async def test_concurrent_workers_leave_exactly_one_active_attempt(spine: Any) -> None:
    """The store's own view has to agree with what the race produced."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)

    await asyncio.gather(
        *(store.create_attempt(node_run.node_run_id) for _ in range(8)),
        return_exceptions=True,
    )

    attempts = await store.list_attempts(node_run.node_run_id)
    active = [a for a in attempts if a.status in (AttemptStatus.CREATED, AttemptStatus.RUNNING)]
    assert len(active) == 1
    assert [a.ordinal for a in attempts] == list(range(1, len(attempts) + 1))


async def test_concurrent_node_runs_get_distinct_ordinals(spine: Any) -> None:
    """`MAX(ordinal) + 1` read by two writers returns the same number twice."""
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id, node_ids=("node-1", "node-2", "node-3", "node-4"))
    )

    results = await asyncio.gather(
        *(
            store.create_node_run(run.run_id, node_id=node_id)
            for node_id in ("node-1", "node-2", "node-3", "node-4")
        ),
        return_exceptions=True,
    )

    created = [r for r in results if not isinstance(r, BaseException)]
    assert len(created) == 4, f"none should have collided: {results}"
    assert sorted(nr.ordinal for nr in created) == [1, 2, 3, 4]


async def test_a_stale_worker_cannot_overwrite_a_newer_lease(spine: Any) -> None:
    """The fence's whole job: a worker whose lease was superseded must not
    write, even though it holds a token that was valid when it read it."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    first = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    assert first.execution_lease is not None
    stale_token = first.execution_lease.fencing_token

    await store.transition_attempt(
        first.attempt_id, AttemptStatus.RUNNING, fencing_token=stale_token
    )
    await store.transition_attempt(
        first.attempt_id, AttemptStatus.TIMED_OUT, fencing_token=stale_token
    )
    second = await store.create_attempt(node_run.node_run_id, lease_holder="worker-b")
    assert second.execution_lease is not None

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            second.attempt_id, AttemptStatus.RUNNING, fencing_token=stale_token
        )


def test_postgres_is_covered_when_configured() -> None:
    """Guards the guard: a suite that reports green because it silently ran two
    backends instead of three is the failure this file exists to prevent."""
    if not postgres_dsn():
        pytest.skip("no PostgreSQL configured; the parametrized cases skip by design")
    pytest.importorskip("asyncpg")


# ── non-finite evidence survives every backend (#132 review) ──────


@pytest.mark.parametrize(
    ("value", "check"),
    [
        (float("nan"), lambda item: isinstance(item, float) and math.isnan(item)),
        (float("inf"), lambda item: item == float("inf")),
        (float("-inf"), lambda item: item == float("-inf")),
    ],
)
async def test_a_non_finite_result_reloads_unchanged(spine: Any, value: Any, check: Any) -> None:
    """The durable stores serialise to JSON, and pydantic's default turns NaN
    and the infinities into `null` on the way out. So a NaN result came back as
    `None` — not an error, not a stranded NodeRun, a silently different number,
    and only on the two backends that are the system of record."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="probe")
    lease = attempt.execution_lease
    token = lease.fencing_token if lease is not None else None
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result=value, fencing_token=token
    )

    reloaded = await store.get_attempt(attempt.attempt_id)

    assert reloaded is not None
    assert check(reloaded.result)


async def test_non_finite_evidence_survives_inside_a_container(spine: Any) -> None:
    """Results are `Any`: the non-finite value is as likely to be nested in the
    dict an executor returned as to be the whole result."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="probe")
    lease = attempt.execution_lease
    token = lease.fencing_token if lease is not None else None
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result={"scores": [1.0, float("nan")], "ratio": float("inf")},
        fencing_token=token,
    )

    reloaded = await store.get_attempt(attempt.attempt_id)

    assert reloaded is not None
    assert math.isnan(reloaded.result["scores"][1])
    assert reloaded.result["scores"][0] == 1.0
    assert reloaded.result["ratio"] == float("inf")


async def test_a_finite_result_is_not_disturbed_by_the_codec(spine: Any) -> None:
    """The encoding must be invisible to everything that is already JSON —
    including a dict that happens to have one key."""
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="probe")
    lease = attempt.execution_lease
    token = lease.fencing_token if lease is not None else None
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    payload = {"only": "one key"}
    await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result=payload, fencing_token=token
    )

    reloaded = await store.get_attempt(attempt.attempt_id)

    assert reloaded is not None
    assert reloaded.result == payload


# ── a Run is created in one commit, in the state its caller knows ──


async def test_a_run_can_be_created_already_queued(spine: Any) -> None:
    """One commit. Creating CREATED and transitioning immediately afterwards
    was two, and a process death between them left a CREATED Run whose
    provenance named a receipt that was never queued — with nothing scanning
    for it."""
    store, workspace, project_id = spine

    run = await store.create_run(_graph(workspace, project_id), initial_status=RunStatus.QUEUED)

    assert run.status is RunStatus.QUEUED
    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.QUEUED


async def test_the_default_creation_state_is_unchanged(spine: Any) -> None:
    store, workspace, project_id = spine

    run = await store.create_run(_graph(workspace, project_id))

    assert run.status is RunStatus.CREATED


@pytest.mark.parametrize(
    "status",
    [RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED],
)
async def test_a_run_cannot_be_created_in_a_state_it_never_reached(
    spine: Any, status: RunStatus
) -> None:
    """Work that has not started cannot have ended, and `create_run` is not a
    way to fabricate a Run that already finished."""
    store, workspace, project_id = spine

    with pytest.raises(RunIntegrityError):
        await store.create_run(_graph(workspace, project_id), initial_status=status)


# ── a Project cannot be deleted out from under its Runs ────────────


async def test_a_project_with_runs_cannot_be_deleted(spine: Any) -> None:
    """PostgreSQL enforces this with a foreign key and the in-memory store with
    a registered predicate. Either way, deleting the Project would leave Run
    history pointing at a Project that no longer exists."""
    store, workspace, project_id = spine
    projects = store._project_store
    register = getattr(projects, "set_run_owner", None)
    if register is not None:
        register(store.has_runs_in_project)
    await store.create_run(_graph(workspace, project_id))

    with pytest.raises(ProjectNotEmpty):
        await projects.delete(project_id)

    assert await projects.get(project_id) is not None
