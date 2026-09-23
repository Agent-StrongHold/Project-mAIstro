"""Shared PostgreSQL owns canonical Workspace identity in the shipped stack (#37).

Owner decision (2026-09-23): Hive's embedded runtime points at maistro-engine's
database, so its Container's ``workspace_store`` is the one durable Workspace/
Membership authority. On that path Hive's ``stores.workspaces`` recovery mirror
is legacy import input only: imported once, never written, never replayed.

Every test here boots the real ``MaistroCoreBridge`` against a real database
URL and a real Hive ``PersistedStore`` on disk, then restarts both, because a
restart against an in-process fake proves nothing about durability.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import stores
import yaml
from adapters.maistro_core import MaistroCoreBridge
from config import Settings
from models.workspace import Workspace, WorkspaceMember
from services import workspace_authority

from maistro.state import PersistedStore, State
from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.model import WorkspaceRole as CanonicalWorkspaceRole
from maistro.workspaces.store import InMemoryWorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[4]


def _database_url(backend: str, tmp_path: Path) -> str:
    if backend == "sqlite":
        return f"sqlite:///{tmp_path / 'canonical.db'}"
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the shared-PostgreSQL Workspace owner cannot be checked and must "
                "not be silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    return dsn


class _HiveProcess:
    """One Hive process lifetime: Hive's own state file plus the embedded bridge."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_url: str):
        self._state_db = tmp_path / "hive-state.db"
        self._monkeypatch = monkeypatch
        self._database_url = database_url
        self.state: State | None = None
        self.persisted: PersistedStore | None = None
        self.bridge: MaistroCoreBridge | None = None

    def open_hive_state(self) -> PersistedStore:
        self.state = State(db_path=str(self._state_db))
        self.persisted = PersistedStore(self.state)
        self.persisted.initialize()
        return self.persisted

    async def boot(self) -> None:
        import services.engine as engine_mod

        persisted = self.open_hive_state()
        self._monkeypatch.setattr(stores, "_persisted", persisted)
        self._monkeypatch.setattr(stores.workspaces, "_persisted", persisted)
        stores.workspaces.initialize()
        workspace_authority.reset_for_tests()

        self._monkeypatch.setenv("DATABASE_URL", self._database_url)
        self.bridge = MaistroCoreBridge()
        await self.bridge.start(
            Settings(
                maistro_router_api_key="k" * 32,
                maistro_agents_dir=str(REPO_ROOT / "agents"),
            )
        )
        self._monkeypatch.setattr(engine_mod.get_engine(), "_agent_port", self.bridge)

    async def stop(self) -> None:
        if self.bridge is not None and self.bridge.container is not None:
            await self.bridge.container.aclose()
        self.bridge = None
        self.close_hive_state()

    def close_hive_state(self) -> None:
        if self.state is not None:
            self.state.flush()
            self.state.close()
        self.state = None
        self.persisted = None

    def mirror_rows(self) -> dict[str, Workspace]:
        assert self.persisted is not None
        return {row.id: row for row in self.persisted.list_all("workspaces", Workspace)}

    @property
    def canonical(self) -> Any:
        assert self.bridge is not None
        return self.bridge.container.workspace_store


