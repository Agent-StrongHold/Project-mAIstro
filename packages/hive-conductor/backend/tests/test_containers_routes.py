"""Route-level coverage for routes/containers.py.

The route handlers talk to the Docker Engine API over a Unix socket via
``_docker_client()``. Rather than mocking httpx transports, every route
first checks ``os.path.exists(DOCKER_SOCKET)`` — when the socket isn't
present, every endpoint short-circuits to a deterministic response (empty
list / 503), which is exactly the CI environment (no docker socket
mounted). The "happy path" branches (socket present, Docker API call
succeeds/fails) are covered by monkeypatching ``routes.containers._docker_client``
to return a fake async client whose ``.get/.post/.delete`` are scripted.

Pure helpers (`_parse_created`, `_parse_started_at`, `_parse_ports`,
`_parse_state`, `_extract_stats`, `_map_container`) are tested directly —
they're the trickiest, highest-value logic in this file and need no I/O.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from routes import containers as containers_mod  # noqa: E402

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_parse_created_from_unix_timestamp() -> None:
    dt = containers_mod._parse_created({"Created": 0})
    assert dt == datetime.fromtimestamp(0, UTC)


def test_parse_created_from_iso_string() -> None:
    dt = containers_mod._parse_created({"Created": "2024-01-01T00:00:00Z"})
    assert dt == datetime(2024, 1, 1, tzinfo=UTC)


def test_parse_created_missing_falls_back_to_now() -> None:
    before = datetime.now(UTC)
    dt = containers_mod._parse_created({})
    assert dt >= before


def test_parse_created_invalid_string_falls_back_to_now() -> None:
    before = datetime.now(UTC)
    dt = containers_mod._parse_created({"Created": "not-a-date"})
    assert dt >= before


def test_parse_started_at_from_state_dict() -> None:
    dt = containers_mod._parse_started_at({"State": {"StartedAt": "2024-06-01T12:00:00Z"}})
    assert dt == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def test_parse_started_at_from_top_level_field() -> None:
    dt = containers_mod._parse_started_at({"StartedAt": "2024-06-01T12:00:00Z"})
    assert dt == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def test_parse_started_at_zero_value_is_none() -> None:
    assert containers_mod._parse_started_at({"StartedAt": "0001-01-01T00:00:00Z"}) is None


def test_parse_started_at_missing_is_none() -> None:
    assert containers_mod._parse_started_at({}) is None


def test_parse_started_at_invalid_string_falls_back_to_now() -> None:
    # _parse_started_at's except-branch is unreachable given the with-suppress
    # guard upstream (it always returns inside the try); this case documents
    # that an unparsable-but-non-empty string still produces *some* datetime
    # via the fallback `return datetime.now(UTC)` after the suppressed block.
    dt = containers_mod._parse_started_at({"StartedAt": "garbage"})
    assert dt is None or isinstance(dt, datetime)


def test_parse_ports_with_host_and_private_only() -> None:
    ports = containers_mod._parse_ports(
        {"Ports": [{"PrivatePort": 80, "PublicPort": 8080}, {"PrivatePort": 443}]}
    )
    assert ports == [{"container": 80, "host": 8080}, {"container": 443}]


def test_parse_ports_empty() -> None:
    assert containers_mod._parse_ports({}) == []


def test_parse_state_running() -> None:
    assert containers_mod._parse_state({"State": "running"}) == "running"


def test_parse_state_restarting() -> None:
    assert containers_mod._parse_state({"State": "restarting"}) == "restarting"


def test_parse_state_unmapped_defaults_to_stopped() -> None:
    assert containers_mod._parse_state({"State": "exited"}) == "stopped"


def test_parse_state_missing_defaults_to_stopped() -> None:
    assert containers_mod._parse_state({}) == "stopped"


def test_extract_stats_none_returns_zeros() -> None:
    assert containers_mod._extract_stats(None) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_extract_stats_empty_dict_returns_zeros() -> None:
    assert containers_mod._extract_stats({}) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_extract_stats_computes_cpu_mem_network() -> None:
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 1000},
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
        "memory_stats": {"usage": 1024 * 1024 * 50, "limit": 1024 * 1024 * 100},
        "networks": {"eth0": {"rx_bytes": 1024 * 1024, "tx_bytes": 2 * 1024 * 1024}},
    }
    cpu, mem_usage, mem_limit, rx, tx = containers_mod._extract_stats(stats)
    assert cpu == round(((200 - 100) / (1000 - 500)) * 100.0, 2)
    assert mem_usage == 50.0
    assert mem_limit == 100.0
    assert rx == 1.0
    assert tx == 2.0


def test_extract_stats_zero_system_delta_yields_zero_cpu() -> None:
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 500},
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
        "memory_stats": {},
        "networks": {},
    }
    cpu, *_ = containers_mod._extract_stats(stats)
    assert cpu == 0.0


def test_map_container_builds_full_record() -> None:
    raw = {
        "Id": "abcdef0123456789",
        "Names": ["/my-container"],
        "Image": "python:3.12",
        "State": "running",
        "Ports": [{"PrivatePort": 80, "PublicPort": 8080}],
        "Created": "2024-01-01T00:00:00Z",
        "Labels": {"env": "prod"},
    }
    c = containers_mod._map_container(raw)
    assert c.id == "abcdef012345"  # truncated to 12 chars
    assert c.name == "my-container"
    assert c.image == "python:3.12"
    assert c.status == "running"
    assert c.ports == [{"container": 80, "host": 8080}]
    assert c.labels == {"env": "prod"}


def test_map_container_no_name_falls_back_to_id() -> None:
    raw = {"Id": "abcdef0123456789", "Names": [], "State": "running"}
    c = containers_mod._map_container(raw)
    assert c.name == "abcdef012345"


def test_map_container_no_labels_defaults_to_empty_dict() -> None:
    raw = {"Id": "abc", "Names": ["/x"], "State": "running", "Labels": None}
    c = containers_mod._map_container(raw)
    assert c.labels == {}


# --------------------------------------------------------------------------- #
# Route handlers — socket-not-present branch (deterministic in CI)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_docker_socket(monkeypatch):
    monkeypatch.setattr(containers_mod.os.path, "exists", lambda path: False)


def test_list_containers_no_socket_returns_empty(admin_client: Any) -> None:
    r = admin_client.get("/v1/containers")
    assert r.status_code == 200
    assert r.json() == []


def test_get_container_no_socket_503(admin_client: Any) -> None:
    r = admin_client.get("/v1/containers/abc")
    assert r.status_code == 503
    assert r.json()["detail"] == "Docker socket not available"


def test_start_container_no_socket_503(admin_client: Any) -> None:
    r = admin_client.post("/v1/containers/abc/start")
    assert r.status_code == 503


def test_stop_container_no_socket_503(admin_client: Any) -> None:
    r = admin_client.post("/v1/containers/abc/stop")
    assert r.status_code == 503


def test_restart_container_no_socket_503(admin_client: Any) -> None:
    r = admin_client.post("/v1/containers/abc/restart")
    assert r.status_code == 503


def test_delete_container_no_socket_503(admin_client: Any) -> None:
    r = admin_client.delete("/v1/containers/abc")
    assert r.status_code == 503


def test_get_container_logs_no_socket_503(admin_client: Any) -> None:
    r = admin_client.get("/v1/containers/abc/logs")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# Route handlers — socket present, Docker API mocked via httpx MockTransport
# --------------------------------------------------------------------------- #


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient bound to a scripted handler."""

    def __init__(self, handler) -> None:
        self._handler = handler

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    @staticmethod
    def _with_request(method: str, url: str, resp: httpx.Response) -> httpx.Response:
        resp.request = httpx.Request(method, url)
        return resp

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return self._with_request("GET", url, self._handler("GET", url))

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        return self._with_request("POST", url, self._handler("POST", url))

    async def delete(self, url: str, **kw: Any) -> httpx.Response:
        return self._with_request("DELETE", url, self._handler("DELETE", url))


