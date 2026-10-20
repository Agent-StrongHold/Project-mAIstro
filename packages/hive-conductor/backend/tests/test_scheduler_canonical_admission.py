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
    projects: Any | None = None,
) -> tuple[Any, Any, Any]:
    """A configured-process Container stand-in, optionally over an existing scope.

    ``projects`` lets a "restarted" process share the Workspace's Project
    scope, which is durable in production rather than process-local truth.
    """
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.store import InMemoryRunStore
    from maistro.scheduling.store import InMemoryScheduleStore

    if projects is None:
        projects = InMemoryProjectScopeStore()
        root = await projects.create_root("ws-1")
    else:
        root = await projects.root_for_workspace("ws-1")
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


class _FrozenDatetime(datetime):
    """`datetime.now` under the test's control; everything else is real.

    The tick and `fire_now` read the clock through their module's `datetime`,
    so patching that one name drives both without touching the maistro core.
    """

    at: datetime = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls.at if tz is not None else cls.at.replace(tzinfo=None)


def test_tick_resumes_from_durable_sqlite_state_after_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """#1199: a restart resumes from the durable cursor, not the Hive dict.

    The legacy row comes back from its own persistence stale — no cursor at
    all — which is exactly the state a tick driven by `stores.schedules`
    would evaluate as due. The canonical SQLite store must be what decides.
    """
    import aiosqlite
    import services.scheduler as scheduler_mod
    from services.scheduler import _ScheduleRunner

    from maistro.scheduling import Schedule
    from maistro.scheduling.store import SqliteScheduleStore

    clock = _FrozenDatetime
    monkeypatch.setattr(scheduler_mod, "datetime", clock)
    db = tmp_path / "schedules.db"

    async def scenario() -> None:
        container, row, root = await _fixture()
        _install_row(row)
        conn = await aiosqlite.connect(db)
        durable = SqliteScheduleStore(conn)
        await durable.ensure_schema()
        await durable.put(
            Schedule(
                schedule_id="s-1",
                workspace_id=row.workspace_id,
                project_id=root.project_id,
                name=row.name,
                cron="0 * * * *",
                graph_template_id=row.mission_template_id,
                last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
                next_due_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                created_at=row.created_at,
            )
        )
        container.schedule_store = durable
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        conn2 = None
        try:
            await _ScheduleRunner()._tick()
            fired = await durable.get("s-1")
            assert fired is not None
            assert fired.runs_so_far == 1
            assert fired.last_run_id
            assert fired.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)

            # --- restart: the process, its run store and the projection die --
            await conn.close()
            restarted, stale, _root = await _fixture(projects=container.project_scope_store)
            # A stale product projection: enabled, but no cursor at all.
            stale.next_run = None
            stale.last_run = None
            stale.last_run_id = None
            _install_row(stale)
            conn2 = await aiosqlite.connect(db)
            durable2 = SqliteScheduleStore(conn2)
            await durable2.ensure_schema()
            restarted.schedule_store = durable2
            monkeypatch.setattr(
                _ScheduleRunner, "_canonical_container", staticmethod(lambda: restarted)
            )

            clock.at = datetime(2026, 8, 21, 12, 6, tzinfo=UTC)
            await _ScheduleRunner()._tick()
            resumed = await durable2.get("s-1")
            assert resumed is not None
            assert resumed.runs_so_far == 1, "the restart must not refire the 12:00 firing"
            assert resumed.last_fired_at == datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
            assert resumed.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
            assert len(restarted.run_store._runs) == 0  # type: ignore[attr-defined]

            clock.at = datetime(2026, 8, 21, 13, 5, tzinfo=UTC)
            await _ScheduleRunner()._tick()
            caught_up = await durable2.get("s-1")
            assert caught_up is not None
            assert caught_up.runs_so_far == 2
            assert len(restarted.run_store._runs) == 1  # type: ignore[attr-defined]
            run = await restarted.run_store.get_run(caught_up.last_run_id)
            assert run is not None
            assert run.provenance["schedule_id"] == "s-1"
            assert (
                run.provenance["scheduled_for"]
                == datetime(2026, 8, 21, 13, 0, tzinfo=UTC).isoformat()
            )
        finally:
            if conn2 is not None:
                await conn2.close()
            _remove_row(row)

    asyncio.run(scenario())


def test_manual_fire_and_tick_interleave_on_one_durable_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """#1199: a manual fire and a tick share one cursor and lose neither.

    The tick claims the owed occurrence; `fire_now` fires out of band onto the
    same SQLite cursor; the next tick must neither refire the tick's occurrence
    nor the manual one — every firing counted exactly once.
    """
    import aiosqlite
    import services.scheduler as scheduler_mod
    from services.dag_agents import get_registry
    from services.scheduler import _ScheduleRunner, fire_now

    from maistro.scheduling import Schedule
    from maistro.scheduling.store import SqliteScheduleStore

    clock = _FrozenDatetime
    monkeypatch.setattr(scheduler_mod, "datetime", clock)
    monkeypatch.setattr(scheduler_mod, "_runner", None)
    get_registry().register(
        {
            "id": "scheduled-template",
            "name": "scheduled-template",
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )

    async def scenario() -> None:
        container, row, root = await _fixture()
        _install_row(row)
        conn = await aiosqlite.connect(tmp_path / "schedules.db")
        durable = SqliteScheduleStore(conn)
        await durable.ensure_schema()
        await durable.put(
            Schedule(
                schedule_id="s-1",
                workspace_id=row.workspace_id,
                project_id=root.project_id,
                name=row.name,
                cron="0 * * * *",
                graph_template_id=row.mission_template_id,
                last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
                next_due_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                created_at=row.created_at,
            )
        )
        container.schedule_store = durable
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await _ScheduleRunner()._tick()
            after_tick = await durable.get("s-1")
            assert after_tick is not None
            assert after_tick.runs_so_far == 1
            assert after_tick.last_run_id
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]

            clock.at = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
            manual_run = await fire_now("s-1")
            assert manual_run
            assert manual_run != after_tick.last_run_id
            after_manual = await durable.get("s-1")
            assert after_manual is not None
            assert after_manual.runs_so_far == 2
            assert after_manual.last_run_id == manual_run
            assert after_manual.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)

            clock.at = datetime(2026, 8, 21, 12, 35, tzinfo=UTC)
            await _ScheduleRunner()._tick()
            after = await durable.get("s-1")
            assert after is not None
            assert after.runs_so_far == 2, "no firing is refired after the interleave"
            assert after.last_run_id == manual_run
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        finally:
            await conn.close()
            _remove_row(row)

    asyncio.run(scenario())
