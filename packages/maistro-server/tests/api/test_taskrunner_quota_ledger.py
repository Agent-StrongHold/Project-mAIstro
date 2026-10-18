"""The `/tasks` worker's conductor calls cross the canonical quota ledger (#718).

The server has two doors into the conductor LLM path. The chat door
(`ConductorAgent`) got the canonical effect authority in the #718 cutover;
the `/tasks` queue worker was left calling bare `run_task`, so every task it
completed left no Invocation and no quota evidence while per-provider rows
presented as complete. These tests drive the executor the lifespan actually
hands to `TaskRunner` — through a real Container, a real governed egress, and
a fake gateway — and observe the quota ledger move, including the
missing-usage case the issue says must surface as unreported evidence rather
than a measured zero.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
)
from maistro.credentials.types import CredentialRecord
from maistro.quota.usage_log import (
    InMemoryUsageLog,
    get_default_usage_log,
    set_default_usage_log,
)
from maistro.tasks.models import TaskCreate
from maistro_server.main import lifespan


class _FakeLoop:
    """Minimal event-loop stand-in for lifespan signal registration."""

    def __init__(self) -> None:
        self.add_signal_handler = MagicMock()

    async def run_in_executor(self, _executor: Any, func: Any) -> Any:
        return func()


class _FakeGatewayResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status_code = 200
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeGatewayClient:
    """Stand-in for `httpx.AsyncClient` that answers one canned body.

    Captures the request it served so the ledger entry can be tied back to
    the model alias the conductor actually asked for.
    """

    seen: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @property
    def is_closed(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _FakeGatewayResponse:
        cls = type(self)
        body = dict(cls.response_body)
        cls.seen.append({"url": url, **kwargs})
        return _FakeGatewayResponse(body)

    response_body: ClassVar[dict[str, Any]] = {}


@asynccontextmanager
async def _runner_with_real_container(
    monkeypatch: pytest.MonkeyPatch, gateway_body: dict[str, Any]
):
    """Run the real lifespan; yield the TaskRunner executor and its Container.

    Neither `_build_container` nor `run_task` is stubbed: the point is the
    composition the server actually installs, so the executor is captured
    where `TaskRunner` receives it and driven against the Container that
    `_build_container` really built.
    """
    monkeypatch.setenv("MAISTRO_DRY_RUN", "0")
    monkeypatch.setenv("ROUTER_API_KEY", "test-router-key")
    _FakeGatewayClient.response_body = dict(gateway_body)
    _FakeGatewayClient.seen = []
    # The container wires the process-default usage log into its effect
    # context; a fresh one per run keeps this test's ledger assertions about
    # this test's calls rather than whatever ran earlier in the suite.
    previous_log = get_default_usage_log()
    set_default_usage_log(InMemoryUsageLog())

    captured: dict[str, Any] = {}

    def _capture_runner(
        queue: Any, executor: Any, progress_webhook: Any = None, attempts: Any = None
    ):
        captured["executor"] = executor
        runner = MagicMock()
        runner.start = AsyncMock()
        runner.stop = AsyncMock()
        return runner

    test_app = MagicMock()
    test_app.state = MagicMock()

    try:
        with (
            patch("maistro.memory.store.get_engine", return_value=None),
            patch("maistro.memory.store.reset_engine_cache"),
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.TaskRunner", side_effect=_capture_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                container = test_app.state.container
                # The deployment's gateway key, registered in the scope the
                # conductor's Binding authorizes — exactly what
                # `bootstrap_model_bindings` does for a deployment that declares
                # model bindings. Without it the governed call refuses before any
                # HTTP, which is the fail-closed contract, not a bug.
                container.capability_effects.credentials.add(
                    workspace_id="default",
                    project_id="agent-runtime",
                    record=CredentialRecord(
                        key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
                        provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
                        api_key="test-gateway-key",
                    ),
                )
                with patch.object(httpx, "AsyncClient", _FakeGatewayClient):
                    yield captured["executor"], container
    finally:
        set_default_usage_log(previous_log)


def _gateway_body(*, usage: dict[str, int] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "conductor-test-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"plan": {"summary": "s", "subtasks": []},'
                        ' "final_answer": "done", "success": true}'
                    ),
                }
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


class TestTasksRunnerQuotaLedger:
    async def test_runner_conductor_call_moves_the_quota_ledger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A governed `/tasks` completion records Invocation-linked usage.

        The executor the lifespan installed must route the conductor's LLM
        call through the Container's canonical effect authority, so the
        physical call lands on the quota ledger with provider, token and
        Invocation identity — not as an invisible raw gateway POST.
        """
        async with _runner_with_real_container(
            monkeypatch, _gateway_body(usage={"prompt_tokens": 11, "completion_tokens": 5})
        ) as (executor, container):
            output = await executor(TaskCreate(description="ledger me"))

        assert output.success is True
        assert output.final_answer == "done"

        requested_model = _FakeGatewayClient.seen[0]["json"]["model"]
        assert _FakeGatewayClient.seen[0]["url"].endswith("/chat/completions")

        entries = await container.quota_tracker.get_all_usage()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["provider"] == requested_model
        assert entry["request_count"] == 1
        assert entry["input_tokens"] == 11
        assert entry["output_tokens"] == 5
        assert entry["total_tokens"] == 16
        # Reported usage presents as complete evidence, never silently so.
        assert entry.get("usage_complete") is not False
        assert entry.get("unreported_count", 0) == 0

        events = container.capability_effects.usage_log.events_for(str(entry["provider"]))
        assert len(events) == 1
        event = events[0]
        assert event.input_tokens == 11
        assert event.output_tokens == 5
        assert event.usage_reported is True
        # Canonical identity, not a legacy callback's absent provenance.
        assert event.invocation_id
        assert event.provider == requested_model

    async def test_runner_conductor_call_without_usage_is_unreported_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A gateway that reports no usage is marked, not zero-charged.

        The quota row must say the evidence is missing (`unreported_count`,
        `usage_complete=False`) and the ledger event must carry
        `usage_reported=False` — a measured zero and an unreported call are
        different facts (#717), and folding them is what lets a major call
        class hide inside a "complete" percentage.
        """
        async with _runner_with_real_container(monkeypatch, _gateway_body(usage=None)) as (
            executor,
            container,
        ):
            output = await executor(TaskCreate(description="no usage here"))

        assert output.success is True

        entries = await container.quota_tracker.get_all_usage()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["request_count"] == 1
        assert entry["unreported_count"] == 1
        assert entry["usage_complete"] is False
        assert entry["total_tokens"] == 0

        events = container.capability_effects.usage_log.events_for(str(entry["provider"]))
        assert len(events) == 1
        assert events[0].usage_reported is False
        assert events[0].total_tokens == 0
        assert events[0].invocation_id
