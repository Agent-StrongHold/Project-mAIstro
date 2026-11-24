"""Startup and route authority: the Hive projection repairs from canonical (#2467).

Issue #1199's reactivation and #2467 demonstrated the source-level failure
path the original tick migration left open: the ``/v1/schedules`` routes
commit the canonical ``ScheduleStore`` write *before* the Hive
``stores.schedules`` write, and startup ``reconcile_schedule_projection``
used to push Hive drift back INTO the canonical store. A crash in the
routes' two-write window therefore reverted an acknowledged canonical edit
or resurrected a deleted schedule on the next restart — from a stale
projection.

These tests drive the real scheduler plumbing (a wired ``create_container``
Container, the actual backfill the runner runs before its first tick, and on
the PostgreSQL leg a real server migrated through the alembic chain) and
prove the authority direction is now one-way: routes write canonical truth;
startup and the by-id routes repair the Hive projection *from* it; a
tombstoned deletion is never re-imported; and a genuinely legacy row still
migrates exactly once, without its cursor being rewound.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.container import create_container
from maistro.graph.definitions import GraphTemplate, Node
from maistro.identity import Principal
from maistro.scheduling import Schedule
from maistro.scheduling.pg_store import PgScheduleStore
from maistro.scheduling.store import InMemoryScheduleStore, SqliteScheduleStore
from maistro.state import PersistedStore, State
from maistro.types.config import AgentConfig

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_TPL = "projection-authority-template"
_FAR_FUTURE = datetime(2999, 1, 1, tzinfo=UTC)
_WORKSPACE = "projection-authority"

# The body of an independent OS process that runs the shipped startup
# reconciliation against one shared durable state — the cross-process twin of
# ``test_repeated_and_concurrent_startup_is_idempotent``, whose concurrent
# callers stay in one interpreter. Barriers make the two processes genuinely
# overlap (both are alive and past their own wiring before either reconcile
# starts), so the import pass, the marker write, and the repair pass race for
# real. Results are reported through a file per worker: the parent asserts on
# final durable state, never on a mid-race view.
_WORKER_SCRIPT = """
import asyncio
import json
import pathlib
import sys
import time

backend, hive_path, database_url, workspace_id, ready_file, start_file, result_file = sys.argv[1:8]
sys.path.insert(0, backend)

# A bare interpreter inherits none of pytest's root `pythonpath` wiring, and
# the CI system-python step installs only backend/requirements.txt —
# maistro-core is consumed via sys.path there, never pip-installed. Without
# this entry the worker dies on `import maistro` before writing its ready
# marker, and the parent burns its entire deadline on a barrier that no
# duration can satisfy (the PR #2512 `test` job red). `backend` stays at
# index 0: the core src tree exports only the `maistro` package, so nothing
# shadows the backend's own modules.
sys.path.insert(1, str(pathlib.Path(backend).parents[1] / "maistro-core" / "src"))

import stores
from maistro.state import PersistedStore, State

persisted = PersistedStore(State(db_path=hive_path))
persisted.initialize()
stores.configure_persistence(persisted)

from maistro.container import create_container
from maistro.types.config import AgentConfig
from models.schemas import Schedule as HiveSchedule
from services.model_store import ModelStore

projection = ModelStore("schedules", HiveSchedule, persisted)
projection.initialize()
stores.schedules = projection
import services.schedule_projection  # noqa: F401  (registers its ledger store)

ready = pathlib.Path(ready_file)
ready.write_text("wired", encoding="utf-8")
deadline = time.monotonic() + 120.0
while not pathlib.Path(start_file).exists() and time.monotonic() < deadline:
    time.sleep(0.02)


async def main() -> None:
    container = await create_container(
        AgentConfig(
            router_api_key="test-key",
            workspace_id=workspace_id,
            database_url=database_url,
        )
    )
    try:
        from services.scheduler import _ScheduleRunner, reconcile_schedule_projection

        _ScheduleRunner._canonical_container = staticmethod(lambda: container)
        changed = await reconcile_schedule_projection()
        identities = [s.schedule_id for s in await container.schedule_store.list_all()]
        pathlib.Path(result_file).write_text(
            json.dumps({"changed": changed, "identities": identities}), encoding="utf-8"
        )
    finally:
        await container.aclose()


