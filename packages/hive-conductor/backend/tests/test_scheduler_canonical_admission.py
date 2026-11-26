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
    workspace: bool = False,
) -> tuple[Any, Any, Any]:
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.store import InMemoryRunStore
    from maistro.scheduling.admission import ScheduleRunAdmitter
    from maistro.scheduling.store import InMemoryScheduleStore

    projects = InMemoryProjectScopeStore()
    workspace_store: Any = None
    if workspace:
        from maistro.workspaces.store import InMemoryWorkspaceStore

        # The canonical workspace provisions ws-1's Root Project itself, so
        # identity and membership come from the one authority the scheduler's
        # scope resolution consults.
        workspace_store = InMemoryWorkspaceStore(project_store=projects)
        await workspace_store.create(
            creator_user_id="ws-admin", name="Schedule WS", workspace_id="ws-1"
        )
        from maistro.workspaces.model import WorkspaceRole

        await workspace_store.set_membership(
            "ws-1", user_id="user-1", role=WorkspaceRole.CONTRIBUTOR
        )
    else:
        await projects.create_root("ws-1")
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
        schedule_admitter=ScheduleRunAdmitter(runs, templates, schedules),
        project_scope_store=projects,
        workspace_store=workspace_store,
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


def test_a_schedule_whose_actor_lost_workspace_membership_is_not_admitted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Revocation is explicit on the production automatic-fire path: a due
    definition re-read under the definition lock still re-runs the scope
    resolution, so an actor whose Workspace membership is gone loses
    eligibility even though the definition was persisted while they were a
    member. ``_tick_due`` is the only recurring path a configured Hive takes
    — this test drives it, not a side entry.
    """
    import logging

    from services.scheduler import _ScheduleRunner, put_canonical_definition

    async def scenario() -> None:
        container, row, _root = await _fixture(workspace=True)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        # The routes persist the canonical definition while the actor is
        # still a member; the tick then works from the store, not the row.
        await put_canonical_definition("s-1", row)
        runner = _ScheduleRunner()

        await runner._tick_due(
            datetime(2026, 8, 21, 12, 5, tzinfo=UTC), container, container.schedule_admitter
        )
        recorded = await container.schedule_store.get("s-1")
        assert recorded is not None
        assert recorded.runs_so_far == 1
        assert recorded.actor_principal_id == "user-1"
        assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]

        await container.workspace_store.remove_membership("ws-1", user_id="user-1")

        with caplog.at_level(logging.WARNING, logger="services.scheduler"):
            await runner._tick_due(
                datetime(2026, 8, 21, 13, 5, tzinfo=UTC),
                container,
                container.schedule_admitter,
            )
        assert "no longer a Workspace member" in caplog.text
        still = await container.schedule_store.get("s-1")
        assert still is not None
        assert still.runs_so_far == 1, "revocation stops future automatic fires"
        assert len(container.run_store._runs) == 1, (  # type: ignore[attr-defined]
            "the revoked actor's next occurrence never admits"
        )

    asyncio.run(scenario())


def test_revocation_serializes_with_an_in_flight_admission(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Codex P1-2: the eligibility check and Run admission are separated by
    several awaits, and membership removal holds no definition lock — so a
    removal that lands inside that window used to be followed by a Run
    admitted under the already-revoked principal. Admission now holds the
    same membership-mutation serialization point ``remove_member`` does: a
    concurrent removal either completes before the check (the tick refuses)
    or waits until the Run exists. This test pauses the tick inside
    admission and proves the removal cannot land there.
    """
    import logging

    from services import workspace_authority
    from services.scheduler import _ScheduleRunner, put_canonical_definition

    async def scenario() -> None:
        container, row, _root = await _fixture(workspace=True)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        # Production has one Container, so ``remove_member`` and the
        # scheduler read the same canonical store there; this fixture's
        # monkeypatched Container is a separate object, so point the
        # authority's no-database fallback at the very store the tick reads.
        monkeypatch.setattr(workspace_authority, "_fallback_store", container.workspace_store)
        # ``remove_member`` returns the composed Hive view, so the Workspace
        # needs its presentation record as every product Workspace has.
        from models.workspace import WorkspacePresentation

        workspace_authority.presentation_store()["ws-1"] = WorkspacePresentation(
            workspace_id="ws-1",
            persona_template_id="default",
            updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        await put_canonical_definition("s-1", row)
        runner = _ScheduleRunner()

        entered, release = asyncio.Event(), asyncio.Event()
        admit = container.schedule_admitter.admit_due

        async def paused(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return await admit(*args, **kwargs)

        monkeypatch.setattr(container.schedule_admitter, "admit_due", paused)
        tick = asyncio.create_task(
            runner._tick_due(
                datetime(2026, 8, 21, 12, 5, tzinfo=UTC),
                container,
                container.schedule_admitter,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        # The tick is now inside admission, holding the serialization point.
        removal = asyncio.create_task(workspace_authority.remove_member("ws-1", user_id="user-1"))
        # Event-loop turns, never wall clock: let the removal coroutine run
        # up to the lock and prove it stops there.
        for _ in range(10):
            await asyncio.sleep(0)
        assert not removal.done(), "a revocation must not complete inside an admission"
        release.set()
        await asyncio.gather(tick, removal)

        # The Run was admitted while the actor still held membership; the
        # removal completed only after admission, not inside its window.
        assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        assert not await workspace_authority.is_member("user-1", "ws-1")

        with caplog.at_level(logging.WARNING, logger="services.scheduler"):
            await runner._tick_due(
                datetime(2026, 8, 21, 13, 5, tzinfo=UTC),
                container,
                container.schedule_admitter,
            )
        assert "no longer a Workspace member" in caplog.text
        assert len(container.run_store._runs) == 1, (  # type: ignore[attr-defined]
            "the completed revocation admits no further Run"
        )

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
            assert recorded.workspace_id == "ws-1"
            assert recorded.project_id == root.project_id
            assert recorded.actor_principal_id == "user-1"

            run = await container.run_store.get_run(recorded.last_run_id)
            assert run is not None
            assert run.workspace_id == "ws-1"
            assert run.project_id == root.project_id
            assert run.provenance["admission_source"] == "schedule"
            assert run.provenance["schedule_id"] == "s-1"
            assert run.actor_principal_id == "user-1"
            assert run.provenance["scheduler_service_id"] == "hive-scheduler"
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
        # Composition now provisions the configured Workspace (#1152), so the
        # actor's membership is the piece this scenario owns: the row may
        # already exist with a different owner.
        if await container.workspace_store.get("ws-1") is None:
            await container.workspace_store.create(
                creator_user_id="user-1", name="Schedule WS", workspace_id="ws-1"
            )
        else:
            from maistro.workspaces.model import WorkspaceRole

            await container.workspace_store.set_membership(
                "ws-1", user_id="user-1", role=WorkspaceRole.CONTRIBUTOR
            )
        root = await container.project_scope_store.root_for_workspace("ws-1")
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
            from services.scheduler import backfill_canonical_definitions

            await backfill_canonical_definitions()
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
        async def execute_admitted_runs_accounting(self) -> int:
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
    from types import SimpleNamespace

    from services.scheduler import _ScheduleRunner

    def _quiet() -> SimpleNamespace:
        return SimpleNamespace(attempted=0, succeeded=0, failed=0, skipped=0)

    class _EmptyContainer:
        async def execute_admitted_runs_accounting(self) -> SimpleNamespace:
            return _quiet()

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


def test_foreign_workspace_template_is_reused_and_the_run_lands_in_the_schedules_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#290 (f283f41a): a template already registered under another Workspace
    is reused, not refused, and the admitted Run still lands in the
    schedule's Workspace.

    The store keys templates by ``(template_id, version)`` and refuses
    divergent content itself, so a bundled seed's entry is content-identical
    across Workspaces and its ``workspace_id`` is provenance, not authority.
    Refusing the reuse used to leave a schedule unable to ever compute a
    cursor (and thus ``next_run``) once the template had been primed under
    another Workspace — including stale state from a previous process. The
    other half of the contract lives in the admitter: it instantiates with
    ``schedule.workspace_id``, so the template's provenance never decides
    where the Run executes.
    """

    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        container, row, _root = await _fixture()
        # The store's entry was primed under a foreign Workspace first: a
        # bundled seed another Workspace's schedule put there, or stale state
        # from a previous process. Content is identical, so the store accepts
        # the re-registration (its conflict refusal keys on content, not
        # provenance).
        stored = await container.template_store.get("scheduled-template", version=1)
        assert stored is not None
        foreign = stored.model_copy(update={"workspace_id": "ws-other"})
        await container.template_store.put(foreign)

        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await _ScheduleRunner()._evaluate_schedule(
                "s-1", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
            )
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None and recorded.last_run_id
            runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
            assert len(runs) == 1
            # The Run's Workspace is the schedule's, never the template's
            # provenance.
            assert runs[0].workspace_id == "ws-1"
            assert runs[0].workspace_id != "ws-other"
            # Reuse, not rewrite: the store still holds the
            # foreign-provenance entry, unchanged.
            still = await container.template_store.get("scheduled-template", version=1)
            assert still is not None
            assert still.workspace_id == "ws-other"
            assert still.content_hash == foreign.content_hash
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


_DUE_NOW = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
_DUE_TEMPLATE = "scheduled-template"


def _freeze_scheduler_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the tick's clock so one hourly occurrence is due and the next is not."""
    import services.scheduler as sched_mod

    class _Clock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return _DUE_NOW

    monkeypatch.setattr(sched_mod, "datetime", _Clock)


async def _runs_in(store: Any) -> list[Any]:
    from maistro.runs.model import RunStatus

    found: list[Any] = []
    for status in (
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ):
        found.extend(await store.list_by_status(status, limit=20))
    return found


async def _wired_container(database_url: str = "") -> tuple[Any, Any]:
    from maistro.container import create_container
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.types.config import AgentConfig

    container = await create_container(
        AgentConfig(
            router_api_key="test-key",
            workspace_id="ws-1",
            database_url=database_url,
        )
    )
    # The fire paths re-check the actor's Workspace membership (#1201), so
    # the scenario provisions the membership the routes verify at create
    # time; the canonical Workspace provisions its own Root Project.
    # Idempotent: the restart scenarios build a second container over the
    # same database, and composition itself now provisions the configured
    # Workspace (#1152), so an already-present row gets the actor's
    # membership rather than a second create.
    if await container.workspace_store.get("ws-1") is None:
        await container.workspace_store.create(
            creator_user_id="user-1", name="Schedule WS", workspace_id="ws-1"
        )
    else:
        from maistro.workspaces.model import WorkspaceRole

        await container.workspace_store.set_membership(
            "ws-1", user_id="user-1", role=WorkspaceRole.CONTRIBUTOR
        )
    root = await container.project_scope_store.root_for_workspace("ws-1")
    await container.template_store.put(
        GraphTemplate(
            template_id=_DUE_TEMPLATE,
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
    return container, root


async def _put_hourly(
    container: Any,
    project_id: str,
    schedule_id: str,
    *,
    last_fired_at: datetime | None,
    next_due_at: datetime | None = None,
) -> None:
    from maistro.scheduling import Schedule

    await container.schedule_store.put(
        Schedule(
            schedule_id=schedule_id,
            workspace_id="ws-1",
            project_id=project_id,
            name=schedule_id,
            cron="0 * * * *",
            timezone="UTC",
            graph_template_id=_DUE_TEMPLATE,
            actor_principal_id="user-1",
            enabled=True,
            last_fired_at=last_fired_at,
            next_due_at=next_due_at,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )


def _use_container(monkeypatch: pytest.MonkeyPatch, container: Any) -> None:
    from services.scheduler import _ScheduleRunner

    monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: container))


def _refuse_registered_dag(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.dag_agents as dag_agents

    async def _must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a due schedule must not execute through run_registered_dag")

    monkeypatch.setattr(dag_agents, "run_registered_dag", _must_not_run)


def test_due_canonical_schedule_produces_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A due canonical schedule admits one Run and the consumer finishes it.

    The schedule row keeps the cursor (`last_run_id`, `runs_so_far`). It has
    no execution status — that lives on the Run, the same object a task admit
    writes. A second tick does not admit or execute that occurrence again.
    """
    from services.scheduler import _ScheduleRunner

    from maistro.runs.model import RunStatus

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        _refuse_registered_dag(monkeypatch)
        container, root = await _wired_container()
        _use_container(monkeypatch, container)
        await _put_hourly(
            container,
            root.project_id,
            "s-due",
            last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
        )
        try:
            await _ScheduleRunner()._tick()
            runs = await _runs_in(container.run_store)
            assert len(runs) == 1
            run = runs[0]
            assert run.status is RunStatus.COMPLETED
            assert run.provenance["admission_source"] == "schedule"
            assert run.provenance["schedule_id"] == "s-due"
            assert "task_id" not in run.provenance
            recorded = await container.schedule_store.get("s-due")
            assert recorded is not None
            assert recorded.last_run_id == run.run_id
            assert recorded.runs_so_far == 1
            assert not hasattr(recorded, "status")
            (node_run,) = await container.run_store.list_node_runs(run.run_id)
            (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
            assert node_run.status is RunStatus.COMPLETED
            assert attempt.status.value == "completed"

            await _ScheduleRunner()._tick()
            again = await _runs_in(container.run_store)
            assert [item.run_id for item in again] == [run.run_id]
            attempts = await container.run_store.list_attempts(node_run.node_run_id)
            assert len(attempts) == 1
        finally:
            await container.aclose()

    asyncio.run(scenario())


def test_hive_row_cannot_force_a_schedule_that_is_not_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the canonical row exists, an enabled Hive row is not due authority."""
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        container, root = await _wired_container()
        _use_container(monkeypatch, container)
        await _put_hourly(
            container,
            root.project_id,
            "s-later",
            last_fired_at=_DUE_NOW,
            next_due_at=_DUE_NOW + timedelta(hours=1),
        )
        row = _Row("s-later", _DUE_TEMPLATE, project_id=root.project_id)
        row.cron_expression = "0 * * * *"
        row.last_run = None
        row.enabled = True
        _install_row(row)
        calls: list[str] = []
        real = container.schedule_admitter

        class _Spy:
            async def admit_due(self, schedule: Any, *args: Any, **kwargs: Any) -> Any:
                calls.append(schedule.schedule_id)
                return await real.admit_due(schedule, *args, **kwargs)

        container.schedule_admitter = _Spy()
        try:
            await _ScheduleRunner()._tick()
            assert calls == []
            assert await _runs_in(container.run_store) == []
        finally:
            _remove_row(row)
            await container.aclose()

    asyncio.run(scenario())


def test_a_bad_hive_row_does_not_block_due_admission(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed legacy projection cannot participate in canonical due selection."""
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        container, root = await _wired_container()
        _use_container(monkeypatch, container)
        await _put_hourly(
            container,
            root.project_id,
            "s-due",
            last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
        )
        bad = _Row("s-bad-scope", _DUE_TEMPLATE, project_id="missing-project")
        _install_row(bad)
        try:
            with caplog.at_level("WARNING", logger="services.scheduler"):
                await _ScheduleRunner()._tick()
            assert await container.schedule_store.get("s-bad-scope") is None
            runs = await _runs_in(container.run_store)
            assert len(runs) == 1
            assert runs[0].provenance["schedule_id"] == "s-due"
        finally:
            _remove_row(bad)
            await container.aclose()

    asyncio.run(scenario())


def test_one_admission_failure_does_not_block_the_next_due_schedule(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        container, root = await _wired_container()
        _use_container(monkeypatch, container)
        last = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)
        await _put_hourly(container, root.project_id, "s-bad", last_fired_at=last)
        await _put_hourly(container, root.project_id, "s-ok", last_fired_at=last)
        real = container.schedule_admitter

        class _Boom:
            async def admit_due(self, schedule: Any, *args: Any, **kwargs: Any) -> Any:
                if schedule.schedule_id == "s-bad":
                    raise RuntimeError("synthetic admit failure")
                return await real.admit_due(schedule, *args, **kwargs)

        container.schedule_admitter = _Boom()
        try:
            with caplog.at_level("WARNING", logger="services.scheduler"):
                await _ScheduleRunner()._tick()
            assert "Failed to evaluate schedule s-bad" in caplog.text
            runs = await _runs_in(container.run_store)
            assert len(runs) == 1
            assert runs[0].provenance["schedule_id"] == "s-ok"
        finally:
            await container.aclose()

    asyncio.run(scenario())


def test_restart_executes_the_queued_run_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A process that dies after admission still executes that Run, once.

    The first process admits and records the cursor, then stops before the
    consumer runs. A new container on the same SQLite file is the restart:
    the schedule is no longer due, and the QUEUED Run is the fire. A further
    tick does not admit or execute it again.
    """
    from services.scheduler import _ScheduleRunner

    from maistro.runs.model import RunStatus

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        url = "sqlite:///" + (tmp_path / "restart.sqlite").as_posix()
        first, root = await _wired_container(url)
        _use_container(monkeypatch, first)

        async def _defer_consumer() -> Any:
            from maistro.runs.consumption import TickAccounting

            return TickAccounting(attempted=0, succeeded=0, failed=0, parked=0, skipped=0)

        first.execute_admitted_runs_accounting = _defer_consumer
        await _put_hourly(
            first,
            root.project_id,
            "s-restart",
            last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
        )
        try:
            await _ScheduleRunner()._tick()
            queued = await _runs_in(first.run_store)
            assert len(queued) == 1
            assert queued[0].status is RunStatus.QUEUED
            run_id = queued[0].run_id
            recorded = await first.schedule_store.get("s-restart")
            assert recorded is not None and recorded.last_run_id == run_id
        finally:
            await first.aclose()

        second, _root = await _wired_container(url)
        _use_container(monkeypatch, second)
        try:
            await _ScheduleRunner()._tick()
            runs = await _runs_in(second.run_store)
            assert [item.run_id for item in runs] == [run_id]
            assert runs[0].status is RunStatus.COMPLETED
            (node_run,) = await second.run_store.list_node_runs(run_id)
            attempts = await second.run_store.list_attempts(node_run.node_run_id)
            assert len(attempts) == 1
            assert attempts[0].status.value == "completed"

            await _ScheduleRunner()._tick()
            still = await _runs_in(second.run_store)
            assert [item.run_id for item in still] == [run_id]
            assert len(await second.run_store.list_attempts(node_run.node_run_id)) == 1
        finally:
            await second.aclose()

    asyncio.run(scenario())


def test_restart_after_a_cursor_crash_keeps_the_same_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A crash after the Run insert and before the cursor does not double-fire.

    The occurrence claim on the Run is the idempotent fire identity. The
    restarted tick reconciles to that Run instead of admitting another.
    """
    from services.scheduler import _ScheduleRunner

    from maistro.runs.model import RunStatus

    async def scenario() -> None:
        _freeze_scheduler_clock(monkeypatch)
        url = "sqlite:///" + (tmp_path / "crash.sqlite").as_posix()
        first, root = await _wired_container(url)
        _use_container(monkeypatch, first)
        await _put_hourly(
            first,
            root.project_id,
            "s-crash",
            last_fired_at=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
        )
        original = first.schedule_store.record_fire

        async def _die_before_cursor(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("run_id"):
                raise RuntimeError("died before the cursor")
            return await original(*args, **kwargs)

        first.schedule_store.record_fire = _die_before_cursor
        try:
            await _ScheduleRunner()._tick()
            created = await _runs_in(first.run_store)
            assert len(created) == 1
            run_id = created[0].run_id
            assert created[0].status is RunStatus.COMPLETED
        finally:
            await first.aclose()

        second, _root = await _wired_container(url)
        _use_container(monkeypatch, second)
        try:
            await _ScheduleRunner()._tick()
            runs = await _runs_in(second.run_store)
            assert [item.run_id for item in runs] == [run_id]
            assert runs[0].status is RunStatus.COMPLETED
            recorded = await second.schedule_store.get("s-crash")
            assert recorded is not None
            assert recorded.last_run_id == run_id
            (node_run,) = await second.run_store.list_node_runs(run_id)
            assert len(await second.run_store.list_attempts(node_run.node_run_id)) == 1
        finally:
            await second.aclose()

    asyncio.run(scenario())
