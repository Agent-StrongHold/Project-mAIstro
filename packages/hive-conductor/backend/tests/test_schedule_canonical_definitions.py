"""`/v1/schedules` writes the canonical Schedule definition first (#1199).

In a configured process the canonical ``ScheduleStore`` is the authority for
what is due; the Hive row is a projection written after it.  Before this, the
create/update/delete routes wrote only the Hive dictionary, so a disabled or
deleted schedule left an enabled canonical row that ``due()`` would return.

Each scenario runs against the in-memory store and a SQLite store on a tmp
file, behind a real ``create_container`` Container swapped into the engine.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_TPL = "canonical-definition-template"
_FAR_FUTURE = datetime(2999, 1, 1, tzinfo=UTC)


async def _bind_workspace() -> str:
    from services import workspace_authority

    workspace = await workspace_authority.create_workspace(
        creator_user_id="user-1",
        name="Canonical definitions",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    await workspace_authority.set_member(workspace.id, user_id="admin", role="editor")
    return str(workspace.id)


async def _sqlite_store(path: pathlib.Path) -> Any:
    import aiosqlite

    from maistro.scheduling.store import SqliteScheduleStore

    conn = await aiosqlite.connect(path)
    store = SqliteScheduleStore(conn)
    await store.ensure_schema()
    return store


@pytest.fixture(params=["memory", "sqlite"])
def configured(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> Iterator[Any]:
    """A real Container behind the engine, with the parametrised ScheduleStore."""
    import services.engine as engine_mod

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = asyncio.run(create_container(AgentConfig(router_api_key="test-key")))
    sqlite = None
    if request.param == "sqlite":
        sqlite = asyncio.run(_sqlite_store(tmp_path / "schedules.db"))
        container.schedule_store = sqlite
    service = engine_mod.get_engine()
    previous = service._agent_port
    service._agent_port = SimpleNamespace(container=container)
    try:
        container.test_workspace = asyncio.run(_bind_workspace())
        yield container
    finally:
        service._agent_port = previous
        if sqlite is not None:
            asyncio.run(sqlite._conn.close())


def _create(client: Any, workspace_id: str, **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "nightly",
        "cron_expression": "0 3 * * *",
        "mission_template_id": _TPL,
        "workspace_id": workspace_id,
        **overrides,
    }
    response = client.post("/v1/schedules", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _drop_hive_row(sid: str) -> None:
    import stores

    stores.schedules._data.pop(sid, None)


def _due_ids(container: Any) -> set[str]:
    due = asyncio.run(container.schedule_store.due(now=_FAR_FUTURE))
    return {schedule.schedule_id for schedule in due}


def test_create_writes_a_canonical_row_scoped_to_the_root_project(
    admin_client: Any, configured: Any
) -> None:
    created = _create(admin_client, configured.test_workspace)
    sid = created["id"]
    try:
        stored = asyncio.run(configured.schedule_store.get(sid))
        root = asyncio.run(
            configured.project_scope_store.root_for_workspace(created["workspace_id"])
        )
        assert stored is not None
        assert stored.workspace_id == configured.test_workspace
        assert stored.project_id == root.project_id == created["project_id"]
        assert stored.graph_template_id == _TPL
        assert stored.cron == "0 3 * * *"
        assert stored.enabled is True
        assert stored.actor_principal_id == "admin"
        assert sid in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_disable_reaches_the_canonical_row_and_leaves_due(
    admin_client: Any, configured: Any
) -> None:
    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        response = admin_client.put(f"/v1/schedules/{sid}", json={"enabled": False})
        assert response.status_code == 200, response.text
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None
        assert stored.enabled is False
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_recurrence_change_clears_next_due_and_keeps_run_history(
    admin_client: Any, configured: Any
) -> None:
    sid = _create(admin_client, configured.test_workspace)["id"]
    store = configured.schedule_store
    fired_at = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
    try:
        asyncio.run(
            store.record_fire(
                sid,
                fired_at=fired_at,
                run_id="run-1",
                next_due_at=fired_at + timedelta(days=1),
            )
        )
        response = admin_client.put(f"/v1/schedules/{sid}", json={"cron_expression": "30 4 * * *"})
        assert response.status_code == 200, response.text
        stored = asyncio.run(store.get(sid))
        assert stored is not None
        assert stored.cron == "30 4 * * *"
        assert stored.next_due_at is None
        assert stored.runs_so_far == 1
        assert stored.last_run_id == "run-1"
    finally:
        _drop_hive_row(sid)


def test_delete_removes_the_canonical_row(admin_client: Any, configured: Any) -> None:
    import stores

    sid = _create(admin_client, configured.test_workspace)["id"]
    response = admin_client.delete(f"/v1/schedules/{sid}")
    assert response.status_code == 204, response.text
    assert stores.schedules.get(sid) is None
    assert asyncio.run(configured.schedule_store.get(sid)) is None
    assert sid not in _due_ids(configured)


def test_an_unreadable_cron_is_refused_before_any_row_exists(
    admin_client: Any, configured: Any
) -> None:
    import stores

    before = set(stores.schedules.keys())
    response = admin_client.post(
        "/v1/schedules",
        json={
            "name": "broken",
            "cron_expression": "not a cron",
            "mission_template_id": _TPL,
            "workspace_id": configured.test_workspace,
        },
    )
    assert response.status_code == 422, response.text
    assert set(stores.schedules.keys()) == before


def test_a_container_without_a_schedule_store_is_a_503_that_writes_nothing(
    admin_client: Any, configured: Any
) -> None:
    import stores

    configured.schedule_store = None
    before = set(stores.schedules.keys())
    response = admin_client.post(
        "/v1/schedules",
        json={
            "name": "unwired",
            "cron_expression": "0 3 * * *",
            "mission_template_id": _TPL,
            "workspace_id": configured.test_workspace,
        },
    )
    assert response.status_code == 503, response.text
    assert set(stores.schedules.keys()) == before


def _legacy_row(workspace_id: str, project_id: str, *, enabled: bool = True) -> Any:
    from models.schemas import Schedule

    now = datetime.now(UTC)
    return Schedule(
        id="s-legacy-backfill",
        user_id="user-1",
        workspace_id=workspace_id,
        project_id=project_id,
        name="legacy",
        description="",
        cron_expression="0 3 * * *",
        mission_template_id=_TPL,
        enabled=enabled,
        timezone="UTC",
        max_runs=None,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=now,
        updated_at=now,
    )


def test_backfill_puts_a_missing_row_once_and_never_rewinds_its_cursor(
    configured: Any,
) -> None:
    import stores
    from services.scheduler import backfill_canonical_definitions

    store = configured.schedule_store
    workspace_id = configured.test_workspace
    root = asyncio.run(configured.project_scope_store.root_for_workspace(workspace_id))
    row = _legacy_row(workspace_id, root.project_id, enabled=False)
    stores.schedules._data[row.id] = row
    fired_at = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
    try:
        assert asyncio.run(backfill_canonical_definitions()) >= 1
        stored = asyncio.run(store.get(row.id))
        assert stored is not None
        assert stored.enabled is False, "a disabled legacy row stays disabled"
        assert stored.project_id == root.project_id

        asyncio.run(
            store.record_fire(
                row.id,
                fired_at=fired_at,
                run_id="run-1",
                next_due_at=fired_at + timedelta(days=1),
            )
        )
        stores.schedules._data[row.id] = row.model_copy(
            update={"name": "renamed in the projection only"}
        )
        assert asyncio.run(backfill_canonical_definitions()) == 0
        again = asyncio.run(store.get(row.id))
        assert again is not None
        assert again.runs_so_far == 1
        assert again.last_run_id == "run-1"
        assert again.next_due_at == fired_at + timedelta(days=1)
        assert again.name == "legacy", "an existing canonical row is never re-put"
    finally:
        _drop_hive_row(row.id)


def test_backfill_is_a_noop_without_a_container() -> None:
    from services.scheduler import backfill_canonical_definitions

    assert asyncio.run(backfill_canonical_definitions()) == 0


def test_the_runner_backfills_once_before_its_first_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.scheduler as scheduler

    calls: list[str] = []

    async def backfill() -> int:
        calls.append("backfill")
        return 0

    runner = scheduler._ScheduleRunner()

    async def tick() -> None:
        calls.append("tick")
        runner.stop()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(scheduler, "backfill_canonical_definitions", backfill)
    monkeypatch.setattr(runner, "_tick", tick)
    monkeypatch.setattr(runner, "_self_repair_tick", tick)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    asyncio.run(runner.run())
    assert calls[:2] == ["backfill", "tick"]
    assert calls.count("backfill") == 1


def test_clearing_the_template_removes_the_canonical_row(
    admin_client: Any, configured: Any
) -> None:
    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        response = admin_client.put(f"/v1/schedules/{sid}", json={"mission_template_id": ""})
        assert response.status_code == 200, response.text
        assert asyncio.run(configured.schedule_store.get(sid)) is None
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_an_update_racing_a_delete_does_not_resurrect_the_canonical_row(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.scheduler as scheduler

    sid = _create(admin_client, configured.test_workspace)["id"]
    original = scheduler.put_canonical_definition

    async def put_then_lose_the_row(schedule_id: str, schedule: Any) -> None:
        await original(schedule_id, schedule)
        _drop_hive_row(schedule_id)

    monkeypatch.setattr(scheduler, "put_canonical_definition", put_then_lose_the_row)
    response = admin_client.put(f"/v1/schedules/{sid}", json={"name": "renamed"})
    assert response.status_code == 404, response.text
    assert asyncio.run(configured.schedule_store.get(sid)) is None


def test_delete_with_an_unwired_container_is_a_503_that_keeps_the_row(
    admin_client: Any, configured: Any
) -> None:
    import stores

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        configured.schedule_store = None
        response = admin_client.delete(f"/v1/schedules/{sid}")
        assert response.status_code == 503, response.text
        assert stores.schedules.get(sid) is not None
    finally:
        _drop_hive_row(sid)
