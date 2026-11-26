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
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import (
    TaskRunAdmitter,
    WorkspaceNotAdmissible,
    WorkspaceRoutingAdmitter,
)
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.workspaces.model import WorkspaceNotFound


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


# --- run cancellation routed through the shared seam -----------------------


async def test_the_router_cancels_a_run_it_admitted(spine) -> None:
    _projects, runs, router = spine
    queue = TaskQueue(admitter=router)
    task = await queue.submit(TaskCreate(description="Routed work"), workspace_id="w-cancel")

    assert await router.cancel_run(task.run_id or "") is True
    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.CANCELLED


async def test_the_router_reports_a_run_that_never_existed(spine) -> None:
    _projects, _runs, router = spine

    assert await router.cancel_run("run-never-was") is False


# --- run lookup routed through the shared seam ------------------------------


async def test_the_router_reads_a_run_through_the_default_admitter(spine) -> None:
    _projects, runs, router = spine
    queue = TaskQueue(admitter=router)
    task = await queue.submit(TaskCreate(description="Routed work"), workspace_id="w-lookup")

    found = await router.lookup_run(task.run_id or "")
    assert found is not None
    assert found == await runs.get_run(task.run_id or "")
    assert found.workspace_id == "w-lookup"
    assert found.status is RunStatus.QUEUED


async def test_the_router_reports_a_lookup_of_a_run_that_never_existed(spine) -> None:
    _projects, _runs, router = spine

    assert await router.lookup_run("run-never-was") is None


# --- task receipt lookup routed through the shared seam (#1690) -------------


async def test_the_router_resolves_a_task_receipt_through_the_default_binding(spine) -> None:
    """A task's Run knows its own Workspace, so the read needs none of the request."""
    _projects, runs, router = spine
    queue = TaskQueue(admitter=router)
    task = await queue.submit(TaskCreate(description="Routed receipt"), workspace_id="w-receipt")

    found = await router.find_task_run(task.task_id)
    assert found is not None
    assert found.run_id == task.run_id
    assert found.workspace_id == "w-receipt"
    # A receipt id nobody admitted is a plain None, the same as lookup_run's.
    assert await router.find_task_run("task-never-was") is None
    assert found == await runs.get_run(task.run_id or "")


# --- the canonical-authority fence (#37) ------------------------------------


class _AuthorizedSpine:
    """The routing spine with the canonical Workspace authority bound.

    `InMemoryWorkspaceStore.__init__` binds its Project store, which is what
    makes `create_root` — the router's every-call verification — able to
    refuse a Workspace id nothing canonical owns.
    """

    def __init__(self) -> None:
        from maistro.workspaces.store import InMemoryWorkspaceStore

        self.projects = InMemoryProjectScopeStore()
        self.workspaces = InMemoryWorkspaceStore(project_store=self.projects)
        self.runs = InMemoryRunStore(project_store=self.projects)
        self.router = WorkspaceRoutingAdmitter(
            self.runs, self.projects, default_workspace_id="default"
        )

    async def provision(self, workspace_id: str) -> str:
        workspace = await self.workspaces.create(
            creator_user_id="owner", name=workspace_id, workspace_id=workspace_id
        )
        return workspace.workspace_id


async def test_an_unknown_workspace_fails_before_any_write() -> None:
    """A submission naming an id no canonical Workspace owns admits nothing.

    This is the hole the 2026-11 recheck reproduced statically: the router
    used to build a Root Project for whatever id it was handed. The refusal
    now happens before the Project or Run store is touched, so a rejected
    submission leaves zero rows behind.
    """
    spine = _AuthorizedSpine()
    await spine.provision("w-real")
    queue = TaskQueue(admitter=spine.router)

    with pytest.raises(WorkspaceNotFound):
        await queue.submit(TaskCreate(description="Ghost work"), workspace_id="w-ghost")

    from maistro.projects.scope import ProjectNotFound

    with pytest.raises(ProjectNotFound):
        await spine.projects.root_for_workspace("w-ghost")
    # The real Workspace was never touched either.
    real_root = await spine.projects.root_for_workspace("w-real")
    assert real_root.is_root
    # The refusal minted no Run anywhere: the refusal happened in the router,
    # before any Run write, so the spine is still empty.
    assert await spine.runs.has_runs_in_project(real_root.project_id) is False


