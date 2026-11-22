"""Startup reconciliation converges the Hive schedule projection on canonical
truth (#2467).

The `/v1/schedules` routes write the canonical ``ScheduleStore`` definition
first and the Hive row second, into a separate store with no shared commit.
A crash between the halves used to be "repaired" at every runner startup by
re-deriving a definition from the Hive row and putting it canonically
whenever it was missing or drifted — the projection overruling the
authority: an acknowledged canonical edit reverted, a deleted schedule
recreated, an interrupted create left an enabled orphan only ``due()`` could
see. These tests hold the replacement policy to the issue's acceptance:

- a restart that finds the projection behind a committed canonical edit
  repairs the projection, never the definition (enabled flips, and
  separately name and recurrence/template edits);
- a canonically deleted schedule stays deleted, whatever Hive record
  survives, tombstoned or not;
- an interrupted create resolves to one visible identity, or closes as
  never-committed — no invisible orphan, no duplicate;
- legacy import happens exactly once, bounded by the durable migration
  marker;
- recorded cursors, Run ids, and due state survive reconciliation, and
  repeated and concurrent reconciliations are idempotent;
- the regression guard: a post-marker startup must not run the import pass
  for a previously canonicalized id, and the fire path must defer to
  canonical truth rather than the stale row.

Each scenario runs against the in-memory store and a SQLite store on a tmp
file, behind a real ``create_container`` Container swapped into the engine —
the same harness ``test_schedule_canonical_definitions.py`` uses. The SQLite
leg re-opens the store on the same file across the simulated restart, so the
canonical row under test is the persisted one, not an in-memory survivor.
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

from maistro.identity import Principal

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_TPL = "projection-authority-template"
_FAR_FUTURE = datetime(2999, 1, 1, tzinfo=UTC)


async def _bind_workspace() -> str:
    from services import workspace_authority

    workspace = await workspace_authority.create_workspace(
        creator_user_id="user-1",
        name="Projection authority",
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
    if request.param == "sqlite":
        container.schedule_store = asyncio.run(_sqlite_store(tmp_path / "schedules.db"))
        container.sqlite_path = tmp_path / "schedules.db"
    else:
        container.sqlite_path = None
    service = engine_mod.get_engine()
    previous = service._agent_port
    service._agent_port = SimpleNamespace(container=container)
    try:
        container.test_workspace = asyncio.run(_bind_workspace())
        yield container
    finally:
        service._agent_port = previous
        store = getattr(container, "schedule_store", None)
        conn = getattr(store, "_conn", None)
        if conn is not None:
            asyncio.run(conn.close())


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


def _restart_canonical_store(configured: Any) -> None:
    """Re-open the canonical store the way a fresh process would.

    The SQLite leg re-connects to the same file, so the rows the "restarted"
    reconciliation sees are the persisted ones. The in-memory leg has nothing
    to re-open — its policy behavior is identical; persistence is not what
    that leg is for.
    """
    if getattr(configured, "sqlite_path", None) is None:
        return
    configured.schedule_store = asyncio.run(_sqlite_store(configured.sqlite_path))


def _reconcile(configured: Any) -> int:
    from services.schedule_projection import run_startup_reconciliation

    return asyncio.run(run_startup_reconciliation())


def _reconcile_coro() -> Any:
    """The reconciliation coroutine, for concurrent startups on one loop."""
    from services.schedule_projection import run_startup_reconciliation

    return run_startup_reconciliation()


def _put_canonical_half(sid: str, row: Any, **updates: Any) -> None:
    """Commit exactly what ``update_schedule`` commits before its crash.

    The route's canonical half is ``put_canonical_definition`` on the updated
    row; the crash removes everything after it, leaving the Hive row stale.
    """
    from services.scheduler import put_canonical_definition

    asyncio.run(put_canonical_definition(sid, row.model_copy(update=dict(updates))))


def _request_as_admin() -> Any:
    return SimpleNamespace(state=SimpleNamespace(principal=Principal(user_id="admin")))


def _legacy_row(sid: str, workspace_id: str, project_id: str, **overrides: Any) -> Any:
    from models.schemas import Schedule

    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "id": sid,
        "user_id": "user-1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "name": "legacy",
        "description": "",
        "cron_expression": "0 3 * * *",
        "mission_template_id": _TPL,
        "enabled": True,
        "timezone": "UTC",
        "max_runs": None,
        "last_run": None,
        "last_run_id": None,
        "next_run": None,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return Schedule(**fields)


def test_a_restart_keeps_a_canonical_disable_the_crash_interrupted(
    admin_client: Any, configured: Any
) -> None:
    """AC: crash after the canonical ``enabled: false`` commit, before the Hive
    row moved — the fresh reconciliation repairs the projection, never the
    definition."""
    import stores
    from services.schedule_projection import ledger

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0
        assert ledger().migrated(), "the first completed pass bounds legacy import"
        _restart_canonical_store(configured)
        hive = stores.schedules.get(sid)
        assert hive is not None
        _put_canonical_half(sid, hive, enabled=False)
        # The Hive row still says enabled: this is the crash window.
        assert stores.schedules.get(sid).enabled is True

        assert _reconcile(configured) >= 1
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None and stored.enabled is False, (
            "the acknowledged canonical disable survives the restart"
        )
        repaired = stores.schedules.get(sid)
        assert repaired is not None and repaired.enabled is False, (
            "the projection is repaired from canonical, not the reverse"
        )
        assert sid not in _due_ids(configured)
        assert admin_client.get(f"/v1/schedules/{sid}").json()["enabled"] is False
    finally:
        _drop_hive_row(sid)


def test_a_restart_keeps_canonical_name_and_recurrence_edits(
    admin_client: Any, configured: Any
) -> None:
    """AC: the same holds for a rename and, separately, a recurrence edit —
    and a recurrence change clears the due cursor exactly as the substrate's
    ``put`` contract requires, while the fired-Run cursor survives."""
    import stores

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0
        fired_at = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
        next_due = fired_at + timedelta(days=1)
        asyncio.run(
            configured.schedule_store.record_fire(
                sid, fired_at=fired_at, run_id="run-1", next_due_at=next_due
            )
        )
        _restart_canonical_store(configured)
        hive = stores.schedules.get(sid)
        assert hive is not None

        # A rename the crash interrupted: due cursor untouched.
        _put_canonical_half(sid, hive, name="renamed")
        assert _reconcile(configured) >= 1
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None
        assert stored.name == "renamed"
        assert (stored.runs_so_far, stored.last_run_id, stored.next_due_at) == (
            1,
            "run-1",
            next_due,
        ), "the recorded cursor survives the projection repair"
        repaired = stores.schedules.get(sid)
        assert repaired is not None and repaired.name == "renamed"
        assert repaired.next_run == next_due

        # A recurrence edit the crash interrupted: the due cursor is the
        # substrate's to clear (a new rule invalidates the recorded due
        # moment); the fired-Run cursor still survives.
        hive = stores.schedules.get(sid)
        assert hive is not None
        _put_canonical_half(sid, hive, cron_expression="30 4 * * *", timezone="Europe/Paris")
        assert _reconcile(configured) >= 1
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None
        assert (stored.cron, stored.timezone) == ("30 4 * * *", "Europe/Paris")
        assert stored.next_due_at is None, "a changed recurrence clears the due cursor"
        assert (stored.runs_so_far, stored.last_run_id) == (1, "run-1")
        repaired = stores.schedules.get(sid)
        assert repaired is not None
        assert (repaired.cron_expression, repaired.timezone, repaired.next_run) == (
            "30 4 * * *",
            "Europe/Paris",
            None,
        )
    finally:
        _drop_hive_row(sid)


def test_a_deleted_schedule_stays_deleted_across_a_restart(
    admin_client: Any, configured: Any
) -> None:
    """AC: crash after the canonical delete — a surviving Hive record under the
    deletion tombstone is dropped, never recreated or executed."""
    import stores
    from services.schedule_projection import ledger

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0
        # What a crash before the projection cleanup would leave behind.
        surviving = stores.schedules.get(sid)
        assert surviving is not None
        response = admin_client.delete(f"/v1/schedules/{sid}")
        assert response.status_code == 204, response.text
        assert ledger().is_tombstoned(sid), "the delete route records a durable tombstone"
        assert asyncio.run(configured.schedule_store.get(sid)) is None

        # The restarted process finds the stale record under the tombstone.
        _restart_canonical_store(configured)
        stores.schedules._data[sid] = surviving
        _reconcile(configured)
        assert asyncio.run(configured.schedule_store.get(sid)) is None
        assert stores.schedules.get(sid) is None, "the stale record is dropped, not reimported"
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_a_stale_row_without_a_tombstone_is_never_reimported(
    admin_client: Any, configured: Any
) -> None:
    """AC: post-marker, canonical absence is authority even with no tombstone —
    the row is reported degraded, never reimported, never fired."""
    import stores
    from services.schedule_projection import ledger, projection_health

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0
        assert ledger().migrated()
        # A canonical deletion whose tombstone write itself crashed (or a
        # direct canonical-side deletion): the Hive row survives, no tombstone.
        from services.scheduler import delete_canonical_definition

        asyncio.run(delete_canonical_definition(sid))
        assert stores.schedules.get(sid) is not None

        _restart_canonical_store(configured)
        _reconcile(configured)
        assert asyncio.run(configured.schedule_store.get(sid)) is None, (
            "a migrated schedule is not reimported from its Hive record"
        )
        assert stores.schedules.get(sid) is not None, "the row stays, honestly degraded"
        assert sid in projection_health()["degraded"], "the degraded row is surfaced (#290)"
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_an_interrupted_create_resolves_to_one_visible_identity(
    configured: Any,
) -> None:
    """AC: crash inside the create route's two-write window — the committed
    canonical half is projected at restart, one identity, no orphan, and the
    pending marker closes."""
    import stores
    from services.schedule_projection import ledger, mark_pending_create
    from services.scheduler import put_canonical_definition

    assert _reconcile(configured) >= 0
    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-interrupted-create"
    row = _legacy_row(sid, configured.test_workspace, root.project_id)

    assert mark_pending_create(sid), "the create route opens its marker before the canonical put"
    asyncio.run(put_canonical_definition(sid, row))
    try:
        _restart_canonical_store(configured)
        assert _reconcile(configured) >= 1

        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None and stored.enabled is True
        projected = stores.schedules.get(sid)
        assert projected is not None, "the schedule is visible, not an invisible orphan"
        assert projected.id == sid, "one identity: the projection reuses the canonical sid"
        assert projected.name == "legacy" and projected.enabled is True
        listed = asyncio.run(
            configured.schedule_store.list_for_project(
                workspace_id=configured.test_workspace, project_id=root.project_id
            )
        )
        assert [schedule.schedule_id for schedule in listed] == [sid], "no duplicate identity"
        assert not ledger().pending_creates(), "the marker closes once resolved"
    finally:
        _drop_hive_row(sid)


def test_a_pending_marker_without_a_canonical_row_closes_with_nothing_to_project(
    configured: Any,
) -> None:
    """AC: the other half of the create window — the crash landed before the
    canonical put, so the restart closes the create without projecting."""
    import stores
    from services.schedule_projection import ledger, mark_pending_create

    assert _reconcile(configured) >= 0
    sid = "s-never-committed"
    assert mark_pending_create(sid)
    _reconcile(configured)
    assert stores.schedules.get(sid) is None
    assert asyncio.run(configured.schedule_store.get(sid)) is None
    assert not ledger().pending_creates()


def test_legacy_import_happens_exactly_once(configured: Any) -> None:
    """AC: a genuinely never-imported legacy row imports once when the marker
    authorizes it; after the marker it is never reimported."""
    import stores
    from services.schedule_projection import ledger

    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-legacy-once"
    stores.schedules._data[sid] = _legacy_row(
        sid, configured.test_workspace, root.project_id, enabled=False
    )
    try:
        assert _reconcile(configured) >= 1
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None and stored.enabled is False
        assert ledger().migrated(), "the completed pass writes the durable marker"

        from services.scheduler import delete_canonical_definition

        asyncio.run(delete_canonical_definition(sid))
        _restart_canonical_store(configured)
        _reconcile(configured)
        assert asyncio.run(configured.schedule_store.get(sid)) is None, (
            "a previously migrated schedule cannot be reimported"
        )
    finally:
        _drop_hive_row(sid)


def test_cursors_survive_and_repeated_concurrent_reconciliations_are_idempotent(
    configured: Any,
) -> None:
    """AC: fired Run ids, counts, and the due index survive reconciliation;
    repeated and concurrent startups change nothing and rewind nothing."""
    import stores

    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-idempotent"
    stores.schedules._data[sid] = _legacy_row(
        sid, configured.test_workspace, root.project_id, enabled=False
    )
    try:
        assert _reconcile(configured) >= 1
        fired_at = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
        next_due = fired_at + timedelta(days=2)
        asyncio.run(
            configured.schedule_store.record_fire(
                sid, fired_at=fired_at, run_id="run-9", next_due_at=next_due
            )
        )
        # The projection catches up to the cursor the store recorded.
        assert _reconcile(configured) >= 0
        before = asyncio.run(configured.schedule_store.get(sid))
        assert before is not None
        projected = stores.schedules.get(sid)
        assert projected is not None
        assert (projected.last_run_id, projected.next_run) == ("run-9", next_due)

        assert _reconcile(configured) == 0, "an agreeing projection changes nothing"
        assert _reconcile(configured) == 0

        async def two_replicas_start() -> list[int]:
            return await asyncio.gather(_reconcile_coro(), _reconcile_coro())

        # Two replicas starting at once: both reconcile, neither rewrites.
        gathered = asyncio.run(two_replicas_start())
        assert gathered == [0, 0]
        after = asyncio.run(configured.schedule_store.get(sid))
        assert after is not None
        assert (
            after.runs_so_far,
            after.last_run_id,
            after.next_due_at,
            after.last_fired_at,
        ) == (
            before.runs_so_far,
            before.last_run_id,
            before.next_due_at,
            before.last_fired_at,
        )
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_a_post_marker_startup_never_runs_the_import_pass(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC regression guard: if the import pass ever ran — or any drift ``put``
    came back — for a previously canonicalized id, the stale Hive row would
    re-enable the canonical schedule this test disabled for real."""
    import services.scheduler as scheduler
    import stores

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0
        response = admin_client.put(f"/v1/schedules/{sid}", json={"enabled": False})
        assert response.status_code == 200, response.text
        stored = asyncio.run(configured.schedule_store.get(sid))
        assert stored is not None and stored.enabled is False

        # A projection snapshot from before the acknowledged disable.
        _restart_canonical_store(configured)
        hive = stores.schedules.get(sid)
        assert hive is not None
        stores.schedules[sid] = hive.model_copy(update={"enabled": True, "name": "nightly"})

        imported: list[str] = []

        async def spy_import(runner: Any, sid_: str, container: Any) -> int:
            imported.append(sid_)
            return 0

        monkeypatch.setattr(scheduler, "_backfill_one", spy_import)
        assert _reconcile(configured) >= 1
        assert imported == [], (
            "post-marker startup must not run the import pass for a canonicalized id (#2467)"
        )
        final = asyncio.run(configured.schedule_store.get(sid))
        assert final is not None and final.enabled is False, "canonical truth stands"
        assert stores.schedules.get(sid).enabled is False, "the projection caught up"
        assert sid not in _due_ids(configured)
    finally:
        _drop_hive_row(sid)