asyncio.run(main())
"""


@pytest.fixture(scope="module")
def postgres_database() -> Iterator[str]:
    """Own a scratch database, never truncate the configured database's data."""
    from sqlalchemy.engine import make_url

    from maistro.testing.postgres import postgres_dsn

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError("MAISTRO_REQUIRE_PG_LEGS needs MAISTRO_TEST_PG_DSN")
        pytest.skip("MAISTRO_TEST_PG_DSN is unset")
    import psycopg

    name = f"projection_authority_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        yield url
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def database_url(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'projection-authority.db'}"
    if request.param == "postgres":
        return str(request.getfixturevalue("postgres_database"))
    return ""


class HiveProjection:
    """The shipped ModelStore/PersistedStore boundary, reopened from disk."""

    def __init__(self, path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.path = path
        self.monkeypatch = monkeypatch
        self.state: State | None = None
        self.reopen()

    def reopen(self) -> None:
        import stores
        from models.schemas import Schedule as HiveSchedule
        from services.model_store import ModelStore

        self.close()
        self.state = State(db_path=str(self.path))
        persisted = PersistedStore(self.state)
        persisted.initialize()
        projection = ModelStore("schedules", HiveSchedule, persisted)
        projection.initialize()
        self.monkeypatch.setattr(stores, "schedules", projection)

    def close(self) -> None:
        if self.state is not None:
            self.state.close()
            self.state = None


@pytest.fixture
def persisted_projection(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[HiveProjection]:
    projection = HiveProjection(tmp_path / "hive-state.db", monkeypatch)
    try:
        yield projection
    finally:
        projection.close()


class Harness:
    """The configured process: its Container, and a way to crash-restart it."""

    def __init__(
        self,
        container: Any,
        database_url: str,
        service: Any,
        previous: Any,
        projection: HiveProjection,
    ) -> None:
        self.container = container
        self.database_url = database_url
        self._service = service
        self._previous = previous
        self.projection = projection

    async def restart(self, monkeypatch: pytest.MonkeyPatch) -> Harness:
        """A fresh process on the same durable state.

        SQL backends get a real close-and-reopen of the database (a new
        Container on the same URL — a tombstone or an edited definition must
        be in the database, not in the test's head). The memory backend has
        no durability to reopen, so the same Container stands in for the
        restarted process.
        """
        self.projection.reopen()
        if self.database_url == "":
            return self
        await self.container.aclose()
        fresh = await create_container(
            AgentConfig(
                router_api_key="test-key",
                workspace_id=_WORKSPACE,
                database_url=self.database_url,
            )
        )
        self.container = fresh
        self._service._agent_port = SimpleNamespace(container=fresh)
        monkeypatch.setattr(_schedule_runner(), "_canonical_container", staticmethod(lambda: fresh))
        return self

    async def aclose(self) -> None:
        self._service._agent_port = self._previous
        await self.container.aclose()


@pytest.fixture
async def configured(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    persisted_projection: HiveProjection,
) -> AsyncIterator[Harness]:
    """A real Container behind the engine, with the parametrised ScheduleStore."""
    import services.engine as engine_mod
    from services import workspace_authority

    container = await create_container(
        AgentConfig(router_api_key="test-key", workspace_id=_WORKSPACE, database_url=database_url)
    )
    if database_url.startswith("postgres"):
        assert isinstance(container.schedule_store, PgScheduleStore)
        # Only our freshly created database, never the configured server's DB.
        await container.pg_pool.execute(
            "TRUNCATE canonical_workspaces, canonical_workspace_memberships, canonical_projects,"
            " canonical_project_memberships, canonical_project_resources,"
            " schedules, schedule_deletions, graph_templates RESTART IDENTITY CASCADE"
        )
    elif database_url.startswith("sqlite"):
        assert isinstance(container.schedule_store, SqliteScheduleStore)
    else:
        assert isinstance(container.schedule_store, InMemoryScheduleStore)
    import stores

    # These are the only Hive rows this scenario is allowed to see.
    monkeypatch.setattr(stores.schedules, "_data", {})
    service = engine_mod.get_engine()
    previous = service._agent_port
    service._agent_port = SimpleNamespace(container=container)
    monkeypatch.setattr(_schedule_runner(), "_canonical_container", staticmethod(lambda: container))
    harness = Harness(container, database_url, service, previous, persisted_projection)
    try:
        workspace = await workspace_authority.create_workspace(
            creator_user_id="user-1",
            name=f"Projection authority {uuid.uuid4().hex[:8]}",
            persona_template_id="default",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
        await workspace_authority.set_member(workspace.id, user_id="admin", role="editor")
        container.test_workspace = str(workspace.id)
        await container.template_store.put(
            GraphTemplate(
                template_id=_TPL,
                workspace_id=container.test_workspace,
                version=1,
                name="Projection authority template",
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
        yield harness
    finally:
        await harness.aclose()


def _schedule_runner() -> Any:
    from services.scheduler import _ScheduleRunner

    return _ScheduleRunner


def _legacy_row(workspace_id: str, project_id: str, *, enabled: bool = True) -> Any:
    from models.schemas import Schedule as HiveSchedule

    now = datetime.now(UTC)
    return HiveSchedule(
        id="s-legacy-projection",
        user_id="admin",
        workspace_id=workspace_id,
        project_id=project_id,
        name="legacy",
        description="",
        cron_expression="0 3 * * *",
        mission_template_id=_TPL,
        enabled=enabled,
        timezone="UTC",
        max_runs=None,
        catchup_window_seconds=3600.0,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=now,
        updated_at=now,
    )


def _install_row(row: Any) -> None:
    import stores

    stores.schedules[row.id] = row


def _drop_row(sid: str) -> None:
    import stores

    stores.schedules.pop(sid, None)


async def _create_via_route(container: Any, **overrides: Any) -> Any:
    """``POST /v1/schedules`` semantics, called in-loop.

    The route functions are called directly, like the neighboring route
    suites do: auth is carried by the principal request (the middleware
    contract those suites already cover), and the calls stay on this loop so
    an ``asyncpg``-backed Container is reachable. The username claim index
    lives on the default engine's Container, so password login through a
    swapped port would misrepresent the auth surface anyway.
    """
    from routes.schedules import CreateScheduleBody, create_schedule

    body = CreateScheduleBody(
        name=overrides.pop("name", "nightly"),
        cron_expression=overrides.pop("cron_expression", "0 3 * * *"),
        mission_template_id=overrides.pop("mission_template_id", _TPL),
        workspace_id=overrides.pop("workspace_id", container.test_workspace),
        **overrides,
    )
    return await create_schedule(body, _request_as_admin())


async def _get_via_route(schedule_id: str) -> Any:
    from routes.schedules import get_schedule

    return await get_schedule(schedule_id, _request_as_admin())


async def _update_via_route(schedule_id: str, **fields: Any) -> Any:
    from routes.schedules import UpdateScheduleBody, update_schedule

    return await update_schedule(schedule_id, UpdateScheduleBody(**fields), _request_as_admin())


async def _delete_via_route(schedule_id: str) -> None:
    from routes.schedules import delete_schedule

    return await delete_schedule(schedule_id, _request_as_admin())


def _request_as_admin() -> Any:
    return SimpleNamespace(state=SimpleNamespace(principal=Principal(user_id="admin")))


async def test_restart_retains_a_canonical_edit_and_repairs_the_stale_row(
    configured: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: an edit acknowledged by the canonical store survives a restart.

    The route's second write (the Hive projection) never happens — that is
    the crash window — so the Hive row still says what was true before the
    edit. Startup must keep the canonical values and repair the projection,
    never the reverse.
    """
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:
        # The canonical commit; the Hive write below it never lands.
        stored = await container.schedule_store.get(sid)
        assert stored is not None
        await container.schedule_store.put(
            stored.model_copy(
                update={
                    "enabled": False,
                    "cron": "30 4 * * *",
                    "timezone": "Asia/Tokyo",
                    "graph_template_id": "edited-template",
                }
            )
        )
        hive = stores.schedules.get(sid)
        assert hive is not None and hive.enabled is True, "the crash left the row stale"
        assert hive.cron_expression == "0 3 * * *"

        container = (await configured.restart(monkeypatch)).container
        moved = await reconcile_schedule_projection()

        assert moved >= 1, "the stale projection is repaired"
        kept = await container.schedule_store.get(sid)
        assert kept is not None
        assert kept.enabled is False, "the acknowledged canonical edit survives the restart"
        assert kept.cron == "30 4 * * *"
        assert kept.timezone == "Asia/Tokyo"
        assert kept.graph_template_id == "edited-template"
        repaired = stores.schedules.get(sid)
        assert repaired is not None
        assert repaired.mission_template_id == "edited-template"
        assert (repaired.enabled, repaired.cron_expression, repaired.timezone) == (
            False,
            "30 4 * * *",
            "Asia/Tokyo",
        )
        # Repeated startup is a no-op once the projection agrees.
        assert await reconcile_schedule_projection() == 0
        served = await _get_via_route(sid)
        assert served.enabled is False
    finally:
        _drop_row(sid)


async def test_the_retired_any_drift_push_reverts_an_acknowledged_edit(
    configured: Harness,
) -> None:
    """The negative leg: replay the retired startup policy, watch it revert.

    This is the #2467 failure mode, reproduced against the shipped seam: the
    old ``_backfill_one`` derived a definition from whatever Hive row it
    found and ``put`` it whenever that disagreed with the canonical row.
    Replaying it against a crash-window state reverts the acknowledged
    disable — which is why the shipped backfill must never perform a drift
    put for a canonicalized id, and why
    ``test_restart_retains_a_canonical_edit_and_repairs_the_stale_row`` fails
    if it ever does again.
    """
    import stores
    from services.scheduler import (
        _ScheduleRunner,
        _scoped_definition,
        definition_lock,
        reconcile_schedule_projection,
    )

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:
        stored = await container.schedule_store.get(sid)
        assert stored is not None
        await container.schedule_store.put(stored.model_copy(update={"enabled": False}))
        hive = stores.schedules.get(sid)
        assert hive is not None and hive.enabled is True

        async def retired_policy() -> None:
            # Exactly what `_backfill_one` used to do on drift: derive from
            # the Hive row, put when the canonical row disagrees.
            async with definition_lock(sid):
                derived = await _scoped_definition(_ScheduleRunner(), sid, hive, container)
                existing = await container.schedule_store.get(sid)
                assert derived is not None and existing is not None
                drifted = (
                    existing.name != derived.name
                    or existing.cron != derived.cron
                    or existing.timezone != derived.timezone
                    or existing.enabled != derived.enabled
                )
                if drifted:
                    await container.schedule_store.put(derived)

        # The negative leg: the retired policy on this crash-window state.
        await retired_policy()
        reverted = await container.schedule_store.get(sid)
        assert reverted is not None and reverted.enabled is True, (
            "the retired policy reverts the acknowledged disable from the stale row"
        )

        # Restore the crash-window state the shipped policy must handle.
        await container.schedule_store.put(stored.model_copy(update={"enabled": False}))
        _install_row(hive)
        moved = await reconcile_schedule_projection()
        assert moved >= 1
        final = await container.schedule_store.get(sid)
        assert final is not None and final.enabled is False, (
            "the shipped policy keeps the canonical edit and repairs the projection"
        )
        repaired = stores.schedules.get(sid)
        assert repaired is not None and repaired.enabled is False
    finally:
        _drop_row(sid)


async def test_a_deleted_schedule_is_not_resurrected_and_its_stale_row_is_removed(
    configured: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: a delete acknowledged by the canonical store survives a restart.

    The route's Hive ``pop`` never happens — the crash window — so the stale
    row is the only place the deleted schedule still exists. The durable
    tombstone ``delete`` recorded is what startup reads to retire the row
    instead of importing it, and on the SQL backends the tombstone is proven
    across a real database reopen.
    """
    import stores
    from fastapi import HTTPException
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:
        # The canonical delete commits; the Hive pop never lands.
        assert await container.schedule_store.delete(sid) is True
        from services.schedule_projection import record_tombstone

        record_tombstone(sid)
        assert stores.schedules.get(sid) is not None, "the crash left the row behind"

        container = (await configured.restart(monkeypatch)).container
        moved = await reconcile_schedule_projection()

        assert moved >= 1, "the stale row is retired"
        assert await container.schedule_store.get(sid) is None, "no resurrection"
        assert stores.schedules.get(sid) is None, "the stale projection row is removed"
        due = await container.schedule_store.due(now=_FAR_FUTURE)
        assert sid not in {schedule.schedule_id for schedule in due}, "nothing re-armed"
        assert await reconcile_schedule_projection() == 0, "startup is idempotent"
        with pytest.raises(HTTPException) as gone:
            await _get_via_route(sid)
        assert gone.value.status_code == 404, gone.value
    finally:
        _drop_row(sid)


async def test_a_tombstoned_historical_row_cannot_override_canonical_authority(
    configured: Harness,
) -> None:
    """AC: a tombstoned or already-imported row cannot override canonical authority.

    A "historical" Hive copy of the deleted schedule — what a backup restore
    or a slow replica might produce — must not re-arm it: the tombstone, not
    the row, decides.
    """
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:
        historical = stores.schedules.get(sid)
        assert historical is not None
        assert await container.schedule_store.delete(sid) is True
        from services.schedule_projection import record_tombstone

        record_tombstone(sid)
        # The deletion's Hive pop "never happened", and worse: the row comes
        # back enabled, as a restored historical copy would.
        _install_row(historical.model_copy(update={"enabled": True}))

        await reconcile_schedule_projection()

        assert await container.schedule_store.get(sid) is None
        assert stores.schedules.get(sid) is None, "the historical row is retired, not imported"
        assert await reconcile_schedule_projection() == 0
    finally:
        _drop_row(sid)


async def test_a_never_imported_legacy_row_migrates_exactly_once(
    configured: Harness,
) -> None:
    """AC: a genuinely un-imported legacy row migrates once, cursor intact.

    The one legitimate import: a row from before the routes wrote
    canonically. It becomes the canonical definition exactly once, real
    Workspace scope included; every later startup reconciles from that row
    and can never re-derive it from a stale Hive copy.
    """
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    root = await container.project_scope_store.root_for_workspace(container.test_workspace)
    row = _legacy_row(container.test_workspace, root.project_id, enabled=False)
    _install_row(row)
    try:
        moved = await reconcile_schedule_projection()
        assert moved >= 1
        imported = await container.schedule_store.get(row.id)
        assert imported is not None
        assert imported.enabled is False, "a disabled legacy row stays disabled"
        assert imported.workspace_id == container.test_workspace
        assert imported.project_id == root.project_id
        assert imported.cron == "0 3 * * *"

        assert await reconcile_schedule_projection() == 0, "the import happens exactly once"

        # The imported row is now canonical authority: a later Hive-only edit
        # (a pre-canonical PUT's residue) cannot revert it.
        await container.schedule_store.record_fire(
            row.id,
            fired_at=datetime(2026, 11, 22, 3, 0, tzinfo=UTC),
            run_id="run-1",
            next_due_at=datetime(2026, 11, 22, 4, 0, tzinfo=UTC),
        )
        _install_row(row.model_copy(update={"enabled": True, "name": "renamed-legacy"}))
        await reconcile_schedule_projection()
        still = await container.schedule_store.get(row.id)
        assert still is not None
        assert still.enabled is False, "the already-imported row cannot override canonical"
        assert still.runs_so_far == 1
        assert still.last_run_id == "run-1"
        assert still.next_due_at == datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
        repaired = stores.schedules.get(row.id)
        assert repaired is not None
        assert repaired.enabled is False and repaired.name == "legacy"
    finally:
        _drop_row(row.id)


async def test_repeated_and_concurrent_startup_is_idempotent(
    configured: Harness,
) -> None:
    """AC: repeated/concurrent startups preserve exactly one schedule identity."""
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    root = await container.project_scope_store.root_for_workspace(container.test_workspace)
    row = _legacy_row(container.test_workspace, root.project_id)
    _install_row(row)
    try:
        await asyncio.gather(reconcile_schedule_projection(), reconcile_schedule_projection())
        assert await container.schedule_store.get(row.id) is not None
        identities = await container.schedule_store.list_all()
        assert [s.schedule_id for s in identities] == [row.id]
        assert row.id in stores.schedules._data  # type: ignore[attr-defined]

        await asyncio.gather(reconcile_schedule_projection(), reconcile_schedule_projection())
        assert await reconcile_schedule_projection() == 0
        again = await container.schedule_store.list_all()
        assert [s.schedule_id for s in again] == [row.id], "still exactly one identity"
    finally:
        _drop_row(row.id)


def _exited_worker_detail(workers: list[subprocess.Popen[bytes]]) -> str:
    """Name each worker's own failure at the ready/start barrier.

    A wiring crash (import error, store init) is visible only in the exited
    worker's stderr, and only while it is reaped — without this the barrier
    reports an unexplained timeout and the real error never reaches CI.
    """

    detail: list[str] = []
    for i, worker in enumerate(workers):
        tail: list[str] = []
        if worker.poll() is not None:
            out, err = worker.communicate(timeout=30)
            text = (err or out or b"").decode(errors="replace").strip()
            tail = text.splitlines()[-3:]
        detail.append(f"worker[{i}] rc={worker.poll()} stderr_tail={tail}")
    return "; ".join(detail)


async def test_independent_processes_racing_startup_converge_on_canonical_truth(
    configured: Harness, database_url: str, tmp_path: pathlib.Path
) -> None:
    """AC: two OS processes booting one deployment converge without loss.

    The same-process ``asyncio.gather`` twins prove the reconciliation is
    idempotent within an interpreter; replicas in a real deployment are
    independent processes sharing the durable state. Both processes here run
    the shipped ``reconcile_schedule_projection`` against the same canonical
    database and the same Hive file, genuinely overlapped by a ready/start
    barrier, and the durable end state must be: exactly one canonical
    identity, the projection repaired from it, and a single-winner migration
    marker — whatever interleaving the two imports took.
    """
    if database_url == "":
        pytest.skip("two processes need durable state to share")

    import json as json_mod
    import time

    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    root = await container.project_scope_store.root_for_workspace(container.test_workspace)
    row = _legacy_row(container.test_workspace, root.project_id)
    _install_row(row)

    driver = tmp_path / "startup_worker.py"
    driver.write_text(_WORKER_SCRIPT, encoding="utf-8")
    workers: list[subprocess.Popen[bytes]] = []
    paths: list[dict[str, pathlib.Path]] = []
    try:
        for i in range(2):
            worker_paths = {
                "ready": tmp_path / f"ready-{i}",
                "start": tmp_path / "start",
                "result": tmp_path / f"result-{i}.json",
            }
            paths.append(worker_paths)
            workers.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(driver),
                        str(_BACKEND),
                        str(configured.projection.path),
                        database_url,
                        container.test_workspace,
                        str(worker_paths["ready"]),
                        str(worker_paths["start"]),
                        str(worker_paths["result"]),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + 120.0
        while not all(p["ready"].exists() for p in paths) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            # A worker that exited before its ready marker can never become
            # ready; stop waiting and report why instead of burning the rest
            # of the deadline on an impossible barrier.
            if any(worker.poll() is not None for worker in workers):
                break
        if not all(p["ready"].exists() for p in paths):
            raise AssertionError(
                "both workers finished wiring their own persistence before the race: "
                + _exited_worker_detail(workers)
            )
        paths[0]["start"].write_text("go", encoding="utf-8")

        for worker in workers:
            stdout, stderr = worker.communicate(timeout=180)
            assert worker.returncode == 0, (
                f"an independent startup process crashed (rc={worker.returncode}): "
                f"{stderr.decode(errors='replace') or stdout.decode(errors='replace')}"
            )
        reports = [json_mod.loads(p["result"].read_text()) for p in paths]
        for report in reports:
            assert isinstance(report["changed"], int) and report["changed"] >= 0, report

        # Converged durable truth, whatever interleaving the two imports took:
        # exactly one canonical identity carrying the legacy row's definition,
        # and the durable projection agreeing with it.
        identities = await container.schedule_store.list_all()
        assert [s.schedule_id for s in identities] == [row.id], "no duplicate identity"
        canonical = await container.schedule_store.get(row.id)
        assert canonical is not None
        assert canonical.enabled is True and canonical.name == "legacy"
        assert canonical.cron == "0 3 * * *" and canonical.timezone == "UTC"
        assert canonical.workspace_id == container.test_workspace

        configured.projection.reopen()
        projected = stores.schedules.get(row.id)
        assert projected is not None, "the projection exists on the shared Hive disk"
        assert projected.name == "legacy" and projected.enabled is True
        assert projected.cron_expression == "0 3 * * *"

        # The migration marker is single-winner across processes and durable
        # in the shared ledger store — the next boot of either replica runs
        # the repair pass, never a second import.
        marker_raw = stores.schedules._persisted.get_raw("schedule_migration", "migration")
        assert marker_raw is not None, "the marker is durable, not a per-process memory"
        assert json_mod.loads(marker_raw).get("version") == 1

        # The race left the reconciliation idempotent: a further startup in
        # this interpreter changes nothing and keeps exactly one identity.
        assert await reconcile_schedule_projection() == 0
        again = await container.schedule_store.list_all()
        assert [s.schedule_id for s in again] == [row.id]
    finally:
        for worker in workers:
            if worker.poll() is None:  # pragma: no cover - only on earlier failure
                worker.kill()
                worker.communicate(timeout=30)
        _drop_row(row.id)


async def test_a_create_orphan_is_surfaced_by_startup(configured: Harness) -> None:
    """AC: restart during create's two-write window leaves no invisible orphan.

    The canonical row exists and the Hive row does not — the crash window of
    ``POST /v1/schedules``. Startup surfaces the canonical row into the
    projection, so the schedule is exactly one identity, visible to the
    routes that own it, instead of an enabled row only the tick could see.
    """
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    root = await container.project_scope_store.root_for_workspace(container.test_workspace)
    definition = Schedule(
        schedule_id="s-create-orphan",
        workspace_id=container.test_workspace,
        project_id=root.project_id,
        name="orphaned create",
        cron="0 3 * * *",
        timezone="UTC",
        graph_template_id=_TPL,
        actor_principal_id="admin",
        enabled=True,
        created_at=datetime.now(UTC),
    )
    await container.schedule_store.put(definition)
    assert stores.schedules.get("s-create-orphan") is None
    try:
        moved = await reconcile_schedule_projection()
        assert moved >= 1
        surfaced = stores.schedules.get("s-create-orphan")
        assert surfaced is not None
        assert surfaced.name == "orphaned create" and surfaced.enabled is True
        assert surfaced.workspace_id == container.test_workspace
        assert surfaced.cron_expression == "0 3 * * *"
        identities = await container.schedule_store.list_all()
        assert [s.schedule_id for s in identities] == ["s-create-orphan"]

        served = await _get_via_route("s-create-orphan")
        assert served.name == "orphaned create"
    finally:
        _drop_row("s-create-orphan")


async def test_routes_obey_canonical_truth_after_a_projection_crash(
    configured: Harness,
) -> None:
    """AC: read/update/delete obey canonical definition truth after a crash.

    No restart needed: the by-id routes repair the projection from canonical
    truth at read time, so a stale enabled flag is never silently served —
    and a canonically deleted schedule 404s even with its stale row present.
    """
    import stores
    from fastapi import HTTPException

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:
        stored = await container.schedule_store.get(sid)
        assert stored is not None
        await container.schedule_store.put(
            stored.model_copy(update={"enabled": False, "cron": "15 5 * * *"})
        )
        served = await _get_via_route(sid)
        assert served.enabled is False, "canonical truth, not the stale projection"
        assert served.cron_expression == "15 5 * * *"
        repaired = stores.schedules.get(sid)
        assert repaired is not None and repaired.enabled is False

        updated = await _update_via_route(sid, enabled=True)
        assert updated.enabled is True
        after = await container.schedule_store.get(sid)
        assert after is not None and after.enabled is True
        hive_after = stores.schedules.get(sid)
        assert hive_after is not None and hive_after.enabled is True

        await _delete_via_route(sid)
        assert await container.schedule_store.get(sid) is None
        assert stores.schedules.get(sid) is None

        # The crash-window delete: canonical deleted, tombstone set, Hive
        # row still present. The route serves canonical truth: gone, row
        # retired.
        created2 = await _create_via_route(container)
        sid2 = str(created2.id)
        try:
            assert await container.schedule_store.delete(sid2) is True
            assert stores.schedules.get(sid2) is not None
            with pytest.raises(HTTPException) as gone:
                await _get_via_route(sid2)
            assert gone.value.status_code == 404, gone.value
            assert stores.schedules.get(sid2) is None, "the read retired the stale row"
        finally:
            _drop_row(sid2)
    finally:
        _drop_row(sid)


async def test_an_update_whose_projection_write_fails_acknowledges_degraded(
    configured: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: truthful degraded semantics for a projection failure after commit.

    The canonical update is already committed when the Hive write fails, so
    the route must not pretend nothing happened: the caller gets an explicit
    degraded 503 naming the persisted edit, and the canonical row really does
    carry it. Compensation would revert an acknowledged definition because a
    response-only row hiccupped.
    """
    import stores
    from fastapi import HTTPException
    from routes import schedules as routes

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    try:

        def failing_setitem(self: Any, key: str, value: Any) -> None:
            raise RuntimeError("simulated projection outage")

        with monkeypatch.context() as failure:
            failure.setattr(type(stores.schedules), "__setitem__", failing_setitem)
            with pytest.raises(HTTPException) as degraded:
                await routes.update_schedule(
                    sid, routes.UpdateScheduleBody(enabled=False), _request_as_admin()
                )
        assert degraded.value.status_code == 503, degraded.value
        assert "persisted" in degraded.value.detail

        stored = await container.schedule_store.get(sid)
        assert stored is not None and stored.enabled is False, (
            "the canonical update really persisted"
        )
        # The next read repairs the projection from the persisted truth.
        projected = await routes._canonical_projection(sid)
        assert projected is not None and projected.enabled is False
    finally:
        _drop_row(sid)


async def test_delete_projection_failure_reports_committed_truth_and_heals_on_restart(
    configured: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed durable Hive delete must not obscure a committed canonical delete."""
    import stores
    from fastapi import HTTPException
    from services.scheduler import reconcile_schedule_projection

    created = await _create_via_route(configured.container)
    sid = str(created.id)
    try:

        def unavailable(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Hive persistence delete unavailable")

        with monkeypatch.context() as failure:
            failure.setattr(stores.schedules._persisted, "delete", unavailable)
            with pytest.raises(HTTPException) as degraded:
                await _delete_via_route(sid)
        assert degraded.value.status_code == 503
        assert sid in degraded.value.detail and "persisted" in degraded.value.detail
        assert await configured.container.schedule_store.get(sid) is None
        assert sid in await configured.container.schedule_store.tombstoned_ids()
        assert stores.schedules.get(sid) is not None

        container = (await configured.restart(monkeypatch)).container
        assert stores.schedules.get(sid) is not None, "stale row reloaded from Hive disk"
        await reconcile_schedule_projection()
        assert stores.schedules.get(sid) is None
        assert await container.schedule_store.get(sid) is None
        assert sid not in {
            s.schedule_id for s in await container.schedule_store.due(now=_FAR_FUTURE)
        }
        # The healed projection deletion is itself durable, not just a cache edit.
        configured.projection.reopen()
        assert stores.schedules.get(sid) is None
    finally:
        _drop_row(sid)


async def test_startup_projection_leaves_recorded_cursors_stable(
    configured: Harness,
) -> None:
    """AC: existing next_due_at, last_run_id and runs_so_far stay stable.

    Repairing the projection must never rewind the canonical cursor. Cursor
    mirroring into the Hive row stays the tick's own post-fire write
    (``_project_cursor``): projection repair compares definition truth, so a
    cursor a fire has not yet mirrored is tick timing, not drift to repair.
    """
    import stores
    from services.scheduler import reconcile_schedule_projection

    container = configured.container
    created = await _create_via_route(container)
    sid = str(created.id)
    fired_at = datetime(2026, 11, 22, 3, 0, tzinfo=UTC)
    try:
        recorded = await container.schedule_store.record_fire(
            sid,
            fired_at=fired_at,
            run_id="run-42",
            next_due_at=fired_at + timedelta(days=1),
        )
        assert recorded is not None and recorded.runs_so_far == 1
        # Rewind the Hive row to its pre-fire projection — the crash window.
        stale = stores.schedules.get(sid)
        assert stale is not None
        _install_row(
            stale.model_copy(update={"last_run": None, "last_run_id": None, "next_run": None})
        )

        moved = await reconcile_schedule_projection()

        assert moved == 0, "cursor-only differences are the tick's timing, not drift"
        kept = await container.schedule_store.get(sid)
        assert kept is not None
        assert kept.runs_so_far == 1
        assert kept.last_run_id == "run-42"
        assert kept.next_due_at == fired_at + timedelta(days=1)
        assert kept.last_fired_at == fired_at
        hive = stores.schedules.get(sid)
        assert hive is not None and hive.enabled is True, "the definition row is untouched"
    finally:
        _drop_row(sid)
