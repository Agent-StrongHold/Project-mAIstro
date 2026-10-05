"""PostgreSQL parity checks for canonical Invocation quota settlement."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
    ReconciliationDisposition,
)
from maistro.quota.invocation_quota import (
    InvocationQuotaDenied,
    QuotaBudget,
    QuotaEstimate,
    QuotaEvidenceConflict,
    QuotaObservation,
)
from maistro.quota.pg_invocation_quota import PgInvocationQuota


def _pg_dsn() -> str:
    return os.getenv("MAISTRO_TEST_PG_DSN", "").strip()


requires_postgres = pytest.mark.skipif(
    not _pg_dsn(), reason="set MAISTRO_TEST_PG_DSN to a PostgreSQL DSN"
)


def _binding(suffix: str, *, provider_name: str = "provider-pg") -> Binding:
    return Binding(
        binding_id=f"pg-binding-{suffix}",
        workspace_id=f"pg-workspace-{suffix}",
        project_id="pg-project",
        capability="model.chat",
        provider_name=provider_name,
    )


def _invocation(
    binding: Binding,
    *,
    invocation_id: str,
    effect_key: str = "effect",
    provider_name: str | None = None,
) -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id="pg-run",
        node_run_id="pg-node",
        attempt_id=f"attempt-{invocation_id}",
        binding=ResolvedBinding(
            binding_id=binding.binding_id,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            capability=binding.capability,
            provider_name=provider_name or binding.provider_name,
            provider_trust_tier="trusted",
        ),
        effect_key=effect_key,
    )


async def _cleanup(pool: Any, suffix: str, budget_ids: list[str]) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM invocation_quota_evidence WHERE invocation_id IN "
            "(SELECT invocation_id FROM invocation_quota_reservations WHERE invocation_id LIKE $1)",
            f"pg-invocation-%-{suffix}",
        )
        await conn.execute(
            "DELETE FROM invocation_quota_allocations WHERE invocation_id IN "
            "(SELECT invocation_id FROM invocation_quota_reservations WHERE invocation_id LIKE $1)",
            f"pg-invocation-%-{suffix}",
        )
        await conn.execute(
            "DELETE FROM invocation_quota_reservations WHERE invocation_id LIKE $1",
            f"pg-invocation-%-{suffix}",
        )
        for budget_id in budget_ids:
            await conn.execute("DELETE FROM invocation_quota_budgets WHERE budget_id=$1", budget_id)


@pytest.mark.asyncio
async def test_pg_quota_releases_not_applied_and_reconciles_partial_usage() -> None:
    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if "://" not in dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a PostgreSQL DSN")
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-quota-{suffix}"
    binding = Binding(
        binding_id=f"pg-binding-{suffix}",
        workspace_id=f"pg-workspace-{suffix}",
        project_id="pg-project",
        capability="model.chat",
        provider_name="provider-pg",
    )

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=60)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )
        failed = Invocation(
            invocation_id=f"pg-invocation-failed-{suffix}",
            run_id="pg-run",
            node_run_id="pg-node",
            attempt_id="pg-attempt-failed",
            binding=ResolvedBinding(
                binding_id=binding.binding_id,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                capability=binding.capability,
                provider_name="provider-pg",
                provider_trust_tier="trusted",
            ),
            effect_key="known-not-applied",
        )
        await quota.reserve(failed, binding)
        await quota.observe(
            failed.model_copy(
                update={"status": InvocationStatus.FAILED, "finished_at": datetime.now(UTC)}
            )
        )
        row = await pool.fetchrow(
            "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1",
            failed.invocation_id,
        )
        assert row["state"] == "released"

        completed = failed.model_copy(
            update={
                "invocation_id": f"pg-invocation-completed-{suffix}",
                "attempt_id": "pg-attempt-completed",
                "effect_key": "completed-without-usage",
                "status": InvocationStatus.CREATED,
                "finished_at": None,
            }
        )
        await quota.reserve(completed, binding)
        await quota.observe(
            completed.model_copy(
                update={"status": InvocationStatus.COMPLETED, "finished_at": datetime.now(UTC)}
            )
        )
        row = await pool.fetchrow(
            "SELECT spent, held FROM invocation_quota_allocations WHERE invocation_id=$1",
            completed.invocation_id,
        )
        assert row["spent"] == 0 and row["held"] == 60
        await quota.reconcile(
            QuotaObservation(
                invocation_id=completed.invocation_id,
                provider_name="provider-pg",
                evidence_id="provider-record-1",
                revision=1,
                outcome="completed",
                tokens=20,
            )
        )
        row = await pool.fetchrow(
            "SELECT spent, held FROM invocation_quota_allocations WHERE invocation_id=$1",
            completed.invocation_id,
        )
        assert row["spent"] == 20 and row["held"] == 0
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM invocation_quota_evidence WHERE invocation_id IN "
                "(SELECT invocation_id FROM invocation_quota_reservations WHERE invocation_id LIKE $1)",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute(
                "DELETE FROM invocation_quota_allocations WHERE invocation_id IN "
                "(SELECT invocation_id FROM invocation_quota_reservations WHERE invocation_id LIKE $1)",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute(
                "DELETE FROM invocation_quota_reservations WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute("DELETE FROM invocation_quota_budgets WHERE budget_id=$1", budget_id)
        await pool.close()


@pytest.mark.asyncio
async def test_pg_admission_subtracts_opening_spend_like_sqlite() -> None:
    """A budget's verified prior spend bounds what is still admissible.

    `opening_spend` is attested spend already made inside this period, and the
    SQLite backend has always counted it. PostgreSQL did not, so a limit of 100
    with opening spend 90 reported 100 units available and admitted a 20-unit
    request against the 10 that actually remained -- a configured budget
    exceeded by up to its entire opening balance (Codex, #1362).
    """

    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if "://" not in dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a PostgreSQL DSN")
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-opening-{suffix}"
    binding = Binding(
        binding_id=f"pg-binding-{suffix}",
        workspace_id=f"pg-workspace-{suffix}",
        project_id="pg-project",
        capability="model.chat",
        provider_name="provider-pg",
    )

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=20)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=90,  # only 10 of the 100 remain
                provider_name="provider-pg",
            )
        )
        invocation = Invocation(
            invocation_id=f"pg-invocation-opening-{suffix}",
            run_id="pg-run",
            node_run_id="pg-node",
            attempt_id="pg-attempt-opening",
            binding=ResolvedBinding(
                binding_id=binding.binding_id,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                capability=binding.capability,
                provider_name="provider-pg",
                provider_trust_tier="trusted",
            ),
            effect_key="over-the-opening-balance",
        )

        with pytest.raises(InvocationQuotaDenied, match="exhausted"):
            await quota.reserve(invocation, binding)

        # Refused before any hold: a denial records the decision and nothing else.
        row = await pool.fetchrow(
            "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["state"] == "denied"
        held = await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_allocations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert held == 0
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM invocation_quota_allocations WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute(
                "DELETE FROM invocation_quota_reservations WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute("DELETE FROM invocation_quota_budgets WHERE budget_id=$1", budget_id)
        await pool.close()


@pytest.mark.asyncio
async def test_pg_restores_the_hold_when_completion_retracts_a_release() -> None:
    """Newer evidence saying the call *did* happen must not leave it free.

    A `not_applied` observation releases the allocation: `spent=0`, `held=0`,
    `measured=true`. If a later, higher-revision observation says the provider
    was dispatched after all but still carries no usage for a dimension, the
    released zeros belong to the proof being retracted. Keeping them settles a
    real but unmeasured provider call as consuming no quota at all.

    SQLite has always restored `held=maximum` for this transition; PostgreSQL
    kept the zeros and marked the reservation settled (Codex, #1362).
    """

    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if "://" not in dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a PostgreSQL DSN")
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-retract-{suffix}"
    binding = Binding(
        binding_id=f"pg-binding-{suffix}",
        workspace_id=f"pg-workspace-{suffix}",
        project_id="pg-project",
        capability="model.chat",
        provider_name="provider-pg",
    )

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=40)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )
        invocation = Invocation(
            invocation_id=f"pg-invocation-retract-{suffix}",
            run_id="pg-run",
            node_run_id="pg-node",
            attempt_id="pg-attempt-retract",
            binding=ResolvedBinding(
                binding_id=binding.binding_id,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                capability=binding.capability,
                provider_name="provider-pg",
                provider_trust_tier="trusted",
            ),
            effect_key="released-then-completed",
        )
        await quota.reserve(invocation, binding)

        # Revision 0: the canonical terminal record says it never applied.
        await quota.observe(
            invocation.model_copy(
                update={"status": InvocationStatus.FAILED, "finished_at": datetime.now(UTC)}
            )
        )
        row = await pool.fetchrow(
            "SELECT spent, held, measured FROM invocation_quota_allocations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert (row["spent"], row["held"]) == (0, 0)

        # Revision 1: trusted provider evidence retracts that, with no usage.
        await quota.reconcile(
            QuotaObservation(
                invocation_id=invocation.invocation_id,
                provider_name="provider-pg",
                evidence_id="provider-correction",
                revision=1,
                outcome="completed",
                tokens=None,
                micro_usd=None,
            )
        )

        row = await pool.fetchrow(
            "SELECT spent, held, measured FROM invocation_quota_allocations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        # The hold comes back, unmeasured: a real call that consumed something
        # nobody has reported yet.
        assert row["spent"] == 0
        assert row["held"] == 40
        assert row["measured"] is False
        state = await pool.fetchval(
            "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert state == "pending_usage"
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM invocation_quota_evidence WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute(
                "DELETE FROM invocation_quota_allocations WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute(
                "DELETE FROM invocation_quota_reservations WHERE invocation_id LIKE $1",
                f"pg-invocation-%-{suffix}",
            )
            await conn.execute("DELETE FROM invocation_quota_budgets WHERE budget_id=$1", budget_id)
        await pool.close()


# ---------------------------------------------------------------------------
# #1362 diff-coverage gate: the admission/settlement branches above were never
# exercised against a real server -- an empty budget registry vs. one that
# covers nothing applicable, a replayed/reused/denied reservation, an
# out-of-period or unbounded budget, a non-terminal or "unknown" terminal
# status, a stale or byte-mismatched reconciliation, and an unknown outcome
# trying to overwrite a confirmed one.
# ---------------------------------------------------------------------------


@requires_postgres
async def test_pg_register_budget_rejects_a_redefinition_of_the_same_budget_id() -> None:
    """A budget_id names one immutable policy; a second, different
    definition under the same id is a caller bug, not a new version."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-immutable-{suffix}"

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
            )
        )

        with pytest.raises(QuotaEvidenceConflict, match="budget identity is immutable"):
            await quota.register_budget(
                QuotaBudget(
                    budget_id=budget_id,
                    unit="tokens",
                    limit=200,  # a different definition under the same id
                    period_start=0,
                    period_end=1000,
                    coverage_ref="test",
                    opening_spend=0,
                )
            )
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_reserve_admits_freely_when_no_budget_is_registered() -> None:
    """An empty budget registry means quota admission is not configured at
    all, and an unconfigured door admits -- distinct from a registry that
    covers nothing applicable to this call, which refuses (Codex, #1362)."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-noconfig-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)

        row = await pool.fetchrow(
            "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["state"] == "held"
        allocated = await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_allocations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert allocated == 0
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reserve_denies_when_budgets_exist_but_none_apply() -> None:
    """A populated budget table that covers nothing applicable to this call
    is a policy gap worth refusing, unlike an empty one (Codex, #1362)."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-inapplicable-{suffix}"
    binding = _binding(suffix, provider_name="provider-pg")

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(
        binding, invocation_id=f"pg-invocation-inapplicable-{suffix}", provider_name="provider-pg"
    )
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="some-other-provider",
            )
        )

        with pytest.raises(InvocationQuotaDenied, match="missing applicable quota policy"):
            await quota.reserve(invocation, binding)

        row = await pool.fetchrow(
            "SELECT state, reason FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["state"] == "denied"
        assert row["reason"] == "missing applicable quota policy"
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_reserve_rejects_a_nonfinite_admission_clock() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: math.nan)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-badclock-{suffix}")
    try:
        await quota.ensure_schema()
        with pytest.raises(ValueError, match="invalid admission clock"):
            await quota.reserve(invocation, binding)
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reserve_is_idempotent_for_the_same_invocation_and_identity() -> None:
    """A retried `reserve` call for the same physical Invocation is a replay,
    not a second admission decision: the second call must not raise and must
    not allocate a second hold."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-replay-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-replay-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )
        await quota.reserve(invocation, binding)
        await quota.reserve(invocation, binding)  # replay, must not raise or double-hold

        allocation_count = await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_allocations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert allocation_count == 1
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_reserve_rejects_identity_reuse_on_the_same_invocation_id() -> None:
    """The same `invocation_id` reserving for a different effect entirely is
    not a replay -- it is the identity being reused for a different call,
    which must be refused rather than silently answered with the first
    call's decision."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)
    invocation_id = f"pg-invocation-identity-{suffix}"

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    first = _invocation(binding, invocation_id=invocation_id, effect_key="effect-a")
    second = _invocation(binding, invocation_id=invocation_id, effect_key="effect-b")
    try:
        await quota.ensure_schema()
        await quota.reserve(first, binding)

        with pytest.raises(QuotaEvidenceConflict, match="identity was reused"):
            await quota.reserve(second, binding)
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reserve_replays_a_prior_denial_without_re_deciding() -> None:
    """Once denied, a retried `reserve` for the same Invocation must stay
    denied even if the budget would now admit it -- the decision was already
    made and recorded, not re-opened against a budget that may since have
    freed up."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-denyreplay-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=1000)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-denyreplay-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=10,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )
        with pytest.raises(InvocationQuotaDenied, match="quota exhausted"):
            await quota.reserve(invocation, binding)

        # Raise the ceiling so the budget would now admit the same request --
        # the replay must still see the original denial, not a fresh decision.
        await pool.execute(
            "UPDATE invocation_quota_budgets "
            "SET definition = jsonb_set(definition, '{limit}', '100000') "
            "WHERE budget_id=$1",
            budget_id,
        )

        with pytest.raises(InvocationQuotaDenied, match="quota exhausted"):
            await quota.reserve(invocation, binding)
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_hold_against_treats_an_out_of_period_budget_as_inapplicable() -> None:
    """A budget whose period does not cover the admission clock is exactly
    as inapplicable as one scoped to a different provider/workspace."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-period-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    # The clock (900) falls after this budget's period ends (500).
    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 900)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-period-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=500,
                coverage_ref="test",
                opening_spend=0,
            )
        )

        with pytest.raises(InvocationQuotaDenied, match="missing applicable quota policy"):
            await quota.reserve(invocation, binding)
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_reserve_rejects_when_the_estimate_has_no_upper_bound() -> None:
    """The only applicable budget is priced in `micro_usd`, but the
    estimator could not bound this call's cost -- admission must refuse
    rather than hold an unbounded amount."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-nobound-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10, micro_usd=None)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-nobound-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="micro_usd",
                limit=100,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )

        with pytest.raises(
            InvocationQuotaDenied, match=f"missing upper bound for budget {budget_id}"
        ):
            await quota.reserve(invocation, binding)
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_observe_ignores_nonterminal_invocation_status() -> None:
    """`observe` must return before touching the database at all for a
    CREATED or RUNNING Invocation -- neither is a terminal fact yet."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    created = _invocation(binding, invocation_id=f"pg-invocation-created-{suffix}")
    running = created.model_copy(
        update={
            "invocation_id": f"pg-invocation-running-{suffix}",
            "status": InvocationStatus.RUNNING,
        }
    )
    try:
        await quota.ensure_schema()
        # Neither was ever reserved.
        await quota.observe(created)
        await quota.observe(running)

        count = await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_reservations "
            "WHERE invocation_id = ANY($1::text[])",
            [created.invocation_id, running.invocation_id],
        )
        assert count == 0
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_observe_records_token_and_cost_usage_from_a_completed_invocation() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    token_budget_id = f"pg-budget-tokens-{suffix}"
    cost_budget_id = f"pg-budget-cost-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=100, micro_usd=100_000)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-usage-{suffix}")
    try:
        await quota.ensure_schema()
        for budget_id, unit in ((token_budget_id, "tokens"), (cost_budget_id, "micro_usd")):
            await quota.register_budget(
                QuotaBudget(
                    budget_id=budget_id,
                    unit=unit,
                    limit=1_000_000,
                    period_start=0,
                    period_end=1000,
                    coverage_ref="test",
                    opening_spend=0,
                    provider_name="provider-pg",
                )
            )
        await quota.reserve(invocation, binding)

        await quota.observe(
            invocation.model_copy(
                update={
                    "status": InvocationStatus.COMPLETED,
                    "finished_at": datetime.now(UTC),
                    "usage": InvocationUsage(
                        units="tokens", input_units=30, output_units=20, cost_cents=2.5
                    ),
                }
            )
        )

        token_row = await pool.fetchrow(
            "SELECT spent, held FROM invocation_quota_allocations "
            "WHERE invocation_id=$1 AND budget_id=$2",
            invocation.invocation_id,
            token_budget_id,
        )
        assert (token_row["spent"], token_row["held"]) == (50, 0)
        cost_row = await pool.fetchrow(
            "SELECT spent, held FROM invocation_quota_allocations "
            "WHERE invocation_id=$1 AND budget_id=$2",
            invocation.invocation_id,
            cost_budget_id,
        )
        # 2.5 cost_cents -> 25,000 micro_usd (cents * 10_000, rounded up).
        assert (cost_row["spent"], cost_row["held"]) == (25_000, 0)
    finally:
        await _cleanup(pool, suffix, [token_budget_id, cost_budget_id])
        await pool.close()


