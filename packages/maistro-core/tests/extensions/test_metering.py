"""Acceptance evidence for extension metering and Workspace/org quotas (#977).

Each cluster names the #977 acceptance criterion it pins:

- physical usage recorded once — a provider call routed through an extension
  is charged once in canonical totals and attributed once at the extension
  seam (retry, re-hand-out and alias re-reports conflict, never charge);
- nested delegation preserves causal lineage without additive copies;
- budget exhaustion survives retries, new Agents, and extension aliases;
- aggregation by Workspace, extension, publisher, capability, time window;
- concurrency (asyncio tasks and OS processes) cannot oversubscribe or race
  remaining budget;
- rollback/refund semantics for unexecuted reserved work;
- provider-reported usage corrections with monotonic revisions.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    Invocation,
    InvocationStatus,
    InvocationUsage,
)
from maistro.extensions import (
    ExtensionMeter,
    ExtensionQuotaConflict,
    ExtensionQuotaDenied,
    ExtensionQuotaLedger,
    ExtensionQuotaPolicy,
    ExtensionQuotaRequest,
    ExtensionUsageAmounts,
    ExtensionUsageConflict,
    ExtensionUsageEvent,
)
from maistro.quota.invocation_quota import QuotaBudget, QuotaEstimate
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

CLOCK = 1_000.0


@dataclass(frozen=True)
class Provider:
    name: str = "provider-a"
    slot: str = "model.chat"
    trust_tier: str = "trusted"


def policy(name: str = "workspace-tokens", **kwargs: Any) -> ExtensionQuotaPolicy:
    fields: dict[str, Any] = {
        "policy_id": name,
        "org_id": "org-a",
        "unit": "tokens",
        "limit": 100,
        "period_start": 0,
        "period_end": 10_000,
        "coverage_ref": "operator-attested-fresh-period",
    }
    fields.update(kwargs)
    return ExtensionQuotaPolicy(**fields)


def request(
    name: str = "res-one",
    *,
    extension: str = "ext-x",
    caller: str = "agent-a",
    tokens: int | None = 60,
    **kwargs: Any,
) -> ExtensionQuotaRequest:
    fields: dict[str, Any] = {
        "reservation_id": name,
        "org_id": "org-a",
        "workspace_id": "workspace-a",
        "extension_id": extension,
        "publisher_id": "pub-a",
        "capability": "model.chat",
        "caller_id": caller,
        "tokens": tokens,
    }
    fields.update(kwargs)
    return ExtensionQuotaRequest(**fields)


def event(name: str = "evt-one", **kwargs: Any) -> ExtensionUsageEvent:
    fields: dict[str, Any] = {
        "event_id": name,
        "org_id": "org-a",
        "workspace_id": "workspace-a",
        "extension_id": "ext-x",
        "extension_version": "1.0.0",
        "publisher_id": "pub-a",
        "capability": "model.chat",
        "caller_id": "agent-a",
        "invocation_id": f"invocation-{name}",
        "provider_name": "provider-a",
        "input_tokens": 40,
        "output_tokens": 20,
        "micro_usd": 500,
        "requests": 1,
    }
    fields.update(kwargs)
    return ExtensionUsageEvent(**fields)


@pytest.fixture
async def meter(tmp_path: Path) -> ExtensionMeter:
    result = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await result.ensure_schema()
    return result


@pytest.fixture
async def quota(tmp_path: Path) -> ExtensionQuotaLedger:
    result = ExtensionQuotaLedger(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await result.ensure_schema()
    return result


# ---------------------------------------------------------------------------
# Physical usage is recorded once (AC: no double counting in canonical totals)
# ---------------------------------------------------------------------------


async def test_provider_call_through_extension_charges_once_in_canonical_totals(
    tmp_path: Path,
) -> None:
    """Canonical totals charge the Invocation once; the extension seam
    attributes the same physical call once; every duplicate path conflicts."""
    path = tmp_path / "shared.sqlite"

    async def estimate(inv: Invocation, bound: Binding) -> QuotaEstimate:
        del inv, bound
        return QuotaEstimate(principal_id="principal-a", tokens=60)

    canonical = SqliteInvocationQuota(path, estimate=estimate, clock=lambda: 100)
    await canonical.ensure_schema()
    await canonical.register_budget(
        QuotaBudget(
            budget_id="tokens",
            unit="tokens",
            limit=100,
            period_start=0,
            period_end=1_000,
            provider_name="provider-a",
            opening_spend=0,
            coverage_ref="operator-attested-fresh-period",
        )
    )
    meter_ledger = ExtensionMeter(path)
    quota_ledger = ExtensionQuotaLedger(path)
    await meter_ledger.ensure_schema()
    await quota_ledger.ensure_schema()

    base = Binding(
        binding_id="binding-a",
        workspace_id="workspace-a",
        project_id="project-a",
        capability="model.chat",
    )
    provider = ResolvedBinding.from_provider(base, Provider())
    invocation = Invocation(
        invocation_id="invocation-one",
        run_id="run-one",
        node_run_id="node-one",
        attempt_id="attempt-one",
        effect_key="call",
        binding=provider,
    )
    await canonical.reserve(invocation, base)
    usage = InvocationUsage(units="tokens", input_units=40, output_units=20)
    completed = invocation.model_copy(update={"status": InvocationStatus.COMPLETED, "usage": usage})
    await canonical.observe(completed)

    await meter_ledger.record(
        event("evt-one", invocation_id="invocation-one", input_tokens=40, output_tokens=20)
    )
    totals = await meter_ledger.totals(org_id="org-a", workspace_id="workspace-a")
    assert (totals.input_tokens, totals.output_tokens) == (40, 20)
    assert (await canonical.balance("tokens")).spent == 60

    # Canonical re-observation of the same Invocation charges nothing more.
    await canonical.observe(completed)
    assert (await canonical.balance("tokens")).spent == 60

    # An alternate extension alias re-reporting the same physical call is a
    # conflict, not a second charge — canonical or extension-side.
    with pytest.raises(ExtensionUsageConflict, match="already carries"):
        await meter_ledger.record(
            event(
                "evt-alias",
                invocation_id="invocation-one",
                extension_id="ext-x-alias",
                input_tokens=40,
                output_tokens=20,
            )
        )
    totals = await meter_ledger.totals(org_id="org-a", workspace_id="workspace-a")
    assert (totals.input_tokens, totals.output_tokens) == (40, 20)
    assert (await canonical.balance("tokens")).spent == 60


async def test_usage_event_retry_is_idempotent_and_changed_facts_conflict(
    meter: ExtensionMeter,
) -> None:
    await meter.record(event("evt-one"))
    await meter.record(event("evt-one"))  # identical retry: no-op
    totals = await meter.totals(org_id="org-a")
    assert totals.events == 1
    with pytest.raises(ExtensionUsageConflict, match="identity was reused"):
        await meter.record(event("evt-one", input_tokens=999))
    totals = await meter.totals(org_id="org-a")
    assert totals.input_tokens == 40


async def test_incomplete_nested_lineage_is_refused(meter: ExtensionMeter) -> None:
    with pytest.raises(ValueError, match="parent and root lineage"):
        await meter.record(event("evt-orph", root_invocation_id="invocation-root"))


# ---------------------------------------------------------------------------
# Nested delegation: causal attribution without double counting (AC 2)
# ---------------------------------------------------------------------------


async def test_nested_calls_preserve_lineage_without_double_counting(meter: ExtensionMeter) -> None:
    """The orchestrator's call and its delegate's call are two physical rows;
    re-attributing the delegate's usage to the orchestrator conflicts, and
    every aggregate still sums each physical use exactly once."""
    await meter.record(
        event(
            "evt-root",
            invocation_id="invocation-root",
            extension_id="ext-orchestrator",
            input_tokens=60,
            output_tokens=0,
        )
    )
    await meter.record(
        event(
            "evt-nested",
            invocation_id="invocation-nested",
            extension_id="ext-sub",
            parent_invocation_id="invocation-root",
            root_invocation_id="invocation-root",
            depth=1,
            input_tokens=0,
            output_tokens=40,
        )
    )
    # A naive nested meter would add the delegate's usage again for the
    # orchestrator; the physical-use identity refuses that copy.
    with pytest.raises(ExtensionUsageConflict, match="already carries"):
        await meter.record(
            event(
                "evt-nested-copy",
                invocation_id="invocation-nested",
                extension_id="ext-orchestrator",
                parent_invocation_id="invocation-root",
                root_invocation_id="invocation-root",
                depth=1,
                input_tokens=0,
                output_tokens=40,
            )
        )

    chain = await meter.lineage("invocation-root")
    assert [(row.extension_id, row.depth) for row in chain] == [
        ("ext-orchestrator", 0),
        ("ext-sub", 1),
    ]
    totals = await meter.totals(org_id="org-a")
    assert (totals.input_tokens, totals.output_tokens) == (60, 40)
    by_extension = await meter.breakdown("extension", org_id="org-a")
    assert by_extension["ext-orchestrator"].input_tokens == 60
    assert by_extension["ext-sub"].output_tokens == 40
    assert sum(bucket.events for bucket in by_extension.values()) == totals.events


# ---------------------------------------------------------------------------
# Aggregation by Workspace, extension, publisher, capability, time (AC 5)
# ---------------------------------------------------------------------------


async def test_aggregation_filters_by_every_scope_dimension(meter: ExtensionMeter) -> None:
    await meter.record(event("evt-1"))  # workspace-a / ext-x / pub-a / chat @ t=1000
    await meter.record(
        event(
            "evt-2",
            workspace_id="workspace-b",
            extension_id="ext-y",
            publisher_id="pub-b",
            capability="tool.fetch",
            input_tokens=7,
            output_tokens=3,
        )
    )
    await meter.record(event("evt-3", invocation_id=None, input_tokens=1))  # host-measured

    assert (await meter.totals(org_id="org-a")).events == 3
    assert (await meter.totals(org_id="org-a", workspace_id="workspace-a")).events == 2
    assert (await meter.totals(org_id="org-a", workspace_id="workspace-b")).input_tokens == 7
    assert (await meter.totals(org_id="org-a", extension_id="ext-x")).events == 2
    assert (await meter.totals(org_id="org-a", publisher_id="pub-b")).input_tokens == 7
    assert (await meter.totals(org_id="org-a", capability="tool.fetch")).output_tokens == 3

    by_workspace = await meter.breakdown("workspace", org_id="org-a")
    assert set(by_workspace) == {"workspace-a", "workspace-b"}
    by_capability = await meter.breakdown("capability", org_id="org-a", workspace_id="workspace-a")
    assert by_capability["model.chat"].events == 2

    early = await meter.totals(org_id="org-a", since=0, until=1_000)
    late = await meter.totals(org_id="org-a", since=1_000)
    empty = await meter.totals(org_id="org-a", since=0, until=0)
    assert early.events == 0 and late.events == 3 and empty.events == 0
    windowed = await meter.totals(org_id="org-a", since=900, until=1_100)
    assert windowed.events == 3  # fixture clock stamps every row at t=1000


async def test_host_measured_resources_sum_only_where_measured(meter: ExtensionMeter) -> None:
    await meter.record(event("evt-cpu", invocation_id=None, cpu_ms=250, memory_bytes=1024))
    await meter.record(event("evt-plain", input_tokens=5))
    totals = await meter.totals(org_id="org-a")
    assert totals.cpu_ms == 250 and totals.memory_bytes == 1024
    assert totals.network_bytes is None  # no row in scope measured it


# ---------------------------------------------------------------------------
# Quota admission, exhaustion, and bypass resistance (AC 3, 4)
# ---------------------------------------------------------------------------


async def test_reserve_holds_then_commit_settles_and_release_refunds(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy())
    await quota.reserve(request("res-a"))
    held = await quota.policy_balance("workspace-tokens")
    assert (held.held, held.spent, held.available) == (60, 0, 40)

    await quota.commit("res-a", ExtensionUsageAmounts(tokens=55))
    settled = await quota.policy_balance("workspace-tokens")
    assert (settled.held, settled.spent, settled.available) == (0, 55, 45)

    await quota.reserve(request("res-b", tokens=45))
    held_again = await quota.policy_balance("workspace-tokens")
    assert (held_again.held, held_again.available) == (45, 0)
    await quota.release("res-b")
    refunded = await quota.policy_balance("workspace-tokens")
    assert (refunded.held, refunded.spent, refunded.available) == (0, 55, 45)
    await quota.release("res-b")  # idempotent refund


async def test_exhaustion_cannot_be_bypassed_by_retry_new_agent_or_alias(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy(limit=100))
    await quota.reserve(request("res-a", caller="agent-a", extension="ext-x", tokens=100))
    assert (await quota.policy_balance("workspace-tokens")).available == 0

    # A refused reservation commits its refusal evidence: the retry re-raises
    # the same denial, and reshaping the facts under the same id conflicts
    # instead of escaping the ledger.
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(request("res-b", caller="agent-b", tokens=200))
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(request("res-b", caller="agent-b", tokens=200))
    with pytest.raises(ExtensionQuotaConflict, match="different facts"):
        await quota.reserve(request("res-b", caller="agent-b", tokens=1))

    # A new Agent and an alternate extension alias draw from the same
    # Workspace budget: both refused, nothing additional held.
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(request("res-c", caller="agent-b", tokens=1))
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(
            request("res-d", extension="ext-x-alias", publisher_id="pub-alias", tokens=1)
        )
    assert (await quota.policy_balance("workspace-tokens")).held == 100


async def test_org_wide_policy_backstops_alias_workspaces(quota: ExtensionQuotaLedger) -> None:
    """An org-wide budget is matched by scope, not by caller or extension
    identity, so exhaustion in one Workspace denies every alias elsewhere."""
    await quota.register_policy(policy("org-tokens", limit=100, workspace_id=None))
    await quota.reserve(request("res-a", tokens=100))
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(
            request(
                "res-b",
                workspace_id="workspace-b",
                caller="agent-b",
                extension="ext-alias",
                publisher_id="pub-alias",
                tokens=1,
            )
        )


async def test_reservation_id_is_idempotent_but_facts_changes_conflict(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy())
    await quota.reserve(request("res-a", tokens=60))
    await quota.reserve(request("res-a", tokens=60))  # identical retry
    assert (await quota.policy_balance("workspace-tokens")).held == 60
    with pytest.raises(ExtensionQuotaConflict, match="different facts"):
        await quota.reserve(request("res-a", tokens=61))
    assert (await quota.policy_balance("workspace-tokens")).held == 60


async def test_release_then_commit_is_an_evidence_conflict(quota: ExtensionQuotaLedger) -> None:
    await quota.register_policy(policy())
    await quota.reserve(request("res-a"))
    await quota.release("res-a")
    with pytest.raises(ExtensionQuotaConflict, match="released reservation cannot settle"):
        await quota.commit("res-a", ExtensionUsageAmounts(tokens=60))
    with pytest.raises(ExtensionQuotaConflict, match="unknown reservation"):
        await quota.commit("res-missing", ExtensionUsageAmounts(tokens=1))


async def test_commit_actual_above_hold_is_truthful_overage(quota: ExtensionQuotaLedger) -> None:
    await quota.register_policy(policy(limit=100))
    await quota.reserve(request("res-a", tokens=60))
    await quota.commit("res-a", ExtensionUsageAmounts(tokens=120))
    balance = await quota.policy_balance("workspace-tokens")
    assert (balance.spent, balance.available) == (120, -20)


async def test_provider_corrections_revise_settled_spend_with_monotonic_revisions(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy(limit=100))
    await quota.reserve(request("res-a", tokens=60))
    await quota.commit("res-a", ExtensionUsageAmounts(tokens=100))
    await quota.correct(
        "res-a",
        revision=1,
        evidence_id="provider-batch-9",
        amounts=ExtensionUsageAmounts(tokens=80),
    )
    assert (await quota.policy_balance("workspace-tokens")).spent == 80

    await quota.correct(
        "res-a",
        revision=1,
        evidence_id="provider-batch-9",
        amounts=ExtensionUsageAmounts(tokens=80),
    )
    assert (await quota.policy_balance("workspace-tokens")).spent == 80  # idempotent replay

    with pytest.raises(ExtensionQuotaConflict, match="correction identity/revision was reused"):
        await quota.correct(
            "res-a",
            revision=1,
            evidence_id="provider-batch-9",
            amounts=ExtensionUsageAmounts(tokens=70),
        )
    with pytest.raises(ValueError, match="revision zero"):
        await quota.correct(
            "res-a", revision=0, evidence_id="x", amounts=ExtensionUsageAmounts(tokens=1)
        )

    # A newer revision applies; a stale-but-unclaimed revision (never used
    # before) is recorded as evidence and never rolls accounting backwards.
    await quota.correct(
        "res-a",
        revision=3,
        evidence_id="provider-batch-13",
        amounts=ExtensionUsageAmounts(tokens=90),
    )
    assert (await quota.policy_balance("workspace-tokens")).spent == 90
    await quota.correct(
        "res-a",
        revision=2,
        evidence_id="provider-batch-12",
        amounts=ExtensionUsageAmounts(tokens=10),
    )
    assert (await quota.policy_balance("workspace-tokens")).spent == 90
    # Re-claiming an already-used revision number with different facts is a
    # revision collision, not a correction.
    with pytest.raises(ExtensionQuotaConflict, match="correction identity/revision was reused"):
        await quota.correct(
            "res-a",
            revision=2,
            evidence_id="provider-batch-14",
            amounts=ExtensionUsageAmounts(tokens=5),
        )


async def test_rate_limit_refuses_inside_window_and_refusals_consume_nothing(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy(rate_limit=2, rate_window_s=60))
    await quota.reserve(request("res-a", tokens=1))
    await quota.reserve(request("res-b", tokens=1))
    with pytest.raises(ExtensionQuotaDenied, match="rate limit exceeded"):
        await quota.reserve(request("res-c", tokens=1))
    with pytest.raises(ExtensionQuotaDenied, match="rate limit exceeded"):
        await quota.reserve(request("res-d", tokens=1))
    windowed = ExtensionQuotaLedger(quota._path, clock=lambda: CLOCK + 61)
    await windowed.reserve(request("res-e", tokens=1))
    assert (await quota.policy_balance("workspace-tokens")).spent == 0


async def test_unconfigured_admits_but_applicable_gap_denies(quota: ExtensionQuotaLedger) -> None:
    await quota.reserve(request("res-a"))  # no policies anywhere: unconfigured admits
    await quota.register_policy(
        policy("other-org", org_id="org-b"),
    )
    with pytest.raises(ExtensionQuotaDenied, match="missing applicable quota policy"):
        await quota.reserve(request("res-b"))


async def test_missing_upper_bound_denies(quota: ExtensionQuotaLedger) -> None:
    await quota.register_policy(policy())
    with pytest.raises(ExtensionQuotaDenied, match="missing upper bound"):
        await quota.reserve(request("res-a", tokens=None))
    assert (await quota.policy_balance("workspace-tokens")).held == 0


async def test_opening_spend_and_reserve_shrink_the_usable_ceiling(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(
        policy(limit=100, opening_spend=30, reserve=10, coverage_ref="operator-attested")
    )
    await quota.reserve(request("res-a", tokens=60))
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(request("res-b", tokens=1))
    balance = await quota.policy_balance("workspace-tokens")
    assert balance.ceiling == 90 and balance.spent == 30 and balance.held == 60


# ---------------------------------------------------------------------------
# Concurrency (AC 3): server-side enforcement under multi-worker load
# ---------------------------------------------------------------------------


async def test_concurrent_admissions_cannot_oversubscribe_remaining_budget(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(policy(limit=100))
    outcomes = await asyncio.gather(
        *[_reserve_result(quota, request(f"res-{index}", tokens=60)) for index in range(4)]
    )
    assert outcomes.count("admitted") == 1
    assert outcomes.count("denied") == 3
    assert (await quota.policy_balance("workspace-tokens")).held == 60


async def _reserve_result(ledger: ExtensionQuotaLedger, attempt: ExtensionQuotaRequest) -> str:
    try:
        await ledger.reserve(attempt)
    except ExtensionQuotaDenied:
        return "denied"
    return "admitted"


async def test_concurrent_duplicate_reservations_hold_once(quota: ExtensionQuotaLedger) -> None:
    await quota.register_policy(policy(limit=100))
    outcomes = await asyncio.gather(
        *[_reserve_result(quota, request("res-same", tokens=60)) for _ in range(6)]
    )
    assert outcomes == ["admitted"] * 6
    assert (await quota.policy_balance("workspace-tokens")).held == 60


def _process_reserve(path: str, barrier: Any, queue: Any, name: str) -> None:
    async def run() -> None:
        replica = ExtensionQuotaLedger(path, clock=lambda: CLOCK)
        barrier.wait(timeout=30)
        try:
            await replica.reserve(request(f"res-{name}", caller=f"agent-{name}", tokens=60))
            queue.put("admitted")
        except ExtensionQuotaDenied:
            queue.put("denied")
        barrier.wait(timeout=30)

    asyncio.run(run())


async def test_two_os_processes_cannot_race_same_remaining_budget(
    tmp_path: Path,
) -> None:
    quota = ExtensionQuotaLedger(tmp_path / "quota.sqlite", clock=lambda: CLOCK)
    await quota.ensure_schema()
    await quota.register_policy(policy(limit=100))
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(target=_process_reserve, args=(str(quota._path), barrier, queue, name))
        for name in ("one", "two")
    ]
    # pytest's importlib import mode keeps the tests tree off sys.path, but
    # the spawned replica must import this module by name to unpickle the
    # worker. Hand it the tests root; the child inherits the parent's path.
    old_path = list(sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        for process in processes:
            process.start()
        results = [await asyncio.to_thread(queue.get, True, 60) for _ in processes]
        assert sorted(results) == ["admitted", "denied"]
        for process in processes:
            await asyncio.to_thread(process.join, 60)
            assert process.exitcode == 0
        assert (await quota.policy_balance("workspace-tokens")).held == 60
    finally:
        sys.path[:] = old_path
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        queue.close()


# ---------------------------------------------------------------------------
# Ledger configuration refusals (AC: quotas are enforced server-side — a
# malformed policy or misconfigured ledger never half-registers)
# ---------------------------------------------------------------------------


def test_quota_policy_construction_refuses_invalid_configuration() -> None:
    """A policy that cannot be honored is refused at declaration time, not at
    admission time: every field pair that would make a limit meaningless
    (unknown unit, reserve above limit, empty or inverted billing period,
    half-specified rate limiting, a rate limit that refuses every call) is a
    construction error."""
    with pytest.raises(ValueError, match="unknown quota unit"):
        policy(unit="bits")
    with pytest.raises(ValueError, match="invalid reserve or billing period"):
        policy(reserve=101)
    with pytest.raises(ValueError, match="invalid reserve or billing period"):
        policy(period_start=10_000, period_end=10_000)
    with pytest.raises(ValueError, match="rate limiting needs both"):
        policy(rate_limit=5)
    with pytest.raises(ValueError, match="rate limiting needs both"):
        policy(rate_window_s=60)
    with pytest.raises(ValueError, match="rate_limit of zero refuses every call"):
        policy(rate_limit=0, rate_window_s=60)


def test_ledger_refuses_memory_or_blank_database_paths() -> None:
    """Quota and usage ledgers are shared, durable state: ``:memory:`` would
    give every process its own private budget and silently void server-side
    enforcement, so an explicit shared file is mandatory."""
    with pytest.raises(ValueError, match="explicit shared SQLite file"):
        ExtensionQuotaLedger(":memory:")
    with pytest.raises(ValueError, match="explicit shared SQLite file"):
        ExtensionMeter("   ")


async def test_register_policy_is_idempotent_but_identity_is_immutable(
    quota: ExtensionQuotaLedger,
) -> None:
    """Re-declaring a policy verbatim is a no-op (operators retry); changing a
    registered policy's facts under the same identity conflicts, because a new
    limit needs a new ``policy_id`` to stay auditable."""
    await quota.register_policy(policy("p", limit=100))
    await quota.register_policy(policy("p", limit=100))  # verbatim re-declaration
    with pytest.raises(ExtensionQuotaConflict, match="policy identity is immutable"):
        await quota.register_policy(policy("p", limit=200))


async def test_policy_balance_of_unknown_policy_names_it(
    quota: ExtensionQuotaLedger,
) -> None:
    with pytest.raises(KeyError, match="no-such-policy"):
        await quota.policy_balance("no-such-policy")


async def test_non_finite_admission_clock_is_refused(tmp_path: Path) -> None:
    """Admission samples the clock after taking the write lock; a broken clock
    must refuse admission rather than reserve against a nonsense timestamp."""
    path = tmp_path / "metering.sqlite"
    quota = ExtensionQuotaLedger(path, clock=lambda: CLOCK)
    await quota.ensure_schema()
    await quota.register_policy(policy())
    broken = ExtensionQuotaLedger(path, clock=lambda: float("nan"))
    await broken.ensure_schema()
    with pytest.raises(ValueError, match="invalid admission clock"):
        await broken.reserve(request("res-clock"))
    assert (await quota.policy_balance("workspace-tokens")).held == 0


# ---------------------------------------------------------------------------
# Policy scope and period gating (AC: usage queries and enforcement aggregate
# by scope — a policy only governs the scope and window it declares)
# ---------------------------------------------------------------------------


async def test_policy_scope_and_period_gate_applicability(tmp_path: Path) -> None:
    now = [CLOCK]
    quota = ExtensionQuotaLedger(tmp_path / "metering.sqlite", clock=lambda: now[0])
    await quota.ensure_schema()
    await quota.register_policy(policy("scoped", limit=100, workspace_id="workspace-a"))

    # A different Workspace matches no applicable policy: refused by the gap
    # rule, never silently admitted without governance.
    with pytest.raises(ExtensionQuotaDenied, match="missing applicable quota policy"):
        await quota.reserve(request("res-other-ws", workspace_id="workspace-b"))

    # The period is half-open: at ``period_end`` the same policy stops
    # applying, so post-period admissions are refused, not charged to the
    # closed period.
    now[0] = 10_000.0
    with pytest.raises(ExtensionQuotaDenied, match="missing applicable quota policy"):
        await quota.reserve(request("res-after-window"))
    assert (await quota.policy_balance("scoped")).held == 0


# ---------------------------------------------------------------------------
# Non-token quota units settle in their own unit (AC: provider/tool spend
# attribution — micro_usd and request budgets are first-class, not token
# proxies)
# ---------------------------------------------------------------------------


async def test_micro_usd_and_request_policies_settle_in_their_own_unit(
    quota: ExtensionQuotaLedger,
) -> None:
    await quota.register_policy(
        policy("usd", unit="micro_usd", limit=1_000, capability="model.spend")
    )
    await quota.reserve(request("res-usd", tokens=None, micro_usd=400, capability="model.spend"))
    await quota.commit("res-usd", ExtensionUsageAmounts(tokens=0, micro_usd=400, requests=1))
    assert (await quota.policy_balance("usd")).spent == 400

    # ``requests`` is always bounded (one reservation is one request), so a
    # request policy admits without any caller-supplied upper bound.
    await quota.register_policy(
        policy("reqs", unit="requests", limit=10, capability="model.invoke")
    )
    await quota.reserve(request("res-reqs", tokens=None, micro_usd=None, capability="model.invoke"))
    await quota.commit("res-reqs", ExtensionUsageAmounts(tokens=0, micro_usd=0, requests=1))
    assert (await quota.policy_balance("reqs")).spent == 1


# ---------------------------------------------------------------------------
# Terminal-state guards (AC: rollback/refund semantics and provider-reported
# corrections cannot contradict committed facts)
# ---------------------------------------------------------------------------


async def test_denied_reservations_carry_no_provider_outcome(
    quota: ExtensionQuotaLedger,
) -> None:
    """A reservation that was refused never dispatched work, so it has no
    measured usage to settle — settling one would fabricate spend evidence."""
    await quota.register_policy(policy(limit=100))
    await quota.reserve(request("res-hold", tokens=100))
    with pytest.raises(ExtensionQuotaDenied, match="quota exhausted"):
        await quota.reserve(request("res-refused", tokens=1))
    with pytest.raises(ExtensionQuotaConflict, match="denied reservation has no provider outcome"):
        await quota.commit("res-refused", ExtensionUsageAmounts(tokens=1))


async def test_commit_replay_is_idempotent_but_changed_amounts_conflict(
    quota: ExtensionQuotaLedger,
) -> None:
    """Settlement is idempotent on verbatim retry (the caller may crash after
    the provider call and retry), but different amounts under the same
    reservation identity are two contradictory facts about one execution."""
    await quota.register_policy(policy(limit=100))
    await quota.reserve(request("res-a", tokens=60))
    await quota.commit("res-a", ExtensionUsageAmounts(tokens=60))
    await quota.commit("res-a", ExtensionUsageAmounts(tokens=60))  # identical replay
    assert (await quota.policy_balance("workspace-tokens")).spent == 60
    with pytest.raises(ExtensionQuotaConflict, match="settlement identity was reused"):
        await quota.commit("res-a", ExtensionUsageAmounts(tokens=61))


async def test_settled_reservations_cannot_be_released(
    quota: ExtensionQuotaLedger,
) -> None:
    """Refunding executed work would un-charge spend the ledger already
    reported; a settled reservation is past the refundable stage."""
    await quota.register_policy(policy())
    await quota.reserve(request("res-a"))
    await quota.commit("res-a", ExtensionUsageAmounts(tokens=60))
    with pytest.raises(ExtensionQuotaConflict, match="settled reservation cannot be released"):
        await quota.release("res-a")


async def test_corrections_apply_only_to_settled_reservations(
    quota: ExtensionQuotaLedger,
) -> None:
    """Provider-reported corrections revise measured usage; a held reservation
    has no measured usage yet, and revision zero is the canonical settlement
    itself, never a correction."""
    await quota.register_policy(policy())
    await quota.reserve(request("res-a"))
    with pytest.raises(ValueError, match="revision zero is reserved"):
        await quota.correct(
            "res-a",
            revision=0,
            evidence_id="evg-zero",
            amounts=ExtensionUsageAmounts(tokens=1),
        )
    with pytest.raises(
        ExtensionQuotaConflict,
        match="only settled reservations carry measured usage to correct",
    ):
        await quota.correct(
            "res-a",
            revision=1,
            evidence_id="evg-1",
            amounts=ExtensionUsageAmounts(tokens=1),
        )


# ---------------------------------------------------------------------------
# Aggregation scope (AC: usage queries aggregate by Workspace, extension,
# publisher, capability and time window — including across every org)
# ---------------------------------------------------------------------------


async def test_totals_without_org_filter_aggregate_every_org(
    meter: ExtensionMeter,
) -> None:
    await meter.record(event("evt-a", org_id="org-a"))
    await meter.record(event("evt-b", org_id="org-b"))
    every_org = await meter.totals()
    org_a = await meter.totals(org_id="org-a")
    assert every_org.events == 2
    assert every_org.input_tokens == org_a.input_tokens * 2
    assert every_org.micro_usd == org_a.micro_usd * 2
    org_filtered = await meter.totals(org_id="org-b")
    assert org_filtered.events == 1


# ---------------------------------------------------------------------------
# Cancellation during admission (AC: concurrent enforcement — a cancelled
# caller must not lose or duplicate its hold)
# ---------------------------------------------------------------------------


async def test_cancelled_admission_propagates_after_the_transaction_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling a caller that awaits admission propagates cancellation only
    after the in-flight SQLite transaction finishes — never mid-transaction —
    so the reservation is either fully taken or not taken. The identical retry
    is then an idempotent no-op: the hold is neither lost nor doubled."""
    path = tmp_path / "metering.sqlite"
    quota = ExtensionQuotaLedger(path, clock=lambda: CLOCK)
    await quota.ensure_schema()
    await quota.register_policy(policy())

    release = asyncio.Event()

    async def gated_to_thread(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        await release.wait()
        return fn(*args, **kwargs)

    monkeypatch.setattr("maistro.extensions.metering.asyncio.to_thread", gated_to_thread)
    task = asyncio.create_task(quota.reserve(request("res-cancel")))
    await asyncio.sleep(0)  # park the admission inside the gated hand-off
    task.cancel()
    release.set()  # the transaction always completes
    with pytest.raises(asyncio.CancelledError):
        await task

    # The completed transaction stands: an identical retry holds nothing more.
    await quota.reserve(request("res-cancel"))
    assert (await quota.policy_balance("workspace-tokens")).held == 60
