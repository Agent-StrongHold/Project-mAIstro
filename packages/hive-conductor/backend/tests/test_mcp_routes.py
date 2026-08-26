"""Route-level coverage for routes/mcp.py (servers CRUD + health-check + test/discover).

`services.mcp_client.test_mcp_server` (real network I/O) and httpx calls in
`_health_check` are mocked/avoided — servers use non-Atlassian, unroutable
URLs so the `_health_check` "disconnected" branch is reached deterministically
without actually depending on network availability in CI.
"""

from __future__ import annotations

import logging
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


# --------------------------------------------------------------------------- #
# Outbound policy on the health path (#368)
# --------------------------------------------------------------------------- #


class TestAPolicyRefusalIsNotADownServer:
    """Both fail the health check; they need opposite responses.

    A refused origin will be refused on every future check until an operator
    configures it or changes the URL. A server that is down comes back when it
    is started. Reporting both as `disconnected` — which the old
    `except Exception` did — hid a standing authorization decision behind a
    status that reads as transient.
    """

    def test_a_loopback_url_is_refused_not_reported_as_down(self, admin_client: Any) -> None:
        """The attacker-controlled stored URL case: anyone who can register an
        MCP server could point it at loopback. The guard blocks it; this pins
        that the *report* says so."""
        stores.mcp_servers["s1"] = _make_server(url="http://127.0.0.1:9/")
        body = admin_client.get("/v1/mcp/servers").json()[0]
        assert body["status"] == "error"
        assert "refused by outbound policy" in body["last_error"]

    def test_the_metadata_endpoint_is_refused(self, admin_client: Any) -> None:
        stores.mcp_servers["s1"] = _make_server(url="http://169.254.169.254/latest/meta-data/")
        body = admin_client.get("/v1/mcp/servers").json()[0]
        assert body["status"] == "error"

    def test_a_private_range_url_is_refused(self, admin_client: Any) -> None:
        stores.mcp_servers["s1"] = _make_server(url="http://10.0.0.1/")
        assert admin_client.get("/v1/mcp/servers").json()[0]["status"] == "error"

    def test_a_non_http_scheme_is_refused(self, admin_client: Any) -> None:
        stores.mcp_servers["s1"] = _make_server(url="file:///etc/passwd")
        assert admin_client.get("/v1/mcp/servers").json()[0]["status"] == "error"

    def test_an_unresolvable_host_stays_disconnected(self, admin_client: Any) -> None:
        """The other direction, and the reason this is not simply "any block is
        an error". The guard fails closed on a host it cannot resolve, which is
        the same situation as a server being down — calling that a policy
        refusal would be a new inaccuracy in place of the old one."""
        stores.mcp_servers["s1"] = _make_server(url="http://example.invalid/")
        body = admin_client.get("/v1/mcp/servers").json()[0]
        assert body["status"] == "disconnected"
        assert body["last_error"] is None

    def test_the_refusal_names_the_origin_not_the_url(self, admin_client: Any) -> None:
        """A stored MCP URL can carry a token in its query string or userinfo,
        and `last_error` is returned to the browser."""
        stores.mcp_servers["s1"] = _make_server(url="http://user:pw@127.0.0.1:9/?token=secret123")
        body = admin_client.get("/v1/mcp/servers").json()[0]
        assert "secret123" not in body["last_error"]
        assert "user:pw" not in body["last_error"]

    def test_a_healthy_server_carries_no_error(self, admin_client: Any, monkeypatch) -> None:
        """`last_error` has to be cleared on recovery, or a server that was
        refused once keeps explaining itself after the URL is corrected."""
        stores.mcp_servers["s1"] = _make_server(url="http://127.0.0.1:9/")
        assert admin_client.get("/v1/mcp/servers").json()[0]["last_error"]
        stores.mcp_servers["s1"] = stores.mcp_servers["s1"].model_copy(
            update={"url": "http://example.invalid/"}
        )
        assert admin_client.get("/v1/mcp/servers").json()[0]["last_error"] is None


class TestTheFanOutIsBounded:
    def test_a_listing_does_not_open_one_connection_per_server(
        self, admin_client: Any, monkeypatch
    ) -> None:
        """One GET used to `asyncio.gather` over the whole store, so a caller
        who can add servers could turn a single request into arbitrarily many
        concurrent outbound connections."""
        import routes.mcp as mcp_routes

        for index in range(40):
            stores.mcp_servers[f"s{index}"] = _make_server(sid=f"s{index}")

        peak = 0
        live = 0
        real = mcp_routes._health_check

        async def counted(server, **kwargs):
            nonlocal peak, live
            live += 1
            peak = max(peak, live)
            try:
                return await real(server, **kwargs)
            finally:
                live -= 1

        monkeypatch.setattr(mcp_routes, "_health_check", counted)
        admin_client.get("/v1/mcp/servers")
        assert peak <= mcp_routes.HEALTH_FANOUT_LIMIT, f"peak concurrency was {peak}"

    def test_every_server_is_still_checked(self, admin_client: Any) -> None:
        """Bounding the fan-out must not drop anyone from the result."""
        for index in range(20):
            stores.mcp_servers[f"s{index}"] = _make_server(sid=f"s{index}")
        assert len(admin_client.get("/v1/mcp/servers").json()) == 20