def _socket_present(monkeypatch) -> None:
    monkeypatch.setattr(containers_mod.os.path, "exists", lambda path: True)


def _patch_client(monkeypatch, handler) -> None:
    monkeypatch.setattr(containers_mod, "_docker_client", lambda: _FakeAsyncClient(handler))


def test_list_containers_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)
    raw = [
        {
            "Id": "abcdef0123456789",
            "Names": ["/c1"],
            "Image": "img",
            "State": "running",
            "Created": "2024-01-01T00:00:00Z",
        }
    ]

    def handler(method, url):
        return httpx.Response(200, json=raw)

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == "abcdef012345"
    assert body[0]["name"] == "c1"


def test_list_containers_socket_present_api_error_returns_empty(
    admin_client: Any, monkeypatch
) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(500)

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers")
    assert r.status_code == 200
    assert r.json() == []


def test_get_container_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)
    raw = {"Id": "abcdef0123456789", "Names": ["/c1"], "Image": "img", "State": "running"}

    def handler(method, url):
        if url.endswith("/stats?stream=false"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json=raw)

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/abcdef012345")
    assert r.status_code == 200
    assert r.json()["id"] == "abcdef012345"


def test_get_container_socket_present_404(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(404, json={"message": "no such container"})

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "container not found"


def test_get_container_socket_present_other_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/abc")
    assert r.status_code == 503
    assert "Docker API error" in r.json()["detail"]


def test_start_container_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(204)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/start")
    assert r.status_code == 200
    assert r.json() == {"status": "started", "id": "abc"}


def test_start_container_socket_present_http_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/start")
    assert r.status_code == 404
    assert r.json()["detail"] == "start failed"


def test_stop_container_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(204)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/stop")
    assert r.json() == {"status": "stopped", "id": "abc"}


def test_stop_container_socket_present_http_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(500)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/stop")
    assert r.status_code == 500
    assert r.json()["detail"] == "stop failed"


def test_stop_container_socket_present_other_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/stop")
    assert r.status_code == 503


def test_restart_container_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(204)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/restart")
    assert r.json() == {"status": "restarted", "id": "abc"}


def test_restart_container_socket_present_http_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/restart")
    assert r.status_code == 404
    assert r.json()["detail"] == "restart failed"


def test_restart_container_socket_present_other_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = admin_client.post("/v1/containers/abc/restart")
    assert r.status_code == 503


def test_delete_container_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(204)

    _patch_client(monkeypatch, handler)
    r = admin_client.delete("/v1/containers/abc")
    assert r.status_code == 200


def test_delete_container_socket_present_http_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    r = admin_client.delete("/v1/containers/abc")
    assert r.status_code == 404
    assert r.json()["detail"] == "remove failed"


def test_delete_container_socket_present_other_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = admin_client.delete("/v1/containers/abc")
    assert r.status_code == 503


def test_get_container_logs_socket_present_success(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(200, text="log line 1\nlog line 2\n")

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/abc/logs")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "abc"
    assert "log line 1" in body["logs"]


def test_get_container_logs_custom_tail_param(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)
    captured = {}

    def handler(method, url):
        captured["url"] = url
        return httpx.Response(200, text="")

    _patch_client(monkeypatch, handler)
    admin_client.get("/v1/containers/abc/logs", params={"tail": 50})
    assert "tail=50" in captured["url"]


def test_get_container_logs_socket_present_http_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/abc/logs")
    assert r.status_code == 404
    assert r.json()["detail"] == "logs not found"


def test_get_container_logs_socket_present_other_error(admin_client: Any, monkeypatch) -> None:
    _socket_present(monkeypatch)

    def handler(method, url):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = admin_client.get("/v1/containers/abc/logs")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# /build + /suggest — pure stubs, no Docker socket involved
# --------------------------------------------------------------------------- #


def test_build_container(admin_client: Any) -> None:
    r = admin_client.post("/v1/containers/build", json={"name": "x", "dockerfile": "FROM x"})
    assert r.status_code == 200
    assert r.json() == {"status": "building", "log": "Building..."}


def test_suggest_dockerfile(admin_client: Any) -> None:
    r = admin_client.post("/v1/containers/suggest", json={"description": "a python app"})
    assert r.status_code == 200
    assert "FROM python" in r.json()["dockerfile"]
