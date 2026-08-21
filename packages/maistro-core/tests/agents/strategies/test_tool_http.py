"""Tests for HTTPToolExecutor: calls dev-tools-mcp and other HTTP tool servers."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maistro.agents.strategies.tool_http import HTTPToolExecutor


def _client_factory(handler: Any) -> type[httpx.AsyncClient]:
    """Build an httpx.AsyncClient subclass whose __init__ ignores kwargs except
    injecting our MockTransport -- HTTPToolExecutor constructs the client itself,
    so we patch the class rather than inject an instance."""
    transport = httpx.MockTransport(handler)

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    return _PatchedClient


async def test_call_returns_passed_summary_when_passed_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"passed": True, "summary": "all good"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor(base_url="http://dev-tools-mcp:8300")

    result = await executor.call("run_pytest", {"path": "tests/"})

    assert result == '"passed": true, "summary": "all good"'


async def test_call_returns_passed_default_summary_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"passed": True})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("run_pytest", {})

    assert result == '"passed": true, "summary": "OK"'


async def test_call_returns_failure_with_raw_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"passed": False, "summary": "2 failed", "raw_output": "traceback..."}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("run_pytest", {})

    assert result == '"passed": false, "summary": "2 failed"\ntraceback...'


async def test_call_returns_error_status_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "boom", "status": "failed"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("run_mypy", {})

    assert result == '"status": "failed", "error": "boom"'


async def test_call_returns_generic_json_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"foo": "bar"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("list_files", {"path": "."})

    assert result == json.dumps({"foo": "bar"}, indent=None)


async def test_call_truncates_generic_json_dump_to_3000_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    big_value = "x" * 5000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": big_value})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("list_files", {})

    assert len(result) == 3000


async def test_call_non_200_status_returns_error_with_body_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("run_bandit", {})

    assert result == "Error: HTTP 500 - internal server error"


async def test_call_request_exception_returns_error_string(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.call("run_ruff_check", {})

    assert result == "Error: connection refused"


async def test_base_url_trailing_slash_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor(base_url="http://dev-tools-mcp:8300/")

    await executor.call("foo", {})

    assert captured["url"] == "http://dev-tools-mcp:8300/tools/foo"


async def test_list_tools_returns_tools_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tools": [{"name": "run_pytest"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.list_tools()

    assert result == [{"name": "run_pytest"}]


async def test_list_tools_returns_empty_list_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.list_tools()

    assert result == []


async def test_list_tools_returns_empty_list_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    executor = HTTPToolExecutor()

    result = await executor.list_tools()

    assert result == []
