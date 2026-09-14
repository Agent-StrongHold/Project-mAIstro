"""Quota admission belongs to the canonical physical Invocation path (#1196)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import (
    EffectNotApplied,
    GovernedLLMClient,
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
)
from maistro.quota.invocation import (
    InMemoryInvocationQuota,
    QuotaAmount,
    SqliteInvocationQuota,
)
from maistro.quota.rate_profile import LimitUnit, LimitWindow, ModelRateProfile, RateConstraint
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.types.errors import QuotaReserveError


class _Provider:
    slot = "model.chat"
    trust_tier = "t1"

    def __init__(self, name: str = "model-a") -> None:
        self.name = name


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="workspace-1",
        project_id="project-1",
        capability="model.chat",
    )


def _quota(log: InMemoryUsageLog | None = None) -> InMemoryInvocationQuota:
    def profile(provider: str) -> ModelRateProfile:
        return ModelRateProfile(
            provider=provider,
            model=provider,
            scope_key_fields=("provider", "model", "workspace", "principal"),
            constraints=(
                RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=1),
            ),
        )

    return InMemoryInvocationQuota(usage_log=log, profile_for=profile)


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


async def test_invocation_reserves_before_dispatch_and_records_same_effect() -> None:
    log = InMemoryUsageLog()
    quota = _quota(log)
    service = InvocationExecutionService(
        store=InMemoryInvocationStore(),
        quota_admission=quota,
    )
    dispatched: list[str] = []

    async def execute(_provider: _Provider, request: Any) -> dict[str, object]:
        dispatched.append(str(request))
        return {"ok": True}

    invocation = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-1",
        attempt_id="attempt-1",
        effect_key="effect-1",
        request="ordinary-agent-request",
        resolver=_resolver,
        executor=execute,
        principal_id="principal-1",
        quota_estimate=QuotaAmount(),
    )

    assert dispatched == ["ordinary-agent-request"]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.quota is not None
    assert invocation.quota.state == "committed"
    assert invocation.quota.workspace_id == "workspace-1"
    assert invocation.quota.principal_id == "principal-1"
    assert log.count_since(invocation.quota.scope_key, 60) == 1


@pytest.mark.asyncio
async def test_reserve_exhaustion_blocks_bypass_route_before_provider_dispatch() -> None:
    quota = _quota()
    service = InvocationExecutionService(
        store=InMemoryInvocationStore(),
        quota_admission=quota,
    )
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {}

    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "run-1",
        "node_run_id": "node-1",
        "attempt_id": "attempt-1",
        "request": {},
        "resolver": _resolver,
        "executor": execute,
        "principal_id": "principal-1",
    }
    await service.invoke(effect_key="first", **kwargs)

    # The second caller uses a different effect key and skips any router, but
    # the same canonical provider quota still admits no physical call.
    with pytest.raises(QuotaReserveError):
        await service.invoke(effect_key="alternate-strategy", **kwargs)
    assert calls == 1

    history = await service.latest_effect(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-1",
        effect_key="alternate-strategy",
    )
    assert history is not None
    assert history.status is InvocationStatus.FAILED
    assert history.quota is not None
    assert history.quota.state == "denied"


@pytest.mark.asyncio
async def test_concurrent_invocations_cannot_race_one_remaining_reservation() -> None:
    quota = _quota()
    service = InvocationExecutionService(
        store=InMemoryInvocationStore(),
        quota_admission=quota,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {}

    async def invoke(effect_key: str) -> object:
        return await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-1",
            attempt_id=effect_key,
            effect_key=effect_key,
            request={},
            resolver=_resolver,
            executor=execute,
            principal_id="principal-1",
        )

    first = asyncio.create_task(invoke("one"))
    await started.wait()
    second = asyncio.create_task(invoke("two"))
    with pytest.raises(QuotaReserveError):
        await second
    release.set()
    await first
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_two_sqlite_replicas_share_reservations_before_dispatch(tmp_path: Any) -> None:
    path = str(tmp_path / "quota.db")
    first_conn = await aiosqlite.connect(path)
    second_conn = await aiosqlite.connect(path)
    try:
        first_quota = _sqlite_quota(first_conn)
        second_quota = _sqlite_quota(second_conn)
        await first_quota.ensure_schema()
        first_store = InMemoryInvocationStore()
        second_store = InMemoryInvocationStore()
        first = InvocationExecutionService(store=first_store, quota_admission=first_quota)
        second = InvocationExecutionService(store=second_store, quota_admission=second_quota)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def execute(_provider: _Provider, _request: Any) -> dict[str, object]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {}

        async def invoke(service: InvocationExecutionService, key: str) -> object:
            return await service.invoke(
                binding=_binding(),
                run_id=key,
                node_run_id=key,
                attempt_id=key,
                effect_key=key,
                request={},
                resolver=_resolver,
                executor=execute,
                principal_id="principal-1",
            )

        owner = asyncio.create_task(invoke(first, "one"))
        await started.wait()
        contender = asyncio.create_task(invoke(second, "two"))
        with pytest.raises(QuotaReserveError):
            await contender
        release.set()
        await owner
        assert calls == 1
    finally:
        await first_conn.close()
        await second_conn.close()


@pytest.mark.asyncio
async def test_governed_llm_adapter_records_alternate_strategy_calls() -> None:
    quota = _quota()
    effects = new_in_memory_effect_context(quota_admission=quota)

    class FakeLLM:
        async def complete(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "model": "model-a",
                "choices": [{"message": {"content": "governed"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    client = GovernedLLMClient(
        FakeLLM(),
        invocation_service=effects.invocations,
        workspace_id="workspace-1",
        project_id="project-1",
        principal_id="principal-1",
        agent_id="direct",
        run_id="turn-1",
    )
    assert (await client.complete([], "model-a"))["choices"]
    with pytest.raises(QuotaReserveError):
        await client.complete([], "model-a")
    records = await effects.invocation_store.list_effect(
        run_id="turn-1",
        node_run_id="direct",
        binding_id="agent-llm:direct:workspace-1:project-1:model-a",
        effect_key="llm-completion:2",
    )
    assert records and records[0].quota is not None and records[0].quota.state == "denied"


def _sqlite_quota(conn: Any) -> SqliteInvocationQuota:
    return SqliteInvocationQuota(
        conn,
        profile_for=lambda provider: ModelRateProfile(
            provider=provider,
            model=provider,
            scope_key_fields=("provider", "model", "workspace", "principal"),
            constraints=(
                RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=1),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_proven_failure_rolls_back_but_ambiguous_success_waits_for_reconciliation() -> None:
    log = InMemoryUsageLog()
    quota = _quota(log)
    service = InvocationExecutionService(
        store=InMemoryInvocationStore(),
        quota_admission=quota,
    )

    async def not_applied(_provider: _Provider, _request: Any) -> object:
        raise EffectNotApplied("connection failed before dispatch")

    with pytest.raises(EffectNotApplied):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-1",
            attempt_id="a1",
            effect_key="rollback",
            request={},
            resolver=_resolver,
            executor=not_applied,
            principal_id="principal-1",
        )

    async def succeeds(_provider: _Provider, _request: Any) -> dict[str, object]:
        return {}

    # Rollback means the next physical effect can use the slot.
    completed = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-1",
        attempt_id="a2",
        effect_key="after-rollback",
        request={},
        resolver=_resolver,
        executor=succeeds,
        principal_id="principal-1",
    )
    assert completed.status is InvocationStatus.COMPLETED

    async def ambiguous(_provider: _Provider, _request: Any) -> object:
        raise RuntimeError("provider response lost")

    # Use a second workspace to isolate the still-uncertain reservation from
    # the successful request above while retaining the same provider route.
    ambiguous_binding = _binding().model_copy(update={"workspace_id": "workspace-2"})
    with pytest.raises(RuntimeError):
        await service.invoke(
            binding=ambiguous_binding,
            run_id="run-2",
            node_run_id="node-2",
            attempt_id="a3",
            effect_key="ambiguous",
            request={},
            resolver=_resolver,
            executor=ambiguous,
            principal_id="principal-1",
        )
    assert len(quota.pending_invocations()) == 1
    unknown = await service.latest_effect(
        binding=ambiguous_binding, run_id="run-2", node_run_id="node-2", effect_key="ambiguous"
    )
    assert unknown is not None
    assert unknown.status is InvocationStatus.UNKNOWN

    reconciled = await service.reconcile_unknown(
        unknown.invocation_id,
        usage=InvocationUsage(input_units=4, output_units=2, provider="model-a"),
    )
    assert reconciled.status is InvocationStatus.COMPLETED
    assert reconciled.quota is not None
    assert reconciled.quota.state == "committed"
    assert quota.pending_invocations() == ()
    assert log.count_since(reconciled.quota.scope_key, 60) == 1

    deduped = await service.invoke(
        binding=ambiguous_binding,
        run_id="run-2",
        node_run_id="node-2",
        attempt_id="a4",
        effect_key="ambiguous",
        request={},
        resolver=_resolver,
        executor=succeeds,
        principal_id="principal-1",
    )
    assert deduped.invocation_id == reconciled.invocation_id
