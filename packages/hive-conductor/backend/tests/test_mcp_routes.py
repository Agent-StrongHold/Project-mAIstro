"""Route-level coverage for routes/mcp.py (servers CRUD + health-check + test/discover).

`services.mcp_client.test_mcp_server` (real network I/O) and httpx calls in
`_health_check` are mocked/avoided — servers use non-Atlassian, unroutable
URLs so the `_health_check` "disconnected" branch is reached deterministically
without actually depending on network availability in CI.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from models.schemas import MCPServer, MCPTool  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_mcp_stores():
    _clear(stores.mcp_servers)
    _clear(stores.mcp_tools)
    yield
    _clear(stores.mcp_servers)
    _clear(stores.mcp_tools)


def _make_server(sid: str = "s1", url: str = "http://example.invalid") -> MCPServer:
    return MCPServer(
        id=sid, name="Server", description="d", url=url, status="connecting", tools_count=0
    )


# --------------------------------------------------------------------------- #
# GET /servers — health-checks every server
# --------------------------------------------------------------------------- #


def test_list_servers_marks_non_atlassian_unreachable_as_disconnected(admin_client: Any) -> None:
    stores.mcp_servers["s1"] = _make_server()
    r = admin_client.get("/v1/mcp/servers")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["status"] == "disconnected"
    assert stores.mcp_servers["s1"].status == "disconnected"


def test_list_servers_atlassian_rovo_url_uses_mcp_health_check(
    admin_client: Any, monkeypatch
) -> None:
    stores.mcp_servers["s1"] = _make_server(url="https://mcp.atlassian.com/foo")

    async def fake_test(server_id, *, user_id=None, url=""):
        return {"ok": True}

    monkeypatch.setattr("services.mcp_client.test_mcp_server", fake_test)

    r = admin_client.get("/v1/mcp/servers")
    body = r.json()
    assert body[0]["status"] == "connected"


def test_list_servers_atlassian_rovo_url_failed_check_is_connecting(
    admin_client: Any, monkeypatch
) -> None:
    stores.mcp_servers["s1"] = _make_server(url="https://mcp.atlassian.com/foo")

    async def fake_test(server_id, *, user_id=None, url=""):
        return {"ok": False}

    monkeypatch.setattr("services.mcp_client.test_mcp_server", fake_test)

    r = admin_client.get("/v1/mcp/servers")
    body = r.json()
    assert body[0]["status"] == "connecting"


def test_list_servers_empty(admin_client: Any) -> None:
    r = admin_client.get("/v1/mcp/servers")
    assert r.status_code == 200
    assert r.json() == []


# --------------------------------------------------------------------------- #
# GET /servers/{id}
# --------------------------------------------------------------------------- #


def test_get_server_found(admin_client: Any) -> None:
    stores.mcp_servers["s1"] = _make_server()
    r = admin_client.get("/v1/mcp/servers/s1")
    assert r.status_code == 200
    assert r.json()["id"] == "s1"


def test_get_server_missing_404(admin_client: Any) -> None:
    r = admin_client.get("/v1/mcp/servers/missing")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# POST /servers (admin-gated by middleware: "mcp.write")
# --------------------------------------------------------------------------- #


def test_add_server(admin_client: Any) -> None:
    r = admin_client.post(
        "/v1/mcp/servers", json={"name": "New", "description": "d", "url": "http://x"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New"
    assert body["status"] == "connecting"
    assert body["id"] in stores.mcp_servers


# --------------------------------------------------------------------------- #
# DELETE /servers/{id} (admin-gated: "mcp.delete")
# --------------------------------------------------------------------------- #


def test_delete_server(admin_client: Any) -> None:
    stores.mcp_servers["s1"] = _make_server()
    r = admin_client.delete("/v1/mcp/servers/s1")
    assert r.status_code == 204
    assert "s1" not in stores.mcp_servers


def test_delete_server_missing_404(admin_client: Any) -> None:
    r = admin_client.delete("/v1/mcp/servers/missing")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# POST /servers/{id}/scan
# --------------------------------------------------------------------------- #


def test_scan_server_found(admin_client: Any) -> None:
    stores.mcp_servers["s1"] = _make_server()
    r = admin_client.post("/v1/mcp/servers/s1/scan")
    assert r.status_code == 200
    assert r.json() == {"findings": [], "status": "clean"}


def test_scan_server_missing_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/mcp/servers/missing/scan")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# POST /test
# --------------------------------------------------------------------------- #


def test_test_connection_specific_server(admin_client: Any, monkeypatch) -> None:
    stores.mcp_servers["s1"] = _make_server()
    captured = {}

    async def fake_test(server_id, *, user_id=None, url=""):
        captured["server_id"] = server_id
        captured["url"] = url
        return {"ok": True, "mode": "stub"}

    monkeypatch.setattr("services.mcp_client.test_mcp_server", fake_test)

    r = admin_client.post("/v1/mcp/test", json={"server_id": "s1"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "mode": "stub"}
    assert captured["server_id"] == "s1"


def test_test_connection_missing_server_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/mcp/test", json={"server_id": "missing"})
    assert r.status_code == 404


def test_test_connection_no_server_id_tests_all(admin_client: Any, monkeypatch) -> None:
    stores.mcp_servers["s1"] = _make_server(sid="s1")
    stores.mcp_servers["s2"] = _make_server(sid="s2")

    async def fake_test(server_id, *, user_id=None, url=""):
        return {"ok": True, "server_id": server_id}

    monkeypatch.setattr("services.mcp_client.test_mcp_server", fake_test)

    r = admin_client.post("/v1/mcp/test", json={})
    assert r.status_code == 200
    results = r.json()["results"]
    assert {res["server_id"] for res in results} == {"s1", "s2"}


def test_test_connection_no_servers_returns_empty_results(admin_client: Any) -> None:
    r = admin_client.post("/v1/mcp/test", json={})
    assert r.json() == {"results": []}


# --------------------------------------------------------------------------- #
# GET /tools
# --------------------------------------------------------------------------- #


def test_list_tools(admin_client: Any) -> None:
    stores.mcp_tools["t1"] = MCPTool(
        id="t1", server_id="s1", name="tool", description="d", category="general"
    )
    r = admin_client.get("/v1/mcp/tools")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == ["t1"]


def test_list_tools_empty(admin_client: Any) -> None:
    r = admin_client.get("/v1/mcp/tools")
    assert r.json() == []


# --------------------------------------------------------------------------- #
# POST /discover
# --------------------------------------------------------------------------- #


def test_discover_tools(admin_client: Any) -> None:
    r = admin_client.post("/v1/mcp/discover", json={"url": "http://x"})
    assert r.status_code == 200
    assert r.json() == {"tools": [], "status": "scanning"}
