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
from maistro.runs.lifecycle import UnearnedRunCompletion
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler, CancellationCause
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import (
    ActiveAttemptExists,
    AttemptNotFound,
    DuplicateOccurrence,
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


# ── deletion, and the two things it refuses ────────────────────────
#
# `delete_run` was covered per-backend in `test_store.py` and
# `test_sqlite_store.py` and nowhere across all three, so PostgreSQL's copy of
# these refusals — the ones that keep a retention sweep from orphaning history —
# was the only unproven one. That asymmetry is what this file exists to end.


async def test_a_terminal_run_can_be_deleted(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED)

    assert await store.delete_run(run.run_id) is True
    assert await store.get_run(run.run_id) is None


async def test_deleting_an_unknown_run_is_false_not_an_error(spine: Any) -> None:
    """A sweep that raced another sweep asked about a Run already gone. That is
    an ordinary outcome, not a failure to report."""
    store, _workspace, _project_id = spine

    assert await store.delete_run("run-that-never-existed") is False


async def test_a_running_run_is_not_deletable(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    with pytest.raises(RunIntegrityError, match="non-terminal"):
        await store.delete_run(run.run_id)

    assert await store.get_run(run.run_id) is not None


async def test_force_skips_the_terminal_check_and_nothing_else(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    assert await store.delete_run(run.run_id, force=True) is True
    assert await store.get_run(run.run_id) is None


async def test_a_run_with_children_is_never_deletable_even_forced(spine: Any) -> None:
    """The child check is not a policy knob. Deleting a parent out from under
    its children leaves a `parent_run_id` pointing at nothing, on every backend
    — PostgreSQL would refuse it with a foreign key and the others must agree."""
    store, workspace, project_id = spine
    parent = await _run(spine)
    await store.create_run(_graph(workspace, project_id), parent_run_id=parent.run_id)
    await store.transition_run(parent.run_id, RunStatus.QUEUED)
    await store.transition_run(parent.run_id, RunStatus.RUNNING)
    await store.transition_run(parent.run_id, RunStatus.COMPLETED)

    for force in (False, True):
        with pytest.raises(RunIntegrityError, match="child Run"):
            await store.delete_run(parent.run_id, force=force)

    assert await store.get_run(parent.run_id) is not None


async def test_deleting_a_run_takes_its_node_runs_and_attempts(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.FAILED)

    await store.delete_run(run.run_id)

    assert await store.get_node_run(node_run.node_run_id) is None
    assert await store.get_attempt(attempt.attempt_id) is None


# ── has_runs_in_project ────────────────────────────────────────────


async def test_a_project_reports_whether_it_owns_runs(spine: Any) -> None:
    """The predicate `PgProjectScopeStore.delete()` consults, so its refusal
    names the rule rather than surfacing a raw constraint name."""
    store, workspace, project_id = spine

    assert await store.has_runs_in_project(project_id) is False
    await store.create_run(_graph(workspace, project_id))
    assert await store.has_runs_in_project(project_id) is True


# ── the remaining child-Run refusals ───────────────────────────────


async def test_a_child_run_cannot_implicitly_cross_projects(spine: Any) -> None:
    """Crossing Workspaces is never allowed; crossing Projects requires the
    caller to have authorized the destination and say so."""
    store, workspace, _project_id = spine
    projects = store._project_store
    root = await projects.create_root(workspace)
    sibling = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Sibling"
    )
    parent = await _run(spine)

    with pytest.raises(RunIntegrityError, match="cross Project"):
        await store.create_run(_graph(workspace, sibling.project_id), parent_run_id=parent.run_id)

    allowed = await store.create_run(
        _graph(workspace, sibling.project_id),
        parent_run_id=parent.run_id,
        allow_cross_project=True,
    )
    assert allowed.project_id == sibling.project_id


async def test_a_parent_node_run_must_belong_to_the_parent_run(spine: Any) -> None:
    """Otherwise the child cites a delegating node in some other Run's history."""
    store, workspace, project_id = spine
    parent = await _run(spine)
    unrelated = await _run(spine)
    foreign_node_run = await store.create_node_run(unrelated.run_id, node_id="node-1")

    with pytest.raises(RunIntegrityError, match="does not belong"):
        await store.create_run(
            _graph(workspace, project_id),
            parent_run_id=parent.run_id,
            parent_node_run_id=foreign_node_run.node_run_id,
        )


# ── Attempts under a NodeRun that has already ended ────────────────


async def test_an_attempt_under_a_terminal_node_run_is_refused(spine: Any) -> None:
    store, _workspace, _project_id = spine
    node_run = await _node_run(spine)
    # Cancelled rather than completed: both are terminal, and cancellation is
    # reachable straight from CREATED, so the test states the rule under
    # examination without also walking the acceptance-evidence machinery.
    await store.transition_node_run(node_run.node_run_id, RunStatus.CANCELLED)

    with pytest.raises(RunIntegrityError, match="terminal NodeRun"):
        await store.create_attempt(node_run.node_run_id)


# ── a Run cannot outlive its NodeRuns (#226, ADR-082426-a47f) ──────
#
# Both halves were reachable on the ordinary path before this: a Run reached
# `completed` while its only node was still `running`, and that node could then
# move to `failed` afterwards. Neither needed a race, and every domain that
# terminalizes a Run does so from its own outcome without knowing what nodes
# exist under it — so the rule belongs at the store, once, rather than in each
# of them.


async def _running_run_with_node(spine: Any) -> Any:
    """A RUNNING Run whose single NodeRun is RUNNING too."""
    store, _workspace, _project_id = spine
    run = await _run(spine)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return run, node_run


@pytest.mark.parametrize(
    "terminal",
    [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT],
)
async def test_terminalizing_a_run_settles_its_open_node_run(
    spine: Any, terminal: RunStatus
) -> None:
    """Whatever the Run ends as, an open node under it ends `cancelled`.

    Not mirroring the Run: the node did not itself succeed, fail or time out,
    and calling it `failed` under a failed Run invents a physical outcome it
    never had and counts one failure twice.
    """
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)

    await store.transition_run(run.run_id, terminal)

    settled = await store.get_node_run(node_run.node_run_id)
    assert settled is not None
    assert settled.status is RunStatus.CANCELLED
    assert settled.finished_at is not None


async def test_the_settled_node_run_says_which_run_ended_it(spine: Any) -> None:
    """Otherwise a cascade is indistinguishable from nodes each cancelled on
    their own, which is the one thing a reader is trying to tell apart."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)

    await store.transition_run(run.run_id, RunStatus.FAILED, error="boom")

    settled = await store.get_node_run(node_run.node_run_id)
    assert settled is not None
    assert settled.error == "cancelled because its Run terminalized as failed"


async def test_every_open_node_run_is_settled_not_just_the_first(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id, node_ids=("node-1", "node-2")))
    first = await store.create_node_run(run.run_id, node_id="node-1")
    second = await store.create_node_run(run.run_id, node_id="node-2")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    await store.transition_run(run.run_id, RunStatus.CANCELLED)

    for node_run_id in (first.node_run_id, second.node_run_id):
        settled = await store.get_node_run(node_run_id)
        assert settled is not None
        assert settled.status is RunStatus.CANCELLED


async def test_a_parked_node_run_is_settled_too(spine: Any) -> None:
    """WAITING is the state a failed Attempt parks its node in, awaiting a
    retry decision. Once the Run is over that decision will never come, so
    leaving it parked is the "a process died here" reading terminalization
    exists to remove."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    await store.transition_node_run(node_run.node_run_id, RunStatus.WAITING)

    await store.transition_run(run.run_id, RunStatus.FAILED)

    settled = await store.get_node_run(node_run.node_run_id)
    assert settled is not None
    assert settled.status is RunStatus.CANCELLED


async def test_an_already_terminal_node_run_keeps_its_own_outcome(spine: Any) -> None:
    """The cascade settles what is open. A node that finished on its own has an
    outcome of its own, and overwriting it would lose the result."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    await store.transition_node_run(
        node_run.node_run_id, RunStatus.FAILED, error="the node itself failed"
    )

    await store.transition_run(run.run_id, RunStatus.FAILED)

    settled = await store.get_node_run(node_run.node_run_id)
    assert settled is not None
    assert settled.status is RunStatus.FAILED
    assert settled.error == "the node itself failed"


async def test_a_non_terminal_run_transition_settles_nothing(spine: Any) -> None:
    """The cascade is terminalization's, not every transition's. A Run parking
    itself in WAITING has not finished, and its node may still be retried."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)

    await store.transition_run(run.run_id, RunStatus.WAITING)

    unchanged = await store.get_node_run(node_run.node_run_id)
    assert unchanged is not None
    assert unchanged.status is RunStatus.RUNNING


async def test_an_illegal_run_transition_settles_nothing(spine: Any) -> None:
    """The Run's own transition is validated first. A refused terminalization
    that had already cancelled the nodes would leave the Run running with every
    node under it dead."""
    store, _workspace, _project_id = spine
    run = await _run(spine)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")

    # CREATED has no edge to FAILED.
    with pytest.raises(Exception):  # noqa: B017 - the backends raise their own types
        await store.transition_run(run.run_id, RunStatus.FAILED)

    unchanged = await store.get_node_run(node_run.node_run_id)
    assert unchanged is not None
    assert unchanged.status is RunStatus.CREATED
    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.CREATED


async def test_a_node_run_cannot_move_once_its_run_is_terminal(spine: Any) -> None:
    """A reconciliation that lands late must not rewrite the history of a Run
    that is closed — including by undoing the cascade that settled it."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, result={"ok": True})

    with pytest.raises(RunIntegrityError, match="is terminal"):
        await store.transition_node_run(node_run.node_run_id, RunStatus.FAILED, error="late")

    settled = await store.get_node_run(node_run.node_run_id)
    assert settled is not None
    assert settled.status is RunStatus.CANCELLED


async def test_terminalizing_a_terminal_run_is_still_refused(spine: Any) -> None:
    """So the cascade cannot run twice, and a second terminalization cannot
    rewrite the first one's answer."""
    store, _workspace, _project_id = spine
    run, _node_run = await _running_run_with_node(spine)
    await store.transition_run(run.run_id, RunStatus.COMPLETED)

    with pytest.raises(Exception):  # noqa: B017 - the backends raise their own types
        await store.transition_run(run.run_id, RunStatus.FAILED)

    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.COMPLETED


# ── one Run per schedule firing (#220, ADR-082426-82c7) ───────────
#
# `(schedule_id, scheduled_for)` is the identity of a firing; the cursor never
# was. Before this a crash between creating a Run and stamping the cursor
# repeated the occurrence on the next tick, and two tickers on one schedule
# both created Runs for every occurrence they both enumerated.


def _occurrence(schedule_id: str = "sched-1", when: str = "2026-08-24T12:00:00+00:00") -> dict:
    return {
        ADMISSION_SOURCE: SCHEDULE_SOURCE,
        SCHEDULE_ID_KEY: schedule_id,
        SCHEDULED_FOR_KEY: when,
    }


async def test_a_second_run_for_one_occurrence_is_refused(spine: Any) -> None:
    store, workspace, project_id = spine
    await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    with pytest.raises(DuplicateOccurrence) as caught:
        await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    assert caught.value.schedule_id == "sched-1"
    assert caught.value.scheduled_for == "2026-08-24T12:00:00+00:00"


async def test_a_catch_up_fire_collides_with_the_on_time_one(spine: Any) -> None:
    """They are the same occurrence. That one was noticed later than the other
    is why `catchup` exists — it is not a reason to run the work twice."""
    store, workspace, project_id = spine
    await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    with pytest.raises(DuplicateOccurrence):
        await store.create_run(
            _graph(workspace, project_id),
            provenance={**_occurrence(), SCHEDULE_CATCHUP_KEY: True},
        )


async def test_a_different_occurrence_of_the_same_schedule_is_admitted(spine: Any) -> None:
    store, workspace, project_id = spine
    await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    other = await store.create_run(
        _graph(workspace, project_id),
        provenance=_occurrence(when="2026-08-24T13:00:00+00:00"),
    )

    assert other.run_id


async def test_the_same_time_on_a_different_schedule_is_admitted(spine: Any) -> None:
    store, workspace, project_id = spine
    await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    other = await store.create_run(
        _graph(workspace, project_id), provenance=_occurrence(schedule_id="sched-2")
    )

    assert other.run_id


async def test_runs_that_claim_no_occurrence_do_not_collide(spine: Any) -> None:
    """Task and chat Runs carry neither key. Without a partial claim every one
    of them would collide with every other on a pair of missing values."""
    store, workspace, project_id = spine
    provenance = {ADMISSION_SOURCE: "task_queue", "task_id": "t-1"}

    run_ids = {
        (await store.create_run(_graph(workspace, project_id), provenance=dict(provenance))).run_id
        for _ in range(3)
    }

    assert len(run_ids) == 3


async def test_half_an_occurrence_key_claims_nothing(spine: Any) -> None:
    """A Run carrying one key without the other cannot say which firing it
    belongs to. Inventing a key for it would collide unrelated work."""
    store, workspace, project_id = spine
    partial = {ADMISSION_SOURCE: SCHEDULE_SOURCE, SCHEDULE_ID_KEY: "sched-1"}

    first = await store.create_run(_graph(workspace, project_id), provenance=partial)
    second = await store.create_run(_graph(workspace, project_id), provenance=dict(partial))

    assert first.run_id != second.run_id


async def test_only_one_of_many_concurrent_tickers_admits_an_occurrence(spine: Any) -> None:
    """Eight tickers race on one firing. Seven must lose.

    Under SQLite the database serialises them and the application check would
    be enough on its own; under PostgreSQL they run genuinely at once, which
    is the case #220 is actually about — "exactly one run_id per firing" must
    not depend on how many replicas happen to be deployed.
    """
    store, workspace, project_id = spine

    results = await asyncio.gather(
        *(
            store.create_run(_graph(workspace, project_id), provenance=_occurrence())
            for _ in range(8)
        ),
        return_exceptions=True,
    )

    admitted = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, DuplicateOccurrence)]
    unexpected = [
        r
        for r in results
        if isinstance(r, BaseException) and not isinstance(r, DuplicateOccurrence)
    ]

    assert unexpected == [], f"losers must be refused cleanly, not crash: {unexpected}"
    assert len(admitted) == 1
    assert len(refused) == 7


