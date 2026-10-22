"""Canonical ambiguity resolution must settle real reservations without rewriting evidence."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.quota.invocation_quota import (
    QuotaBudget,
    QuotaEstimate,
    QuotaEvidenceConflict,
    QuotaObservation,
)
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota


@dataclass(frozen=True)
class Provider:
    name: str = "provider"
    slot: str = "model.chat"
    trust_tier: str = "trusted"


async def estimate(_invocation, _binding):
    return QuotaEstimate(principal_id="operator", tokens=10)


@pytest.fixture
async def recovery(tmp_path):
    path = tmp_path / "canonical.sqlite"
    quota = SqliteInvocationQuota(path, estimate=estimate, clock=lambda: 100)
    await quota.ensure_schema()
    await quota.register_budget(
        QuotaBudget(
            budget_id="tokens",
            unit="tokens",
            limit=100,
            period_start=0,
            period_end=1000,
            provider_name="provider",
            opening_spend=0,
            coverage_ref="fixture-fresh-period",
        )
    )
    async with aiosqlite.connect(path) as connection:
        store = SqliteInvocationStore(connection)
        await store.ensure_schema()
        service = InvocationExecutionService(store=store, quota=quota)
        binding = Binding(
            binding_id="binding",
            workspace_id="workspace",
            project_id="project",
            capability="model.chat",
        )
        calls = []

        async def resolver(_binding):
            return Provider()

        async def executor(_provider, _request):
            calls.append("dispatch")
            if len(calls) == 1:
                raise ConnectionError("outcome unavailable")
            return "done"

        async def invoke():
            return await service.invoke(
                binding=binding,
                run_id="run",
                node_run_id="node",
                attempt_id=f"attempt-{len(calls) + 1}",
                effect_key="effect",
                request={},
                resolver=resolver,
                executor=executor,
                usage_from=lambda _: InvocationUsage(input_units=7),
            )

        with pytest.raises(ConnectionError):
            await invoke()
        unknown = (await service.discover_ambiguous(stale_before=datetime.now(UTC)))[0]
        yield SimpleNamespace(
            path=path,
            quota=quota,
            store=store,
            service=service,
            unknown=unknown,
            invoke=invoke,
            calls=calls,
        )


def evidence(recovery):
    with sqlite3.connect(recovery.path) as conn:
        return conn.execute(
            "SELECT revision, evidence_id, payload FROM invocation_quota_evidence WHERE invocation_id = ? ORDER BY revision",
            (recovery.unknown.invocation_id,),
        ).fetchall()


async def settle(recovery, disposition):
    applied = disposition is ReconciliationDisposition.APPLIED
    return await recovery.service.reconcile(
        recovery.unknown.invocation_id,
        disposition=disposition,
        source="operator",
        actor="operator",
        reason="verified provider outcome",
        workspace_id="workspace",
        project_id="project",
        evidence=None
        if disposition is ReconciliationDisposition.INDETERMINATE
        else {"receipt": "verified"},
        result="accepted" if applied else None,
        usage=InvocationUsage(input_units=7) if applied else None,
    )


@pytest.mark.parametrize(
    "disposition,spent,held",
    [
        (ReconciliationDisposition.APPLIED, 7, 0),
        (ReconciliationDisposition.NOT_APPLIED, 0, 0),
        (ReconciliationDisposition.INDETERMINATE, 0, 10),
    ],
)
async def test_canonical_reconciliation_keeps_original_evidence_and_repairs_idempotently(
    recovery, disposition, spent, held
):
    original = evidence(recovery)
    assert original[0][:2] == (0, "canonical-terminal")
    assert (await recovery.quota.balance("tokens")).held == 10
    settled = await settle(recovery, disposition)
    balance = await recovery.quota.balance("tokens")
    assert (balance.spent, balance.held) == (spent, held)
    recorded = evidence(recovery)
    assert recorded[0] == original[0]
    if disposition is ReconciliationDisposition.INDETERMINATE:
        assert recorded == original
        with pytest.raises(UnsafeEffectRetry):
            await recovery.invoke()
    else:
        assert recorded[1][:2] == (1, "canonical-reconciliation")
        reopened = SqliteInvocationQuota(recovery.path, estimate=estimate, clock=lambda: 100)
        await asyncio.gather(reopened.observe(settled), recovery.quota.observe(settled))
        await reopened.observe(recovery.unknown)
        assert evidence(recovery) == recorded
        assert await recovery.quota.balance("tokens") == balance
        result = await recovery.invoke()
        assert result.status is InvocationStatus.COMPLETED
        assert len(recovery.calls) == (1 if disposition is ReconciliationDisposition.APPLIED else 2)


async def test_provider_corrections_share_ordering_without_identity_collisions(recovery):
    inv = recovery.unknown
    corrected = QuotaObservation(
        invocation_id=inv.invocation_id,
        provider_name="provider",
        evidence_id="provider-before",
        revision=7,
        outcome="completed",
        tokens=9,
    )
    await recovery.quota.reconcile(corrected)
    settled = await settle(recovery, ReconciliationDisposition.APPLIED)
    assert evidence(recovery)[-1][:2] == (8, "canonical-reconciliation")
    latest = replace(corrected, evidence_id="provider-after", revision=9, tokens=6)
    await recovery.quota.reconcile(latest)
    await recovery.quota.observe(settled)
    await recovery.quota.observe(inv)
    assert (await recovery.quota.balance("tokens")).spent == 6
    assert [row[0] for row in evidence(recovery)] == [0, 7, 8, 9]
    with pytest.raises(QuotaEvidenceConflict, match="reused"):
        await recovery.quota.reconcile(replace(latest, tokens=5))
    # The canonical settlement also stays immutable under its existing identity.
    with pytest.raises(QuotaEvidenceConflict, match="reused"):
        await recovery.quota.observe(
            settled.model_copy(update={"usage": InvocationUsage(input_units=8)})
        )
    payloads = [json.loads(row[2]) for row in evidence(recovery)]
    assert [item["tokens"] for item in payloads] == [None, 9, 7, 6]


@pytest.mark.parametrize("identity", ["canonical-terminal", "canonical-reconciliation"])
async def test_provider_cannot_claim_canonical_evidence_identity(recovery, identity):
    with pytest.raises(ValueError, match="identities are reserved"):
        await recovery.quota.reconcile(
            QuotaObservation(
                invocation_id=recovery.unknown.invocation_id,
                provider_name="provider",
                evidence_id=identity,
                revision=1,
                outcome="not_applied",
            )
        )


async def test_repair_after_settlement_crash_allocates_one_revision_across_connections(recovery):
    # The lifecycle commit survived but its quota projection did not. Two
    # recovering consumers see the same durable settlement independently.
    recovery.service = InvocationExecutionService(store=recovery.store)
    settled = await settle(recovery, ReconciliationDisposition.NOT_APPLIED)
    assert (await recovery.quota.balance("tokens")).held == 10
    reopened = SqliteInvocationQuota(recovery.path, estimate=estimate, clock=lambda: 100)
    await asyncio.gather(recovery.quota.observe(settled), reopened.observe(settled))
    assert [row[:2] for row in evidence(recovery)] == [
        (0, "canonical-terminal"),
        (1, "canonical-reconciliation"),
    ]
    balance = await reopened.balance("tokens")
    assert balance.spent == balance.held == 0


@pytest.mark.parametrize(
    "disposition", [ReconciliationDisposition.APPLIED, ReconciliationDisposition.NOT_APPLIED]
)
@pytest.mark.parametrize("replay_entry", ["operator", "provider"])
async def test_service_replay_repairs_quota_after_partial_settlement(
    recovery, monkeypatch, disposition, replay_entry
):
    original_observe = recovery.quota.observe

    async def unavailable(_invocation):
        raise RuntimeError("quota temporarily unavailable")

    monkeypatch.setattr(recovery.quota, "observe", unavailable)
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await settle(recovery, disposition)
    saved = await recovery.store.get(recovery.unknown.invocation_id)
    assert saved.status in {InvocationStatus.COMPLETED, InvocationStatus.FAILED}
    assert (await recovery.quota.balance("tokens")).held == 10
    monkeypatch.setattr(recovery.quota, "observe", original_observe)
    if replay_entry == "operator":
        replay = await settle(recovery, disposition)
    else:

        class MustNotContactProvider:
            async def reconcile(self, _invocation):
                pytest.fail("terminal replay must use its durable evidence")

        replay = await recovery.service.reconcile_with_provider(
            saved.invocation_id, MustNotContactProvider()
        )
    assert replay == saved
    assert len(replay.reconciliation_history) == 1
    assert len(recovery.calls) == 1
    balance = await recovery.quota.balance("tokens")
    assert balance.held == 0
    assert balance.spent == (7 if disposition is ReconciliationDisposition.APPLIED else 0)


@pytest.mark.parametrize("winner_path", ["provider_lookup", "save_race"])
async def test_concurrent_settlement_winner_repairs_quota_before_return(
    recovery, monkeypatch, winner_path
):
    original_observe = recovery.quota.observe
    original_save = recovery.store.save
    winner = InvocationExecutionService(store=recovery.store, quota=recovery.quota)
    competed = False

    async def compete():
        async def unavailable(_invocation):
            raise RuntimeError("quota temporarily unavailable")

        monkeypatch.setattr(recovery.quota, "observe", unavailable)
        try:
            with pytest.raises(RuntimeError, match="temporarily unavailable"):
                await winner.reconcile(
                    recovery.unknown.invocation_id,
                    disposition=ReconciliationDisposition.NOT_APPLIED,
                    source="operator",
                    actor="winner",
                    reason="verified absence",
                    evidence={"receipt": "winner"},
                    workspace_id="workspace",
                    project_id="project",
                )
        finally:
            monkeypatch.setattr(recovery.quota, "observe", original_observe)

    if winner_path == "provider_lookup":

        class RacingAdapter:
            async def reconcile(self, _invocation):
                await compete()
                raise RuntimeError("lookup no longer needed")

        settled = await recovery.service.reconcile_with_provider(
            recovery.unknown.invocation_id, RacingAdapter()
        )
    else:

        async def racing_save(candidate):
            nonlocal competed
            if not competed:
                competed = True
                await compete()
            return await original_save(candidate)

        monkeypatch.setattr(recovery.store, "save", racing_save)
        settled = await settle(recovery, ReconciliationDisposition.APPLIED)
    assert settled.status is InvocationStatus.FAILED
    assert settled.reconciliation_history[-1].actor == "winner"
    assert len(settled.reconciliation_history) == 1
    assert len(recovery.calls) == 1
    assert (await recovery.quota.balance("tokens")).held == 0


@pytest.mark.parametrize("replay_entry", ["claim", "late_terminal"])
async def test_completed_admission_and_late_worker_replays_repair_quota(
    recovery, monkeypatch, replay_entry
):
    # Persist the settlement as if another worker died before quota projection.
    settlement_service = InvocationExecutionService(store=recovery.store)
    await settlement_service.reconcile(
        recovery.unknown.invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="operator",
        actor="operator",
        reason="verified result",
        evidence={"receipt": "verified"},
        workspace_id="workspace",
        project_id="project",
        result="accepted",
        usage=InvocationUsage(input_units=7),
    )
    assert (await recovery.quota.balance("tokens")).held == 10
    if replay_entry == "claim":
        real_list = recovery.store.list_effect
        first = True

        async def stale_history(**kwargs):
            nonlocal first
            if first:
                first = False
                return []
            return await real_list(**kwargs)

        monkeypatch.setattr(recovery.store, "list_effect", stale_history)
        replay = await recovery.invoke()
    else:
        # A delayed worker terminalizes its old snapshot after the winner committed.
        replay = await recovery.service._terminalize(
            recovery.unknown, InvocationStatus.COMPLETED, result="late obsolete result"
        )
    assert replay.status is InvocationStatus.COMPLETED
    assert replay.result == "accepted"
    assert len(replay.reconciliation_history) == 1
    assert len(recovery.calls) == 1
    balance = await recovery.quota.balance("tokens")
    assert (balance.spent, balance.held) == (7, 0)


@pytest.mark.parametrize(
    "usage",
    [
        InvocationUsage(input_units=2**63),
        InvocationUsage(input_units=2**62, output_units=2**62),
        InvocationUsage(cost_cents=1e308),
    ],
)
async def test_unsupported_usage_refuses_before_immutable_settlement(recovery, usage):
    before = await recovery.store.get(recovery.unknown.invocation_id)
    with pytest.raises(ValueError):
        await recovery.service.reconcile(
            before.invocation_id,
            disposition=ReconciliationDisposition.APPLIED,
            source="operator",
            actor="operator",
            reason="reported usage",
            evidence={"receipt": "provider"},
            workspace_id="workspace",
            project_id="project",
            usage=usage,
        )
    assert await recovery.store.get(before.invocation_id) == before
    assert (await recovery.quota.balance("tokens")).held == 10
    assert len(evidence(recovery)) == 1


async def test_historical_oversized_usage_remains_readable_and_requires_valid_replacement(recovery):
    legacy = await recovery.store.save(
        recovery.unknown.model_copy(update={"usage": InvocationUsage(input_units=2**63)})
    )
    assert (await recovery.store.get(legacy.invocation_id)).usage.input_units == 2**63
    assert (await recovery.service.discover_ambiguous(stale_before=datetime.now(UTC)))[
        0
    ].usage.input_units == 2**63
    with pytest.raises(ValueError):
        await recovery.service.reconcile(
            legacy.invocation_id,
            disposition=ReconciliationDisposition.APPLIED,
            source="operator",
            actor="operator",
            reason="verified outcome without corrected usage",
            evidence={"receipt": "provider"},
            workspace_id="workspace",
            project_id="project",
        )
    assert await recovery.store.get(legacy.invocation_id) == legacy
    assert (await recovery.quota.balance("tokens")).held == 10
    settled = await settle(recovery, ReconciliationDisposition.APPLIED)
    assert settled.usage.input_units == 7
    assert (await recovery.quota.balance("tokens")).spent == 7
