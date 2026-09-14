"""A manual fire is a first-class occurrence of the canonical spine (#1120).

The recurring loop has been on `ScheduleRunAdmitter` since #231. Manual fire
(`fire_now`, `POST /v1/schedules/{id}/run`) kept the legacy in-process path:
it fabricated the `hive:schedule:{sid}` execution scope, executed through the
process-local DAG registry, and stamped its occurrence identity with
`datetime.now()` — which minted a *fresh* identity for every retry of the same
logical request, so a double submit became two Runs and neither belonged to the
schedule's own occurrence ledger.

These tests hold the replacement to the same bar the recurring side is held
to: same admission authority, same durable occurrence claim, canonical
Workspace/Project/Run identity, template from the canonical GraphTemplate
store, and a receipt that survives a retry — with the one deliberate
difference that a manual fire never moves the recurring enumeration cursor.
"""

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


def _canonical_container(container: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: container))


def _forbid_legacy_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy path must not run in configured mode — make it loud."""
    import services.dag_agents as dag_agents

    def _legacy_must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run_registered_dag must not run for a manual fire")

    monkeypatch.setattr(dag_agents, "run_registered_dag", _legacy_must_not_run)


def test_a_manual_fire_admits_a_first_class_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same admission spine as a recurring tick: canonical scope, QUEUED Run,
    provenance that names the schedule — and names the trigger *manual*."""
    from services.scheduler import ScheduleNotFireable, fire_now

    from maistro.runs.model import RunStatus

    async def scenario() -> None:
        container, row, root = await _fixture()
        _install_row(row)
        _canonical_container(container, monkeypatch)
        _forbid_legacy_execution(monkeypatch)
        try:
            before = datetime.now(UTC)
            run_id = await fire_now("s-1", fire_id="retry-token-1")
            after = datetime.now(UTC)

            run = await container.run_store.get_run(run_id)
            assert run is not None
            # Canonical Workspace/Project, never the fabricated
            # `hive:schedule:{sid}` scope.
            assert run.workspace_id == "ws-1"
            assert run.project_id == root.project_id
            provenance = run.provenance
            assert provenance["admission_source"] == "schedule"
            assert provenance["schedule_id"] == "s-1"
            assert provenance["schedule_trigger"] == "manual"
            assert provenance["schedule_fire_id"] == "retry-token-1"
            # The instant is observability, not identity: it names when the
            # fire was asked for, and is a real instant — not a fabricated
            # cron time.
            requested = datetime.fromisoformat(provenance["scheduled_for"])
            assert before <= requested <= after
            # Admitted, in the same insert — the submission is the admission.
            assert run.status is RunStatus.QUEUED

            # The schedule's receipt: counted, named, but the recurring
            # cursor untouched — `last_fired_at` still carries whatever the
            # recurring enumeration last recorded (here the row's pre-fire
            # value), not this hand fire's instant.
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.last_run_id == run_id
            assert recorded.last_fired_at == row.last_run
            assert recorded.enabled is True

            # The legacy Hive row shows the receipt too (the projection
            # replaces the stored row, so read it back from the store).
            import stores

            projected = stores.schedules["s-1"]
            assert projected.last_run_id == run_id
            assert projected.last_run is not None
        except ScheduleNotFireable as exc:  # pragma: no cover - failure detail
            raise AssertionError(f"manual fire refused: {exc}") from exc
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_double_submit_reconciles_to_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two calls, one fire_id, one Run. The loser of the race resolves the
    winner's receipt from the durable claim — not from local memory — so this
    is also the restart story."""
    from services.scheduler import fire_now

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        _canonical_container(container, monkeypatch)
        _forbid_legacy_execution(monkeypatch)
        try:
            first, second = await asyncio.gather(
                fire_now("s-1", fire_id="same-token"),
                fire_now("s-1", fire_id="same-token"),
            )

            assert first == second
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.last_run_id == first
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_retry_after_completion_returns_the_same_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller that cannot know whether its first request landed retries with
    the same fire_id after the first Run already finished. The reconciliation
    must still name the original Run, and must not spend a second unit of
    `max_runs` on the retry."""
    from services.scheduler import fire_now

    from maistro.runs.model import RunStatus

    async def scenario() -> None:
        container, row, _root = await _fixture(max_runs=2)
        _install_row(row)
        _canonical_container(container, monkeypatch)
        try:
            first = await fire_now("s-1", fire_id="retry-token-1")
            run = await container.run_store.get_run(first)
            assert run is not None
            # Complete it through the legal lifecycle (QUEUED -> RUNNING ->
            # COMPLETED), as the canonical consumer would.
            await container.run_store.transition_run(first, RunStatus.RUNNING, at=datetime.now(UTC))
            await container.run_store.transition_run(
                first, RunStatus.COMPLETED, at=datetime.now(UTC)
            )

            second = await fire_now("s-1", fire_id="retry-token-1")

            assert second == first
            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_distinct_fire_ids_are_distinct_deliberate_firings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different tokens are two different hand fires — the identity is
    the caller's token, not dedupe-by-schedule. Each spends its own unit."""
    from services.scheduler import fire_now

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        _canonical_container(container, monkeypatch)
        try:
            first = await fire_now("s-1", fire_id="token-a")
            second = await fire_now("s-1", fire_id="token-b")

            assert first != second
            assert len(container.run_store._runs) == 2  # type: ignore[attr-defined]
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 2
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_manual_fire_never_moves_the_recurring_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cursor is the recurring enumeration's state. A hand fire that
    advanced `last_fired_at` would make the next tick resume enumeration after
    the hand fire, silently dropping nominal occurrences still owed inside the
    catch-up window."""
    from datetime import timedelta

    from services.scheduler import fire_now

    from maistro.scheduling.model import Schedule as CoreSchedule

    async def scenario() -> None:
        container, row, root = await _fixture()
        _install_row(row)
        _canonical_container(container, monkeypatch)
        last_fired = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        next_due = last_fired + timedelta(hours=1)
        await container.schedule_store.put(
            CoreSchedule(
                schedule_id="s-1",
                workspace_id="ws-1",
                project_id=root.project_id,
                name=row.name,
                cron="0 * * * *",
                graph_template_id="scheduled-template",
                runs_so_far=0,
                last_fired_at=last_fired,
                next_due_at=next_due,
            )
        )
        try:
            await fire_now("s-1", fire_id="retry-token-1")

            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_fired_at == last_fired
            assert recorded.next_due_at == next_due
            assert recorded.runs_so_far == 1
            assert recorded.enabled is True
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_persisted_template_survives_an_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Template resolution is the canonical GraphTemplate store. The
    process-local registry is only a migration source for a descriptor that
    has not been written there yet — a configured instance with the template
    already persisted needs no registry at all."""
    from services.scheduler import fire_now

    async def scenario() -> None:
        container, row, _root = await _fixture()
        _install_row(row)
        _canonical_container(container, monkeypatch)

        import services.dag_agents as dag_agents

        def _registry_must_not_be_read() -> None:
            raise AssertionError("registry must not be consulted")

        monkeypatch.setattr(dag_agents, "get_registry", _registry_must_not_be_read)
        try:
            run_id = await fire_now("s-1", fire_id="retry-token-1")
            assert await container.run_store.get_run(run_id) is not None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_failure_before_admission_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No template, no Run, no receipt, no cursor movement: a fire that cannot
    be admitted never existed, so there is nothing to reconcile later."""
    from services.scheduler import ScheduleNotFireable, fire_now

    async def scenario() -> None:
        container, row, _root = await _fixture(template=False)
        _install_row(row)
        _canonical_container(container, monkeypatch)
        before = row.last_run
        try:
            with pytest.raises(ScheduleNotFireable):
                await fire_now("s-1", fire_id="retry-token-1")

            assert len(container.run_store._runs) == 0  # type: ignore[attr-defined]
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 0
            assert recorded.last_run_id is None
            import stores

            assert stores.schedules["s-1"].last_run == before
            assert stores.schedules["s-1"].last_run_id is None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_exhaustion_is_enforced_on_the_canonical_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`max_runs` counts manual fires too: the last unit can be spent by hand,
    and the request after it is refused — with the schedule disabled, exactly
    as a recurring fire that hit the bound would disable it."""
    from services.scheduler import ScheduleNotFireable, fire_now

    async def scenario() -> None:
        container, row, _root = await _fixture(max_runs=1)
        _install_row(row)
        _canonical_container(container, monkeypatch)
        try:
            first = await fire_now("s-1", fire_id="token-a")
            assert await container.run_store.get_run(first) is not None

            with pytest.raises(ScheduleNotFireable):
                await fire_now("s-1", fire_id="token-b")

            assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.runs_so_far == 1
            assert recorded.enabled is False
            # The Hive row follows the disable.
            import stores

            projected = stores.schedules["s-1"]
            assert projected.enabled is False
            assert projected.next_run is None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_the_manual_fire_route_runs_the_canonical_spine_end_to_end(
    monkeypatch: pytest.MonkeyPatch, admin_client: Any
) -> None:
    """The real route, a real Container: double submit through `POST /run`
    with one `Idempotency-Key`, one canonical Run, consumed promptly through
    the same tick recurring admissions use — down to a NodeRun and an Attempt
    that actually executed."""
    from services.scheduler import _ScheduleRunner

    from maistro.container import AgentConfig, create_container
    from maistro.graph.definitions import GraphTemplate, Node

    async def scenario() -> None:
        container = await create_container(AgentConfig(router_api_key="test-key"))
        projects = container.project_scope_store
        root = await projects.create_root("ws-route")
        await container.template_store.put(
            GraphTemplate(
                template_id="route-template",
                workspace_id="ws-route",
                version=1,
                name="Route template",
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
        row = _Row("s-route", "route-template", project_id=root.project_id)
        row.workspace_id = "ws-route"
        row.name = "schedule-s-route"
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            headers = {"Idempotency-Key": "route-fire-1"}
            first = admin_client.post(f"/v1/schedules/{row.id}/run", headers=headers)
            second = admin_client.post(f"/v1/schedules/{row.id}/run", headers=headers)

            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text

            # One Run behind both responses, in canonical scope.
            runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
            assert len(runs) == 1
            (run,) = runs
            assert run.workspace_id == "ws-route"
            assert run.project_id == root.project_id
            assert run.provenance["schedule_trigger"] == "manual"
            assert run.provenance["schedule_fire_id"] == "route-fire-1"

            # Consumed promptly through the canonical tick: NodeRun + Attempt
            # with real physical evidence, run completed.
            from maistro.runs.model import RunStatus

            final = await container.run_store.get_run(run.run_id)
            assert final is not None
            assert final.status is RunStatus.COMPLETED
            (node_run,) = await container.run_store.list_node_runs(run.run_id)
            assert node_run.status is RunStatus.COMPLETED
            (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
            assert attempt.status.value == "completed"

            # Both responses carry the same receipt; the schedule counted one
            # fire, not two.
            assert first.json()["last_run_id"] == run.run_id
            assert second.json()["last_run_id"] == run.run_id
            recorded = await container.schedule_store.get(row.id)
            assert recorded is not None
            assert recorded.runs_so_far == 1
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_the_standalone_fallback_is_gated_to_no_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a core Container (standalone/demo), the historical immediate
    path still works — and the gate that selects it is the same
    `_canonical_admitter` predicate the recurring loop uses, so a configured
    instance can never land on it by a different rule than its ticks do."""
    import stores
    from services.scheduler import _ScheduleRunner, fire_now

    async def scenario() -> None:
        row = _Row("s-demo", "registered-dag", project_id="standalone")
        row.workspace_id = ""
        _install_row(row)

        executed: dict[str, Any] = {}

        async def _fake_fire_schedule(
            self: Any, sid: str, schedule: Any, **kwargs: Any
        ) -> str | None:
            executed["sid"] = sid
            return "legacy-run-1"

        monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _fake_fire_schedule)
        try:
            # No `_canonical_container` patch: the suite's stub agent port has
            # no container, so the gate must close and the fallback must run.
            assert _ScheduleRunner()._canonical_container() is None
            run_id = await fire_now("s-demo")

            assert run_id == "legacy-run-1"
            assert executed["sid"] == "s-demo"
            assert stores.schedules["s-demo"].last_run_id == "legacy-run-1"
        finally:
            _remove_row(row)

    asyncio.run(scenario())
