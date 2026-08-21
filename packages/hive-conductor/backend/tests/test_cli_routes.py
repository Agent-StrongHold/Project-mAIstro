"""Route-level coverage for routes/cli.py (CLI session bookkeeping)."""

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
def _clear_cli_sessions():
    _clear(stores.cli_sessions)
    yield
    _clear(stores.cli_sessions)


def test_list_cli_sessions_seeds_default_when_empty(authed_client: Any) -> None:
    r = authed_client.get("/v1/cli/sessions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == "default"
    assert body[0]["cwd"] == "/"
    assert body[0]["history"] == []
    assert "default" in stores.cli_sessions


def test_list_cli_sessions_does_not_reseed_when_nonempty(authed_client: Any) -> None:
    stores.cli_sessions["existing"] = {
        "id": "existing",
        "cwd": "/tmp",  # nosec B108 — fixture data for a CLI session record, not a filesystem write target
        "history": ["ls"],
    }
    r = authed_client.get("/v1/cli/sessions")
    body = r.json()
    assert [s["id"] for s in body] == ["existing"]


def test_create_cli_session_returns_new_session(authed_client: Any) -> None:
    r = authed_client.post("/v1/cli/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["cwd"] == "/"
    assert body["history"] == []
    assert len(body["id"]) == 8
    assert body["id"] in stores.cli_sessions


def test_create_cli_session_ids_are_unique(authed_client: Any) -> None:
    r1 = authed_client.post("/v1/cli/sessions").json()
    r2 = authed_client.post("/v1/cli/sessions").json()
    assert r1["id"] != r2["id"]
