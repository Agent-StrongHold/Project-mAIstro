"""Edge-case coverage for canonical durable graph stores."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph.durable_runs.fair_scan import cursor_time
from maistro.graph.durable_runs.stores import (
    InMemoryDurableRunStore,
    SqliteDurableRunStore,
)
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun, RunStatus

from .._canonical_helpers import durable_record, hitl_authorization


def _record_for(run_id: str, **overrides: object):  # type: ignore[no-untyped-def]
    status = overrides.pop("status", RunStatus.RUNNING)
    project_id = overrides.pop("project_id", "test-project")
    active_node_id = overrides.pop("active_node_id", None)
    if overrides:
        raise AssertionError(f"unsupported test overrides: {sorted(overrides)}")
    nodes = [{"id": active_node_id, "kind": "test.noop"}] if active_node_id else [{"id": "n1"}]
    node_runs = ()
    if status is RunStatus.PAUSED and active_node_id:
        node_run = NodeRun(run_id=run_id, node_id=str(active_node_id), ordinal=1)
        node_run = transition_node_run(node_run, RunStatus.QUEUED)
        node_run = transition_node_run(node_run, RunStatus.RUNNING)
        node_run = transition_node_run(node_run, RunStatus.PAUSED)
        node_runs = (node_run,)
    return durable_record(
        {"id": "d1", "nodes": nodes, "edges": []},
        run_id=run_id,
        status=status,
        active_node_id=active_node_id,
        project_id=str(project_id),
        node_runs=node_runs,
    )


async def test_update_missing_run_raises_keyerror() -> None:
    store = InMemoryDurableRunStore()
    with pytest.raises(KeyError, match="no such run"):
        await store.update(_record_for("missing"))


async def test_list_by_status_respects_limit() -> None:
    store = InMemoryDurableRunStore()
    for i in range(5):
        await store.create(_record_for(f"r{i}"))
    out = await store.list_by_status(RunStatus.RUNNING, limit=2)
    assert len(out) == 2


async def test_list_by_status_filters_by_project_id() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_record_for("a", project_id="p1"))
    await store.create(_record_for("b", project_id="p2"))
    out = await store.list_by_status(RunStatus.RUNNING, project_id="p1")
    assert [record.run_id for record in out] == ["a"]


async def test_list_for_project_respects_limit_and_ordering() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_record_for("a", project_id="p1"))
    await store.create(_record_for("b", project_id="p1"))
    out = await store.list_for_project("p1", limit=1)
    assert len(out) == 1


async def test_submit_hitl_answer_missing_run_raises_keyerror() -> None:
    store = InMemoryDurableRunStore()
    with pytest.raises(KeyError, match="no such run"):
        await store.submit_hitl_answer(
            "missing", "n1", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_submit_hitl_answer_wrong_status_raises_valueerror() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_record_for("r1", status=RunStatus.RUNNING))
    with pytest.raises(ValueError, match="not paused on HITL"):
        await store.submit_hitl_answer(
            "r1", "n1", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_submit_hitl_answer_wrong_node_raises_valueerror() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_record_for("r1", status=RunStatus.PAUSED, active_node_id="ask"))
    with pytest.raises(ValueError, match="waiting on frontier"):
        await store.submit_hitl_answer(
            "r1", "wrong-node", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_sqlite_create_collision_raises_valueerror(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("r1"))
    with pytest.raises(ValueError, match="collision"):
        await store.create(_record_for("r1"))


async def test_sqlite_update_missing_run_raises_keyerror(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    with pytest.raises(KeyError, match="no such run"):
        await store.update(_record_for("missing"))


async def test_sqlite_get_missing_returns_none(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    assert await store.get("missing") is None


async def test_sqlite_list_by_status_filters_by_project_id(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("a", project_id="p1"))
    await store.create(_record_for("b", project_id="p2"))
    out = await store.list_by_status(RunStatus.RUNNING, project_id="p1")
    assert [record.run_id for record in out] == ["a"]


async def test_sqlite_list_by_status_respects_limit(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    for i in range(5):
        await store.create(_record_for(f"r{i}"))
    out = await store.list_by_status(RunStatus.RUNNING, limit=2)
    assert len(out) == 2


async def test_sqlite_list_for_project_filters_and_limits(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("a", project_id="p1"))
    await store.create(_record_for("b", project_id="p1"))
    await store.create(_record_for("c", project_id="p2"))
    out = await store.list_for_project("p1", limit=1)
    assert len(out) == 1
    assert out[0].project_id == "p1"


async def test_sqlite_submit_hitl_answer_missing_run_raises_keyerror(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    with pytest.raises(KeyError, match="no such run"):
        await store.submit_hitl_answer(
            "missing", "n1", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_sqlite_submit_hitl_answer_wrong_status_raises_valueerror(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("r1", status=RunStatus.RUNNING))
    with pytest.raises(ValueError, match="not paused on HITL"):
        await store.submit_hitl_answer(
            "r1", "n1", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_sqlite_submit_hitl_answer_wrong_node_raises_valueerror(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("r1", status=RunStatus.PAUSED, active_node_id="ask"))
    with pytest.raises(ValueError, match="waiting on frontier"):
        await store.submit_hitl_answer(
            "r1", "wrong-node", {"answer": "x"}, authorization=hitl_authorization()
        )


async def test_sqlite_submit_hitl_answer_success_updates_record(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    await store.create(_record_for("r1", status=RunStatus.PAUSED, active_node_id="ask"))
    updated = await store.submit_hitl_answer(
        "r1", "ask", {"answer": "yes"}, authorization=hitl_authorization()
    )
    assert updated.status is RunStatus.QUEUED
    assert updated.hitl_answers["ask"]["answer"] == "yes"
    assert updated.version == 2


def _at(record, created_at):  # type: ignore[no-untyped-def]
    """The same record, created at a chosen instant, so order is deterministic."""
    return record.model_copy(
        update={"run": record.run.model_copy(update={"created_at": created_at})}
    )


@pytest.mark.asyncio
async def test_in_memory_status_listing_pages_past_the_cursor() -> None:
    """`after` is the keyset the #1109 pending-work walk advances.

    Without it the route re-reads the same fixed prefix every page and the
    human pause behind it is never reached, so the parameter has to actually
    page rather than merely be accepted.
    """
    store = InMemoryDurableRunStore()
    base = datetime(2026, 9, 1, 12, tzinfo=UTC)
    for index in range(3):
        await store.create(
            _at(_record_for(f"mem-{index}"), base + timedelta(minutes=index)),
        )

    first = await store.list_by_status(RunStatus.RUNNING, limit=1)
    assert [record.run_id for record in first] == ["mem-0"]

    cursor = (cursor_time(first[0].run.created_at), first[0].run_id)
    rest = await store.list_by_status(RunStatus.RUNNING, limit=5, after=cursor)
    assert [record.run_id for record in rest] == ["mem-1", "mem-2"]

    last = (cursor_time(base + timedelta(minutes=2)), "mem-2")
    assert await store.list_by_status(RunStatus.RUNNING, limit=5, after=last) == []


@pytest.mark.asyncio
async def test_sqlite_status_listing_pages_past_the_cursor(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The SQLite twin builds the same keyset predicate in SQL.

    Its `(created_at, run_id) > (?, ?)` clause is a different implementation
    of the same contract, so it gets the same walk rather than being trusted
    to agree with the in-memory one.
    """
    store = SqliteDurableRunStore(tmp_path / "keyset.db")
    base = datetime(2026, 9, 1, 12, tzinfo=UTC)
    for index in range(3):
        await store.create(
            _at(_record_for(f"lite-{index}"), base + timedelta(minutes=index)),
        )

    first = await store.list_by_status(RunStatus.RUNNING, limit=1)
    assert [record.run_id for record in first] == ["lite-0"]

    cursor = (cursor_time(first[0].run.created_at), first[0].run_id)
    rest = await store.list_by_status(RunStatus.RUNNING, limit=5, after=cursor)
    assert [record.run_id for record in rest] == ["lite-1", "lite-2"]

    last = (cursor_time(base + timedelta(minutes=2)), "lite-2")
    assert await store.list_by_status(RunStatus.RUNNING, limit=5, after=last) == []
