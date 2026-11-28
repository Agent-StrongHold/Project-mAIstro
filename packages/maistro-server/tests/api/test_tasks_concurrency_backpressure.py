"""POST /tasks answers a full active-root-Run ceiling with 429, not 500 (#860 F9).

``RunConcurrencyExceeded`` is governed admission backpressure (#1182): the
ceiling is full, nothing about the request is wrong, and the identical request
becomes admissible once a slot frees. The soak's sustained admission profile
(#860) filled the per-principal ceiling within seconds and exposed the raw
exception escaping the handler as an unhandled 500 — a server-fault shape for
a designed rejection, plus a traceback per refused request.

The contract proven here, on the exact wiring production uses (router through
the process queue singleton onto a real Run spine, no runner started so
admitted Runs stay QUEUED and hold their slots):

- the submissions within the baseline ceiling answer 202;
- the submission that would exceed the per-principal ceiling answers
  **429** with a ``Retry-After`` header;
- a different principal is not punished for another principal's full ceiling
  (per-principal scoping is the ceiling's own contract);
- and a later submission succeeds once a slot frees (the backpressure is
  advisory, not a latched refusal).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import RunStatus
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.idempotency import InMemoryTaskIdempotencyStore
from maistro.tasks.queue import TaskQueue, configure_task_queue
from maistro_server.api.tasks import router as tasks_router

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired() -> AsyncIterator[tuple[TaskQueue, object, FastAPI]]:
    """Same shape as the idempotency contract tests: real spine, real router.

    The ceiling under test is the store's own configured limits, tightened to
    a small bound so the test fills it deterministically without depending on
    the baseline's numeric value.
    """
    previous = queue_module._queue
    queue_module._queue = None
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="test-workspace")
    run_store._concurrency_limits = RunConcurrencyLimits(per_principal=2, per_workspace=8)
    queue = configure_task_queue(
        admitter=admitter, idempotency_store=InMemoryTaskIdempotencyStore()
    )
    app = FastAPI()
    app.include_router(tasks_router)
    # Distinct principals must exist for the per-principal ceiling scoping to
    # be exercised; the settings override is the same pattern the idempotency
    # contract tests use for two-caller cases.
    app.dependency_overrides[get_settings] = lambda: Settings(
        api_keys=["alice:alice-secret", "bob:bob-secret"]
    )
    try:
        yield queue, run_store, app
    finally:
        queue_module._queue = previous


def _submit(client: TestClient, description: str, token: str = "alice-secret") -> object:
    return client.post(
        "/tasks",
        json={"description": description, "workspace": WORKSPACE},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.anyio
async def test_full_ceiling_answers_429_with_retry_after(wired: tuple) -> None:
    queue, run_store, app = wired
    with TestClient(app) as client:
        # No runner is started, so every admitted Run stays QUEUED and keeps
        # holding its active-root slot: the ceiling fills deterministically.
        first = _submit(client, "ceiling filler 1")
        assert first.status_code == 202, first.text
        second = _submit(client, "ceiling filler 2")
        assert second.status_code == 202, second.text

        refused = _submit(client, "one over the principal ceiling")
        assert refused.status_code == 429, refused.text
        assert "Retry-After" in refused.headers
        assert "ceiling" in refused.json()["detail"].lower()

        # A second principal's ceiling is independent: their first admission
        # must not be punished for the first principal's full slots.
        other = _submit(client, "other principal", token="bob-secret")
        assert other.status_code == 202, other.text

        # Backpressure is not a latched refusal: once a slot frees, the same
        # caller is admissible again.
        victim = next(
            r
            for r in run_store._runs.values()
            if r.status == RunStatus.QUEUED and r.actor_principal_id is not None
        )
        await run_store.transition_run(victim.run_id, RunStatus.CANCELLED)
        retried = _submit(client, "admissible again after a slot freed")
        assert retried.status_code == 202, retried.text
        assert queue is not None
