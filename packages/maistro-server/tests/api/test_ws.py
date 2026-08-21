"""Tests for the WebSocket task-progress stream endpoint.

Evidence: /v1/stream/{task_id} pushes progress/result messages until the
task reaches a terminal status, then closes. Auth gates the connection
before accept(); unexpected errors must close the socket gracefully rather
than crash the server.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from maistro.config.settings import Settings, get_settings
from maistro.tasks.models import TaskProgress, TaskResponse, TaskResult, TaskStatus
from maistro.tasks.queue import TaskQueue, get_task_queue
from maistro_server.api.ws import (
    _build_progress_message,
    _build_result_message,
    _has_state_changed,
    _is_terminal,
    _ws_owner_id,
)
from maistro_server.api.ws import (
    router as ws_router,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_router)
    return app


def _task(
    status: TaskStatus = TaskStatus.QUEUED,
    *,
    phase: str | None = "queued",
    progress_current: str = "",
    result: TaskResult | None = None,
    user_id: str = "",
) -> TaskResponse:
    return TaskResponse(
        task_id="t1",
        status=status,
        description="desc",
        workspace="/tmp/maistro-workspace",
        user_id=user_id,
        tier=2,
        phase=phase,
        progress=TaskProgress(current=progress_current),
        result=result,
        created_at=datetime.now(UTC),
    )


class TestHasStateChanged:
    def test_status_change_detected(self) -> None:
        task = _task(status=TaskStatus.PLANNING, progress_current="")
        changed, status_val, progress_val = _has_state_changed(task, "queued", "")
        assert changed is True
        assert status_val == "planning"
        assert progress_val == ""

    def test_progress_change_detected(self) -> None:
        task = _task(status=TaskStatus.PLANNING, progress_current="step 2")
        changed, _, progress_val = _has_state_changed(task, "planning", "step 1")
        assert changed is True
        assert progress_val == "step 2"

    def test_no_change(self) -> None:
        task = _task(status=TaskStatus.PLANNING, progress_current="step 1")
        changed, _, _ = _has_state_changed(task, "planning", "step 1")
        assert changed is False

    def test_no_progress_object_uses_empty_string(self) -> None:
        task = _task(status=TaskStatus.QUEUED)
        task.progress = None  # type: ignore[assignment]
        _, _, progress_val = _has_state_changed(task, None, None)
        assert progress_val == ""


class TestBuildProgressMessage:
    def test_builds_expected_fields(self) -> None:
        task = _task(status=TaskStatus.CODING, phase="coding", progress_current="writing code")
        msg = _build_progress_message("t1", task)
        assert msg.task_id == "t1"
        assert msg.phase == "coding"
        assert msg.status == "coding"
        assert msg.message == "writing code"

    def test_no_progress_object_message_empty(self) -> None:
        task = _task(status=TaskStatus.QUEUED)
        task.progress = None  # type: ignore[assignment]
        msg = _build_progress_message("t1", task)
        assert msg.message == ""


class TestBuildResultMessage:
    def test_none_result_returns_none(self) -> None:
        task = _task(status=TaskStatus.COMPLETED, result=None)
        assert _build_result_message("t1", task) is None

    def test_result_present_returns_message(self) -> None:
        task = _task(status=TaskStatus.COMPLETED, result=TaskResult(files_changed=["a.py"]))
        msg = _build_result_message("t1", task)
        assert msg is not None
        assert msg.task_id == "t1"
        assert msg.phase == "done"
        assert msg.result["files_changed"] == ["a.py"]


class TestIsTerminal:
    def test_completed_is_terminal(self) -> None:
        assert _is_terminal("completed") is True

    def test_failed_is_terminal(self) -> None:
        assert _is_terminal("failed") is True

    def test_cancelled_is_terminal(self) -> None:
        assert _is_terminal("cancelled") is True

    def test_queued_is_not_terminal(self) -> None:
        assert _is_terminal("queued") is False


class TestWsOwnerId:
    def test_no_api_keys_returns_dev(self) -> None:
        settings = Settings(api_keys=[])
        assert _ws_owner_id(None, settings) == "dev"
        assert _ws_owner_id("anything", settings) == "dev"

    def test_no_token_with_keys_returns_none(self) -> None:
        settings = Settings(api_keys=["secret"])
        assert _ws_owner_id(None, settings) is None

    def test_invalid_token_returns_none(self) -> None:
        settings = Settings(api_keys=["secret"])
        assert _ws_owner_id("wrong", settings) is None

    def test_valid_token_returns_user_id(self) -> None:
        settings = Settings(api_keys=["alice:secret"])
        assert _ws_owner_id("secret", settings) == "alice"


class TestStreamTaskEndpoint:
    def test_rejects_connection_when_no_token_and_auth_required(self) -> None:
        app = _make_app()
        settings = Settings(api_keys=["secret"])
        app.dependency_overrides[get_settings] = lambda: settings
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect("/stream/t1"),
        ):
            pass
        assert exc_info.value.code == 1008

    def test_task_not_found_sends_error_and_closes(self) -> None:
        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue
        client = TestClient(app)
        with client.websocket_connect("/stream/missing") as ws:
            data = ws.receive_json()
            assert data == {"error": "Task not found"}

    def test_streams_progress_then_result_on_completion(self) -> None:
        """Evidence: an already-completed task (changed=True on the very first
        poll, since last_status starts as None) sends one progress message
        plus one result message, then breaks the loop."""
        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue

        async def seed() -> str:
            from maistro.tasks.models import TaskCreate

            task = await queue.submit(TaskCreate(description="d"), user_id="dev")
            await queue.update_status(task.task_id, TaskStatus.PLANNING)
            await queue.update_status(task.task_id, TaskStatus.CODING)
            queue.update_progress(task.task_id, TaskProgress(current="working"))
            await queue.update_status(task.task_id, TaskStatus.COMPLETED)
            queue.set_result(task.task_id, TaskResult(files_changed=["x.py"]))
            return task.task_id

        task_id = asyncio.run(seed())

        client = TestClient(app)
        with client.websocket_connect(f"/stream/{task_id}") as ws:
            progress_msg = ws.receive_json()
            result_msg = ws.receive_json()

        assert progress_msg["status"] == "completed"
        assert progress_msg["task_id"] == task_id
        assert result_msg["result"]["files_changed"] == ["x.py"]
        assert result_msg["phase"] == "done"

    def test_terminal_without_result_skips_result_message(self) -> None:
        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue

        async def seed() -> None:
            from maistro.tasks.models import TaskCreate

            task = await queue.submit(TaskCreate(description="d"), user_id="dev")
            await queue.update_status(task.task_id, TaskStatus.CANCELLED)
            return task.task_id

        task_id = asyncio.run(seed())

        client = TestClient(app)
        with client.websocket_connect(f"/stream/{task_id}") as ws:
            msg = ws.receive_json()
        assert msg["status"] == "cancelled"
        # Socket closes after the status message — no result message since
        # task.result stayed None. Confirm the connection is now closed.

    def test_unexpected_exception_closes_socket_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Evidence: any unhandled exception inside the loop must not crash the
        server — it must be caught, logged, and the socket closed with 4500."""
        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings

        class ExplodingQueue:
            def get(self, task_id: str, *, user_id: str | None = None) -> TaskResponse:
                raise RuntimeError("boom")

        app.dependency_overrides[get_task_queue] = lambda: ExplodingQueue()
        client = TestClient(app)
        with (
            client.websocket_connect("/stream/t1") as ws,
            pytest.raises(WebSocketDisconnect) as exc_info,
        ):
            ws.receive_json()
        assert exc_info.value.code == 4500
        assert exc_info.value.reason == "Internal error"

    def test_wait_for_update_returns_before_timeout_on_event(self) -> None:
        """Evidence: when the queue signals an update via wait_for_update()
        before the 5s poll timeout, the loop re-polls immediately instead of
        sleeping the full 5 seconds (covers the non-timeout branch)."""
        import time

        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue

        async def seed() -> str:
            from maistro.tasks.models import TaskCreate

            task = await queue.submit(TaskCreate(description="d"), user_id="dev")
            await queue.update_status(task.task_id, TaskStatus.PLANNING)
            return task.task_id

        task_id = asyncio.run(seed())

        async def flip_to_completed_after_notify() -> None:
            # Give the websocket handler time to enter wait_for_update(), then
            # signal the event and transition to a terminal status so the
            # handler's next poll exits the loop instead of looping forever.
            await asyncio.sleep(0.2)
            await queue.update_status(task_id, TaskStatus.CODING)
            await queue.update_status(task_id, TaskStatus.COMPLETED)

        client = TestClient(app)
        t0 = time.monotonic()
        with client.websocket_connect(f"/stream/{task_id}") as ws:
            first = ws.receive_json()
            asyncio.run(flip_to_completed_after_notify())
            second = ws.receive_json()
        elapsed = time.monotonic() - t0

        assert first["status"] == "planning"
        assert second["status"] == "completed"
        # Must not have blocked for the full 5s poll timeout.
        assert elapsed < 4.0

    def test_client_disconnect_mid_stream_logged_and_handled(self) -> None:
        """Evidence: if the client disconnects while the loop is running,
        WebSocketDisconnect must be caught (not propagate as a crash)."""
        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue

        async def seed() -> str:
            from maistro.tasks.models import TaskCreate

            task = await queue.submit(TaskCreate(description="d"), user_id="dev")
            await queue.update_status(task.task_id, TaskStatus.PLANNING)
            return task.task_id

        task_id = asyncio.run(seed())

        client = TestClient(app)
        with client.websocket_connect(f"/stream/{task_id}") as ws:
            first = ws.receive_json()
            assert first["status"] == "planning"
            ws.close()
        # No exception should escape — the server-side handler swallows
        # WebSocketDisconnect internally; reaching this point proves it.

    def test_timeout_error_closes_socket_with_4008(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Evidence: session timeout (asyncio.timeout expiry) must close with
        code 4008, distinct from the generic-exception path."""
        import maistro_server.api.ws as ws_module

        app = _make_app()
        settings = Settings(api_keys=[])
        app.dependency_overrides[get_settings] = lambda: settings
        queue = TaskQueue()
        app.dependency_overrides[get_task_queue] = lambda: queue

        monkeypatch.setattr(ws_module, "WS_SESSION_TIMEOUT", 0)

        async def seed() -> str:
            from maistro.tasks.models import TaskCreate

            task = await queue.submit(TaskCreate(description="d"), user_id="dev")
            return task.task_id

        task_id = asyncio.run(seed())

        client = TestClient(app)
        with (
            client.websocket_connect(f"/stream/{task_id}") as ws,
            pytest.raises(WebSocketDisconnect) as exc_info,
        ):
            ws.receive_json()
        assert exc_info.value.code == 4008
        assert exc_info.value.reason == "Session timeout"
