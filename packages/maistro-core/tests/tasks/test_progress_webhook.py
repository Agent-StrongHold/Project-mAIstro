"""Tests for SPEC-175 task progress webhook."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus
from maistro.tasks.progress_webhook import (
    ConductorProgressPayload,
    ProgressWebhookNotifier,
    payload_from_task,
)
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_conductor_progress_payload_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        ConductorProgressPayload.model_validate(
            {"task_id": "x", "status": "queued", "extra_field": 1}
        )


@pytest.mark.ac("SPEC-175/AC-2")
@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_payload_from_task_maps_queue_snapshot() -> None:
    async def _inner() -> tuple[TaskQueue, TaskResponse]:
        q = TaskQueue()
        t = await q.submit(TaskCreate(description="hello", workspace="/tmp/x", tier=2))
        return q, t

    q, t = asyncio.run(_inner())
    snap = q.get(t.task_id)
    assert snap is not None
    p = payload_from_task(snap)
    assert p.task_id == t.task_id
    assert p.status == "queued"
    assert p.current_step == ""


@pytest.mark.ac("SPEC-175/AC-2")
@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
@pytest.mark.asyncio
async def test_progress_webhook_notifier_posts_json() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    notifier = ProgressWebhookNotifier(
        post_url="http://example.test/v1/conductor/progress",
        api_key="secret",
        client=client,
    )
    await notifier.notify(
        ConductorProgressPayload(
            task_id="tid1",
            status="planning",
            current_step="Analyzing…",
            steps_total=3,
            steps_completed=1,
        )
    )
    await notifier.aclose()
    await client.aclose()

    assert captured["url"] == "http://example.test/v1/conductor/progress"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["task_id"] == "tid1"
    assert captured["body"]["status"] == "planning"
    assert captured["body"]["current_step"] == "Analyzing…"
    assert captured["body"]["steps_total"] == 3
    assert captured["body"]["steps_completed"] == 1
    assert captured["body"]["details"] == {}
    assert captured["body"]["error"] is None


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
@pytest.mark.asyncio
@pytest.mark.ac("SPEC-175/AC-3")
async def test_progress_webhook_notifier_swallows_errors() -> None:
    attempts = 0

    def boom(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(boom)
    client = httpx.AsyncClient(transport=transport)
    notifier = ProgressWebhookNotifier(
        post_url="http://example.test/v1/conductor/progress",
        client=client,
    )
    await notifier.notify(ConductorProgressPayload(task_id="x", status="failed"))
    await notifier.aclose()
    await client.aclose()

    assert attempts == 1


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
@pytest.mark.ac("SPEC-175/AC-2")
async def test_task_runner_emits_webhook_snapshots() -> None:
    payloads: list[ConductorProgressPayload] = []

    class RecordingSink:
        async def notify(self, payload: ConductorProgressPayload) -> None:
            payloads.append(payload)

        async def aclose(self) -> None:
            return

    queue = TaskQueue()

    async def fake_exec(_req: TaskCreate) -> ConductorOutput:
        return ConductorOutput(
            success=True,
            code=CodeOutput(files_changed=["a.py"], description="ok"),
        )

    runner = TaskRunner(
        queue,
        executor=fake_exec,
        max_workers=2,
        progress_webhook=RecordingSink(),
    )
    await runner.start()
    submitted = await queue.submit(TaskCreate(description="job", workspace="/tmp/w", tier=1))

    while True:
        cur = queue.get(submitted.task_id)
        assert cur is not None
        if cur.status == TaskStatus.COMPLETED:
            break
        await queue.wait_for_update(submitted.task_id)

    await runner.stop(drain_timeout=5.0)

    statuses = {p.status for p in payloads}
    assert "planning" in statuses
    assert "coding" in statuses
    assert "completed" in statuses
    assert payloads[-1].status == "completed"