async def test_a_failed_occurrences_run_is_still_retryable(spine: Any) -> None:
    """The claim refuses duplicate *occurrences*, not duplicate *attempts*. A
    scheduled Run that failed is retried by executing another Attempt under its
    existing NodeRun — which never goes back through `create_run`, so a
    constraint that blocked it would be a worse bug than the one being fixed.
    """
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id), provenance=_occurrence())
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    first = await store.create_attempt(node_run.node_run_id, lease_holder="ticker-a")
    assert first.execution_lease is not None
    token = first.execution_lease.fencing_token
    await store.transition_attempt(first.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    await store.transition_attempt(
        first.attempt_id, AttemptStatus.FAILED, error="provider down", fencing_token=token
    )

    second = await store.create_attempt(node_run.node_run_id, lease_holder="ticker-a")

    assert second.ordinal == 2


async def test_deleting_a_run_releases_its_occurrence(spine: Any) -> None:
    """The claim lives on the Run, so it goes when the Run does. Nothing is
    duplicated by re-admitting a firing whose only record was deliberately
    destroyed, and a claim outliving its Run would assert something no longer
    true."""
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id), provenance=_occurrence())
    await store.delete_run(run.run_id, force=True)

    readmitted = await store.create_run(_graph(workspace, project_id), provenance=_occurrence())

    assert readmitted.run_id != run.run_id


