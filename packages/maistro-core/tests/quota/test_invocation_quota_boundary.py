"""Acceptance evidence for the opt-in canonical Invocation quota slice (#1196)."""

from __future__ import annotations

import asyncio
import math
import multiprocessing
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from maistro.capabilities.binding import Binding, ResolvedBinding, ResolvedCapabilityProvider
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
    UnsafeEffectRetry,
)
from maistro.quota.invocation_quota import (
    InvocationQuotaDenied,
    QuotaBudget,
    QuotaEstimate,
    QuotaEvidenceConflict,
    QuotaObservation,
)
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota


@dataclass(frozen=True)
class Provider:
    name: str = "provider-a"
    slot: str = "model.chat"
    trust_tier: str = "trusted"


def binding(workspace: str = "workspace-a") -> Binding:
    return Binding(
        binding_id=f"binding-{workspace}",
        workspace_id=workspace,
        project_id="project-a",
        capability="model.chat",
    )


def invocation(number: str = "one", *, workspace: str = "workspace-a") -> Invocation:
    return Invocation(
        invocation_id=f"invocation-{number}",
        run_id=f"run-{number}",
        node_run_id=f"node-{number}",
        attempt_id="attempt-one",
        effect_key="call",
        binding=ResolvedBinding.from_provider(binding(workspace), Provider()),
    )


def budget(name: str = "tokens", **kwargs: Any) -> QuotaBudget:
    fields: dict[str, Any] = dict(
        budget_id=name,
        unit="tokens",
        limit=100,
        period_start=0,
        period_end=1000,
        provider_name="provider-a",
        opening_spend=0,
        coverage_ref="operator-attested-fresh-period",
    )
    fields.update(kwargs)
    return QuotaBudget(**fields)


async def estimate(inv: Invocation, bound: Binding) -> QuotaEstimate:
    del inv, bound
    return QuotaEstimate(principal_id="principal-a", tokens=60, micro_usd=50_000)


@pytest_asyncio.fixture
async def quota(tmp_path: Path) -> SqliteInvocationQuota:
    result = SqliteInvocationQuota(tmp_path / "quota.sqlite", estimate=estimate, clock=lambda: 100)
    await result.ensure_schema()
    return result


async def execute(
    service: InvocationExecutionService,
    *,
    run: str = "run-one",
    bound: Binding | None = None,
    executor: Any = None,
    usage_from: Any = None,
    request: Any = None,
    provider: Provider | None = None,
) -> Invocation:
    selected = provider or Provider()

    async def resolve(_: Binding) -> ResolvedCapabilityProvider:
        return selected

    async def default_executor(_: ResolvedCapabilityProvider, value: Any) -> dict[str, Any]:
        return {"answer": "done", "request": value}

    return await service.invoke(
        binding=bound or binding(),
        run_id=run,
        node_run_id="node-one",
        attempt_id="attempt-one",
        effect_key="call",
        request=request or {"prompt": "example"},
        resolver=resolve,
        executor=executor or default_executor,
        usage_from=usage_from,
    )


def observed(
    inv: Invocation,
    *,
    revision: int = 1,
    outcome: Any = "completed",
    tokens: int | None = 30,
    micro_usd: int | None = None,
    evidence_id: str | None = None,
) -> QuotaObservation:
    return QuotaObservation(
        invocation_id=inv.invocation_id,
        provider_name=inv.binding.provider_name,
        evidence_id=evidence_id or f"provider-record-v{revision}",
        revision=revision,
        outcome=outcome,
        tokens=tokens,
        micro_usd=micro_usd,
    )


def terminal(inv: Invocation, status: InvocationStatus, usage: InvocationUsage | None = None) -> Invocation:
    return inv.model_copy(update={
        "status": status,
        "usage": usage,
        "finished_at": datetime.now(UTC),
    })