@requires_postgres
async def test_pg_observe_rejects_a_negative_cost_cents() -> None:
    """`InvocationUsage` itself already refuses a negative/non-finite
    `cost_cents` at construction (its own `model_validator`), so this
    exercises the quota door's own belt-and-suspenders check the same way
    `test_invalid_bypassed_usage_validation_keeps_prior_hold` does for the
    SQLite door: `model_construct` bypasses Pydantic validation to stand in
    for usage that reached this far some other way (e.g. a deserialized
    record), and the quota accounting must still refuse it rather than
    silently computing a negative or infinite micro_usd charge."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-negcost-{suffix}")
    malformed_usage = InvocationUsage.model_construct(units="tokens", cost_cents=-1.0)
    try:
        await quota.ensure_schema()

        with pytest.raises(ValueError, match="cost must be finite and nonnegative"):
            await quota.observe(
                invocation.model_copy(
                    update={
                        "status": InvocationStatus.COMPLETED,
                        "finished_at": datetime.now(UTC),
                        "usage": malformed_usage,
                    }
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reconcile_rejects_revision_zero() -> None:
    """Revision zero is reserved for the canonical terminal record `observe`
    writes; a reconciliation adapter claiming it is a confused caller, not a
    legitimate correction."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        with pytest.raises(ValueError, match="revision zero is reserved"):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=f"pg-invocation-revzero-{suffix}",
                    provider_name="provider-pg",
                    evidence_id="ev-1",
                    revision=0,
                    outcome="completed",
                    tokens=10,
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_observe_tolerates_a_failed_invocation_that_was_never_reserved() -> None:
    """`observe(FAILED)` must tolerate a missing reservation: a Binding
    resolution failure or similar can fail an Invocation before `reserve`
    ever ran, and that is not a quota-accounting bug to raise about."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-neverreserved-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.observe(
            invocation.model_copy(
                update={"status": InvocationStatus.FAILED, "finished_at": datetime.now(UTC)}
            )
        )

        row = await pool.fetchrow(
            "SELECT 1 FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row is None
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reconcile_without_a_prior_reservation_raises_key_error() -> None:
    """Unlike `observe(FAILED)`, `reconcile` never tolerates a missing
    reservation -- trusted provider evidence settling nothing this process
    ever admitted is a coverage gap in the reconciliation adapter itself."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        with pytest.raises(KeyError, match="reconcile coverage"):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=f"pg-invocation-unreserved-{suffix}",
                    provider_name="provider-pg",
                    evidence_id="ev-1",
                    revision=1,
                    outcome="completed",
                    tokens=10,
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reconcile_rejects_evidence_from_a_different_provider() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix, provider_name="provider-pg")

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(
        binding,
        invocation_id=f"pg-invocation-providermismatch-{suffix}",
        provider_name="provider-pg",
    )
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)

        with pytest.raises(QuotaEvidenceConflict, match="does not match Invocation"):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=invocation.invocation_id,
                    provider_name="some-other-provider",
                    evidence_id="ev-1",
                    revision=1,
                    outcome="completed",
                    tokens=10,
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_reconcile_rejects_a_completed_outcome_against_a_denied_reservation() -> None:
    """A denied reservation means the provider was never dispatched; evidence
    later claiming it completed anyway is a conflict, not a correction."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-budget-deniedreconcile-{suffix}"
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=1000)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-deniedreconcile-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=10,
                period_start=0,
                period_end=1000,
                coverage_ref="test",
                opening_spend=0,
                provider_name="provider-pg",
            )
        )
        with pytest.raises(InvocationQuotaDenied):
            await quota.reserve(invocation, binding)

        with pytest.raises(QuotaEvidenceConflict, match="no provider dispatch"):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=invocation.invocation_id,
                    provider_name="provider-pg",
                    evidence_id="ev-1",
                    revision=1,
                    outcome="completed",
                    tokens=5,
                )
            )
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()


@requires_postgres
async def test_pg_apply_rejects_evidence_byte_mismatch_on_replay() -> None:
    """Different bytes under a revision or evidence id already used is a
    conflict, not an update -- evidence is append-only."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-evidence-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)
        await quota.reconcile(
            QuotaObservation(
                invocation_id=invocation.invocation_id,
                provider_name="provider-pg",
                evidence_id="ev-same",
                revision=1,
                outcome="completed",
                tokens=5,
            )
        )

        with pytest.raises(QuotaEvidenceConflict, match="evidence identity/revision was reused"):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=invocation.invocation_id,
                    provider_name="provider-pg",
                    evidence_id="ev-same",
                    revision=1,
                    outcome="completed",
                    tokens=999,  # different bytes under the same revision/evidence_id
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_apply_is_idempotent_for_identical_replayed_evidence() -> None:
    """The exact same evidence delivered twice (an at-least-once adapter
    retry) must settle once, not fold a second time."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-idempotent-{suffix}")
    observation = QuotaObservation(
        invocation_id=invocation.invocation_id,
        provider_name="provider-pg",
        evidence_id="ev-replay",
        revision=1,
        outcome="completed",
        tokens=5,
    )
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)
        await quota.reconcile(observation)
        await quota.reconcile(observation)  # byte-identical replay

        row = await pool.fetchrow(
            "SELECT state, revision FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["revision"] == 1
        evidence_count = await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_evidence WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert evidence_count == 1
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_apply_ignores_a_stale_out_of_order_revision() -> None:
    """An older revision arriving after a newer one has already settled must
    be silently ignored, not folded backwards over the newer state."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-stale-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)
        await quota.reconcile(
            QuotaObservation(
                invocation_id=invocation.invocation_id,
                provider_name="provider-pg",
                evidence_id="ev-new",
                revision=2,
                outcome="completed",
                tokens=5,
            )
        )
        # An older revision, under a different evidence id so it is not a
        # byte-identical replay of the one above.
        await quota.reconcile(
            QuotaObservation(
                invocation_id=invocation.invocation_id,
                provider_name="provider-pg",
                evidence_id="ev-old",
                revision=1,
                outcome="completed",
                tokens=999,
            )
        )

        row = await pool.fetchrow(
            "SELECT revision FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["revision"] == 2
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_apply_rejects_unknown_outcome_overwriting_a_settled_reservation() -> None:
    """An inconclusive outcome may not overwrite a settled one."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-unknownoverwrite-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)
        await quota.observe(
            invocation.model_copy(
                update={"status": InvocationStatus.COMPLETED, "finished_at": datetime.now(UTC)}
            )
        )  # settles the reservation (revision 0, no budget -> settled outright)

        with pytest.raises(
            QuotaEvidenceConflict, match="unknown cannot replace a confirmed provider outcome"
        ):
            await quota.reconcile(
                QuotaObservation(
                    invocation_id=invocation.invocation_id,
                    provider_name="provider-pg",
                    evidence_id="ev-unknown",
                    revision=1,
                    outcome="unknown",
                )
            )
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
async def test_pg_observe_with_unresolved_terminal_status_marks_the_reservation_unknown() -> None:
    """`observe` maps any non-CREATED/RUNNING, non-FAILED, non-COMPLETED
    status to the "unknown" provider outcome, and a reservation that was
    never previously confirmed settles into that same "unknown" state."""
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    binding = _binding(suffix)

    async def estimate(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    invocation = _invocation(binding, invocation_id=f"pg-invocation-unknownstate-{suffix}")
    try:
        await quota.ensure_schema()
        await quota.reserve(invocation, binding)  # "held" -- never previously confirmed

        await quota.observe(
            invocation.model_copy(
                update={"status": InvocationStatus.UNKNOWN, "finished_at": datetime.now(UTC)}
            )
        )

        row = await pool.fetchrow(
            "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1",
            invocation.invocation_id,
        )
        assert row["state"] == "unknown"
    finally:
        await _cleanup(pool, suffix, [])
        await pool.close()


@requires_postgres
@pytest.mark.parametrize(
    "disposition", [ReconciliationDisposition.APPLIED, ReconciliationDisposition.NOT_APPLIED]
)
async def test_pg_canonical_reconciliation_preserves_unknown_and_correction_order(disposition):
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(_pg_dsn(), min_size=1, max_size=2)
    suffix = uuid4().hex
    budget_id = f"pg-reconciliation-{suffix}"
    binding = _binding(suffix)
    original = _invocation(binding, invocation_id=f"pg-invocation-reconciliation-{suffix}")

    async def estimate(_invocation, _binding):
        return QuotaEstimate(principal_id="principal-pg", tokens=10)

    quota = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
    try:
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id=budget_id,
                unit="tokens",
                limit=100,
                period_start=0,
                period_end=1000,
                provider_name="provider-pg",
                workspace_id=binding.workspace_id,
                coverage_ref="fixture-fresh-period",
                opening_spend=0,
            )
        )
        await quota.reserve(original, binding)
        unknown = original.model_copy(
            update={"status": InvocationStatus.UNKNOWN, "finished_at": datetime.now(UTC)}
        )
        await quota.observe(unknown)
        correction = QuotaObservation(
            invocation_id=original.invocation_id,
            provider_name="provider-pg",
            evidence_id="provider-before",
            revision=7,
            outcome="completed",
            tokens=9,
        )
        await quota.reconcile(correction)
        store = InMemoryInvocationStore()
        await store.create(unknown)
        service = InvocationExecutionService(store=store, quota=quota)
        settled = await service.reconcile(
            original.invocation_id,
            disposition=disposition,
            source="operator",
            actor="operator",
            reason="verified provider outcome",
            evidence={"receipt": "verified"},
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            usage=InvocationUsage(input_units=7)
            if disposition is ReconciliationDisposition.APPLIED
            else None,
        )
        await quota.observe(settled)
        await quota.observe(unknown)
        rows = await pool.fetch(
            "SELECT revision,evidence_id FROM invocation_quota_evidence WHERE invocation_id=$1 ORDER BY revision",
            original.invocation_id,
        )
        assert [(row["revision"], row["evidence_id"]) for row in rows] == [
            (0, "canonical-terminal"),
            (7, "provider-before"),
            (8, "canonical-reconciliation"),
        ]
        balance = await quota.balance(budget_id)
        assert balance.held == 0
        assert balance.spent == (7 if disposition is ReconciliationDisposition.APPLIED else 0)
    finally:
        await _cleanup(pool, suffix, [budget_id])
        await pool.close()