@pytest.fixture
async def hive(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[_HiveProcess]:
    monkeypatch.setattr(stores.workspaces, "_data", {})
    process = _HiveProcess(tmp_path, monkeypatch, _database_url(request.param, tmp_path))
    try:
        yield process
    finally:
        await process.stop()
        workspace_authority.reset_for_tests()


def _legacy(workspace_id: str, members: list[WorkspaceMember]) -> Workspace:
    created = datetime(2024, 1, 2, 3, 4, tzinfo=UTC)
    return Workspace(
        id=workspace_id,
        persona_template_id="pm_fleet",
        name=f"Legacy {workspace_id}",
        members=members,
        checklist=["tool:jira"],
        theme_id="default",
        created_at=created,
        updated_at=created,
    )


BACKENDS = pytest.mark.parametrize("hive", ["sqlite", "postgres"], indirect=True)


@BACKENDS
@pytest.mark.asyncio
async def test_bridge_with_database_url_makes_the_canonical_store_the_durable_authority(
    hive: _HiveProcess,
) -> None:
    await hive.boot()

    assert not isinstance(hive.canonical, InMemoryWorkspaceStore)
    assert await workspace_authority.canonical_workspace_store() is hive.canonical


@BACKENDS
@pytest.mark.asyncio
async def test_restart_keeps_revocations_and_deletions_without_any_mirror_writes(
    hive: _HiveProcess,
) -> None:
    await hive.boot()
    kept = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Kept",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    doomed = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Doomed",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    await workspace_authority.set_member(kept.id, user_id="bob", role="editor")
    await workspace_authority.remove_member(kept.id, user_id="bob")
    await workspace_authority.delete_workspace(doomed.id)

    assert hive.mirror_rows() == {}
    assert dict(stores.workspaces.items()) == {}

    await hive.stop()
    await hive.boot()

    view = await workspace_authority.get_view(kept.id)
    assert view is not None
    assert view.members == [WorkspaceMember(user_id="alice", role="owner")]
    assert not await workspace_authority.is_member("bob", kept.id)
    assert await hive.canonical.get(doomed.id) is None
    assert await workspace_authority.get_view(doomed.id) is None
    assert hive.mirror_rows() == {}

    await workspace_authority.delete_workspace(kept.id)


@BACKENDS
@pytest.mark.asyncio
async def test_legacy_mirror_rows_import_once_and_never_resurrect(
    hive: _HiveProcess,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    kept_id, doomed_id = f"legacy-kept-{suffix}", f"legacy-doomed-{suffix}"
    seeded = {
        kept_id: _legacy(
            kept_id,
            [
                WorkspaceMember(user_id="alice", role="owner"),
                WorkspaceMember(user_id="bob", role="editor"),
                WorkspaceMember(user_id="carol", role="viewer"),
            ],
        ),
        doomed_id: _legacy(doomed_id, [WorkspaceMember(user_id="alice", role="owner")]),
    }
    persisted = hive.open_hive_state()
    for workspace_id, row in seeded.items():
        persisted.put("workspaces", workspace_id, row)
    hive.close_hive_state()

    await hive.boot()
    view = await workspace_authority.visible_view("bob", kept_id)
    assert view is not None
    assert view.members == seeded[kept_id].members
    assert view.created_at == seeded[kept_id].created_at
    assert await hive.canonical.get(doomed_id) is not None

    # Revocation and deletion made through the shared store directly, the way
    # maistro-server's /v1/workspaces does against the same database.
    await hive.canonical.remove_membership(kept_id, user_id="bob")
    await hive.canonical.set_membership(
        kept_id, user_id="carol", role=CanonicalWorkspaceRole.CONTRIBUTOR
    )
    await hive.canonical.delete(doomed_id)
    assert hive.mirror_rows() == seeded

    for _ in range(2):
        await hive.stop()
        await hive.boot()
        assert await workspace_authority.is_member("alice", kept_id)
        assert not await workspace_authority.is_member("bob", kept_id)
        assert await workspace_authority.member_role("carol", kept_id) == "editor"
        assert await hive.canonical.get(doomed_id) is None
        assert not await workspace_authority.is_member("alice", doomed_id)
        assert hive.mirror_rows() == seeded

    await workspace_authority.delete_workspace(kept_id)
    await hive.stop()
    await hive.boot()
    assert await hive.canonical.get(kept_id) is None
    assert hive.mirror_rows() == seeded


@pytest.mark.asyncio
async def test_a_configured_database_without_a_container_refuses_the_mirror_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed bridge must not quietly revive the mirror as the authority."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://maistro:pw@postgres:5432/maistro")
    stores.workspaces["stale"] = _legacy("stale", [WorkspaceMember(user_id="alice", role="owner")])

    with pytest.raises(workspace_authority.CanonicalWorkspaceStoreUnavailable):
        await workspace_authority.is_member("alice", "stale")
    with pytest.raises(workspace_authority.CanonicalWorkspaceStoreUnavailable):
        await workspace_authority.canonical_workspace_store()


@pytest.mark.asyncio
async def test_without_a_database_the_ephemeral_fallback_still_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    store = await workspace_authority.canonical_workspace_store()

    assert isinstance(store, InMemoryWorkspaceStore)


def test_compose_hive_shares_the_engine_database_and_waits_for_its_migration() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    engine_env = set(services["maistro-engine"]["environment"])
    hive = services["hive-conductor"]
    hive_env = set(hive["environment"])

    shared = {
        item
        for item in engine_env
        if item.split("=", 1)[0] in {"DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"}
        or item.startswith("DB_PASSWORD=")
    }
    assert len(shared) == 6
    assert shared <= hive_env

    # maistro-engine's entrypoint migrates before it serves, so "healthy" is
    # "migrated". Hive never runs alembic itself.
    depends = hive["depends_on"]
    assert depends["maistro-engine"]["condition"] == "service_healthy"
    assert depends["postgres"]["condition"] == "service_healthy"
    assert services["maistro-engine"]["healthcheck"]["start_period"]
    assert "alembic" not in yaml.safe_dump(hive)


@pytest.mark.asyncio
async def test_a_pathless_sqlite_url_keeps_the_mirror_as_recovery_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sqlite://` is SQLite on `:memory:`: a restart loses it, so it is not durable."""
    monkeypatch.setattr(stores.workspaces, "_data", {})
    process = _HiveProcess(tmp_path, monkeypatch, "sqlite://")
    try:
        await process.boot()
        view = await workspace_authority.create_workspace(
            creator_user_id="alice",
            name="Ephemeral",
            persona_template_id="content_creator",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )

        assert view.id in process.mirror_rows()

        await process.stop()
        await process.boot()

        assert await workspace_authority.is_member("alice", view.id)
    finally:
        await process.stop()
        workspace_authority.reset_for_tests()