@pytest.mark.asyncio
async def test_completed_invocation_settles_all_units_once_and_replay_does_not_dispatch(quota):
    await quota.register_budget(budget())
    await quota.register_budget(budget("cost", unit="micro_usd", limit=100_000))
    await quota.register_budget(budget("requests", unit="requests", limit=10))
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store, quota=quota)
    calls = 0

    async def provider(_, request):
        nonlocal calls
        calls += 1
        assert (await quota.balance("tokens")).held == 60
        return "done"

    use = lambda _: InvocationUsage(input_units=10, output_units=20, cost_cents=0.125)
    first = await execute(service, executor=provider, usage_from=use)
    second = await execute(service, executor=provider, usage_from=use)
    assert first.invocation_id == second.invocation_id
    assert calls == 1
    assert first.status is InvocationStatus.COMPLETED
    assert first.usage.input_units == 10
    assert (await quota.balance("tokens")).spent == 30
    assert (await quota.balance("tokens")).held == 0
    assert (await quota.balance("cost")).spent == 1250
    assert (await quota.balance("requests")).spent == 1


@pytest.mark.asyncio
async def test_missing_usage_is_held_but_known_request_count_is_charged(quota):
    await quota.register_budget(budget())
    await quota.register_budget(budget("cost", unit="micro_usd", limit=100_000))
    await quota.register_budget(budget("requests", unit="requests", limit=10))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    inv = await execute(service)
    assert inv.status is InvocationStatus.COMPLETED
    assert inv.usage is None
    assert (await quota.balance("tokens")).held == 60
    assert (await quota.balance("cost")).held == 50_000
    assert (await quota.balance("requests")).spent == 1
    await quota.reconcile(observed(inv, tokens=20, micro_usd=15_000))
    assert (await quota.balance("tokens")).spent == 20
    assert (await quota.balance("cost")).spent == 15_000
    assert (await quota.balance("cost")).held == 0


@pytest.mark.asyncio
async def test_absent_policy_denies_before_physical_dispatch_and_records_refusal(quota):
    calls = 0

    async def provider(*_):
        nonlocal calls
        calls += 1

    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store, quota=quota)
    with pytest.raises(InvocationQuotaDenied, match="missing applicable"):
        await execute(service, executor=provider)
    assert calls == 0
    latest = await service.latest_effect(binding=binding(), run_id="run-one", node_run_id="node-one", effect_key="call")
    assert latest.status is InvocationStatus.FAILED
    with sqlite3.connect(quota._path) as conn:
        assert conn.execute("SELECT state FROM invocation_quota_reservations").fetchone()[0] == "denied"
        assert conn.execute("SELECT COUNT(*) FROM invocation_quota_allocations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_all_matching_scope_budgets_apply_and_refusal_is_atomic(quota):
    await quota.register_budget(budget("provider"))
    await quota.register_budget(budget("workspace", workspace_id="workspace-a", limit=40))
    await quota.register_budget(budget("other-workspace", workspace_id="workspace-b", limit=0))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    with pytest.raises(InvocationQuotaDenied, match="workspace"):
        await execute(service)
    assert (await quota.balance("provider")).held == 0
    assert (await quota.balance("workspace")).held == 0
    await execute(service, bound=binding("workspace-c"))
    assert (await quota.balance("provider")).held == 60
    assert (await quota.balance("other-workspace")).held == 0


@pytest.mark.asyncio
async def test_caller_cannot_override_authoritative_principal_with_payload(quota):
    await quota.register_budget(budget("provider"))
    await quota.register_budget(budget("principal", principal_id="principal-a", limit=20))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    with pytest.raises(InvocationQuotaDenied, match="principal"):
        await execute(service, request={"principal_id": "someone-else", "quota_exempt": True})
    assert (await quota.balance("provider")).held == 0


@pytest.mark.asyncio
async def test_protected_reserve_and_audited_opening_balance_are_enforced(quota):
    await quota.register_budget(budget(limit=100, reserve=20, opening_spend=21))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    with pytest.raises(InvocationQuotaDenied):
        await execute(service)
    balance = await quota.balance("tokens")
    assert balance.available == 59
    assert balance.spent == 21


@pytest.mark.asyncio
async def test_missing_bound_is_not_assumed_zero(quota):
    await quota.register_budget(budget("cost", unit="micro_usd", limit=100_000))

    async def incomplete(*_):
        return QuotaEstimate("principal-a", tokens=60)

    other = SqliteInvocationQuota(quota._path, estimate=incomplete, clock=lambda: 100)
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=other)
    with pytest.raises(InvocationQuotaDenied, match="upper bound"):
        await execute(service)
    assert (await quota.balance("cost")).held == 0


