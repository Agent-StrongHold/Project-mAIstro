from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationReconciliationEvidence,
    InvocationStatus,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


class _ProcessDeath(BaseException):
    pass


class _CrashOnCompletedSave(InMemoryInvocationStore):
    def __init__(self) -> None:
        super().__init__()
        self.crash_on_completed = True

    async def save(self, invocation: Invocation) -> Invocation:
        if self.crash_on_completed and invocation.status is InvocationStatus.COMPLETED:
            raise _ProcessDeath("process died after the provider committed")
        return await super().save(invocation)


@dataclass(frozen=True)
class _Report:
    report: InvocationReconciliationEvidence

    async def reconcile(self, _invocation: Invocation) -> InvocationReconciliationEvidence:
        return self.report


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="workspace-1",
        project_id="project-1",
        capability="external_write",
    )


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


@pytest.mark.asyncio
async def test_crash_after_provider_success_is_discoverable_and_settles_applied() -> None:
    store = _CrashOnCompletedSave()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: Any, request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"remote_id": request["id"]}

    with pytest.raises(_ProcessDeath):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:1",
            request={"id": "remote-1"},
            resolver=_resolver,
            executor=execute,
        )

    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="write:1",
    )
    assert history[0].status is InvocationStatus.RUNNING
    stale = await service.discover_ambiguous(stale_before=datetime.now(UTC) + timedelta(seconds=1))
    assert [item.invocation_id for item in stale] == [history[0].invocation_id]

    store.crash_on_completed = False
    settled = await service.reconcile(
        history[0].invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="operator",
        actor="operator-1",
        reason="provider receipt matched remote-1",
        evidence={"receipt": "receipt-1"},
        result={"remote_id": "remote-1"},
        workspace_id="workspace-1",
        project_id="project-1",
    )
    assert settled.status is InvocationStatus.COMPLETED
    audit = settled.reconciliation_history[-1]
    assert audit.actor == "operator-1"
    assert audit.reason == "provider receipt matched remote-1"
    assert (audit.workspace_id, audit.project_id) == ("workspace-1", "project-1")
    assert (audit.run_id, audit.node_run_id, audit.attempt_id) == (
        "run-1",
        "node-run-1",
        "attempt-1",
    )

    replay = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="write:1",
        request={"id": "remote-1"},
        resolver=_resolver,
        executor=execute,
    )
    assert replay.result == {"remote_id": "remote-1"}
    assert calls == 1


@pytest.mark.asyncio
async def test_sqlite_reopen_keeps_ambiguous_evidence_reconciliation(tmp_path: Path) -> None:
    db_path = tmp_path / "invocations.db"
    async with aiosqlite.connect(db_path) as conn:
        store = SqliteInvocationStore(conn)
        await store.ensure_schema()
        service = InvocationExecutionService(store=store)

        async def provider_committed(_provider: Any, _request: Any) -> dict[str, str]:
            raise _ProcessDeath("provider committed before process death")

        with pytest.raises(_ProcessDeath):
            await service.invoke(
                binding=_binding(),
                run_id="run-sqlite",
                node_run_id="node-sqlite",
                attempt_id="attempt-1",
                effect_key="write:sqlite",
                request={"id": "remote-sqlite"},
                resolver=_resolver,
                executor=provider_committed,
            )
        running = (
            await store.list_effect(
                run_id="run-sqlite",
                node_run_id="node-sqlite",
                binding_id="binding-1",
                effect_key="write:sqlite",
            )
        )[0]

    async with aiosqlite.connect(db_path) as conn:
        reopened = SqliteInvocationStore(conn)
        await reopened.ensure_schema()
        service = InvocationExecutionService(store=reopened)
        assert [
            item.invocation_id
            for item in await service.discover_ambiguous(
                stale_before=datetime.now(UTC) + timedelta(seconds=1)
            )
        ] == [running.invocation_id]
        settled = await service.reconcile(
            running.invocation_id,
            disposition=ReconciliationDisposition.APPLIED,
            source="provider-status",
            actor="provider-a",
            reason="remote receipt found after reopen",
            evidence={"remote_id": "remote-sqlite"},
            result={"remote_id": "remote-sqlite"},
            workspace_id="workspace-1",
            project_id="project-1",
        )
        assert settled.status is InvocationStatus.COMPLETED

    async with aiosqlite.connect(db_path) as conn:
        reopened = SqliteInvocationStore(conn)
        await reopened.ensure_schema()
        persisted = await reopened.get(running.invocation_id)
        assert persisted is not None
        assert persisted.status is InvocationStatus.COMPLETED
        assert persisted.reconciliation_history[-1].evidence == {"remote_id": "remote-sqlite"}


@pytest.mark.asyncio
async def test_provider_reconciliation_settles_applied_without_dispatch() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def ambiguous(_provider: Any, _request: Any) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("transport lost")

    with pytest.raises(ConnectionError):
        await service.invoke(
            binding=_binding(),
            run_id="run-2",
            node_run_id="node-run-2",
            attempt_id="attempt-1",
            effect_key="write:2",
            request={"id": "remote-2"},
            resolver=_resolver,
            executor=ambiguous,
        )
    unknown = (
        await store.list_effect(
            run_id="run-2",
            node_run_id="node-run-2",
            binding_id="binding-1",
            effect_key="write:2",
        )
    )[0]

    settled = await service.reconcile_with_provider(
        unknown.invocation_id,
        _Report(
            InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.APPLIED,
                source="provider-status",
                actor="provider-a",
                reason="idempotency lookup found remote-2",
                evidence={"remote_id": "remote-2"},
                result={"remote_id": "remote-2"},
            )
        ),
    )
    assert settled.status is InvocationStatus.COMPLETED
    assert calls == 1