def test_manual_fire_defers_to_the_canonical_definition_not_the_stale_row(
    configured: Any,
) -> None:
    """AC: the fire path reads the definition it spends from canonical truth —
    a stale projection must not hand an exhausted schedule fresh quota.

    Before the read-first ``_definition_for``, firing here would put the
    stale row's definition canonically (``max_runs=None`` over the stored
    ``max_runs=1``), un-exhaust the schedule, and admit a Run the durable
    quota had already refused."""
    import stores
    from services.scheduler import _definition_authority, fire_now

    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-fire-authority"
    stores.schedules._data[sid] = _legacy_row(
        sid, configured.test_workspace, root.project_id, max_runs=1
    )
    try:
        assert _reconcile(configured) >= 1
        asyncio.run(
            configured.schedule_store.record_fire(
                sid,
                fired_at=datetime(2026, 9, 26, 3, 0, tzinfo=UTC),
                run_id="run-1",
                next_due_at=None,
            )
        )
        # The projection missed the exhaustion: it still offers a full,
        # unbounded quota under its own name.
        stale = stores.schedules.get(sid)
        assert stale is not None
        stores.schedules[sid] = stale.model_copy(
            update={"max_runs": None, "name": "stale-projection"}
        )

        runner, container = _definition_authority()
        assert container is not None

        async def definition() -> Any:
            return await runner._definition_for(
                sid,
                stores.schedules.get(sid),
                store=container.schedule_store,
                scope=(configured.test_workspace, root.project_id),
            )

        definition_ = asyncio.run(definition())
        assert definition_ is not None
        assert definition_.name == "legacy", "the canonical definition is what a fire spends"
        assert definition_.max_runs == 1
        assert definition_.exhausted, "the canonical quota, not the stale row's, governs"
        assert asyncio.run(configured.schedule_store.get(sid)).max_runs == 1, (
            "firing must not write the stale quota back over the canonical row"
        )
        with pytest.raises(Exception, match="used all 1 of its runs"):
            asyncio.run(fire_now(sid))
    finally:
        _drop_hive_row(sid)