@pytest.mark.asyncio
async def test_known_not_applied_releases_and_later_attempt_can_reserve(quota):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)

    async def not_applied(*_):
        raise EffectNotApplied("adapter has proof")

    with pytest.raises(EffectNotApplied):
        await execute(service, executor=not_applied)
    assert (await quota.balance("tokens")).held == 0
    assert (await quota.balance("tokens")).spent == 0
    await execute(service)
    assert (await quota.balance("tokens")).held == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [RuntimeError("remote response lost"), asyncio.CancelledError()])
async def test_unknown_provider_outcome_keeps_hold_and_blocks_retry(quota, exception):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)

    async def fail(*_):
        raise exception

    with pytest.raises(type(exception)):
        await execute(service, executor=fail)
    assert (await quota.balance("tokens")).held == 60
    with pytest.raises(UnsafeEffectRetry):
        await execute(service)
    with pytest.raises(InvocationQuotaDenied):
        await execute(service, run="a-different-run")
    old = await service.latest_effect(binding=binding(), run_id="run-one", node_run_id="node-one", effect_key="call")
    await quota.reconcile(observed(old, outcome="not_applied", tokens=None))
    assert (await quota.balance("tokens")).held == 0
    # Reconciliation of accounting alone does not grant effect replay authority.
    with pytest.raises(UnsafeEffectRetry):
        await execute(service)


@pytest.mark.asyncio
async def test_parser_cannot_make_success_retryable_even_if_it_raises_effect_not_applied(quota):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    calls = 0

    async def provider(*_):
        nonlocal calls
        calls += 1
        return {"physical_result": "committed"}

    def broken_parser(_):
        raise EffectNotApplied("parser error, not provider evidence")

    with pytest.raises(EffectNotApplied):
        await execute(service, executor=provider, usage_from=broken_parser)
    assert (await quota.balance("tokens")).held == 60
    replay = await execute(service, executor=provider, usage_from=broken_parser)
    assert replay.status is InvocationStatus.COMPLETED
    assert replay.result == {"physical_result": "committed"}
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_reported_overage_is_not_clamped_and_blocks_next_dispatch(quota):
    await quota.register_budget(budget(limit=70))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    await execute(service, usage_from=lambda _: InvocationUsage(input_units=90, output_units=10))
    balance = await quota.balance("tokens")
    assert balance.spent == 100 and balance.available == -30
    with pytest.raises(InvocationQuotaDenied):
        await execute(service, run="next")


@pytest.mark.asyncio
async def test_reconciliation_is_absolute_idempotent_versioned_and_scope_checked(quota):
    await quota.register_budget(budget())
    inv = invocation()
    await quota.reserve(inv, binding())
    first = observed(inv, revision=2, tokens=40)
    await quota.reconcile(first)
    await quota.reconcile(first)
    assert (await quota.balance("tokens")).spent == 40
    await quota.reconcile(observed(inv, revision=1, tokens=55))
    assert (await quota.balance("tokens")).spent == 40
    await quota.reconcile(observed(inv, revision=3, tokens=12))
    assert (await quota.balance("tokens")).spent == 12
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(observed(inv, revision=3, tokens=13))
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(replace(observed(inv, revision=4), provider_name="other-provider"))
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(observed(inv, revision=4, evidence_id=first.evidence_id))
    assert (await quota.balance("tokens")).spent == 12


