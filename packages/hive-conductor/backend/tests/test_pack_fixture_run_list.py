"""M7-A13: pack-fixture Runs open through the host run list (#986 surface).

The book/game fixtures live in maistro-core and load through the canonical
spine (Goal -> Graph -> Run -> NodeRun -> Attempt). This suite proves the
Design Studio half of #989's contract on the host side: seeded through the
canonical stores, visible to a reviewer through the workspace authority's
canonical membership (#37), and openable through `services.dag_run_inspection`
— the exact door `GET /v1/dag-runs` answers through (frontend DagRuns.tsx).

Nothing here executes explore/judge: opening is a read, and the canonical
statuses must be identical before and after. The fixtures get no side door —
a principal without membership on the fixture Workspace is refused with the
same 404-shape as any foreign run (#1174).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import stores
from models.workspace import Workspace, WorkspaceMember
from services import workspace_authority
from services.dag_run_inspection import list_visible_runs, visible_run_detail
from services.dag_run_store import get_dag_run_store

from maistro.graph.seeds.pack_fixtures import (
    PACK_FIXTURE_WORKSPACE_ID,
    seed_book_fixture,
    seed_game_fixture,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import RunStatus
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.store import InMemoryRunStore
from maistro.workspaces.store import InMemoryWorkspaceStore

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_REVIEWER = "user"  # the session conftest seeds this principal
_FOREIGNER = "admin"

_GENEROUS_LIMITS = RunConcurrencyLimits(per_principal=16, per_workspace=16)


@pytest.fixture(autouse=True)
def _clear_legacy_workspace_record():
    stores.workspaces.pop(PACK_FIXTURE_WORKSPACE_ID, None)
    yield
    stores.workspaces.pop(PACK_FIXTURE_WORKSPACE_ID, None)


def _legacy_fixture_workspace() -> Workspace:
    """A Hive-side record whose import grants the reviewer canonical membership.

    The import path (legacy record -> canonical Workspace + membership +
    presentation, identity preserved) is the authority's documented way a
    Workspace becomes visible to a principal — the fixtures use it instead of
    inventing a grant.
    """
    now = datetime(2024, 5, 1, tzinfo=UTC)
    return Workspace(
        id=PACK_FIXTURE_WORKSPACE_ID,
        persona_template_id="pm_fleet",
        name="M7 pack fixtures",
        members=[WorkspaceMember(user_id=_REVIEWER, role="owner")],
        checklist=[],
        theme_id="default",
        created_at=now,
        updated_at=now + timedelta(days=1),
    )


async def _seed_and_project(
    run_store: InMemoryRunStore,
    project_store: InMemoryProjectScopeStore,
) -> tuple[str, str]:
    """Seed both fixtures through the canonical spine and project their rows."""
    book = await seed_book_fixture(run_store, project_store)
    game = await seed_game_fixture(run_store, project_store)
    # The projection row is what the run list reads; hosts record it when a
    # run starts through a host surface (cf. test_dag_run_scope.py's seeding).
    for run_id in (book.run_id, game.run_id):
        await get_dag_run_store().start_run(
            run_id=run_id, user_id=_REVIEWER, workspace_id=PACK_FIXTURE_WORKSPACE_ID
        )
    return book.run_id, game.run_id


@pytest.mark.asyncio
async def test_fixture_runs_open_through_the_host_run_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces[PACK_FIXTURE_WORKSPACE_ID] = _legacy_fixture_workspace()

    # Membership first: the reviewer's universe includes the fixture Workspace.
    view = await workspace_authority.visible_view(_REVIEWER, PACK_FIXTURE_WORKSPACE_ID)
    assert view is not None, "fixture Workspace must resolve through the authority import"

    project_store = InMemoryProjectScopeStore()
    run_store = InMemoryRunStore(project_store=project_store, concurrency_limits=_GENEROUS_LIMITS)
    book_run_id, game_run_id = await _seed_and_project(run_store, project_store)

    listed = {row["id"] for row in await list_visible_runs(_REVIEWER, limit=100)}
    assert book_run_id in listed
    assert game_run_id in listed

    book_detail = await visible_run_detail(_REVIEWER, book_run_id)
    assert book_detail is not None
    assert book_detail["workspace_id"] == PACK_FIXTURE_WORKSPACE_ID
    game_detail = await visible_run_detail(_REVIEWER, game_run_id)
    assert game_detail is not None
    assert game_detail["workspace_id"] == PACK_FIXTURE_WORKSPACE_ID


@pytest.mark.asyncio
async def test_opening_a_fixture_executes_nothing_and_has_no_side_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces[PACK_FIXTURE_WORKSPACE_ID] = _legacy_fixture_workspace()
    await workspace_authority.visible_view(_REVIEWER, PACK_FIXTURE_WORKSPACE_ID)

    project_store = InMemoryProjectScopeStore()
    run_store = InMemoryRunStore(project_store=project_store, concurrency_limits=_GENEROUS_LIMITS)
    book, game = (
        await seed_book_fixture(run_store, project_store),
        await seed_game_fixture(run_store, project_store),
    )
    for run_id in (book.run_id, game.run_id):
        await get_dag_run_store().start_run(
            run_id=run_id, user_id=_REVIEWER, workspace_id=PACK_FIXTURE_WORKSPACE_ID
        )

    # Opening is a read: canonical statuses are exactly what seeding left.
    book_detail = await visible_run_detail(_REVIEWER, book.run_id)
    assert book_detail is not None
    game_detail = await visible_run_detail(_REVIEWER, game.run_id)
    assert game_detail is not None
    assert (await run_store.get_run(book.run_id)).status is RunStatus.COMPLETED
    assert (await run_store.get_run(game.run_id)).status is RunStatus.WAITING

    # No side door: a principal without membership on the fixture Workspace
    # cannot even learn the runs exist (#1174's 404-shape).
    assert await visible_run_detail(_FOREIGNER, book.run_id) is None
    assert await visible_run_detail(_FOREIGNER, game.run_id) is None
    foreign_listed = {row["id"] for row in await list_visible_runs(_FOREIGNER, limit=100)}
    assert book.run_id not in foreign_listed
    assert game.run_id not in foreign_listed