def test_a_create_whose_compensation_also_fails_is_resolved_at_restart(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: the deep end of the create window — the Hive write failed AND the
    canonical compensation died with the process. The restart projects the
    committed canonical row: the schedule becomes visible with one identity,
    never an enabled orphan only due() can see."""
    import stores
    from routes import schedules as routes
    from services.schedule_projection import ledger

    async def failing_delete(sid: str) -> None:
        raise RuntimeError("simulated compensation crash")

    monkeypatch.setattr("services.scheduler.delete_canonical_definition", failing_delete)

    def failing_setitem(self: Any, key: str, value: Any) -> None:
        raise RuntimeError("simulated persisted-store outage")

    monkeypatch.setattr(type(stores.schedules), "__setitem__", failing_setitem)
    with pytest.raises(RuntimeError, match="simulated persisted-store outage"):
        asyncio.run(
            routes.create_schedule(
                routes.CreateScheduleBody(
                    name="unprojected",
                    cron_expression="0 3 * * *",
                    mission_template_id=_TPL,
                    workspace_id=configured.test_workspace,
                ),
                _request_as_admin(),
            )
        )
    monkeypatch.undo()
    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = asyncio.run(
        configured.schedule_store.list_for_project(
            workspace_id=configured.test_workspace, project_id=root.project_id
        )
    )[0].schedule_id
    assert stores.schedules.get(sid) is None, "the process died before the projection"

    assert _reconcile(configured) >= 1
    projected = stores.schedules.get(sid)
    assert projected is not None and projected.name == "unprojected", (
        "the restart repairs the projection from the committed canonical row"
    )
    listed = asyncio.run(
        configured.schedule_store.list_for_project(
            workspace_id=configured.test_workspace, project_id=root.project_id
        )
    )
    assert [schedule.schedule_id for schedule in listed] == [sid], "still one identity"
    assert not ledger().pending_creates()


def test_a_create_succeeds_even_when_its_marker_clear_fails(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pending marker is best-effort on the happy path: a failing clear
    must not fail the create, and the next reconciliation closes the marker
    without touching the agreeing rows."""
    import stores
    from services.schedule_projection import ScheduleProjectionLedger, ledger

    calls = 0

    def failing_clear(self: Any, sid: str) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated ledger outage")

    monkeypatch.setattr(ScheduleProjectionLedger, "clear_pending_create", failing_clear)
    sid = _create(admin_client, configured.test_workspace)["id"]
    monkeypatch.undo()
    try:
        assert calls >= 1, "the route tried to close its marker"
        assert sid in ledger().pending_creates(), "the marker survives for the next startup"
        assert stores.schedules.get(sid) is not None
        assert _reconcile(configured) == 0, "the restart closes it without rewriting rows"
        assert sid not in ledger().pending_creates()
    finally:
        _drop_hive_row(sid)


def test_a_delete_survives_a_failing_tombstone_write(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The canonical delete is the commit: a failing tombstone write must not
    fail the already-committed delete, and the restart degrades honestly
    (the stale row, if any, is never reimported) rather than resurrecting."""
    import stores
    from routes import schedules as routes
    from services.schedule_projection import ledger

    sid = _create(admin_client, configured.test_workspace)["id"]
    try:
        assert _reconcile(configured) >= 0

        def failing_tombstone(sid_: str) -> None:
            raise RuntimeError("simulated ledger outage")

        monkeypatch.setattr("services.schedule_projection.record_tombstone", failing_tombstone)
        request = _request_as_admin()
        assert asyncio.run(routes.delete_schedule(sid, request)) is None
        monkeypatch.undo()
        assert asyncio.run(configured.schedule_store.get(sid)) is None, (
            "the canonical delete stands"
        )
        assert stores.schedules.get(sid) is None
        assert not ledger().is_tombstoned(sid), "the tombstone is honestly absent"
    finally:
        _drop_hive_row(sid)


def test_a_tombstoned_row_is_skipped_by_the_import_pass_itself(configured: Any) -> None:
    """AC: the tombstone binds in every phase — a legacy row whose deletion
    already committed cannot be imported by the one pass that imports."""
    import stores
    from services.schedule_projection import ledger, record_tombstone

    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-legacy-tombstoned"
    stores.schedules._data[sid] = _legacy_row(sid, configured.test_workspace, root.project_id)
    record_tombstone(sid)
    try:
        assert not ledger().migrated(), "the import pass is still the one authorized"
        assert _reconcile(configured) >= 0
        assert asyncio.run(configured.schedule_store.get(sid)) is None, (
            "the import pass must not reimport a tombstoned schedule"
        )
        assert stores.schedules.get(sid) is None, "the stale record is dropped instead"
        assert ledger().migrated(), "the pass still completes and writes the marker"
    finally:
        _drop_hive_row(sid)


def test_scheduler_status_reports_the_projection_state(configured: Any) -> None:
    """AC: the health surface says whether reconciliation ran and which rows
    it could not vouch for, instead of silently serving a stale flag (#290)."""
    import stores
    from services.scheduler import scheduler_status

    root = asyncio.run(configured.project_scope_store.root_for_workspace(configured.test_workspace))
    sid = "s-degraded-surface"
    assert scheduler_status()["projection"]["migrated"] is False

    stores.schedules._data[sid] = _legacy_row(sid, configured.test_workspace, root.project_id)
    try:
        assert _reconcile(configured) >= 1
        from services.scheduler import delete_canonical_definition

        asyncio.run(delete_canonical_definition(sid))
        _reconcile(configured)
        status = scheduler_status()
        assert status["projection"]["migrated"] is True
        assert sid in status["projection"]["degraded"]
        assert status["projection"]["reconciled_at"] is not None
    finally:
        _drop_hive_row(sid)
