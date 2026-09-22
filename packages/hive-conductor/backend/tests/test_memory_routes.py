"""Route-level coverage for routes/memory.py (namespaces + entries CRUD)."""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from hive_conductor.models.schemas import MemoryEntry  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_memory_entries():
    _clear(stores.memory_entries)
    yield
    _clear(stores.memory_entries)


# --------------------------------------------------------------------------- #
# /namespaces
# --------------------------------------------------------------------------- #


def test_list_namespaces_returns_seeded_values(authed_client: Any) -> None:
    r = authed_client.get("/v1/memory/namespaces")
    assert r.status_code == 200
    names = [n["name"] for n in r.json()]
    assert names == list(stores.memory_namespaces.keys())


# --------------------------------------------------------------------------- #
# /entries — list / filter
# --------------------------------------------------------------------------- #


def test_create_then_list_entries_no_filter(authed_client: Any) -> None:
    authed_client.post("/v1/memory/entries", json={"key": "k1", "value": "v1", "namespace": "a"})
    authed_client.post("/v1/memory/entries", json={"key": "k2", "value": "v2", "namespace": "b"})
    r = authed_client.get("/v1/memory/entries")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_list_entries_filtered_by_namespace(authed_client: Any) -> None:
    authed_client.post("/v1/memory/entries", json={"key": "k1", "value": "v1", "namespace": "a"})
    authed_client.post("/v1/memory/entries", json={"key": "k2", "value": "v2", "namespace": "b"})
    r = authed_client.get("/v1/memory/entries", params={"namespace": "a"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["namespace"] == "a"


# --------------------------------------------------------------------------- #
# /entries — create
# --------------------------------------------------------------------------- #


def test_create_entry_defaults(authed_client: Any) -> None:
    r = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"})
    assert r.status_code == 200
    body = r.json()
    assert body["namespace"] == "default"
    assert body["tags"] == []
    assert body["accessed_count"] == 0
    assert body["id"] in stores.memory_entries


def test_create_entry_with_tags(authed_client: Any) -> None:
    r = authed_client.post(
        "/v1/memory/entries",
        json={"key": "k", "value": "v", "namespace": "ns", "tags": ["t1", "t2"]},
    )
    assert r.json()["tags"] == ["t1", "t2"]
    assert r.json()["namespace"] == "ns"


def test_memory_operations_are_scoped_to_authenticated_owner(authed_client: Any) -> None:
    """A guessed body owner cannot make a global entry visible or mutable."""
    created = authed_client.post(
        "/v1/memory/entries",
        json={"key": "mine", "value": "mine", "user_id": "other-user"},
    )
    assert created.status_code == 200
    assert created.json()["user_id"] == "user"

    now = datetime.now(UTC)
    stores.memory_entries["foreign"] = MemoryEntry(
        id="foreign",
        user_id="other-user",
        key="foreign",
        value="private",
        created_at=now,
        updated_at=now,
    )

    listed = authed_client.get("/v1/memory/entries")
    assert [entry["id"] for entry in listed.json()] == [created.json()["id"]]
    assert authed_client.get("/v1/memory/entries/foreign").status_code == 404

    for method, path, kwargs in (
        ("put", "/v1/memory/entries/foreign", {"json": {"value": "changed"}}),
        ("delete", "/v1/memory/entries/foreign", {}),
        ("post", "/v1/memory/entries/foreign/reinforce", {}),
        ("post", "/v1/memory/entries/foreign/decay", {}),
        ("post", "/v1/memory/entries/foreign/contradict", {}),
    ):
        assert getattr(authed_client, method)(path, **kwargs).status_code == 404

    stats = authed_client.get("/v1/memory/stats")
    assert stats.json()["total"] == 1
    assert stores.memory_entries["foreign"].value == "private"


# --------------------------------------------------------------------------- #
# /entries/{id} — get
# --------------------------------------------------------------------------- #


def test_get_entry_found(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    r = authed_client.get(f"/v1/memory/entries/{eid}")
    assert r.status_code == 200
    assert r.json()["id"] == eid


def test_get_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.get("/v1/memory/entries/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "not found"


# --------------------------------------------------------------------------- #
# /entries/{id} — update
# --------------------------------------------------------------------------- #


def test_update_entry_partial_fields(authed_client: Any) -> None:
    eid = authed_client.post(
        "/v1/memory/entries", json={"key": "k", "value": "v", "tags": ["orig"]}
    ).json()["id"]
    r = authed_client.put(f"/v1/memory/entries/{eid}", json={"value": "new-value"})
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "new-value"
    assert body["key"] == "k"  # untouched field preserved
    assert body["tags"] == ["orig"]  # untouched field preserved


def test_update_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.put("/v1/memory/entries/missing", json={"value": "x"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /entries/{id} — delete
# --------------------------------------------------------------------------- #


def test_delete_entry_removes_it(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    r = authed_client.delete(f"/v1/memory/entries/{eid}")
    assert r.status_code == 204
    assert eid not in stores.memory_entries


def test_delete_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.delete("/v1/memory/entries/missing")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /entries/{id}/reinforce + /decay
# --------------------------------------------------------------------------- #


def test_reinforce_entry_increments_accessed_count(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    r = authed_client.post(f"/v1/memory/entries/{eid}/reinforce")
    assert r.status_code == 200
    assert r.json()["accessed_count"] == 1
    r2 = authed_client.post(f"/v1/memory/entries/{eid}/reinforce")
    assert r2.json()["accessed_count"] == 2


def test_reinforce_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.post("/v1/memory/entries/missing/reinforce")
    assert r.status_code == 404


def test_decay_entry_decrements_accessed_count(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    authed_client.post(f"/v1/memory/entries/{eid}/reinforce")
    authed_client.post(f"/v1/memory/entries/{eid}/reinforce")
    r = authed_client.post(f"/v1/memory/entries/{eid}/decay")
    assert r.json()["accessed_count"] == 1


def test_decay_entry_floors_at_zero(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    r = authed_client.post(f"/v1/memory/entries/{eid}/decay")
    assert r.json()["accessed_count"] == 0  # never goes negative


def test_decay_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.post("/v1/memory/entries/missing/decay")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /entries/{id}/contradict
# --------------------------------------------------------------------------- #


def test_contradict_entry_found(authed_client: Any) -> None:
    eid = authed_client.post("/v1/memory/entries", json={"key": "k", "value": "v"}).json()["id"]
    r = authed_client.post(f"/v1/memory/entries/{eid}/contradict")
    assert r.status_code == 200
    assert r.json() == {"status": "contradiction_registered"}


def test_contradict_entry_missing_404(authed_client: Any) -> None:
    r = authed_client.post("/v1/memory/entries/missing/contradict")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /stats
# --------------------------------------------------------------------------- #


def test_memory_stats_empty(authed_client: Any) -> None:
    r = authed_client.get("/v1/memory/stats")
    assert r.status_code == 200
    body = r.json()
    assert body == {"total": 0, "counts_by_namespace": {}, "avg_accessed_count": 0}


def test_memory_stats_with_entries(authed_client: Any) -> None:
    e1 = authed_client.post(
        "/v1/memory/entries", json={"key": "k1", "value": "v1", "namespace": "a"}
    ).json()["id"]
    authed_client.post("/v1/memory/entries", json={"key": "k2", "value": "v2", "namespace": "a"})
    authed_client.post(f"/v1/memory/entries/{e1}/reinforce")

    r = authed_client.get("/v1/memory/stats")
    body = r.json()
    assert body["total"] == 2
    assert body["counts_by_namespace"] == {"a": 2}
    assert body["avg_accessed_count"] == 0.5


# --------------------------------------------------------------------------- #
# chat-completion memory tools — non-HTTP callers of the owned store
# --------------------------------------------------------------------------- #


def _entry(eid: str, user_id: str, value: str) -> MemoryEntry:
    now = datetime.now(UTC)
    return MemoryEntry(
        id=eid,
        user_id=user_id,
        key=value[:60],
        value=value,
        namespace="general",
        tags=[],
        embedding=None,
        created_at=now,
        updated_at=now,
    )


async def test_chat_memory_add_stamps_owner_and_stores_entry() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_add

    result = await _tool_memory_add({"content": "remember this"}, user_id="u-chat", jira_pat=None)
    assert result["saved"] is True
    stored = stores.memory_entries[result["id"]]
    assert stored.user_id == "u-chat"
    assert stored.value == "remember this"


async def test_chat_memory_add_requires_content() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_add

    assert await _tool_memory_add({}, user_id="u-chat", jira_pat=None) == {
        "error": "content is required"
    }


async def test_chat_memory_search_scopes_to_owner_and_filters() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_search

    stores.memory_entries["own"] = _entry("own", "u-chat", "alpha secret")
    stores.memory_entries["foreign"] = _entry("foreign", "someone-else", "alpha private")

    unfiltered = await _tool_memory_search({}, user_id="u-chat", jira_pat=None)
    assert [e["id"] for e in unfiltered["results"]] == ["own"]
    assert unfiltered["count"] == 1

    own_match = await _tool_memory_search({"query": "secret"}, user_id="u-chat", jira_pat=None)
    assert [e["id"] for e in own_match["results"]] == ["own"]

    # A query matching only foreign content must not leak it.
    foreign_only = await _tool_memory_search({"query": "private"}, user_id="u-chat", jira_pat=None)
    assert foreign_only["results"] == []
    assert stores.memory_entries["foreign"].value == "alpha private"


async def test_chat_memory_delete_requires_entry_id() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_delete

    assert await _tool_memory_delete({}, user_id="u-chat", jira_pat=None) == {
        "error": "entry_id required"
    }


async def test_chat_memory_delete_is_scoped() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_delete

    stores.memory_entries["own"] = _entry("own", "u-chat", "mine")
    stores.memory_entries["foreign"] = _entry("foreign", "someone-else", "theirs")

    assert await _tool_memory_delete({"entry_id": "foreign"}, user_id="u-chat", jira_pat=None) == {
        "error": "not found"
    }
    assert "foreign" in stores.memory_entries

    assert await _tool_memory_delete({"entry_id": "own"}, user_id="u-chat", jira_pat=None) == {
        "deleted": True,
        "id": "own",
    }
    assert "own" not in stores.memory_entries

    assert await _tool_memory_delete({"entry_id": "missing"}, user_id="u-chat", jira_pat=None) == {
        "error": "not found"
    }


async def test_chat_memory_edit_not_found_is_scoped() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_edit

    stores.memory_entries["foreign"] = _entry("foreign", "someone-else", "theirs")

    assert await _tool_memory_edit(
        {"entry_id": "missing", "value": "x"}, user_id="u-chat", jira_pat=None
    ) == {"error": "not found"}
    assert await _tool_memory_edit(
        {"entry_id": "foreign", "value": "x"}, user_id="u-chat", jira_pat=None
    ) == {"error": "not found"}
    assert stores.memory_entries["foreign"].value == "theirs"


async def test_chat_memory_edit_requires_entry_id_and_value() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_edit

    assert await _tool_memory_edit({}, user_id="u-chat", jira_pat=None) == {
        "error": "entry_id and value required"
    }
    assert await _tool_memory_edit({"entry_id": "own"}, user_id="u-chat", jira_pat=None) == {
        "error": "entry_id and value required"
    }


async def test_chat_memory_edit_updates_value_key_and_tags() -> None:
    from hive_conductor.services.chat_completion import _tool_memory_edit

    stores.memory_entries["own"] = _entry("own", "u-chat", "before")

    updated = await _tool_memory_edit(
        {"entry_id": "own", "value": "after"}, user_id="u-chat", jira_pat=None
    )
    assert updated == {"updated": True, "id": "own", "value": "after"}
    row = stores.memory_entries["own"]
    assert row.value == "after"
    assert row.key == "after"
    assert row.user_id == "u-chat"

    # The tags branch overwrites the tag list; without it, tags are preserved.
    retagged = await _tool_memory_edit(
        {"entry_id": "own", "value": "after", "tags": ["a"]}, user_id="u-chat", jira_pat=None
    )
    assert retagged["updated"] is True
    assert stores.memory_entries["own"].tags == ["a"]
