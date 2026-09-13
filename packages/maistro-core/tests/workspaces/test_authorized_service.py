"""Cross-scope conformance for the canonical authorized service boundary."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.security.sentinel.authz_types import Principal
from maistro.testing.postgres import postgres_dsn
from maistro.workspaces import (
    AuthorizedWorkspaceProjectService,
    WorkspaceProjectAccessDenied,
    WorkspaceRole,
)


class _MemoryBackend:
    def __init__(self) -> None:
        from maistro.workspaces.store import InMemoryWorkspaceStore

        projects = InMemoryProjectScopeStore()
        self.workspace = InMemoryWorkspaceStore(project_store=projects)
        self.project = projects

    async def close(self) -> None:
        return None


class _SqliteBackend:
    def __init__(self, tmp_path) -> None:
        self.path = tmp_path / "authorized-workspaces.db"
        self.connections = []

    async def open(self) -> None:
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        connection = await aiosqlite.connect(self.path)
        self.connections.append(connection)
        self.project = SqliteProjectScopeStore(connection)
        await self.project.ensure_schema()
        self.workspace = SqliteWorkspaceStore(connection, project_store=self.project)
        await self.workspace.ensure_schema()

    async def close(self) -> None:
        for connection in self.connections:
            await connection.close()


class _PostgresBackend:
    def __init__(self, pool) -> None:
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.workspaces.pg_store import PgWorkspaceStore

        self.project = PgProjectScopeStore(pool)
        self.workspace = PgWorkspaceStore(pool, project_store=self.project)
        self.pool = pool

    async def close(self) -> None:
        await self.pool.close()


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request, tmp_path) -> AsyncIterator[object]:
    if request.param == "memory":
        value = _MemoryBackend()
        yield value
        await value.close()
        return
    if request.param == "sqlite":
        value = _SqliteBackend(tmp_path)
        await value.open()
        yield value
        await value.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError("MAISTRO_REQUIRE_PG_LEGS requires MAISTRO_TEST_PG_DSN")
        pytest.skip("set MAISTRO_TEST_PG_DSN for the PostgreSQL service leg")
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    value = _PostgresBackend(pool)
    yield value
    await value.close()


def _principal(value: str) -> Principal:
    return Principal(id=value, kind="human")


async def test_two_principals_cannot_cross_read_or_mutate_selected_scopes(backend) -> None:
    alice = _principal(f"alice-{uuid4().hex}")
    bob = _principal(f"bob-{uuid4().hex}")
    service = AuthorizedWorkspaceProjectService(backend.workspace, backend.project)

    alice_workspace = await service.create_workspace(alice, name="Alice")
    bob_workspace = await service.create_workspace(bob, name="Bob")
    alice_root = await service.get_root_project(alice, alice_workspace.workspace_id)
    bob_root = await service.get_root_project(bob, bob_workspace.workspace_id)

    assert (await service.get_workspace(alice, alice_workspace.workspace_id)).name == "Alice"
    with pytest.raises(WorkspaceProjectAccessDenied, match="Workspace not found"):
        await service.get_workspace(alice, bob_workspace.workspace_id)
    with pytest.raises(WorkspaceProjectAccessDenied):
        await service.get_project(alice, bob_workspace.workspace_id, bob_root.project_id)

    with pytest.raises(WorkspaceProjectAccessDenied):
        await service.update_workspace(alice, bob_workspace.workspace_id, name="stolen")
    with pytest.raises(WorkspaceProjectAccessDenied):
        await service.create_project(
            alice,
            bob_workspace.workspace_id,
            parent_project_id=bob_root.project_id,
            name="cross-scope",
        )
    with pytest.raises(WorkspaceProjectAccessDenied):
        await service.update_project_defaults(
            alice,
            bob_workspace.workspace_id,
            bob_root.project_id,
            defaults={"model": "stolen"},
        )

    child = await service.create_project(
        alice,
        alice_workspace.workspace_id,
        parent_project_id=alice_root.project_id,
        name="owned",
    )
    assert child.workspace_id == alice_workspace.workspace_id
    assert await backend.project.get(bob_root.project_id) is not None


async def test_membership_delegation_uses_effective_authorization(backend) -> None:
    alice = _principal(f"owner-{uuid4().hex}")
    bob = _principal(f"member-{uuid4().hex}")
    cara = f"target-{uuid4().hex}"
    service = AuthorizedWorkspaceProjectService(backend.workspace, backend.project)
    workspace = await service.create_workspace(alice, name="Delegation")
    root = await service.get_root_project(alice, workspace.workspace_id)
    await backend.workspace.set_membership(
        workspace.workspace_id, user_id=bob.id, role=WorkspaceRole.CONTRIBUTOR
    )

    from maistro.projects.scope import ProjectMembership

    await backend.project.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id=bob.id,
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    granted = await service.add_project_membership(
        bob,
        workspace.workspace_id,
        root.project_id,
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id=cara,
            grants={"publish"},
        ),
    )
    assert granted.principal_id == cara

    with pytest.raises(WorkspaceProjectAccessDenied):
        await service.add_project_membership(
            bob,
            workspace.workspace_id,
            root.project_id,
            ProjectMembership(
                workspace_id=workspace.workspace_id,
                project_id=root.project_id,
                principal_id=f"other-{uuid4().hex}",
                grants={"delete"},
            ),
        )
