"""The shipped Turing composition shares a budget without sharing authority."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE
from maistro.runs.store import RunIntegrityError

from ..execution import TuringExecutionPlane

pytestmark = [pytest.mark.contract("behavioral")]


def _plane() -> TuringExecutionPlane:
    from ..main import app

    return TuringExecutionPlane(inbound_security=app.state.turing_security, max_retained=2)


class _ReplySession:
    async def handle_message(self, message: str) -> str:
        return f"reply:{message}"


async def _turn(plane: TuringExecutionPlane, user: str) -> Any:
    return await plane.run_chat(
        session=_ReplySession(),  # type: ignore[arg-type]
        user_id=user,
        session_id=f"session-{user}",
        message="hello",
    )


async def _queued(plane: TuringExecutionPlane, user: str, source: str = CHAT_SOURCE) -> Any:
    workspace_id, project_id = await plane._scope_for(user)
    return await plane.run_store.create_run(
        Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="retention fixture",
            nodes=[Node(node_id="turn", node_type="test", name="turn")],
        ),
        actor_principal_id=user,
        initial_status=RunStatus.QUEUED,
        provenance={ADMISSION_SOURCE: source},
    )


def test_users_share_one_oldest_first_window():
    async def scenario() -> None:
        plane = _plane()
        records = [await _turn(plane, f"user-{index}") for index in range(5)]
        assert len(plane._admitters) == 5
        assert plane.retained == 2
        assert [
            record.run_id
            for record in records
            if await plane.run_store.get_run(record.run_id) is not None
        ] == [record.run_id for record in records[-2:]]
        assert await plane._continuations.get(records[-1].run_id) is not None
        for workspace_id, admitter in plane._admitters.items():
            assert admitter.sweeper.scope.workspace_id == workspace_id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind", ["pending", "queued", "leased", "unleased", "stalled", "expired", "finished"]
)
def test_shared_window_preserves_canonical_liveness_shields(kind):
    async def scenario() -> None:
        plane = _plane()
        older = await _queued(plane, "older-user")
        admitter = plane._admitter_for(older.workspace_id)
        if kind == "pending":
            admitter.mark_dispatch_pending(older.run_id)
        await admitter.track(older.run_id)
        if kind != "queued":
            await plane.run_store.transition_run(older.run_id, RunStatus.RUNNING)
        if kind in {"leased", "unleased", "expired", "finished"}:
            node = await plane.run_store.create_node_run(older.run_id, node_id="turn")
            lease_args = (
                {}
                if kind in {"unleased", "finished"}
                else {
                    "lease_holder": "retention-test",
                    "lease_ttl": timedelta(hours=1)
                    if kind == "leased"
                    else timedelta(microseconds=1),
                }
            )
            attempt = await plane.run_store.create_attempt(node.node_run_id, **lease_args)
            if kind == "finished":
                await plane.run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
                await plane.run_store.transition_attempt(
                    attempt.attempt_id, AttemptStatus.COMPLETED
                )
        middle = await _turn(plane, "middle-user")
        newest = await _turn(plane, "newest-user")
        shielded = kind in {"pending", "queued", "leased", "unleased"}
        assert (await plane.run_store.get_run(older.run_id) is not None) is shielded
        assert (await plane.run_store.get_run(middle.run_id) is not None) is not shielded
        assert await plane.run_store.get_run(newest.run_id) is not None
        assert plane.retained == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["foreign", "task", "missing"])
def test_tracking_refuses_foreign_nonchat_or_missing_runs(kind):
    async def scenario() -> None:
        plane = _plane()
        workspace_id, _ = await plane._scope_for("owner")
        run = await _queued(
            plane,
            "other" if kind == "foreign" else "owner",
            "task_queue" if kind == "task" else CHAT_SOURCE,
        )
        with pytest.raises(
            RunIntegrityError if kind == "missing" else ValueError,
            match={"foreign": "outside", "task": "only chat", "missing": "missing"}[kind],
        ):
            await plane._track_admission(
                "missing" if kind == "missing" else run.run_id, workspace_id=workspace_id
            )
        assert plane.retained == 0
        assert await plane.run_store.get_run(run.run_id) is not None

    asyncio.run(scenario())
