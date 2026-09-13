"""PostgreSQL parity checks for canonical Invocation quota settlement."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.quota.invocation_quota import QuotaBudget, QuotaEstimate, QuotaObservation
from maistro.quota.pg_invocation_quota import PgInvocationQuota


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
