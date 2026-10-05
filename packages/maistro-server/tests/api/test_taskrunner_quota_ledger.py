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

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import httpx
import pytest

from maistro.agents.circuit_breaker import DomainCircuitBank, llm_circuits
from maistro.agents.types import ConductorOutput
from maistro.http import set_test_transport
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.quota.invocation_quota import InvocationQuotaDenied, QuotaBudget
from maistro.quota.usage_log import (
    InMemoryUsageLog,
    get_default_usage_log,
    set_default_usage_log,
)
from maistro.runs.admission import admit_direct_work
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.tasks.models import TaskCreate
from maistro.types.config import ModelBindingConfig
from maistro_server.main import lifespan


@asynccontextmanager
async def _runner_with_real_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gateway_body: dict[str, Any]
) -> AsyncIterator[
    tuple[Callable[[TaskCreate], Awaitable[ConductorOutput]], Any, list[httpx.Request]]
]:
    """Real lifespan, configured Binding and canonical task execution; mock HTTP only.

    The Project is created through its durable owner before startup, just as
    deployment configuration names an existing Project. The lifespan must load
    the declared Binding and register its scoped credential itself. Neither the
    conductor nor its admission, Binding or Invocation service is substituted.
    """
    database = tmp_path / "conductor.db"
    async with aiosqlite.connect(database) as connection:
        projects = SqliteProjectScopeStore(connection)
        await projects.ensure_schema()
        project = await projects.create_root("default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("MAISTRO_DRY_RUN", "0")
    monkeypatch.setenv("ROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-gateway-key")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.fixture")
    monkeypatch.setattr(
        "maistro_server.main._model_bindings",
        lambda: [
            ModelBindingConfig(binding_id="configured-conductor", project_id=project.project_id)
        ],
    )
    previous_log = get_default_usage_log()
    set_default_usage_log(InMemoryUsageLog())
    llm_circuits.reset()
    seen: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://gateway.fixture/v1/chat/completions"
        seen.append(request)
        return httpx.Response(200, json=gateway_body)

    # Installed before startup, so no setup or background client can escape.
    set_test_transport(httpx.MockTransport(transport))
    captured: dict[str, Any] = {}

    def capture_runner(
        queue: Any, executor: Any, progress_webhook: Any = None, attempts: Any = None
    ) -> MagicMock:
        captured.update(executor=executor, attempts=attempts)
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
            patch("maistro_server.main.TaskRunner", side_effect=capture_runner),
        ):
            async with lifespan(test_app):
                container = test_app.state.container

                async def execute(task: TaskCreate) -> ConductorOutput:
                    run = await admit_direct_work(
                        container.run_store,
                        workspace_id="default",
                        project_id=project.project_id,
                        node_type="llm.summarize",
                        name="conductor task",
                        source="task_queue",
                        actor_principal_id="authenticated-task-user",
                        initial_status=RunStatus.QUEUED,
                    )
                    output = await captured["attempts"].execute(
                        run.run_id, task, captured["executor"]
                    )
                    nodes = await container.run_store.list_node_runs(run.run_id)
                    assert len(nodes) == 1
                    attempts = await container.run_store.list_attempts(nodes[0].node_run_id)
                    assert len(attempts) == 1
                    assert attempts[0].status is AttemptStatus.COMPLETED
                    assert attempts[0].execution_lease is not None
                    invocations = await container.capability_effects.invocation_store.list_effect(
                        run_id=run.run_id,
                        node_run_id=nodes[0].node_run_id,
                        binding_id="configured-conductor",
                        effect_key="conductor-llm-0",
                    )
                    assert len(invocations) == 1
                    assert invocations[0].attempt_id == attempts[0].attempt_id
                    assert invocations[0].actor_id == "authenticated-task-user"
                    assert invocations[0].binding.project_id == project.project_id
                    return output

                # The same closure cannot be called out of band merely because
                # it has an adapter and a valid key: admission is mandatory.
                with pytest.raises(RunIntegrityError):
                    await captured["executor"](TaskCreate(description="unadmitted task"))
                assert seen == []
                yield execute, container, seen
    finally:
        set_test_transport(None)
        set_default_usage_log(previous_log)
        llm_circuits.reset()


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
    @pytest.mark.parametrize("request_limit", [0, 1])
    async def test_actor_scoped_budget_refuses_before_extra_http(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request_limit: int
    ) -> None:
        circuits = DomainCircuitBank(failure_threshold=1)
        monkeypatch.setattr("maistro.agents.conductor.llm_circuits", circuits)
        async with _runner_with_real_container(
            monkeypatch,
            tmp_path,
            _gateway_body(usage={"prompt_tokens": 11, "completion_tokens": 5}),
        ) as (executor, container, seen):
            quota = container.capability_effects.quota
            assert quota is not None
            await quota.register_budget(
                QuotaBudget(
                    budget_id="actor-conductor",
                    unit="requests",
                    limit=request_limit,
                    period_start=0,
                    period_end=1 << 62,
                    coverage_ref="isolated-fixture-empty-ledger",
                    opening_spend=0,
                    workspace_id="default",
                    principal_id="authenticated-task-user",
                    capability="model.chat",
                )
            )
            if request_limit:
                result = await executor(TaskCreate(description="one authorized call"))
                assert result.success is True
            with pytest.raises(
                InvocationQuotaDenied, match="quota exhausted for budget actor-conductor"
            ):
                await executor(TaskCreate(description="call beyond the actor budget"))
            assert len(seen) == request_limit
            assert all(row["state"] == "closed" for row in circuits.snapshot())
            balance = await quota.balance("actor-conductor")
            assert balance.spent == request_limit
            assert balance.held == 0

    async def test_runner_conductor_call_moves_the_quota_ledger(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async with _runner_with_real_container(
            monkeypatch,
            tmp_path,
            _gateway_body(usage={"prompt_tokens": 11, "completion_tokens": 5}),
        ) as (executor, container, seen):
            output = await executor(TaskCreate(description="ledger me"))
            assert output.success is True
            assert output.final_answer == "done"
            assert len(seen) == 1
            requested_model = json.loads(seen[0].content)["model"]
            assert seen[0].headers["Authorization"] == "Bearer test-gateway-key"
            entries = await container.quota_tracker.get_all_usage()
            assert len(entries) == 1
            entry = entries[0]
            assert entry["provider"] == requested_model
            assert entry["request_count"] == 1
            assert entry["input_tokens"] == 11
            assert entry["output_tokens"] == 5
            assert entry["total_tokens"] == 16
            assert entry.get("usage_complete") is not False
            assert entry.get("unreported_count", 0) == 0
            events = container.capability_effects.usage_log.events_for(str(entry["provider"]))
            assert len(events) == 1
            assert events[0].input_tokens == 11
            assert events[0].output_tokens == 5
            assert events[0].usage_reported is True
            assert events[0].invocation_id
            assert events[0].provider == requested_model

    async def test_runner_conductor_call_without_usage_is_unreported_evidence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async with _runner_with_real_container(
            monkeypatch, tmp_path, _gateway_body(usage=None)
        ) as (
            executor,
            container,
            seen,
        ):
            output = await executor(TaskCreate(description="no usage here"))
            assert output.success is True
            assert len(seen) == 1
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
