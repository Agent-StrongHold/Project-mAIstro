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
    from maistro.scheduling.admission import ScheduleRunAdmitter
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
        schedule_admitter=ScheduleRunAdmitter(runs, templates, schedules),
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


def test_the_tick_reports_a_live_run_the_cursor_did_not_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A crashed winner (#1059) surfaces at the seam as an admission that
    names the live Run the cursor never recorded: the tick says so, and the
    pointer links that winner without this tick creating a second Run."""
    import logging

    from services.scheduler import _ScheduleRunner

    from maistro.scheduling import FireDecision

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
        noon = datetime(2026, 8, 21, 12, tzinfo=UTC)
        # Ticker A died between `create_run` and `record_fire`: the Run for
        # noon exists and holds the occurrence claim, but the cursor was
        # never stamped, so the pointer names nothing.
        runner = _ScheduleRunner()
        scope = await runner._canonical_scope(row, container)
        definition = await runner._definition_for(
            "s-1", row, store=container.schedule_store, scope=scope
        )
        assert definition is not None
        template = await container.template_store.get(
            definition.graph_template_id, version=definition.template_version
        )
        assert template is not None
        winner = await container.schedule_admitter._admit_one(
            definition, template, FireDecision(scheduled_for=noon)
        )
        stored = await container.schedule_store.get("s-1")
        assert stored is not None and stored.last_run_id is None
        try:
            with caplog.at_level(logging.INFO, logger="services.scheduler"):
                await _ScheduleRunner()._evaluate_schedule("s-1", row, now=now)
            live = [
                record
                for record in caplog.records
                if "the cursor did not name" in record.getMessage()
            ]
            assert live, "the tick must report the live Run the pointer missed"
            assert winner in live[0].getMessage()
            assert "cancel requested: False" in live[0].getMessage()
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_run_id == winner, "the cursor follows the crashed winner"
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_scheduler_tick_executes_the_admitted_run_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured scheduler closes admission through canonical execution."""
    from services.scheduler import _ScheduleRunner

    from maistro.container import create_container
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.runs.model import RunStatus
    from maistro.types.config import AgentConfig

    async def scenario() -> None:
        container = await create_container(
            AgentConfig(router_api_key="test-key", workspace_id="ws-1")
        )
        root = await container.project_scope_store.create_root("ws-1")
        await container.template_store.put(
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
        row = _Row("s-1", "scheduled-template", project_id=root.project_id)
        row.cron_expression = "* * * * *"
        row.last_run = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await _ScheduleRunner()._tick()
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None and recorded.last_run_id
            run = await container.run_store.get_run(recorded.last_run_id)
            assert run is not None and run.status is RunStatus.COMPLETED
            (node_run,) = await container.run_store.list_node_runs(run.run_id)
            (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
            assert node_run.status is RunStatus.COMPLETED
            assert attempt.status.value == "completed"
        finally:
            _remove_row(row)
            await container.aclose()

    asyncio.run(scenario())


def test_scheduler_tick_logs_consumer_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A consumer failure is contained and reported by the scheduler tick."""
    from services.scheduler import _ScheduleRunner

    class _FailingContainer:
        async def execute_admitted_runs(self) -> int:
            raise RuntimeError("consumer unavailable")

    async def scenario() -> None:
        monkeypatch.setattr(
            _ScheduleRunner,
            "_canonical_container",
            staticmethod(lambda: _FailingContainer()),
        )
        with caplog.at_level("WARNING", logger="services.scheduler"):
            await _ScheduleRunner()._tick()

    asyncio.run(scenario())
    assert "Failed to consume admitted canonical Runs: consumer unavailable" in caplog.text


def test_scheduler_tick_skips_missing_or_empty_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone ticks and empty consumer queues remain successful no-ops."""
    from services.scheduler import _ScheduleRunner

    class _EmptyContainer:
        async def execute_admitted_runs(self) -> int:
            return 0

    async def scenario() -> None:
        monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: None))
        await _ScheduleRunner()._tick()
        monkeypatch.setattr(
            _ScheduleRunner,
            "_canonical_container",
            staticmethod(lambda: _EmptyContainer()),
        )
        await _ScheduleRunner()._tick()

    asyncio.run(scenario())


def test_scheduler_tick_fails_closed_when_container_lacks_consumer_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured Container without ``execute_admitted_runs`` fails closed.

    The tick used to swallow the missing-method failure behind the same
    ``except Exception`` that contains a failing consumer, so a container
    missing the seam admitted Runs nothing ever executed while the tick kept
    reporting healthy. Missing wiring is a configuration failure
    (``ScheduleAdmissionUnavailable``), not a consumer error to log.
    """
    import asyncio

    from services.scheduler import ScheduleAdmissionUnavailable, _ScheduleRunner

    class _SeamlessContainer:
        """Wired for admission, but with no canonical consumer seam."""

    monkeypatch.setattr(
        _ScheduleRunner, "_canonical_container", staticmethod(lambda: _SeamlessContainer())
    )

    async def scenario() -> None:
        await _ScheduleRunner()._tick()

    with pytest.raises(ScheduleAdmissionUnavailable, match="execute_admitted_runs"):
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


def test_half_wired_container_fails_closed_for_recurring_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured Container must never make a tick use the compatibility path."""
    from services.scheduler import ScheduleAdmissionUnavailable, _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        container.schedule_admitter = None
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )

        async def _compatibility_path(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("configured recurring fire reached compatibility execution")

        monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _compatibility_path)
        try:
            with pytest.raises(ScheduleAdmissionUnavailable):
                await _ScheduleRunner()._evaluate_schedule(
                    "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
                )
            assert len(container.run_store._runs) == 0  # type: ignore[attr-defined]
            assert row.last_run_id is None
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
