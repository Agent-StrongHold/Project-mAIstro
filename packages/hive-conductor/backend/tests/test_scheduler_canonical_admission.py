"""End-to-end guards for the configured Hive scheduler -> ScheduleRunAdmitter seam."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime
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


def test_two_live_runners_claim_one_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            assert run.provenance["scheduled_for"] == datetime(
                2026, 8, 21, 12, 0, tzinfo=UTC
            ).isoformat()
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_persisted_template_survives_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_missing_template_keeps_occurrence_owed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_run_creation_failure_keeps_occurrence_owed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
