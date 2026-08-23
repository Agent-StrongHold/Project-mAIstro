"""A task lands in the Workspace its submission named (#158).

#41 bound one admitter to one Workspace at wiring time, which is right for a
server where one instance is one Workspace (ADR-019/ADR-068) and wrong for the
Conductor, where one process serves every Workspace its users belong to. These
tests hold the routing seam: the Workspace comes from the submission, each
Workspace gets its own Root Project, and an admitter bound to one Workspace
refuses another rather than filing the work in its own.
"""

from __future__ import annotations

import asyncio

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import (
    TaskRunAdmitter,
    WorkspaceNotAdmissible,
    WorkspaceRoutingAdmitter,
)
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue


@pytest.fixture
def spine():
    projects = InMemoryProjectScopeStore()
    runs = InMemoryRunStore(project_store=projects)
    router = WorkspaceRoutingAdmitter(runs, projects, default_workspace_id="default")
    return projects, runs, router


# --- the criteria ---------------------------------------------------------


async def test_a_submission_under_a_workspace_lands_in_that_workspaces_root(spine) -> None:
    projects, runs, router = spine
    queue = TaskQueue(admitter=router)

    task = await queue.submit(TaskCreate(description="Fix the parser"), workspace_id="w-alpha")

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "w-alpha"
    root = await projects.root_for_workspace("w-alpha")
    assert run.project_id == root.project_id


async def test_two_workspaces_produce_runs_in_different_projects(spine) -> None:
    projects, runs, router = spine
    queue = TaskQueue(admitter=router)

    alpha = await queue.submit(TaskCreate(description="Alpha work"), workspace_id="w-alpha")
    beta = await queue.submit(TaskCreate(description="Beta work"), workspace_id="w-beta")

    alpha_run = await runs.get_run(alpha.run_id or "")
    beta_run = await runs.get_run(beta.run_id or "")
    assert alpha_run is not None and beta_run is not None
    # Read the scope tree back, not just the Runs: the point of the criterion
    # is that the *Projects* differ, so a bug that filed both under one root
    # while stamping two workspace_ids onto the Runs would still fail here.
    alpha_root = await projects.root_for_workspace("w-alpha")
    beta_root = await projects.root_for_workspace("w-beta")
    assert alpha_root.project_id != beta_root.project_id
    assert alpha_run.project_id == alpha_root.project_id
    assert beta_run.project_id == beta_root.project_id


async def test_an_unscoped_submission_still_lands_in_the_named_default(spine) -> None:
    projects, runs, router = spine
    queue = TaskQueue(admitter=router)

    task = await queue.submit(TaskCreate(description="No workspace named"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "default"
    assert run.project_id == (await projects.root_for_workspace("default")).project_id


# --- the invariant underneath --------------------------------------------


async def test_a_bound_admitter_refuses_a_workspace_that_is_not_its_own(spine) -> None:
    projects, runs, _router = spine
    root = await projects.create_root("w1")
    bound = TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    queue = TaskQueue(admitter=bound)

    with pytest.raises(WorkspaceNotAdmissible) as excinfo:
        await queue.submit(TaskCreate(description="Wrong workspace"), workspace_id="w2")

    # Both Workspaces named, so the operator can see which was asked for and
    # which the admitter is actually bound to.
    assert "w1" in str(excinfo.value)
    assert "w2" in str(excinfo.value)


async def test_a_bound_admitter_accepts_its_own_workspace_named_redundantly(spine) -> None:
    projects, runs, _router = spine
    root = await projects.create_root("w1")
    bound = TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    task = await TaskQueue(admitter=bound).submit(
        TaskCreate(description="Right workspace"), workspace_id="w1"
    )

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "w1"


async def test_each_workspace_keeps_its_own_bound_admitter(spine) -> None:
    _projects, _runs, router = spine

    alpha = await router.admitter_for("w-alpha")
    beta = await router.admitter_for("w-beta")

    assert alpha is not beta
    assert alpha.workspace_id == "w-alpha"
    assert beta.workspace_id == "w-beta"
    # Cached, not rebuilt: a second submission must reach the same bound
    # admitter, or its resolved Root Project is re-fetched on every task.
    assert await router.admitter_for("w-alpha") is alpha


async def test_concurrent_first_submissions_share_one_admitter(spine) -> None:
    _projects, _runs, router = spine

    admitters = await asyncio.gather(*(router.admitter_for("w-race") for _ in range(8)))

    assert len({id(a) for a in admitters}) == 1


async def test_a_blank_workspace_is_refused_rather_than_treated_as_absent(spine) -> None:
    _projects, _runs, router = spine

    with pytest.raises(ValueError):
        await router.admitter_for("   ")


async def test_the_router_refuses_a_blank_default(spine) -> None:
    projects, runs, _router = spine

    with pytest.raises(ValueError):
        WorkspaceRoutingAdmitter(runs, projects, default_workspace_id="  ")


async def test_transitions_reach_a_run_admitted_under_another_workspace(spine) -> None:
    _projects, runs, router = spine
    queue = TaskQueue(admitter=router)
    task = await queue.submit(TaskCreate(description="Alpha work"), workspace_id="w-alpha")

    # record_transition is Workspace-independent -- the Run already knows its
    # Project. A router that resolved the Workspace again here would fail to
    # advance any Run admitted outside the default.
    #
    # Through RUNNING, because the Run's lifecycle has no QUEUED -> COMPLETED
    # edge; the point being tested is that both hops reach the Run at all.
    assert await router.record_transition(task.run_id or "", TaskStatus.CODING) is True
    advanced = await router.record_transition(task.run_id or "", TaskStatus.COMPLETED)

    assert advanced is True
    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status.value == "completed"


# --- review findings ------------------------------------------------------


async def test_an_empty_workspace_is_not_the_same_as_an_omitted_one(spine) -> None:
    """`?workspace_id=` is a named Workspace that happens to be blank.

    Folding it into the default let the local backend file it there while the
    HTTP backend refused the same non-None value, and contradicted the blank
    check the admitter documents.
    """
    _projects, _runs, router = spine

    with pytest.raises(ValueError):
        await router.admitter_for("")


async def test_omitting_the_workspace_still_means_the_default(spine) -> None:
    _projects, _runs, router = spine

    assert (await router.admitter_for(None)).workspace_id == "default"
    assert (await router.admitter_for()).workspace_id == "default"
