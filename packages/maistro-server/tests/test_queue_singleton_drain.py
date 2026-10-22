"""Shutdown drains the task-queue singleton's receipt writes (#849).

`_drain_queue_singleton` covers the straggler request that terminalized a task
after the runner stopped: its scheduled TaskRecord write would otherwise be
abandoned when the singleton is dropped. The drain is best-effort by contract —
shutdown must proceed even if the drain itself fails, because the canonical Run
still holds the truth and recovery reconciles from it. These tests pin both
halves: the singleton is drained on the shutdown path, and a failing drain is
logged, never raised into lifespan teardown.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_server import main as server_main


class _DrainStubQueue:
    """Just the one method the shutdown drain touches."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.drain_calls = 0

    async def drain_persistence(self, timeout: float = 5.0) -> int:
        self.drain_calls += 1
        if self._error is not None:
            raise self._error
        return 0


async def test_shutdown_drains_the_queue_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _DrainStubQueue()
    monkeypatch.setattr(server_main, "get_task_queue", lambda: stub)

    await server_main._drain_queue_singleton()

    assert stub.drain_calls == 1


async def test_shutdown_drain_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _DrainStubQueue(error=RuntimeError("receipt writer is down"))
    monkeypatch.setattr(server_main, "get_task_queue", lambda: stub)
    warned: list[str] = []

    async def awarning(event: str, **_kwargs: Any) -> None:
        warned.append(event)

    monkeypatch.setattr(
        server_main,
        "logger",
        type("_StubLogger", (), {"awarning": staticmethod(awarning)})(),
    )

    # The failure must not propagate: shutdown proceeds regardless.
    await server_main._drain_queue_singleton()

    assert stub.drain_calls == 1
    assert warned == ["task_receipt_drain_on_shutdown_failed"]