# ── the three physical failures are told apart (#230, ADR-082426-f170) ──
#
# Before this they were not: cancelled, timed-out and failed Attempts all
# parked their NodeRun in WAITING, so a user cancelling their own work looked
# exactly like a provider being down on any record that counts NodeRuns.


async def _terminal_attempt(spine: Any, node_run: Any, status: AttemptStatus) -> Any:
    store, _workspace, _project_id = spine
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    assert attempt.execution_lease is not None
    token = attempt.execution_lease.fencing_token
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    return await store.transition_attempt(
        attempt.attempt_id, status, error="ended", fencing_token=token
    )


async def test_a_requested_cancellation_terminalizes_its_node_run(spine: Any) -> None:
    """The retry decision has been made, and it was *don't*. Parked would mean
    "awaiting a decision" — which is what made a cancelled turn and an outage
    indistinguishable."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, AttemptStatus.CANCELLED)

    await AttemptLifecycleReconciler(store).reconcile(
        attempt, cancellation=CancellationCause.REQUESTED
    )

    settled = await store.get_node_run(node_run.node_run_id)
    reloaded = await store.get_run(run.run_id)
    assert settled is not None and settled.status is RunStatus.CANCELLED
    assert reloaded is not None and reloaded.status is RunStatus.CANCELLED


async def test_a_recovered_cancellation_still_parks_its_node_run(spine: Any) -> None:
    """Crash recovery closes the physical record so a *fresh* Attempt can run.
    Terminalizing here would make recovery destroy the work it exists to
    resume."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, AttemptStatus.CANCELLED)

    await AttemptLifecycleReconciler(store).reconcile(
        attempt, cancellation=CancellationCause.RECOVERED
    )

    parked = await store.get_node_run(node_run.node_run_id)
    reloaded = await store.get_run(run.run_id)
    assert parked is not None and parked.status is RunStatus.WAITING
    assert reloaded is not None and reloaded.status is RunStatus.WAITING


