"""Durable approval identity and decisions survive independent connections.

Lives in persistence/ so the real PostgreSQL coverage producer runs these
cases. The service-free producer still exercises real file-backed SQLite.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    ApprovalStore,
    DurableApproval,
    PgApprovalStore,
    SqliteApprovalStore,
)
from maistro.capabilities.slots.approval import ApprovalRequest

from .pg_capability_fixture import isolated_capability_pools

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]


@pytest_asyncio.fixture(params=["sqlite", "postgres-text", "postgres-production"])
async def stores(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[tuple[ApprovalStore, ApprovalStore]]:
    if request.param == "sqlite":
        database = tmp_path / "approvals.sqlite"
        async with aiosqlite.connect(database) as first, aiosqlite.connect(database) as second:
            writer, reader = SqliteApprovalStore(first), SqliteApprovalStore(second)
            await writer.ensure_schema()
            await reader.ensure_schema()
            yield writer, reader
    else:
        async with isolated_capability_pools(
            production_codecs=request.param == "postgres-production"
        ) as (first, second):
            writer, reader = PgApprovalStore(first), PgApprovalStore(second)
            await writer.ensure_schema()
            await reader.ensure_schema()
            yield writer, reader


def _approval(request_id: str = "request-a", **changes: object) -> DurableApproval:
    values: dict[str, object] = {
        "request": ApprovalRequest(
            request_id=request_id,
            action="invoke:external_write",
            params={"request": {"value": 1}},
            tier="policy",
            requester="node-a",
        ),
        "workspace_id": "workspace-a",
        "project_id": "project-a",
        "run_id": "run-a",
        "node_run_id": "node-a",
        "attempt_id": "attempt-a",
        "binding_id": "binding-a",
        "effect_key": "write-a",
    }
    values.update(changes)
    return DurableApproval.model_validate(values)


async def test_create_is_visible_to_an_independent_connection(
    stores: tuple[ApprovalStore, ApprovalStore],
) -> None:
    writer, reader = stores
    approval = _approval()
    assert await writer.create(approval) == approval
    assert await reader.get(approval.request.request_id) == approval
    assert (
        await reader.find_effect(
            run_id="run-a", node_run_id="node-a", binding_id="binding-a", effect_key="write-a"
        )
        == approval
    )
    assert await reader.get("missing") is None
    assert (
        await reader.find_effect(
            run_id="other-run", node_run_id="node-a", binding_id="binding-a", effect_key="write-a"
        )
        is None
    )


async def test_competing_creates_keep_one_effect_winner(
    stores: tuple[ApprovalStore, ApprovalStore],
) -> None:
    first, second = stores
    left, right = await asyncio.gather(
        first.create(_approval("left")), second.create(_approval("right", attempt_id="attempt-b"))
    )
    assert left.request.request_id == right.request.request_id
    assert left.effect_identity == right.effect_identity
    assert await second.get(left.request.request_id) == left
    loser = "right" if left.request.request_id == "left" else "left"
    assert await first.get(loser) is None


@pytest.mark.parametrize("approved", [True, False])
async def test_decision_is_durable_and_cannot_be_reversed(
    stores: tuple[ApprovalStore, ApprovalStore], approved: bool
) -> None:
    first, second = stores
    approval = await first.create(_approval())
    resolved = await second.resolve(
        approval.request.request_id, approved=approved, actor="reviewer-a"
    )
    assert resolved.status is (ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED)
    assert resolved.actor == "reviewer-a"
    assert resolved.resolved_at is not None
    assert await first.get(approval.request.request_id) == resolved
    replay = await first.resolve(
        approval.request.request_id, approved=not approved, actor="reviewer-b"
    )
    assert replay == resolved
    assert await second.get(approval.request.request_id) == resolved


async def test_resolution_refuses_missing_request_and_empty_actor(
    stores: tuple[ApprovalStore, ApprovalStore],
) -> None:
    first, second = stores
    with pytest.raises(KeyError, match="does not exist"):
        await first.resolve("missing", approved=True, actor="reviewer")
    approval = await first.create(_approval())
    with pytest.raises(ValueError, match="actor"):
        await second.resolve(approval.request.request_id, approved=True, actor=" ")
    persisted = await first.get(approval.request.request_id)
    assert persisted is not None and persisted.status is ApprovalStatus.PENDING
    assert persisted.actor == "" and persisted.resolved_at is None
