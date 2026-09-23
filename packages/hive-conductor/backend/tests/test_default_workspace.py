"""#1037 owner decision 2: a Workspace-less turn runs in the caller's default Workspace.

Driven against the real canonical Workspace store behind
`services.workspace_authority`; one leg runs the canonical store and Hive's
persisted claim on real SQLite files, and one simulates a second process that
won the durable claim first.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import stores
from models.workspace import WorkspacePresentation
from services import default_workspace, workspace_agent, workspace_authority

from maistro.workspaces.store import InMemoryWorkspaceStore


@pytest.fixture(autouse=True)
def canonical(monkeypatch: pytest.MonkeyPatch) -> InMemoryWorkspaceStore:
    store = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: store)
    default_workspace.reset_for_tests()
    _drop_recovery_evidence()
    agents_before = set(stores.agents.keys())
    yield store
    default_workspace.reset_for_tests()
    _drop_recovery_evidence()
    for key in set(stores.agents.keys()) - agents_before:
        stores.agents.pop(key, None)


def _drop_recovery_evidence() -> None:
    # The in-memory canonical fallback replays `stores.workspaces` into every
    # fresh store; one test's Workspaces must not reappear in the next.
    for key in list(stores.workspaces.keys()):
        stores.workspaces.pop(key, None)


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_first_call_creates_a_workspace_owned_by_the_caller(
    canonical: InMemoryWorkspaceStore,
) -> None:
    view = await default_workspace.resolve_default_workspace("alice")

    assert await workspace_authority.member_role("alice", view.id) == "owner"
    assert [w.workspace_id for w in await canonical.list_for_user("alice")] == [view.id]
    assert view.name == default_workspace.DEFAULT_WORKSPACE_NAME


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_later_and_concurrent_calls_return_the_same_workspace(
    canonical: InMemoryWorkspaceStore,
) -> None:
    concurrent = await asyncio.gather(
        *(default_workspace.resolve_default_workspace("alice") for _ in range(10))
    )
    later = await default_workspace.resolve_default_workspace("alice")

    assert {view.id for view in concurrent} == {later.id}
    assert len(await canonical.list_for_user("alice")) == 1


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_each_user_gets_their_own_default(canonical: InMemoryWorkspaceStore) -> None:
    alice, bob = await asyncio.gather(
        default_workspace.resolve_default_workspace("alice"),
        default_workspace.resolve_default_workspace("bob"),
    )

    assert alice.id != bob.id
    assert not await workspace_authority.is_member("bob", alice.id)
    assert not await workspace_authority.is_member("alice", bob.id)


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_a_deleted_default_is_replaced_never_resurrected(
    canonical: InMemoryWorkspaceStore,
) -> None:
    first = await default_workspace.resolve_default_workspace("alice")
    await workspace_authority.delete_workspace(first.id)

    replacement, again = await asyncio.gather(
        default_workspace.resolve_default_workspace("alice"),
        default_workspace.resolve_default_workspace("alice"),
    )

    assert replacement.id == again.id != first.id
    assert await canonical.get(first.id) is None
    assert [w.workspace_id for w in await canonical.list_for_user("alice")] == [replacement.id]


@pytest.mark.asyncio
async def test_a_revoked_default_is_not_handed_back(canonical: InMemoryWorkspaceStore) -> None:
    first = await default_workspace.resolve_default_workspace("alice")
    await workspace_authority.set_member(first.id, user_id="carol", role="owner")
    await workspace_authority.remove_member(first.id, user_id="alice")

    replacement = await default_workspace.resolve_default_workspace("alice")

    assert replacement.id != first.id
    assert await workspace_authority.member_role("alice", replacement.id) == "owner"
    assert not await workspace_authority.is_member("alice", first.id)
    assert await canonical.get(first.id) is not None


@pytest.mark.ac("ADR-092326-7ed7/AC-6")
@pytest.mark.contract("behavioral")
def test_the_default_route_returns_one_owned_workspace_with_its_agent(admin_client) -> None:
    first = admin_client.post("/v1/workspaces/default")
    second = admin_client.post("/v1/workspaces/default")

    assert first.status_code == second.status_code == 200
    body = first.json()
    workspace_id = body["workspace"]["id"]
    assert second.json() == body
    assert body["workspace_agent_id"] == workspace_agent.workspace_agent_id(workspace_id)
    assert body["persona_template_id"] == "program_manager"
    agent = stores.agents[body["workspace_agent_id"]]
    assert agent.workspace_id == workspace_id
    owners = [m for m in body["workspace"]["members"] if m["role"] == "owner"]
    assert len(owners) == 1
    assert admin_client.get(f"/v1/workspaces/{workspace_id}").status_code == 200


@pytest.mark.ac("ADR-092326-7ed7/AC-6")
@pytest.mark.contract("behavioral")
def test_the_default_route_keeps_the_workspaces_write_gate(authed_client) -> None:
    before = set(stores.agents.keys())

    response = authed_client.post("/v1/workspaces/default")

    assert response.status_code == 403
    assert set(stores.agents.keys()) == before


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_a_revoked_default_stays_retired_when_the_caller_is_readded() -> None:
    first = await default_workspace.resolve_default_workspace("alice")
    await workspace_authority.set_member(first.id, user_id="carol", role="owner")
    await workspace_authority.remove_member(first.id, user_id="alice")
    replacement = await default_workspace.resolve_default_workspace("alice")
    await workspace_authority.set_member(first.id, user_id="alice", role="viewer")

    assert (await default_workspace.resolve_default_workspace("alice")).id == replacement.id


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_a_default_the_caller_no_longer_owns_is_replaced() -> None:
    first = await default_workspace.resolve_default_workspace("alice")
    await workspace_authority.set_member(first.id, user_id="carol", role="owner")
    await workspace_authority.set_member(first.id, user_id="alice", role="viewer")

    replacement = await default_workspace.resolve_default_workspace("alice")

    assert replacement.id != first.id
    assert await workspace_authority.member_role("alice", replacement.id) == "owner"


@pytest.mark.asyncio
async def test_an_unreadable_durable_claim_is_skipped_not_looped_on(
    canonical: InMemoryWorkspaceStore,
) -> None:
    default_workspace._claims_store()._data[default_workspace.claim_key("alice", 0)] = None

    view = await default_workspace.resolve_default_workspace("alice")

    assert [w.workspace_id for w in await canonical.list_for_user("alice")] == [view.id]


@pytest.mark.ac("ADR-092326-7ed7/AC-6")
@pytest.mark.contract("behavioral")
def test_the_default_route_maps_a_scanner_outage_to_503(
    admin_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import agent_materialization

    async def _down(*_args, **_kwargs):
        raise RuntimeError("scanner offline")

    monkeypatch.setattr(agent_materialization, "scan_config", _down)

    response = admin_client.post("/v1/workspaces/default")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_a_blank_principal_is_refused() -> None:
    with pytest.raises(ValueError):
        await default_workspace.resolve_default_workspace("  ")


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_losing_the_durable_claim_to_another_process_converges_on_the_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.state import PersistedStore, State
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(tmp_path / "workspaces.db")
    state = State(db_path=str(tmp_path / "hive.db"))
    try:
        scopes = SqliteProjectScopeStore(conn)
        await scopes.ensure_schema()
        canonical = SqliteWorkspaceStore(conn, project_store=scopes)
        await canonical.ensure_schema()
        monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
        persisted = PersistedStore(state)
        persisted.initialize()
        monkeypatch.setattr(stores, "_persisted", persisted)

        winner = await canonical.create(creator_user_id="alice", name="Winner")
        # Another worker already claimed alice's first default; this process's
        # in-memory view has never seen that claim.
        default_workspace.reset_for_tests()
        assert persisted.put_raw_if_absent(
            default_workspace.CLAIM_STORE,
            default_workspace.claim_key("alice", 0),
            json.dumps({"user_id": "alice", "workspace_id": winner.workspace_id}),
        )
        workspace_authority.presentation_store()[winner.workspace_id] = WorkspacePresentation(
            workspace_id=winner.workspace_id,
            persona_template_id="personal",
            updated_at=datetime.now(UTC),
        )

        monkeypatch.setattr(default_workspace._claims_store(), "_data", {})
        resolved = await default_workspace.resolve_default_workspace("alice")
        owned = await canonical.list_for_user("alice")
    finally:
        state.close()
        await conn.close()

    assert resolved.id == winner.workspace_id
    assert [w.workspace_id for w in owned] == [winner.workspace_id]


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_a_winner_this_process_cannot_compose_is_unavailable_not_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.state import PersistedStore, State
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(tmp_path / "workspaces.db")
    state = State(db_path=str(tmp_path / "hive.db"))
    try:
        scopes = SqliteProjectScopeStore(conn)
        await scopes.ensure_schema()
        canonical = SqliteWorkspaceStore(conn, project_store=scopes)
        await canonical.ensure_schema()
        monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
        persisted = PersistedStore(state)
        persisted.initialize()
        monkeypatch.setattr(stores, "_persisted", persisted)

        # Another worker created and claimed alice's default; its presentation
        # never reached this process's cache.
        winner = await canonical.create(creator_user_id="alice", name="Winner")
        assert persisted.put_raw_if_absent(
            default_workspace.CLAIM_STORE,
            default_workspace.claim_key("alice", 0),
            json.dumps({"user_id": "alice", "workspace_id": winner.workspace_id}),
        )
        monkeypatch.setattr(default_workspace._claims_store(), "_data", {})

        with pytest.raises(default_workspace.DefaultWorkspaceUnavailable):
            await default_workspace.resolve_default_workspace("alice")
        owned = await canonical.list_for_user("alice")
    finally:
        state.close()
        await conn.close()

    assert [w.workspace_id for w in owned] == [winner.workspace_id]


@pytest.mark.asyncio
async def test_the_default_survives_a_sqlite_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.state import PersistedStore, State
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(tmp_path / "workspaces.db")
    try:
        scopes = SqliteProjectScopeStore(conn)
        await scopes.ensure_schema()
        canonical = SqliteWorkspaceStore(conn, project_store=scopes)
        await canonical.ensure_schema()
        monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)

        first_state = State(db_path=str(tmp_path / "hive.db"))
        first = PersistedStore(first_state)
        first.initialize()
        monkeypatch.setattr(stores, "_persisted", first)
        created = await default_workspace.resolve_default_workspace("alice")
        first_state.flush()
        first_state.close()

        second_state = State(db_path=str(tmp_path / "hive.db"))
        second = PersistedStore(second_state)
        second.initialize()
        monkeypatch.setattr(stores, "_persisted", second)
        default_workspace.reset_for_tests()
        workspace_authority.reset_for_tests()
        monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
        try:
            after_restart = await default_workspace.resolve_default_workspace("alice")
        finally:
            second_state.close()
        owned = await canonical.list_for_user("alice")
    finally:
        await conn.close()

    assert after_restart.id == created.id
    assert [w.workspace_id for w in owned] == [created.id]


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-4")
@pytest.mark.contract("behavioral")
async def test_a_later_generation_another_process_claimed_wins_over_the_cached_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.state import PersistedStore, State
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(tmp_path / "workspaces.db")
    state = State(db_path=str(tmp_path / "hive.db"))
    try:
        scopes = SqliteProjectScopeStore(conn)
        await scopes.ensure_schema()
        canonical = SqliteWorkspaceStore(conn, project_store=scopes)
        await canonical.ensure_schema()
        monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
        persisted = PersistedStore(state)
        persisted.initialize()
        monkeypatch.setattr(stores, "_persisted", persisted)

        retired = await default_workspace.resolve_default_workspace("alice")
        # Another worker saw alice demoted, retired generation 0 and claimed
        # generation 1; alice was later restored as an owner of the old one.
        # This process's claim cache still holds generation 0 only.
        successor = await canonical.create(creator_user_id="alice", name="Successor")
        workspace_authority.presentation_store()[successor.workspace_id] = WorkspacePresentation(
            workspace_id=successor.workspace_id,
            persona_template_id="personal",
            updated_at=datetime.now(UTC),
        )
        assert persisted.put_raw_if_absent(
            default_workspace.CLAIM_STORE,
            default_workspace.claim_key("alice", 1),
            json.dumps({"user_id": "alice", "workspace_id": successor.workspace_id}),
        )
        assert await workspace_authority.member_role("alice", retired.id) == "owner"

        resolved = await default_workspace.resolve_default_workspace("alice")
    finally:
        state.close()
        await conn.close()

    assert resolved.id == successor.workspace_id


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-6")
@pytest.mark.contract("behavioral")
async def test_the_default_route_refuses_a_request_with_no_principal() -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes import workspaces as workspace_routes

    before = set(stores.agents.keys())

    with pytest.raises(HTTPException) as refused:
        await workspace_routes.ensure_default_workspace(
            SimpleNamespace(state=SimpleNamespace(user=None))
        )

    assert refused.value.status_code == 401
    assert set(stores.agents.keys()) == before


@pytest.mark.ac("ADR-092326-7ed7/AC-6")
@pytest.mark.contract("behavioral")
def test_the_default_route_maps_a_foreign_agent_row_to_409(
    admin_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routes import workspaces as workspace_routes

    async def _held_by_another_workspace(workspace_id: str):
        raise workspace_agent.WorkspaceAgentConflict(f"{workspace_id} is held elsewhere")

    monkeypatch.setattr(workspace_routes, "resolve_workspace_agent", _held_by_another_workspace)

    response = admin_client.post("/v1/workspaces/default")

    assert response.status_code == 409
    assert "held elsewhere" in response.json()["detail"]
