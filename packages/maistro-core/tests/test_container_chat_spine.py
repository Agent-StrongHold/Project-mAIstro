"""`create_container()` wires chat's half of the Run seam (#131).

The admitter and the conduit are proved elsewhere. What this asserts is the
thing wiring tests exist for: that a real container, built the way every
deployment builds one, actually has the seam — and that the chat admitter and
the task admitter file work into the same Workspace, so a run_id means the same
thing whichever door the work came through.
"""

from __future__ import annotations

import pytest

from maistro.container import create_container
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.chat import CHAT_TURN_SOURCE, ChatRunAdmitter
from maistro.runs.model import RunStatus
from maistro.tasks.models import TaskCreate
from maistro.types.config import AgentConfig


async def _container():
    return await create_container(AgentConfig(router_api_key="test-key", workspace_id="tenant-x"))


@pytest.mark.scope("integration")
async def test_the_container_has_a_chat_admitter() -> None:
    container = await _container()

    assert isinstance(container.chat_admitter, ChatRunAdmitter)


@pytest.mark.scope("integration")
async def test_chat_and_task_admit_into_the_same_workspace() -> None:
    """Two admitters over one store. If they disagreed about the Workspace, a
    run_id would mean different things depending on which door it came through
    — the exact drift `runs/wiring.py` exists to prevent."""
    container = await _container()

    chat_run = await container.chat_admitter.admit_chat_turn(prompt="hello")
    task = await _submit_task(container)

    assert chat_run.workspace_id == "tenant-x"
    task_run = await container.run_store.get_run(task.run_id or "")
    assert task_run is not None
    assert task_run.workspace_id == chat_run.workspace_id
    assert task_run.project_id == chat_run.project_id


@pytest.mark.scope("integration")
async def test_a_chat_run_is_distinguishable_from_a_task_run() -> None:
    """Same store, same Project — so the only thing separating them is the
    provenance an audit reads."""
    container = await _container()

    run = await container.chat_admitter.admit_chat_turn(prompt="hello")

    stored = await container.run_store.get_run(run.run_id)
    assert stored is not None
    assert stored.provenance[ADMISSION_SOURCE] == CHAT_TURN_SOURCE
    assert stored.status is RunStatus.RUNNING


@pytest.mark.scope("integration")
async def test_chat_runs_are_bounded_by_default() -> None:
    """The acceptance criterion: chat-originated Runs carry an explicit bound
    without a deployment having to ask for one."""
    container = await _container()

    run = await container.chat_admitter.admit_chat_turn(prompt="hello")

    assert run.retention_expires_at is not None


@pytest.mark.scope("integration")
async def test_task_runs_keep_their_indefinite_retention() -> None:
    """The other half of the same claim: nothing outside chat changed."""
    container = await _container()

    task = await _submit_task(container)

    run = await container.run_store.get_run(task.run_id or "")
    assert run is not None
    assert run.retention_expires_at is None


async def _submit_task(container):
    """Through the real queue, so the task side is admitted the way it ships."""
    from maistro.tasks.queue import TaskQueue

    queue = TaskQueue(admitter=container.task_admitter)
    return await queue.submit(TaskCreate(description="ship it", task_type="code"))
