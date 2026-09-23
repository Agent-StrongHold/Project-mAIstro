"""#1037 owner decision 1: one stable Workspace Agent per Workspace.

Driven against the real canonical stores: the canonical Workspace store behind
`services.workspace_authority` and the one product roster (`stores.agents`,
written only through `services.agent_materialization`). One leg runs both on
real SQLite files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import stores
from services import workspace_agent, workspace_authority

from maistro.workspaces.store import InMemoryWorkspaceStore


@pytest.fixture(autouse=True)
def canonical(monkeypatch: pytest.MonkeyPatch) -> InMemoryWorkspaceStore:
    store = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: store)
    before = set(stores.agents.keys())
    yield store
    for key in set(stores.agents.keys()) - before:
        stores.agents.pop(key, None)
    # The in-memory canonical fallback replays `stores.workspaces` into every
    # fresh store; one test's Workspaces must not reappear in the next.
    for key in list(stores.workspaces.keys()):
        stores.workspaces.pop(key, None)


async def _workspace(owner: str = "alice", name: str = "Ops") -> str:
    view = await workspace_authority.create_workspace(
        creator_user_id=owner,
        name=name,
        persona_template_id="personal",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    return view.id


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-1")
@pytest.mark.contract("behavioral")
async def test_repeated_resolution_returns_one_stable_agent_per_workspace() -> None:
    first_ws = await _workspace()
    second_ws = await _workspace(name="Other")

    first = await workspace_agent.resolve_workspace_agent(first_ws)
    again = await workspace_agent.resolve_workspace_agent(first_ws)
    other = await workspace_agent.resolve_workspace_agent(second_ws)

    assert first.id == again.id
    assert first.created_at == again.created_at
    assert other.id != first.id
    assert first.workspace_id == first_ws
    assert other.workspace_id == second_ws
    assert stores.agents[first.id].workspace_id == first_ws
    assert workspace_agent.persona_template_id(first) == "program_manager"


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-2")
@pytest.mark.contract("behavioral")
async def test_concurrent_first_resolution_materializes_exactly_one_agent() -> None:
    ws = await _workspace()

    resolved = await asyncio.gather(
        *(workspace_agent.resolve_workspace_agent(ws) for _ in range(10))
    )

    assert {agent.id for agent in resolved} == {resolved[0].id}
    assert {agent.created_at for agent in resolved} == {resolved[0].created_at}
    in_workspace = [a for a in stores.agents.values() if a.workspace_id == ws]
    assert [a.id for a in in_workspace] == [resolved[0].id]


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-3")
@pytest.mark.contract("behavioral")
async def test_swapping_the_persona_keeps_the_agent_identity() -> None:
    ws = await _workspace()
    original = await workspace_agent.resolve_workspace_agent(ws)

    swapped = await workspace_agent.set_workspace_agent_persona(ws, "risk_dependency")
    reread = await workspace_agent.resolve_workspace_agent(ws)

    assert swapped.id == original.id == reread.id
    assert swapped.created_at == original.created_at
    assert workspace_agent.persona_template_id(reread) == "risk_dependency"
    assert workspace_agent.persona_template_id(stores.agents[original.id]) == "risk_dependency"
    assert stores.agents[original.id].config["provenance"]["source"] == "workspace-agent"


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-3")
@pytest.mark.contract("behavioral")
async def test_persona_swap_racing_first_materialization_is_not_lost() -> None:
    ws = await _workspace()

    await asyncio.gather(
        workspace_agent.resolve_workspace_agent(ws),
        workspace_agent.set_workspace_agent_persona(ws, "delivery"),
        workspace_agent.resolve_workspace_agent(ws),
    )

    agent = await workspace_agent.resolve_workspace_agent(ws)
    assert workspace_agent.persona_template_id(agent) == "delivery"


@pytest.mark.asyncio
@pytest.mark.parametrize("persona", ["", "Program Manager", "../etc", "x" * 65])
@pytest.mark.ac("ADR-092326-7ed7/AC-3")
@pytest.mark.contract("behavioral")
async def test_an_unshaped_persona_is_refused_before_anything_is_written(persona: str) -> None:
    ws = await _workspace()
    original = await workspace_agent.resolve_workspace_agent(ws)

    with pytest.raises(ValueError):
        await workspace_agent.set_workspace_agent_persona(ws, persona)

    assert workspace_agent.persona_template_id(stores.agents[original.id]) == "program_manager"


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-1")
@pytest.mark.contract("behavioral")
async def test_a_missing_or_deleted_workspace_gets_no_agent(
    canonical: InMemoryWorkspaceStore,
) -> None:
    with pytest.raises(workspace_agent.WorkspaceNotFound):
        await workspace_agent.resolve_workspace_agent("no-such-workspace")
    assert workspace_agent.workspace_agent_id("no-such-workspace") not in stores.agents

    ws = await _workspace()
    await workspace_agent.resolve_workspace_agent(ws)
    await workspace_authority.delete_workspace(ws)
    assert await canonical.get(ws) is None

    with pytest.raises(workspace_agent.WorkspaceNotFound):
        await workspace_agent.resolve_workspace_agent(ws)
    with pytest.raises(workspace_agent.WorkspaceNotFound):
        await workspace_agent.set_workspace_agent_persona(ws, "delivery")


@pytest.mark.asyncio
async def test_the_workspace_agent_id_cannot_be_squatted_by_a_chat_created_action() -> None:
    from services.agent_materialization import chat_agent_id

    ws = await _workspace()
    aid = workspace_agent.workspace_agent_id(ws)

    for name in ("workspace-agent", f"x.{aid}", aid, "workspace.agent"):
        assert chat_agent_id(ws, name) != aid
        assert chat_agent_id(None, name) != aid


@pytest.mark.asyncio
async def test_a_foreign_row_under_the_agent_id_is_refused_not_adopted() -> None:
    from datetime import UTC, datetime

    from models.schemas import Agent
    from services.agent_materialization import upsert_agent_definition

    ws = await _workspace()
    other = await _workspace(name="Other")
    now = datetime.now(UTC)
    await upsert_agent_definition(
        Agent(
            id=workspace_agent.workspace_agent_id(ws),
            workspace_id=other,
            name="imposter",
            description="",
            model="x",
            status="idle",
            created_at=now,
        ),
        source="crud",
    )

    with pytest.raises(workspace_agent.WorkspaceAgentConflict):
        await workspace_agent.resolve_workspace_agent(ws)


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-5")
@pytest.mark.contract("behavioral")
async def test_the_canonical_roster_gains_only_the_workspace_agents() -> None:
    before = dict(stores.agents.items())
    first_ws = await _workspace()
    second_ws = await _workspace(name="Other")

    for ws in (first_ws, second_ws, first_ws, second_ws):
        await workspace_agent.resolve_workspace_agent(ws)

    added = set(stores.agents.keys()) - set(before)
    assert added == {
        workspace_agent.workspace_agent_id(first_ws),
        workspace_agent.workspace_agent_id(second_ws),
    }
    assert not any(key.startswith("agent-") for key in added)
    names = [a.name for a in stores.agents.values()]
    assert len(names) == len(set(names))


@pytest.mark.asyncio
@pytest.mark.ac("ADR-092326-7ed7/AC-2")
@pytest.mark.ac("ADR-092326-7ed7/AC-3")
@pytest.mark.contract("behavioral")
async def test_identity_and_persona_survive_a_sqlite_restart(
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

        state = State(db_path=str(tmp_path / "hive.db"))
        persisted = PersistedStore(state)
        persisted.initialize()
        monkeypatch.setattr(stores, "_persisted", persisted)
        monkeypatch.setattr(stores.agents, "_persisted", persisted)
        try:
            ws = await _workspace()
            resolved = await asyncio.gather(
                *(workspace_agent.resolve_workspace_agent(ws) for _ in range(10))
            )
            await workspace_agent.set_workspace_agent_persona(ws, "delivery")
            state.flush()

            reopened = PersistedStore(state)
            reopened.initialize()
            rows = {
                row.id: row
                for row in reopened.list_all("agents", type(resolved[0]))
                if row.workspace_id == ws
            }
        finally:
            monkeypatch.setattr(stores.agents, "_persisted", None)
            state.close()
    finally:
        await conn.close()

    assert list(rows) == [resolved[0].id]
    assert workspace_agent.persona_template_id(rows[resolved[0].id]) == "delivery"