@pytest.mark.asyncio
async def test_not_applied_retry_is_gated_across_two_execution_services() -> None:
    store = InMemoryInvocationStore()
    first_service = InvocationExecutionService(store=store)

    async def not_applied(_provider: Any, _request: Any) -> None:
        raise EffectNotApplied("rejected before dispatch")

    with pytest.raises(EffectNotApplied):
        await first_service.invoke(
            binding=_binding(),
            run_id="run-concurrent",
            node_run_id="node-concurrent",
            attempt_id="attempt-1",
            effect_key="write:concurrent",
            request={"id": "remote-concurrent"},
            resolver=_resolver,
            executor=not_applied,
        )
    await first_service.reconcile(
        (
            await store.list_effect(
                run_id="run-concurrent",
                node_run_id="node-concurrent",
                binding_id="binding-1",
                effect_key="write:concurrent",
            )
        )[0].invocation_id,
        disposition=ReconciliationDisposition.NOT_APPLIED,
        source="operator",
        actor="operator-1",
        reason="verified no remote effect",
        evidence={"receipt": "absent"},
        workspace_id="workspace-1",
        project_id="project-1",
    )

    second_service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: Any, _request: Any) -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "committed"

    results = await asyncio.gather(
        first_service.invoke(
            binding=_binding(),
            run_id="run-concurrent",
            node_run_id="node-concurrent",
            attempt_id="attempt-2",
            effect_key="write:concurrent",
            request={"id": "remote-concurrent"},
            resolver=_resolver,
            executor=execute,
        ),
        second_service.invoke(
            binding=_binding(),
            run_id="run-concurrent",
            node_run_id="node-concurrent",
            attempt_id="attempt-3",
            effect_key="write:concurrent",
            request={"id": "remote-concurrent"},
            resolver=_resolver,
            executor=execute,
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, UnsafeEffectRetry) for result in results) == 1
    assert (
        sum(getattr(result, "status", None) is InvocationStatus.COMPLETED for result in results)
        == 1
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_not_applied_is_retryable_but_indeterminate_stays_blocked() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def executor(_provider: Any, _request: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("transport lost")
        return "committed"

    with pytest.raises(ConnectionError):
        await service.invoke(
            binding=_binding(),
            run_id="run-3",
            node_run_id="node-run-3",
            attempt_id="attempt-1",
            effect_key="write:3",
            request={"id": "remote-3"},
            resolver=_resolver,
            executor=executor,
        )
    unknown = (
        await store.list_effect(
            run_id="run-3",
            node_run_id="node-run-3",
            binding_id="binding-1",
            effect_key="write:3",
        )
    )[0]
    failed = await service.reconcile_with_provider(
        unknown.invocation_id,
        _Report(
            InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.NOT_APPLIED,
                source="provider-status",
                actor="provider-a",
                reason="idempotency lookup found no remote effect",
                evidence={"lookup": "absent"},
            )
        ),
    )
    assert failed.status is InvocationStatus.FAILED
    retry = await service.invoke(
        binding=_binding(),
        run_id="run-3",
        node_run_id="node-run-3",
        attempt_id="attempt-2",
        effect_key="write:3",
        request={"id": "remote-3"},
        resolver=_resolver,
        executor=executor,
    )
    assert retry.status is InvocationStatus.COMPLETED
    assert calls == 2

    async def always_unknown(_provider: Any, _request: Any) -> None:
        raise ConnectionError("transport lost")

    class _IndeterminateAdapter:
        async def reconcile(self, _invocation: Invocation) -> InvocationReconciliationEvidence:
            return InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.INDETERMINATE,
                source="provider-status",
                actor="provider-a",
                reason="status endpoint unavailable",
            )

    with pytest.raises(ConnectionError):
        await service.invoke(
            binding=_binding(),
            run_id="run-4",
            node_run_id="node-run-4",
            attempt_id="attempt-1",
            effect_key="write:4",
            request={"id": "remote-4"},
            resolver=_resolver,
            executor=always_unknown,
        )
    blocked = (
        await store.list_effect(
            run_id="run-4",
            node_run_id="node-run-4",
            binding_id="binding-1",
            effect_key="write:4",
        )
    )[0]
    indeterminate = await service.reconcile_with_provider(
        blocked.invocation_id,
        _IndeterminateAdapter(),
    )
    assert indeterminate.status is InvocationStatus.UNKNOWN
    assert (
        indeterminate.reconciliation_history[-1].disposition
        is ReconciliationDisposition.INDETERMINATE
    )
    with pytest.raises(UnsafeEffectRetry):
        await service.invoke(
            binding=_binding(),
            run_id="run-4",
            node_run_id="node-run-4",
            attempt_id="attempt-2",
            effect_key="write:4",
            request={"id": "remote-4"},
            resolver=_resolver,
            executor=always_unknown,
        )