async def test_recovery_is_the_default_so_a_caller_that_forgets_loses_nothing(
    spine: Any,
) -> None:
    """The two mistakes are not symmetric: defaulting to parked leaves a less
    informative record, defaulting to terminal destroys resumable work."""
    store, _workspace, _project_id = spine
    _run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, AttemptStatus.CANCELLED)

    await AttemptLifecycleReconciler(store).reconcile(attempt)

    parked = await store.get_node_run(node_run.node_run_id)
    assert parked is not None and parked.status is RunStatus.WAITING


@pytest.mark.parametrize("status", [AttemptStatus.FAILED, AttemptStatus.TIMED_OUT])
async def test_a_failure_and_a_timeout_still_park(spine: Any, status: AttemptStatus) -> None:
    """Both are plausibly retryable, and whether to retry belongs to a policy
    above this layer — which is what WAITING is for. Only cancellation is a
    decision already taken."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, status)

    await AttemptLifecycleReconciler(store).reconcile(
        attempt, cancellation=CancellationCause.REQUESTED
    )

    parked = await store.get_node_run(node_run.node_run_id)
    reloaded = await store.get_run(run.run_id)
    assert parked is not None and parked.status is RunStatus.WAITING
    assert reloaded is not None and reloaded.status is RunStatus.WAITING


async def test_the_three_outcomes_do_not_collapse_into_one(spine: Any) -> None:
    """Stated as one assertion because the defect was the *collapse*, not any
    single mapping: all three used to read `waiting`, and asserting each alone
    would not have caught that."""
    store, _workspace, _project_id = spine
    reconciler = AttemptLifecycleReconciler(store)
    seen: dict[str, RunStatus] = {}

    for label, status, cause in (
        ("cancelled", AttemptStatus.CANCELLED, CancellationCause.REQUESTED),
        ("timed_out", AttemptStatus.TIMED_OUT, CancellationCause.RECOVERED),
        ("failed", AttemptStatus.FAILED, CancellationCause.RECOVERED),
    ):
        _run, node_run = await _running_run_with_node(spine)
        attempt = await _terminal_attempt(spine, node_run, status)
        await reconciler.reconcile(attempt, cancellation=cause)
        settled = await store.get_node_run(node_run.node_run_id)
        assert settled is not None
        seen[label] = settled.status

    assert seen["cancelled"] is RunStatus.CANCELLED
    assert seen["timed_out"] is seen["failed"] is RunStatus.WAITING


async def test_a_cancelled_node_does_not_cancel_a_run_with_live_siblings(spine: Any) -> None:
    """One cancelled branch does not decide for the others — the same rule
    `_park_run_if_inactive` already applied to parking."""
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id, node_ids=("node-1", "node-2")))
    cancelled_node = await store.create_node_run(run.run_id, node_id="node-1")
    sibling = await store.create_node_run(run.run_id, node_id="node-2")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    for node_run_id in (cancelled_node.node_run_id, sibling.node_run_id):
        await store.transition_node_run(node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run_id, RunStatus.RUNNING)
    attempt = await _terminal_attempt(spine, cancelled_node, AttemptStatus.CANCELLED)

    await AttemptLifecycleReconciler(store).reconcile(
        attempt, cancellation=CancellationCause.REQUESTED
    )

    reloaded = await store.get_run(run.run_id)
    still_running = await store.get_node_run(sibling.node_run_id)
    assert reloaded is not None and reloaded.status is RunStatus.RUNNING
    assert still_running is not None and still_running.status is RunStatus.RUNNING


async def test_a_cancellation_arriving_after_the_node_finished_changes_nothing(
    spine: Any,
) -> None:
    """A NodeRun that already reached an outcome of its own keeps it. The
    cancellation lost the race, and overwriting would replace a real result
    with the fact that someone asked too late."""
    store, _workspace, _project_id = spine
    _run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, AttemptStatus.CANCELLED)
    await store.transition_node_run(
        node_run.node_run_id, RunStatus.FAILED, error="the node itself failed"
    )

    await AttemptLifecycleReconciler(store).reconcile(
        attempt, cancellation=CancellationCause.REQUESTED
    )

    unchanged = await store.get_node_run(node_run.node_run_id)
    assert unchanged is not None
    assert unchanged.status is RunStatus.FAILED
    assert unchanged.error == "the node itself failed"


async def test_reconciling_the_same_failure_twice_is_idempotent(spine: Any) -> None:
    """Repeated terminalization, which #43 asks about by name. The second pass
    finds the NodeRun already parked and the Run no longer running, and must
    leave both alone rather than re-parking them."""
    store, _workspace, _project_id = spine
    run, node_run = await _running_run_with_node(spine)
    attempt = await _terminal_attempt(spine, node_run, AttemptStatus.FAILED)
    reconciler = AttemptLifecycleReconciler(store)

    await reconciler.reconcile(attempt)
    first = await store.get_run(run.run_id)
    await reconciler.reconcile(attempt)
    second = await store.get_run(run.run_id)

    assert first is not None and second is not None
    assert first.status is second.status is RunStatus.WAITING
    assert first.updated_at == second.updated_at


async def test_a_failure_does_not_park_a_run_with_live_siblings(spine: Any) -> None:
    """The parking half of the same rule the cancellation half follows: one
    branch ending does not decide for the others."""
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id, node_ids=("node-1", "node-2")))
    failing = await store.create_node_run(run.run_id, node_id="node-1")
    sibling = await store.create_node_run(run.run_id, node_id="node-2")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    for node_run_id in (failing.node_run_id, sibling.node_run_id):
        await store.transition_node_run(node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run_id, RunStatus.RUNNING)
    attempt = await _terminal_attempt(spine, failing, AttemptStatus.FAILED)

    await AttemptLifecycleReconciler(store).reconcile(attempt)

    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None and reloaded.status is RunStatus.RUNNING


# ── a Run cannot claim success over a node that failed (#241) ──────────
#
# The same two-test split the fence uses above, for the same reason: the
# parameterized test carries the all-three-stores claim in CI's postgres legs,
# and the in-memory one carries the acceptance criterion in jobs that configure
# no database. The assertions live once, in these helpers.


async def _two_node_running_run(spine: Any) -> Any:
    """A RUNNING Run over a two-node Graph, both NodeRuns RUNNING."""
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id, node_ids=("node-1", "node-2")))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    nodes = []
    for node_id in ("node-1", "node-2"):
        node_run = await store.create_node_run(run.run_id, node_id=node_id)
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        nodes.append(node_run)
    return run, nodes


async def _assert_completion_over_a_failed_node_refused(spine: Any) -> None:
    """#241's reproduction, which needs no race: one node fails, the other
    completes, and the domain asserts COMPLETED from its own receipt."""
    store, _workspace, _project_id = spine
    run, (failed, done) = await _two_node_running_run(spine)
    await store.transition_node_run(failed.node_run_id, RunStatus.FAILED, error="boom")
    await store.transition_node_run(done.node_run_id, RunStatus.COMPLETED)

    with pytest.raises(UnearnedRunCompletion) as caught:
        await store.transition_run(run.run_id, RunStatus.COMPLETED, result={"ok": True})

    assert caught.value.node_id == "node-1"
    assert caught.value.status is RunStatus.FAILED
    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.RUNNING, "the refused transition must not have landed"
    assert reloaded.result is None


async def _assert_failure_over_a_failed_node_allowed(spine: Any) -> None:
    """The asymmetry. Only success has to be earned — the domain must still be
    able to report the failure it actually saw."""
    store, _workspace, _project_id = spine
    run, (failed, done) = await _two_node_running_run(spine)
    await store.transition_node_run(failed.node_run_id, RunStatus.FAILED, error="boom")
    await store.transition_node_run(done.node_run_id, RunStatus.COMPLETED)

    settled = await store.transition_run(run.run_id, RunStatus.FAILED, error="node-1 failed")

    assert settled.status is RunStatus.FAILED
    assert settled.error == "node-1 failed"


async def _assert_cancellation_over_completed_nodes_allowed(spine: Any) -> None:
    """A caller cancelled the work (#230/#233). Every node that ran succeeded,
    and the Run is still CANCELLED — that outcome came from outside any node,
    and deriving the Run's status from the fold would erase it."""
    store, _workspace, _project_id = spine
    run, (first, second) = await _two_node_running_run(spine)
    for node_run in (first, second):
        await store.transition_node_run(node_run.node_run_id, RunStatus.COMPLETED)

    settled = await store.transition_run(run.run_id, RunStatus.CANCELLED, error="user asked")

    assert settled.status is RunStatus.CANCELLED


async def _assert_a_retried_node_does_not_condemn_its_run(spine: Any) -> None:
    """The case a naive "any FAILED NodeRun" rule would break, and it is not
    rare — it is every retry-after-failure path. A re-execution is a *new*
    NodeRun for the same node, so the node holds a failed one and a completed
    one, and only the newest states its outcome."""
    store, _workspace, _project_id = spine
    run = await _run(spine)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    first = await store.create_node_run(run.run_id, node_id="node-1")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.FAILED):
        await store.transition_node_run(first.node_run_id, status)
    second = await store.create_node_run(run.run_id, node_id="node-1")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.COMPLETED):
        await store.transition_node_run(second.node_run_id, status)

    assert second.ordinal > first.ordinal
    settled = await store.transition_run(run.run_id, RunStatus.COMPLETED, result={"ok": True})

    assert settled.status is RunStatus.COMPLETED


