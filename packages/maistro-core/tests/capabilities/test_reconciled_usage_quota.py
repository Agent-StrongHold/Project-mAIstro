"""Reconciled physical effects land on the quota ledger exactly once (#718).

The canonical recorder is installed once at Invocation terminalization. The
develop integration added a second way an Invocation reaches a terminal
`COMPLETED` state — a reconciliation settled `APPLIED` — and that settlement
must feed the same recorder: the physical call happened, so its usage (or its
explicit unreported marker) belongs on the ledger. These tests pin the
at-most-once property across both terminal paths and the paths that must
record nothing at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import (
    InvocationStatus,
    InvocationUsage,
    ReconciliationDisposition,
)
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog


class _Provider:
    name = "provider-a"
    slot = "external_write"
    trust_tier = "trusted"


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="workspace-1",
        project_id="project-1",
        capability="external_write",
    )


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


def _usage(input_units: int, output_units: int) -> InvocationUsage:
    return InvocationUsage(input_units=input_units, output_units=output_units, model="provider-a")


async def _invoke_once(
    governed: Any,
    *,
    effect_key: str,
    executor: Any,
) -> Any:
    try:
        return await governed.invocations.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key=effect_key,
            request={"id": "remote-1"},
            resolver=_resolver,
            executor=executor,
        )
    except RuntimeError:
        # A generic provider failure is terminalized UNKNOWN and re-raised;
        # read the persisted row back so tests can reconcile it.
        history = await governed.invocation_store.list_effect(
            run_id="run-1",
            node_run_id="node-run-1",
            binding_id="binding-1",
            effect_key=effect_key,
        )
        assert history
        return history[-1]


async def _entry(tracker: InMemoryQuotaTracker) -> dict[str, Any]:
    rows = await tracker.get_all_usage()
    assert rows, "expected one aggregate quota row for provider-a"
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
async def test_applied_reconciliation_records_recovered_usage_exactly_once() -> None:
    """A settlement of an UNKNOWN physical call is that call's one ledger row."""

    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    governed = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)

    async def crash(_provider: Any, _request: Any) -> dict[str, Any]:
        raise RuntimeError("connection dropped after the provider committed")

    unknown = await _invoke_once(governed, effect_key="write:1", executor=crash)
    assert unknown.status is InvocationStatus.UNKNOWN
    # Nothing may be counted yet: the outcome is genuinely unknown, and
    # counting a silent zero would understate the provider's own numbers.
    assert await tracker.get_all_usage() == []

    settled = await governed.invocations.reconcile(
        unknown.invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="provider-status",
        actor="provider-a",
        reason="remote write found with its bill",
        evidence={"remote_id": "remote-1"},
        workspace_id="workspace-1",
        project_id="project-1",
        usage=_usage(7, 3),
    )
    assert settled.status is InvocationStatus.COMPLETED

    entry = await _entry(tracker)
    assert entry["input_tokens"] == 7
    assert entry["output_tokens"] == 3
    assert entry["request_count"] == 1
    recorded = usage_log.events_for("provider-a")
    assert recorded and recorded[-1].usage_reported is True

    # The settled Invocation is terminal: re-invoking the same logical effect
    # returns it without a dispatch, and no second ledger row appears.
    calls = 0

    async def execute(_provider: Any, _request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"remote_id": "remote-1"}

    again = await _invoke_once(governed, effect_key="write:1", executor=execute)
    assert again.invocation_id == settled.invocation_id
    assert calls == 0
    assert (await _entry(tracker))["request_count"] == 1


@pytest.mark.asyncio
async def test_not_applied_settlement_records_no_usage() -> None:
    """`NOT_APPLIED` proves no physical effect: the ledger must stay empty."""

    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    governed = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)

    async def crash(_provider: Any, _request: Any) -> dict[str, Any]:
        raise RuntimeError("process died before the request left")

    unknown = await _invoke_once(governed, effect_key="write:2", executor=crash)
    assert unknown.status is InvocationStatus.UNKNOWN

    settled = await governed.invocations.reconcile(
        unknown.invocation_id,
        disposition=ReconciliationDisposition.NOT_APPLIED,
        source="provider-status",
        actor="provider-a",
        reason="no remote write exists for this effect",
        evidence={"remote_id": None},
        workspace_id="workspace-1",
        project_id="project-1",
    )
    assert settled.status is InvocationStatus.FAILED
    assert await tracker.get_all_usage() == []
    assert usage_log.events_for("provider-a") == ()


@pytest.mark.asyncio
async def test_reconciled_missing_usage_is_unreported_not_zero() -> None:
    """An APPLIED settlement without usage evidence records an explicit marker."""

    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    governed = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)

    async def crash(_provider: Any, _request: Any) -> dict[str, Any]:
        raise RuntimeError("crashed mid-call")

    unknown = await _invoke_once(governed, effect_key="write:3", executor=crash)
    await governed.invocations.reconcile(
        unknown.invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="operator",
        actor="operator-1",
        reason="user confirms the write happened; provider billing is unavailable",
        evidence={"confirmed_by": "operator-1"},
        workspace_id="workspace-1",
        project_id="project-1",
        usage=None,
    )

    entry = await _entry(tracker)
    assert entry["request_count"] == 1
    assert entry["unreported_count"] == 1
    assert entry["usage_complete"] is False
    assert entry["total_tokens"] == 0
    recorded = usage_log.events_for("provider-a")
    assert recorded and recorded[-1].usage_reported is False


@pytest.mark.asyncio
async def test_physical_completion_records_once_and_reconciliation_cannot_add() -> None:
    """A normally completed call is recorded once; COMPLETED cannot re-reconcile."""

    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    governed = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)

    async def execute(_provider: Any, _request: Any) -> dict[str, Any]:
        return {"remote_id": "remote-1"}

    completed = await _invoke_once(governed, effect_key="write:4", executor=execute)
    assert completed.status is InvocationStatus.COMPLETED
    entry = await _entry(tracker)
    assert entry["request_count"] == 1

    unchanged = await governed.invocations.reconcile(
        completed.invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="provider-status",
        actor="provider-a",
        reason="late duplicate report for an already settled effect",
        evidence={"remote_id": "remote-1"},
        workspace_id="workspace-1",
        project_id="project-1",
        usage=_usage(100, 100),
    )
    assert unchanged.invocation_id == completed.invocation_id
    assert unchanged.status is InvocationStatus.COMPLETED
    # The idempotent early return settles nothing: no second physical row.
    assert (await _entry(tracker))["request_count"] == 1


@pytest.mark.asyncio
async def test_indeterminate_settlement_keeps_the_ledger_waiting() -> None:
    """`INDETERMINATE` records nothing; the effect stays evidence-requiring."""

    tracker = InMemoryQuotaTracker()
    usage_log = InMemoryUsageLog()
    governed = new_in_memory_effect_context(usage_log=usage_log, quota_tracker=tracker)

    async def crash(_provider: Any, _request: Any) -> dict[str, Any]:
        raise RuntimeError("crashed mid-call")

    unknown = await _invoke_once(governed, effect_key="write:5", executor=crash)
    settled = await governed.invocations.reconcile(
        unknown.invocation_id,
        disposition=ReconciliationDisposition.INDETERMINATE,
        source="provider-status",
        actor="provider-a",
        reason="provider status endpoint unreachable",
        evidence=None,
        workspace_id="workspace-1",
        project_id="project-1",
    )
    assert settled.status is InvocationStatus.UNKNOWN
    assert await tracker.get_all_usage() == []
    assert usage_log.events_for("provider-a") == ()