class TestOneBadRecordCannotBreakTheListing:
    """`POST /v1/mcp/servers` takes `url` as an unrestricted string, so both of
    these are reachable by any authenticated user who can register a server —
    and a single bad record used to break the listing for **every** server, not
    just its own row (#430).

    Both were introduced by #368's narrowing. That narrowing was right — a
    policy refusal and a down server needed to stop reporting identically — but
    the `except Exception` it replaced had been absorbing two exceptions the
    guard never translated.
    """

    def test_a_malformed_ipv6_url_does_not_500_the_listing(self, admin_client: Any) -> None:
        """`outbound_origin` re-parsed a URL the guard had already rejected, and
        its `urlsplit` raised `ValueError: Invalid IPv6 URL` — not an
        `httpx.HTTPError`, so it escaped the refusal branch it was inside."""
        stores.mcp_servers["s1"] = _make_server(url="http://[::1")
        response = admin_client.get("/v1/mcp/servers")
        assert response.status_code == 200

    def test_an_over_long_dns_label_does_not_500_the_listing(self, admin_client: Any) -> None:
        """An ASCII label longer than 63 characters parses as a URL but is
        invalid for DNS, and `socket.getaddrinfo` raises `UnicodeError` rather
        than `socket.gaierror`, which the guard does not translate."""
        stores.mcp_servers["s1"] = _make_server(url=f"http://{'a' * 64}.example.com/")
        response = admin_client.get("/v1/mcp/servers")
        assert response.status_code == 200

    def test_a_good_server_still_lists_beside_a_bad_one(self, admin_client: Any) -> None:
        """The consequence that made this worth a P1: one unusable record took
        the whole listing with it."""
        stores.mcp_servers["bad"] = _make_server(sid="bad", url="http://[::1")
        stores.mcp_servers["ok"] = _make_server(sid="ok", url="http://example.invalid/")
        body = admin_client.get("/v1/mcp/servers").json()
        assert {s["id"] for s in body} == {"bad", "ok"}

    def test_an_unparseable_url_is_reported_as_unusable_not_as_down(
        self, admin_client: Any
    ) -> None:
        """The distinction #368 established has to survive the fix. A URL that
        cannot be parsed is not a server that is down: no amount of starting it
        will help."""
        stores.mcp_servers["s1"] = _make_server(url="http://[::1")
        body = admin_client.get("/v1/mcp/servers").json()[0]
        assert body["status"] == "error"
        assert body["last_error"]

    def test_an_over_long_label_reads_as_unreachable(self, admin_client: Any) -> None:
        """The other direction: an over-long label is genuinely an unresolvable
        host, which is the same situation as a server being down."""
        stores.mcp_servers["s1"] = _make_server(url=f"http://{'a' * 64}.example.com/")
        assert admin_client.get("/v1/mcp/servers").json()[0]["status"] == "disconnected"

    def test_an_unexpected_failure_is_loud_and_not_reported_as_down(
        self, admin_client: Any, monkeypatch, caplog
    ) -> None:
        """The final fallback must not quietly recreate the defect #368
        removed. Something nobody anticipated is reported as `error` and logged
        at ERROR — never as `disconnected`, which reads as "start the server"."""
        import routes.mcp as mcp_routes

        def explode(*_args, **_kwargs):
            # Raised where `shared_client(...)` is *called*, before the
            # `async with`, so nothing is left un-awaited.
            raise RuntimeError("something nobody anticipated")

        monkeypatch.setattr(mcp_routes, "shared_client", explode)
        stores.mcp_servers["s1"] = _make_server(url="https://example.com/")
        with caplog.at_level(logging.ERROR):
            body = admin_client.get("/v1/mcp/servers").json()[0]
        assert body["status"] == "error"
        assert "could not be checked" in body["last_error"]
        assert any(record.levelno >= logging.ERROR for record in caplog.records)


class TestOutboundOriginIsTotal:
    """It is called to *describe* a refusal, so it must never be the thing that
    fails. `_check_shape` already reaches the same conclusion about these URLs
    safely — the describing step was the unguarded one."""

    @pytest.mark.parametrize("url", ["http://[::1", "http://[", "http://[:::]/x"])
    def test_an_unparseable_url_yields_a_sentinel(self, url) -> None:
        from maistro.security.outbound import outbound_origin

        assert outbound_origin(url)

    def test_the_sentinel_matches_no_configured_allowance(self) -> None:
        """The security property. An origin nobody can parse must never compare
        equal to one an operator authorized, or a malformed URL becomes a way
        past the allowlist."""
        from maistro.security.outbound import OutboundPolicy, outbound_origin

        policy = OutboundPolicy().with_origins(["https://api.example.com", "http://localhost:3000"])
        for url in ["http://[::1", "http://[", "http://[:::]/x"]:
            assert not policy.allows(url)
            assert outbound_origin(url) not in policy.origins