async def test_a_cached_admitter_stops_admitting_once_the_workspace_is_deleted() -> None:
    """Deletion fences the cache, not just the first build.

    A Conductor process keeps one bound admitter per Workspace for the life of
    the process. If the Workspace is deleted underneath it — by another
    client, on a shared canonical store — the cached admitter must stop
    admitting the moment the next verification runs, and the failed attempt
    must leave no Run behind.
    """
    spine = _AuthorizedSpine()
    workspace_id = await spine.provision("w-doomed")
    queue = TaskQueue(admitter=spine.router)

    first = await queue.submit(TaskCreate(description="Before"), workspace_id=workspace_id)
    assert (await spine.runs.get_run(first.run_id or "")) is not None
    # Warm the cache explicitly: the delete below must fence the *cached*
    # admitter, not just a cold first build.
    await spine.router.admitter_for(workspace_id)

    await spine.workspaces.delete(workspace_id, principal_id="owner")

    with pytest.raises(WorkspaceNotFound):
        await spine.router.admitter_for(workspace_id)
    with pytest.raises(WorkspaceNotFound):
        await queue.submit(TaskCreate(description="After"), workspace_id=workspace_id)

    # Exactly the runs admitted before the delete: nothing minted afterwards.
    after = await spine.runs.get_run(first.run_id or "")
    assert after is not None
    from maistro.projects.scope import ProjectNotFound

    with pytest.raises(ProjectNotFound):
        await spine.projects.root_for_workspace(workspace_id)


async def test_deleting_the_default_workspace_leaves_existing_run_operations_working() -> None:
    """Existing-run operations survive a deleted default Workspace (#37 review).

    `record_transition`, `run_for_task_receipt`, `lookup_run` and
    `find_task_run` are Workspace-independent: the Run exists and names its
    own Project. The deletion APIs allow removing a default Workspace that
    owns no Runs, so routing these reads through `admitter_for(None)` — which
    now fences on canonical existence — would strand every transition and
    lookup for Runs admitted under other, still-live Workspaces. The fence
    stays on admissions; these operations never consult it.
    """
    spine = _AuthorizedSpine()
    await spine.provision("default")
    await spine.provision("w-live")
    queue = TaskQueue(admitter=spine.router)

    # Only the live Workspace owns a Run: the default must stay empty so its
    # deletion is legal, exactly the deployment shape the finding describes.
    stranded = await queue.submit(TaskCreate(description="Live work"), workspace_id="w-live")

    await spine.workspaces.delete("default", principal_id="owner")

    # Admissions into the deleted default are still fenced ...
    with pytest.raises(WorkspaceNotFound):
        await queue.submit(TaskCreate(description="After delete"))

    # ... while the existing Run in the live Workspace stays fully reachable.
    assert await spine.router.record_transition(stranded.run_id or "", TaskStatus.CODING) is True
    assert await spine.router.run_for_task_receipt(stranded.task_id) == stranded.run_id
    found = await spine.router.lookup_run(stranded.run_id or "")
    assert found is not None
    assert found.workspace_id == "w-live"
    task_run = await spine.router.find_task_run(stranded.task_id)
    assert task_run is not None
    assert task_run.run_id == stranded.run_id


async def test_a_cached_admitter_is_stable_while_the_workspace_lives() -> None:
    """Per-call verification must not rebuild the admitter every time.

    The fence re-resolves the Root through `create_root` on every call, but
    for a live Workspace that is create-or-return and the cache serves. A
    router that dropped its cache on every admission would re-bind admitters
    mid-flight — the loser's resolved project id thrown away under a task.
    """
    spine = _AuthorizedSpine()
    workspace_id = await spine.provision("w-stable")

    first = await spine.router.admitter_for(workspace_id)
    second = await spine.router.admitter_for(workspace_id)
    third = await spine.router.admitter_for(workspace_id)

    assert first is second is third


async def test_the_default_workspace_is_verified_like_any_other() -> None:
    """`admitter_for(None)` resolves to the default and verifies it too.

    The default Workspace is provisioned at composition, so its verification
    passes in production; a deployment whose configured Workspace cannot be
    provisioned fails at startup, not on the first submission. This pins the
    verification itself: a default that vanishes canonically is refused, not
    silently re-rooted.
    """
    spine = _AuthorizedSpine()
    queue = TaskQueue(admitter=spine.router)

    with pytest.raises(WorkspaceNotFound):
        await queue.submit(TaskCreate(description="No default yet"))

    await spine.provision("default")
    task = await queue.submit(TaskCreate(description="Now there is"))
    run = await spine.runs.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "default"
