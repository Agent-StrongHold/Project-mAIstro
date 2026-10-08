"""The live scheduler tick exercises the bounded catch-up contract (#1200).

`test_enumeration_limits.py` pins the pure engine bounds; this file proves
them through the real seam: `_ScheduleRunner._tick()` reading canonical due state after startup backfill,
admitting through `ScheduleRunAdmitter`, and reporting what a bound cost.
The host-selected limits are passed exactly the way a host would — the same
admitter seam the container wires, with `EnumerationLimits` supplied.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_NOW = datetime.now(UTC).replace(second=0, microsecond=0)


class _Row:
    """A `/v1/schedules` row, shaped the way `stores.schedules` holds them."""

    def __init__(self, sid: str, template_id: str) -> None:
        self.id = sid
        self.user_id = "user-1"
        self.workspace_id = "ws-1"
        self.project_id = "proj-1"
        self.name = f"schedule-{sid}"
        self.description = ""
        self.cron_expression = "* * * * *"
        self.mission_template_id = "scheduled-template"
        self.enabled = True
        self.timezone = "UTC"
        self.max_runs = None
        self.catchup_window_seconds = 3_600.0
        self.last_run: datetime | None = None
        self.last_run_id: str | None = None
        self.next_run: datetime | None = None
        self.created_at = _NOW - timedelta(days=30)
        self.updated_at = self.created_at

    def model_copy(self, *, update: dict[str, Any]) -> _Row:
        clone = _Row(self.id, self.mission_template_id)
        clone.__dict__.update(self.__dict__)
        clone.__dict__.update(update)
        return clone


async def _fixture() -> tuple[Any, _Row]:
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
    schedules = InMemoryScheduleStore()
    container = SimpleNamespace(
        run_store=runs,
        template_store=templates,
        schedule_store=schedules,
        schedule_admitter=ScheduleRunAdmitter(runs, templates, schedules),
        project_scope_store=projects,
        test_workspace=root.workspace_id,
    )
    row = _Row("s-1", "scheduled-template")
    row.project_id = root.project_id
    return container, row


_set_aside: dict[Any, Any] = {}


def _install_row(row: _Row) -> None:
    """Install the scenario row, and set aside `stores`' demo seed row: the
    tick iterates every row, and the seed names no real Workspace here."""
    import stores

    data = stores.schedules._data  # type: ignore[attr-defined]
    if "sch-1" in data:
        _set_aside["sch-1"] = data.pop("sch-1")
    data[row.id] = row


def _remove_row(row: _Row) -> None:
    """Remove the scenario row and put the seed row back: it lives in the
    process-wide in-memory store, and a later suite in the same process (the
    #1201 scope suite) asserts it is still there."""
    import stores

    data = stores.schedules._data  # type: ignore[attr-defined]
    data.pop(row.id, None)
    data.update(_set_aside)
    _set_aside.clear()


def _admitter(container: Any, **limits: Any) -> Any:
    from maistro.scheduling.admission import ScheduleRunAdmitter
    from maistro.scheduling.engine import EnumerationLimits

    return ScheduleRunAdmitter(
        container.run_store,
        container.template_store,
        container.schedule_store,
        enumeration_limits=EnumerationLimits(**limits),
    )


def test_a_walk_cut_short_by_its_budget_is_reported_and_reamined(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A zero budget stops the walk before examining anything: the tick must
    say so, run nothing, leave the cursor alone — and the next tick under the
    host's ordinary limits must re-examine the same occurrence and fire it."""
    from services.scheduler import _ScheduleRunner, backfill_canonical_definitions

    async def scenario() -> None:
        container, row = await _fixture()
        row.last_run = _NOW - timedelta(minutes=2)
        _install_row(row)
        container.schedule_admitter = _admitter(container, walk_budget_seconds=0.0)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await backfill_canonical_definitions()
            with caplog.at_level("WARNING", logger="services.scheduler"):
                await _ScheduleRunner()._tick()
            assert "catch-up walk stopped" in caplog.text
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_run_id is None

            # The host's ordinary limits: the owed occurrence is re-examined.
            container.schedule_admitter = _admitter(container)
            caplog.clear()
            await _ScheduleRunner()._tick()
            assert "catch-up walk stopped" not in caplog.text
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_run_id is not None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_window_the_host_clamps_is_reported_at_the_tick(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A row filed with a seven-day window under a host that allows one hour
    fires normally, and the tick says the configured window was not the one
    applied — operator visibility for the clamped backlog (#1200)."""
    from services.scheduler import _ScheduleRunner, backfill_canonical_definitions

    async def scenario() -> None:
        container, row = await _fixture()
        row.catchup_window_seconds = 604_800.0
        row.last_run = _NOW - timedelta(minutes=2)
        _install_row(row)
        container.schedule_admitter = _admitter(
            container, max_window_seconds=3_600.0, walk_budget_seconds=3600.0
        )
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await backfill_canonical_definitions()
            with caplog.at_level("INFO", logger="services.scheduler"):
                await _ScheduleRunner()._tick()
            assert "capped at the host bound" in caplog.text
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            assert recorded.last_run_id is not None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_zero_window_is_honored_not_replaced_by_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`catchup_window_seconds=0` is a legal product value meaning "never
    backfill" (the routes admit it), so the tick's canonical projection must
    carry the zero through: the two occurrences since ``last_run`` are older
    than the now-relative horizon and are skipped, not fired — an ``or``
    fallback would read the falsy zero as "missing" and backfill an hour the
    client refused (#1200)."""
    from services.scheduler import _ScheduleRunner, backfill_canonical_definitions

    async def scenario() -> None:
        container, row = await _fixture()
        row.catchup_window_seconds = 0.0
        row.last_run = _NOW - timedelta(minutes=2)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await backfill_canonical_definitions()
            await _ScheduleRunner()._tick()
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            # The projection carried the zero: the canonical definition and
            # the row agree, and nothing was backfilled behind the client's
            # back.
            assert recorded.catchup_window_seconds == 0.0
            assert recorded.runs_so_far == 0
            assert recorded.last_run_id is None
        finally:
            _remove_row(row)

    asyncio.run(scenario())


def test_a_stale_backlog_tick_stays_within_bounded_wall_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit's failure mode, end to end: a per-minute schedule left stale
    for days must not stall the tick's event loop. Under the substrate's
    default limits the whole tick — evaluate, admit, record — returns in a
    bounded slice of time, whatever the backlog size."""
    from services.scheduler import _ScheduleRunner, backfill_canonical_definitions

    async def scenario() -> None:
        container, row = await _fixture()
        row.last_run = _NOW - timedelta(days=7)
        _install_row(row)
        monkeypatch.setattr(
            _ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
        )
        try:
            await backfill_canonical_definitions()
            start = time.monotonic()
            await _ScheduleRunner()._tick()
            elapsed = time.monotonic() - start
            assert elapsed < 2.0, f"tick took {elapsed:.2f}s for a seven-day backlog"
            recorded = await container.schedule_store.get("s-1")
            assert recorded is not None
            # The walk is capped at the newest 512 occurrences per evaluation
            # and TRUNCATED keeps the cursor, so the tick consumed only what
            # it examined and the rest stays owed, truthfully.
            assert recorded.runs_so_far <= 512
        finally:
            _remove_row(row)

    asyncio.run(scenario())