async def test_completion_over_a_failed_node_is_refused(spine: Any) -> None:
    await _assert_completion_over_a_failed_node_refused(spine)


async def test_failure_over_a_failed_node_is_allowed(spine: Any) -> None:
    await _assert_failure_over_a_failed_node_allowed(spine)


async def test_cancellation_over_completed_nodes_is_allowed(spine: Any) -> None:
    await _assert_cancellation_over_completed_nodes_allowed(spine)


async def test_a_retried_node_does_not_condemn_its_run(spine: Any) -> None:
    await _assert_a_retried_node_does_not_condemn_its_run(spine)


@pytest.mark.ac("ADR-082426-19ed/AC-1")
async def test_completion_over_a_failed_node_refused_in_memory(memory_spine: Any) -> None:
    await _assert_completion_over_a_failed_node_refused(memory_spine)


@pytest.mark.ac("ADR-082426-19ed/AC-2")
async def test_failure_over_a_failed_node_allowed_in_memory(memory_spine: Any) -> None:
    await _assert_failure_over_a_failed_node_allowed(memory_spine)


@pytest.mark.ac("ADR-082426-19ed/AC-2")
async def test_cancellation_over_completed_nodes_allowed_in_memory(memory_spine: Any) -> None:
    await _assert_cancellation_over_completed_nodes_allowed(memory_spine)


@pytest.mark.ac("ADR-082426-19ed/AC-3")
async def test_a_retried_node_does_not_condemn_its_run_in_memory(memory_spine: Any) -> None:
    await _assert_a_retried_node_does_not_condemn_its_run(memory_spine)
