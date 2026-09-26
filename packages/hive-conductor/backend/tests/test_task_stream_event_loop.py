"""The task stream must not pin the event loop on a stalled backend (#1180).

A real HTTP server stands in for maistro-server and stalls `GET /tasks/{id}`,
the call the websocket stream makes to check ownership before it polls. While
that call is in flight the loop has to keep serving everything else, and
cancelling the stream has to take effect at once rather than after the stall.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

_STALL_S = 2.0

_TASK_BODY = {
    "task_id": "t1",
    "status": "completed",
    "description": "ship it",
    "workspace": "/tmp/maistro-workspace",  # nosec B108 — static test fixture, mirrors TaskCreate's documented default
    "tier": 2,
    "phase": "completed",
    "progress": {"subtasks": 0, "completed": 0, "current": ""},
    "result": None,
    "created_at": "2026-06-20T00:00:00Z",
    "started_at": None,
    "completed_at": None,
}


class _StallingTaskServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    stall_s = _STALL_S


class _Handler(BaseHTTPRequestHandler):
    server: _StallingTaskServer

    def do_GET(self) -> None:
        if self.path.startswith("/tasks/"):
            # Only the first probe stalls; the stream's later polls answer at once.
            stall, self.server.stall_s = self.server.stall_s, 0.0
            time.sleep(stall)
            self._send(200, _TASK_BODY)
        elif self.path.startswith("/tasks"):
            self._send(200, {"items": [_TASK_BODY], "next_cursor": None, "count": 1})
        else:
            self._send(404, {})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        return None


@pytest.fixture
def task_server() -> Iterator[_StallingTaskServer]:
    from maistro.security.outbound import configure_outbound_policy

    server = _StallingTaskServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    configure_outbound_policy(_origin(server))
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _origin(server: _StallingTaskServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host!s}:{port}"


def _engine_over(server: _StallingTaskServer) -> Any:
    from adapters.task_backend import MaistroServerTaskBackend
    from services.engine import EngineService

    svc = EngineService()
    svc._backend = MaistroServerTaskBackend(base_url=_origin(server), api_key=None)
    return svc


async def test_stalled_ownership_probe_does_not_block_the_loop(
    task_server: _StallingTaskServer,
) -> None:
    svc = _engine_over(task_server)
    done = asyncio.Event()
    max_gap = 0.0

    async def _heartbeat() -> None:
        nonlocal max_gap
        last = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            max_gap = max(max_gap, now - last)
            last = now

    async def _consume() -> list[dict[str, Any]]:
        try:
            return [ev async for ev in svc.iter_task_events("t1", user_id="u1")]
        finally:
            done.set()

    beat = asyncio.create_task(_heartbeat())
    await asyncio.sleep(0.05)
    events = await _consume()
    await beat

    assert [e["status"] for e in events] == ["completed"]
    assert max_gap < 0.25, f"event loop stalled for {max_gap:.2f}s"


async def test_cancelling_the_stream_mid_stall_returns_promptly(
    task_server: _StallingTaskServer,
) -> None:
    svc = _engine_over(task_server)

    async def _consume() -> None:
        async for _ in svc.iter_task_events("t1", user_id="u1"):
            pass

    started = time.monotonic()
    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0.2)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert time.monotonic() - started < 0.7


async def test_sync_callers_reuse_one_owned_client_closed_on_stop(
    task_server: _StallingTaskServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.http import sync_client

    built: list[Any] = []

    def _counting(**kw: Any) -> Any:
        client = sync_client(**kw)
        built.append(client)
        return client

    monkeypatch.setattr("adapters.task_backend.sync_client", _counting)
    task_server.stall_s = 0.0
    svc = _engine_over(task_server)

    for _ in range(3):
        rec = await asyncio.to_thread(svc.get_task, "t1", user_id="u1")
        assert rec is not None and rec.id == "t1"
    for _ in range(2):
        assert [r.id for r in await asyncio.to_thread(svc.list_tasks)] == ["t1"]

    assert len(built) == 1
    assert not built[0].is_closed

    await svc.stop()
    assert built[0].is_closed