@pytest.mark.asyncio
async def test_partial_corrections_preserve_known_dimensions(quota):
    await quota.register_budget(budget())
    await quota.register_budget(budget("cost", unit="micro_usd", limit=100_000))
    inv = invocation()
    await quota.reserve(inv, binding())
    await quota.reconcile(observed(inv, tokens=15))
    assert (await quota.balance("cost")).held == 50_000
    await quota.reconcile(observed(inv, revision=2, tokens=None, micro_usd=10_000))
    assert (await quota.balance("tokens")).spent == 15
    assert (await quota.balance("cost")).spent == 10_000
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(observed(inv, revision=3, outcome="unknown", tokens=None))


@pytest.mark.asyncio
async def test_late_accounting_stays_in_original_period_and_survives_reopen(quota):
    await quota.register_budget(budget())
    old = invocation()
    await quota.reserve(old, binding())
    await quota.observe(terminal(old, InvocationStatus.UNKNOWN))
    reopen = SqliteInvocationQuota(quota._path, estimate=estimate, clock=lambda: 1100)
    await reopen.ensure_schema()
    assert (await reopen.balance("tokens")).held == 60
    await reopen.register_budget(budget("next-period", period_start=1000, period_end=2000))
    newer = invocation("two")
    await reopen.reserve(newer, binding())
    await reopen.reconcile(observed(old, tokens=10))
    assert (await reopen.balance("tokens")).spent == 10
    assert (await reopen.balance("next-period")).held == 60
    assert (await reopen.balance("next-period")).spent == 0


@pytest.mark.asyncio
async def test_budget_identity_immutable_and_reserve_identity_checked(quota):
    config = budget()
    await quota.register_budget(config)
    await quota.register_budget(config)
    with pytest.raises(QuotaEvidenceConflict):
        await quota.register_budget(replace(config, limit=9999))
    inv = invocation()
    await quota.reserve(inv, binding())
    await quota.reserve(inv, binding())
    assert (await quota.balance("tokens")).held == 60
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reserve(inv.model_copy(update={"run_id": "different-run"}), binding())


@pytest.mark.asyncio
async def test_settlement_write_failure_repaired_on_cached_replay_without_dispatch(quota):
    await quota.register_budget(budget())

    class OnceFailingQuota:
        failed = False

        async def reserve(self, inv, bound):
            await quota.reserve(inv, bound)

        async def observe(self, inv):
            if inv.status is InvocationStatus.COMPLETED and not self.failed:
                self.failed = True
                raise OSError("simulated ledger unavailable")
            await quota.observe(inv)

    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store, quota=OnceFailingQuota())
    calls = 0

    async def provider(*_):
        nonlocal calls
        calls += 1
        return "done"

    use = lambda _: InvocationUsage(input_units=10, output_units=5)
    with pytest.raises(OSError):
        await execute(service, executor=provider, usage_from=use)
    assert (await quota.balance("tokens")).held == 60
    result = await execute(service, executor=provider, usage_from=use)
    assert result.status is InvocationStatus.COMPLETED
    assert (await quota.balance("tokens")).held == 0
    assert (await quota.balance("tokens")).spent == 15
    assert calls == 1


@pytest.mark.asyncio
async def test_running_save_failure_never_dispatches_and_releases_hold(quota):
    await quota.register_budget(budget())

    class FailRunningStore(InMemoryInvocationStore):
        async def save(self, inv):
            if inv.status is InvocationStatus.RUNNING:
                raise OSError("running write refused")
            return await super().save(inv)

    service = InvocationExecutionService(store=FailRunningStore(), quota=quota)
    with pytest.raises(OSError):
        await execute(service)
    assert (await quota.balance("tokens")).held == 0


