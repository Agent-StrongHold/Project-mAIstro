"""Route-level coverage for routes/memory.py (namespaces + entries CRUD)."""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402


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
