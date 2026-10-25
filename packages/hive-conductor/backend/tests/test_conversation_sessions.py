"""Workspace-scoped conversation session metadata + SessionStore transcripts (#1822).

Does not invent a second transcript authority: metadata lives in a service-owned
JsonStore; message bodies go through maistro SessionStore. Unscoped legacy
`stores.chat_sessions` rows stay quarantined and are never auto-migrated.
"""

from __future__ import annotations

import pytest
from services import conversation_sessions, workspace_authority


@pytest.fixture(autouse=True)
def _clean_conversation_sessions():
    conversation_sessions.reset_for_tests()
    yield
    conversation_sessions.reset_for_tests()


async def _workspace(owner: str = "user", name: str = "Ops") -> str:
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
async def test_create_and_list_are_scoped_to_workspace() -> None:
    ws_a = await _workspace(name="A")
    ws_b = await _workspace(name="B")

    a1 = await conversation_sessions.create("user", ws_a, "alpha")
    a2 = await conversation_sessions.create("user", ws_a, "beta")
    b1 = await conversation_sessions.create("user", ws_b, "gamma")

    listed_a = await conversation_sessions.list_for("user", ws_a)
    listed_b = await conversation_sessions.list_for("user", ws_b)

    assert {r.session_id for r in listed_a} == {a1.session_id, a2.session_id}
    assert {r.session_id for r in listed_b} == {b1.session_id}
    assert all(r.workspace_id == ws_a for r in listed_a)
    assert all(r.workspace_id == ws_b for r in listed_b)


@pytest.mark.asyncio
async def test_foreign_workspace_is_isolated() -> None:
    ws_a = await _workspace(owner="user", name="Alice WS")
    ws_b = await _workspace(owner="user-bob-312", name="Bob WS")

    alice = await conversation_sessions.create("user", ws_a, "alice chat")
    bob = await conversation_sessions.create("user-bob-312", ws_b, "bob chat")

    with pytest.raises(Exception) as denied:
        await conversation_sessions.list_for("user", ws_b)
    assert getattr(denied.value, "status_code", None) == 404

    with pytest.raises(Exception) as foreign_get:
        await conversation_sessions.get("user", bob.session_id)
    assert getattr(foreign_get.value, "status_code", None) == 404

    with pytest.raises(Exception) as foreign_owned:
        conversation_sessions.require_owned("user", bob.session_id)
    assert getattr(foreign_owned.value, "status_code", None) == 404

    mine, msgs = await conversation_sessions.get("user", alice.session_id)
    assert mine.session_id == alice.session_id
    assert msgs == []


@pytest.mark.asyncio
async def test_append_and_get_roundtrip_via_session_store() -> None:
    ws = await _workspace()
    record = await conversation_sessions.create("user", ws, "thread")

    await conversation_sessions.append_turn(
        record.session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        turn_id="turn-1",
    )

    loaded, messages = await conversation_sessions.get("user", record.session_id)
    assert loaded.session_id == record.session_id
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "hello"),
        ("assistant", "hi there"),
    ]


@pytest.mark.asyncio
async def test_empty_tools_turn_idempotent_via_turn_id() -> None:
    ws = await _workspace()
    record = await conversation_sessions.create("user", ws, "idem")

    batch = [
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": "pong"},
    ]
    await conversation_sessions.append_turn(record.session_id, batch, turn_id="same-turn")
    await conversation_sessions.append_turn(record.session_id, batch, turn_id="same-turn")

    _loaded, messages = await conversation_sessions.get("user", record.session_id)
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_require_owned_optional_workspace_match() -> None:
    ws_a = await _workspace(name="A")
    ws_b = await _workspace(name="B")
    record = await conversation_sessions.create("user", ws_a, "scoped")

    assert conversation_sessions.require_owned("user", record.session_id).session_id == (
        record.session_id
    )
    assert (
        conversation_sessions.require_owned("user", record.session_id, workspace_id=ws_a).session_id
        == record.session_id
    )

    with pytest.raises(Exception) as mismatch:
        conversation_sessions.require_owned("user", record.session_id, workspace_id=ws_b)
    assert getattr(mismatch.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_list_for_roots_adr048_session_search() -> None:
    """CONNECT: list_for filters through maistro.sessions.search (ADR-048)."""
    ws = await _workspace(name="Search")
    hit = await conversation_sessions.create("user", ws, "alpha thread")
    miss = await conversation_sessions.create("user", ws, "beta thread")
    await conversation_sessions.append_turn(
        hit.session_id,
        [{"role": "user", "content": "find the neon widget"}],
        turn_id="t-hit",
    )
    await conversation_sessions.append_turn(
        miss.session_id,
        [{"role": "user", "content": "unrelated chatter"}],
        turn_id="t-miss",
    )

    unfiltered = await conversation_sessions.list_for("user", ws)
    assert {r.session_id for r in unfiltered} == {hit.session_id, miss.session_id}

    filtered = await conversation_sessions.list_for("user", ws, query="neon widget")
    assert [r.session_id for r in filtered] == [hit.session_id]


@pytest.mark.asyncio
async def test_unscoped_legacy_chat_sessions_are_not_listed() -> None:
    """AC-6: legacy stores.chat_sessions rows stay inaccessible via new APIs."""
    from datetime import UTC, datetime

    import stores
    from models.schemas import ChatSession

    ws = await _workspace()
    now = datetime.now(UTC)
    stores.chat_sessions["legacy-unscoped"] = ChatSession(
        id="legacy-unscoped",
        user_id="user",
        title="legacy",
        messages=[],
        created_at=now,
        updated_at=now,
    )
    try:
        listed = await conversation_sessions.list_for("user", ws)
        assert all(r.session_id != "legacy-unscoped" for r in listed)
        with pytest.raises(Exception) as missing:
            await conversation_sessions.get("user", "legacy-unscoped")
        assert getattr(missing.value, "status_code", None) == 404
    finally:
        stores.chat_sessions.pop("legacy-unscoped", None)