@pytest.mark.asyncio
async def test_separate_service_instances_and_alternate_strategy_share_admission(quota):
    await quota.register_budget(budget())
    second = SqliteInvocationQuota(quota._path, estimate=estimate, clock=lambda: 100)
    first_service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    other_service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=second)
    entered = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def slow_provider(*_):
        nonlocal calls
        calls += 1
        entered.set()
        await finish.wait()
        return "done"

    task = asyncio.create_task(execute(first_service, executor=slow_provider))
    await entered.wait()
    try:
        # No RouterEngine or Agent strategy checks participate in this refusal.
        with pytest.raises(InvocationQuotaDenied):
            await execute(other_service, run="alternative-strategy", executor=slow_provider)
        with pytest.raises(InvocationQuotaDenied, match="missing applicable"):
            await execute(other_service, run="alternative-provider", provider=Provider(name="other"))
    finally:
        finish.set()
        await task
    assert calls == 1


def _process_reserve(path: str, barrier: Any, queue: Any, number: str) -> None:
    async def run():
        replica = SqliteInvocationQuota(path, estimate=estimate, clock=lambda: 100)
        barrier.wait(timeout=15)
        try:
            await replica.reserve(invocation(number), binding())
            queue.put("admitted")
        except InvocationQuotaDenied:
            queue.put("denied")
        barrier.wait(timeout=15)
    asyncio.run(run())


@pytest.mark.asyncio
async def test_two_os_processes_cannot_race_same_remaining_quota(quota):
    await quota.register_budget(budget())
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(target=_process_reserve, args=(quota._path, barrier, queue, str(i)))
        for i in range(2)
    ]
    for process in processes:
        process.start()
    try:
        results = [await asyncio.to_thread(queue.get, True, 20) for _ in processes]
        assert sorted(results) == ["admitted", "denied"]
        for process in processes:
            await asyncio.to_thread(process.join, 20)
            assert process.exitcode == 0
        assert (await quota.balance("tokens")).held == 60
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        queue.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_reservation_commit_then_releases(quota):
    await quota.register_budget(budget())
    committed = threading.Event()
    release = threading.Event()

    class DelayedReturnQuota(SqliteInvocationQuota):
        def _transaction(self, operation):
            result = super()._transaction(operation)
            if operation.__name__ == "admit":
                committed.set()
                assert release.wait(10)
            return result

    delayed = DelayedReturnQuota(quota._path, estimate=estimate, clock=lambda: 100)
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=delayed)
    task = asyncio.create_task(execute(service))
    assert await asyncio.to_thread(committed.wait, 10)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await quota.balance("tokens")).held == 0
    latest = await service.latest_effect(binding=binding(), run_id="run-one", node_run_id="node-one", effect_key="call")
    assert latest.status is InvocationStatus.FAILED


@pytest.mark.asyncio
async def test_credentials_request_and_result_are_not_copied_into_quota_database(quota):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    bound = binding().model_copy(update={
        "config": {"sensitive": "do-not-copy-configuration"},
        "credential_refs": ("do-not-copy-credential-reference",),
    })
    await execute(service, bound=bound, request={"secret": "do-not-copy-request"})
    with sqlite3.connect(quota._path) as conn:
        dump = "\n".join(conn.iterdump())
    assert "do-not-copy" not in dump
    for required in ("workspace-a", "principal-a", "provider-a", "run-one", "model.chat"):
        assert required in dump


@pytest.mark.asyncio
async def test_unknown_units_do_not_become_tokens_and_cost_rounds_up(quota):
    await quota.register_budget(budget())
    await quota.register_budget(budget("cost", unit="micro_usd", limit=100_000))
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    await execute(service, usage_from=lambda _: InvocationUsage(units="images", input_units=1, cost_cents=0.00001))
    assert (await quota.balance("tokens")).held == 60
    assert (await quota.balance("cost")).spent == 1


@pytest.mark.asyncio
async def test_database_failure_is_not_an_in_memory_fallback(tmp_path):
    broken = SqliteInvocationQuota(tmp_path / "missing-parent" / "q.db", estimate=estimate)
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=broken)
    calls = 0

    async def provider(*_):
        nonlocal calls
        calls += 1

    with pytest.raises(sqlite3.OperationalError):
        await execute(service, executor=provider)
    assert calls == 0


