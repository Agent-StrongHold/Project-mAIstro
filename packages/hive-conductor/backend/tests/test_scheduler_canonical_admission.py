"""End-to-end guards for the configured Hive scheduler -> ScheduleRunAdmitter seam."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


class _Row:
    def __init__(
        self,
        sid: str,
        template_id: str,
        *,
        project_id: str,
        max_runs: int | None = None,
    ) -> None:
        self.id = sid
        self.user_id = "user-1"
        self.workspace_id = "ws-1"
        self.project_id = project_id
        self.name = f"schedule-{sid}"
        self.description = ""
        self.cron_expression = "0 * * * *"
        self.mission_template_id = template_id
        self.enabled = True
        self.timezone = "UTC"
        self.max_runs = max_runs
        self.last_run = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)
        self.last_run_id: str | None = None
        self.next_run: datetime | None = None
        self.created_at = datetime(2026, 8, 1, tzinfo=UTC)
        self.updated_at = self.created_at

    def model_copy(self, *, update: dict[str, Any]) -> _Row:
        clone = _Row(
            self.id,
            self.mission_template_id,
            project_id=self.project_id,
            max_runs=self.max_runs,
        )
        clone.__dict__.update(self.__dict__)
        clone.__dict__.update(update)
        return clone


async def _fixture(
    *,
    template: bool = True,
    max_runs: int | None = None,
) -> tuple[Any, Any, Any]:
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.store import InMemoryRunStore
    from maistro.scheduling.store import InMemoryScheduleStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    runs = InMemoryRunStore(project_store=projects)
    templates = InMemoryGraphTemplateStore()
    schedules = InMemoryScheduleStore()
    if template:
        await templates.put(
            GraphTemplate(
                template_id="scheduled-template",
                workspace_id="ws-1",
                version=1,
                name="Scheduled template",
                nodes=[
                    Node(
                        node_id="only",
                        node_type="transform.alias_keys",
                        parameters={"mapping": {}},
                    )
                ],
                edges=[],
                metadata={"entry_node": "only"},
            )
        )
    container = SimpleNamespace(
        run_store=runs,
        template_store=templates,
        schedule_store=schedules,
        project_scope_store=projects,
    )
    row = _Row(
        "s-1",
        "scheduled-template",
        project_id=root.project_id,
        max_runs=max_runs,
    )
    return container, row, root


def _install_row(row: Any) -> None:
    import stores

    stores.schedules._data[row.id] = row  # type: ignore[attr-defined]


def _remove_row(row: Any) -> None:
    import stores

    stores.schedules._data.pop(row.id, None)  # type: ignore[attr-defined]


def test_tick_uses_canonical_due_state_not_the_legacy_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale Hive row cannot make a future canonical schedule fire."""
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        future = datetime(2099, 8, 21, 13, 0, tzinfo=UTC)
        from maistro.scheduling import Schedule

        await container.schedule_store.put(
            Schedule(
                schedule_id=row.id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                name=row.name,
                cron=row.cron_expression,
                graph_template_id=row.mission_template_id,
                last_fired_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                next_due_at=future,
                created_at=row.created_at,
            )
        )
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        evaluated: list[str] = []

        async def capture(self: Any, definition: Any, **kwargs: Any) -> None:
            evaluated.append(definition.schedule_id)

        monkeypatch.setattr(_ScheduleRunner, "_evaluate_canonical_definition", capture)
        try:
            await _ScheduleRunner()._tick()
            assert evaluated == []
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_tick_admits_a_canonical_due_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        now = datetime.now(UTC)
        from maistro.scheduling import Schedule

        await container.schedule_store.put(
            Schedule(
                schedule_id=row.id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                name=row.name,
                cron="* * * * *",
                graph_template_id=row.mission_template_id,
                last_fired_at=now - timedelta(minutes=1),
                next_due_at=now - timedelta(seconds=1),
                created_at=now - timedelta(days=1),
            )
        )
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await _ScheduleRunner()._tick()
            recorded = await container.schedule_store.get(row.id)
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.last_run_id
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_two_live_runners_claim_one_occurrence(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, root = await _fixture()
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
        try:
            await asyncio.gather(
                _ScheduleRunner()._evaluate_schedule("s-1", row, now=now),
                _ScheduleRunner()._evaluate_schedule("s-1", row, now=now),
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.last_run_id

            run = await container.run_store.get_run(recorded.last_run_id)
            assert run is not None
            assert run.workspace_id == "ws-1"
            assert run.project_id == root.project_id
            assert run.provenance["admission_source"] == "schedule"
            assert run.provenance["schedule_id"] == "s-1"
            assert (
                run.provenance["scheduled_for"]
                == datetime(2026, 8, 21, 12, 0, tzinfo=UTC).isoformat()
            )
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_persisted_template_survives_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )

        import services.dag_agents as dag_agents

        def _registry_must_not_be_read() -> None:
            raise AssertionError("registry must not be consulted")

        monkeypatch.setattr(dag_agents, "get_registry", _registry_must_not_be_read)
        try:
            await _ScheduleRunner()._evaluate_schedule(
                "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None and recorded.last_run_id
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_missing_template_keeps_occurrence_owed(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture(template=False)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        before = row.last_run
        try:
            await _ScheduleRunner()._evaluate_schedule(
                "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_fired_at == before
            assert recorded.last_run_id is None
            assert len(container.run_store._runs) == 0  # type: ignore[attr-defined]
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_run_creation_failure_keeps_occurrence_owed(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        before = row.last_run

        async def _fail_create_run(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic create failure")

        monkeypatch.setattr(container.run_store, "create_run", _fail_create_run)
        try:
            await _ScheduleRunner()._evaluate_schedule(
                "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_fired_at == before
            assert recorded.last_run_id is None
            assert recorded.runs_so_far == 0
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_max_runs_disables_canonical_and_product_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        import stores

        container, row, _root = await _fixture(max_runs=1)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await _ScheduleRunner()._evaluate_schedule(
                "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.enabled is False
            projected = stores.schedules._data["s-1"]  # type: ignore[attr-defined]
            assert projected.enabled is False
            assert projected.last_run_id == recorded.last_run_id
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def _frozen_clock(start: datetime) -> tuple[type, dict[str, datetime]]:
    """A ``datetime`` stand-in whose ``now()`` the test controls.

    Restart evidence has to be deterministic: a wall-clock tick that happens
    to cross an occurrence boundary between the two ticks below would fire a
    second occurrence for reasons that have nothing to do with the restart.
    """
    holder = {"now": start}

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            moment = holder["now"]
            return moment if tz is not None else moment.replace(tzinfo=None)

    return _Frozen, holder


def test_a_process_restart_resumes_from_durable_canonical_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """AC: a restarted process resumes from the store, not the Hive dict.

    Two independent object graphs over one SQLite file stand in for two
    processes. The first connection closes after its tick -- process death --
    and the second is rebuilt from nothing but the file: fresh stores, fresh
    template registry, and the legacy ``stores.schedules`` dict empty, which
    is exactly what a new process starts with. Nothing may fire on the first
    post-restart tick (the cursor is in the future), and once the clock
    reaches the next occurrence exactly one more run fires, with the cursor
    carried across the boundary by the durable state alone.
    """
    import aiosqlite

    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.runs.model import RunStatus
    from maistro.runs.sqlite_store import SqliteRunStore
    from maistro.scheduling import Schedule
    from maistro.scheduling.store import SqliteScheduleStore

    path = tmp_path / "durable-schedules.db"
    t0 = datetime(2026, 8, 21, 12, 0, 30, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 13, 0, 30, tzinfo=UTC)

    async def container_for(conn: aiosqlite.Connection) -> Any:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        schedules = SqliteScheduleStore(conn)
        await schedules.ensure_schema()
        templates = InMemoryGraphTemplateStore()
        await templates.put(
            GraphTemplate(
                template_id="scheduled-template",
                workspace_id="ws-1",
                version=1,
                name="Scheduled template",
                nodes=[
                    Node(
                        node_id="only",
                        node_type="transform.alias_keys",
                        parameters={"mapping": {}},
                    )
                ],
                edges=[],
                metadata={"entry_node": "only"},
            )
        )
        return SimpleNamespace(
            run_store=runs,
            template_store=templates,
            schedule_store=schedules,
            project_scope_store=projects,
        )

    async def scenario() -> None:
        import services.scheduler as scheduler_module
        from services.scheduler import _ScheduleRunner

        frozen, clock = _frozen_clock(t0)
        monkeypatch.setattr(scheduler_module, "datetime", frozen)

        # --- process one: build durable state, tick once, die ---
        conn = await aiosqlite.connect(path)
        first = await container_for(conn)
        root = await first.project_scope_store.create_root("ws-1")
        await first.schedule_store.put(
            Schedule(
                schedule_id="s-restart",
                workspace_id="ws-1",
                project_id=root.project_id,
                name="restart",
                cron="0 * * * *",
                graph_template_id="scheduled-template",
                last_fired_at=datetime(2026, 8, 21, 11, 30, tzinfo=UTC),
                next_due_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        )
        monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: first))
        await _ScheduleRunner()._tick()
        fired = await first.schedule_store.get("s-restart")
        assert fired is not None
        assert fired.runs_so_far == 1
        assert fired.last_run_id
        first_run_id = fired.last_run_id
        # The executor ran the occurrence to completion before the process
        # died: QUEUED -> RUNNING -> COMPLETED, the earned-success path.
        await first.run_store.transition_run(first_run_id, RunStatus.RUNNING)
        await first.run_store.transition_run(first_run_id, RunStatus.COMPLETED, result={"ok": True})
        await conn.close()

        # --- process two: rebuilt from the file alone ---
        import stores

        assert "s-restart" not in stores.schedules._data  # type: ignore[attr-defined]

        conn2 = await aiosqlite.connect(path)
        restarted = await container_for(conn2)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: restarted)
        )
        await _ScheduleRunner()._tick()  # cursor is at 13:00: nothing may fire
        resumed = await restarted.schedule_store.get("s-restart")
        assert resumed is not None
        assert resumed.runs_so_far == 1, "the restart must not re-fire the occurrence"
        assert resumed.last_run_id == first_run_id
        assert resumed.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
        assert await restarted.run_store.get_run(first_run_id) is not None

        # The clock reaches the next occurrence; the durable cursor alone
        # makes it due -- the legacy dict still knows nothing about it.
        clock["now"] = t1
        await _ScheduleRunner()._tick()
        again = await restarted.schedule_store.get("s-restart")
        assert again is not None
        assert again.runs_so_far == 2
        assert again.last_run_id is not None
        assert again.last_run_id != first_run_id
        assert await restarted.run_store.get_run(again.last_run_id) is not None
        assert "s-restart" not in stores.schedules._data  # type: ignore[attr-defined]
        await conn2.close()

    asyncio.run(scenario())