@pytest.mark.parametrize("invalid", [-1, 1.25, True, math.nan, math.inf, 1 << 63])
def test_invalid_quota_amounts_fail_closed(invalid):
    with pytest.raises(ValueError):
        QuotaEstimate("principal", tokens=invalid)
    with pytest.raises(ValueError):
        budget(limit=invalid)
    with pytest.raises(ValueError):
        observed(invocation(), tokens=invalid)


@pytest.mark.parametrize("changes", [{"reserve": 101}, {"period_end": 0}, {"coverage_ref": ""}, {"unit": "dollars"}])
def test_invalid_budget_definition_rejected(changes):
    with pytest.raises(ValueError):
        budget(**changes)


def test_per_operation_memory_database_is_rejected():
    with pytest.raises(ValueError):
        SqliteInvocationQuota(":memory:", estimate=estimate)


@pytest.mark.asyncio
async def test_observation_provider_mismatch_and_unknown_id_refused(quota):
    with pytest.raises(KeyError):
        await quota.reconcile(observed(invocation()))
    with pytest.raises(ValueError):
        await quota.reconcile(observed(invocation(), revision=0))


@pytest.mark.asyncio
async def test_existing_unmetered_constructor_retains_behavior():
    # This compatibility path is why this slice alone cannot close #1196.
    service = InvocationExecutionService(store=InMemoryInvocationStore())
    result = await execute(service)
    assert result.status is InvocationStatus.COMPLETED


@pytest.mark.asyncio
async def test_retracting_not_applied_evidence_restores_unknown_usage_hold(quota):
    await quota.register_budget(budget())
    inv = invocation()
    await quota.reserve(inv, binding())
    await quota.reconcile(observed(inv, outcome="not_applied", tokens=None))
    assert (await quota.balance("tokens")).held == 0
    await quota.reconcile(observed(inv, revision=2, tokens=None))
    assert (await quota.balance("tokens")).held == 60
    assert (await quota.balance("tokens")).spent == 0
    await quota.reconcile(observed(inv, revision=3, tokens=20))
    assert (await quota.balance("tokens")).held == 0
    assert (await quota.balance("tokens")).spent == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [InvocationStatus.COMPLETED, InvocationStatus.UNKNOWN])
async def test_unreserved_provider_outcome_is_a_coverage_gap_not_free_usage(quota, status):
    with pytest.raises(KeyError, match="reconcile coverage"):
        await quota.observe(terminal(invocation(), status))
    # Explicit pre-dispatch refusal is the one safe no-reservation observation.
    await quota.observe(terminal(invocation(), InvocationStatus.FAILED))


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), float("-inf"), -1])
def test_nonfinite_provider_cost_is_rejected_at_canonical_usage_boundary(cost):
    with pytest.raises(ValueError):
        InvocationUsage(cost_cents=cost)


@pytest.mark.asyncio
async def test_wrong_usage_return_type_does_not_poison_persisted_invocation(quota):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)
    with pytest.raises(TypeError, match="usage extractor"):
        await execute(service, usage_from=lambda _: {})
    result = await execute(service)
    assert result.status is InvocationStatus.COMPLETED
    assert result.usage is None
    assert (await quota.balance("tokens")).held == 60


@pytest.mark.asyncio
async def test_invalid_bypassed_usage_validation_keeps_prior_hold(quota):
    await quota.register_budget(budget())
    inv = invocation()
    await quota.reserve(inv, binding())
    malformed = InvocationUsage.model_construct(input_units=-10, output_units=20)
    with pytest.raises(ValueError):
        await quota.observe(terminal(inv, InvocationStatus.COMPLETED, malformed))
    assert (await quota.balance("tokens")).held == 60


@pytest.mark.asyncio
async def test_concurrent_duplicate_settlement_does_not_double_charge(quota):
    await quota.register_budget(budget())
    inv = invocation()
    await quota.reserve(inv, binding())
    peer = SqliteInvocationQuota(quota._path, estimate=estimate, clock=lambda: 100)
    done = terminal(inv, InvocationStatus.COMPLETED, InvocationUsage(input_units=10, output_units=20))
    await asyncio.gather(quota.observe(done), peer.observe(done))
    assert (await quota.balance("tokens")).spent == 30
    assert (await quota.balance("tokens")).held == 0


@pytest.mark.asyncio
async def test_accounting_failure_rolls_back_evidence_and_can_be_corrected(quota):
    await quota.register_budget(budget())
    inv = invocation()
    await quota.reserve(inv, binding())
    await quota.reconcile(observed(inv, revision=1, tokens=20))
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(observed(inv, revision=2, outcome="unknown", tokens=None))
    # The rejected payload must not poison the evidence revision's identity.
    await quota.reconcile(observed(inv, revision=2, tokens=15))
    assert (await quota.balance("tokens")).spent == 15


@pytest.mark.asyncio
async def test_same_denied_admission_is_idempotently_denied(quota):
    await quota.register_budget(budget(limit=40))
    inv = invocation()
    for _ in range(2):
        with pytest.raises(InvocationQuotaDenied):
            await quota.reserve(inv, binding())
    assert (await quota.balance("tokens")).held == 0
    with pytest.raises(QuotaEvidenceConflict):
        await quota.reconcile(observed(inv))


@pytest.mark.asyncio
async def test_wrong_trusted_resolver_return_type_cannot_dispatch(quota):
    await quota.register_budget(budget())

    async def wrong(*_):
        return {"principal_id": "principal-a", "tokens": 0}

    other = SqliteInvocationQuota(quota._path, estimate=wrong, clock=lambda: 100)
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=other)
    with pytest.raises(TypeError, match="QuotaEstimate"):
        await execute(service)
    assert (await quota.balance("tokens")).held == 0


@pytest.mark.asyncio
async def test_cancellation_in_usage_parser_preserves_completed_result(quota):
    await quota.register_budget(budget())
    service = InvocationExecutionService(store=InMemoryInvocationStore(), quota=quota)

    def cancelled(_):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await execute(service, usage_from=cancelled)
    result = await execute(service)
    assert result.status is InvocationStatus.COMPLETED
    assert (await quota.balance("tokens")).held == 60


@pytest.mark.asyncio
async def test_cached_unmetered_result_requires_accounting_coverage_not_redispatch(quota):
    await quota.register_budget(budget())
    store = InMemoryInvocationStore()
    old_service = InvocationExecutionService(store=store)
    result = await execute(old_service)
    metered_service = InvocationExecutionService(store=store, quota=quota)
    with pytest.raises(KeyError, match="reconcile coverage"):
        await execute(metered_service)
    assert (await store.get(result.invocation_id)).status is InvocationStatus.COMPLETED
    assert (await quota.balance("tokens")).held == 0


@pytest.mark.asyncio
async def test_period_is_selected_after_waiting_for_database_lock(quota):
    await quota.register_budget(budget())
    entered = threading.Event()
    now = [100]

    class SignalsBeforeLock(SqliteInvocationQuota):
        def _transaction(self, operation):
            if operation.__name__ == "admit":
                entered.set()
            return super()._transaction(operation)

    delayed = SignalsBeforeLock(quota._path, estimate=estimate, clock=lambda: now[0])
    with sqlite3.connect(quota._path, isolation_level=None) as holder:
        holder.execute("BEGIN IMMEDIATE")
        task = asyncio.create_task(delayed.reserve(invocation(), binding()))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            now[0] = 1000  # End of [0, 1000), before the waiting admission owns the lock.
        finally:
            holder.commit()
        with pytest.raises(InvocationQuotaDenied, match="missing applicable"):
            await task
    assert (await quota.balance("tokens")).held == 0
