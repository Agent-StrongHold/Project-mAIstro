"""Real quota rows interoperate across standard and production JSON codecs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
import pytest_asyncio

from maistro.capabilities.invocation import InvocationStatus, InvocationUsage
from maistro.quota.invocation_quota import QuotaEstimate, QuotaEvidenceConflict
from maistro.quota.pg_invocation_quota import PgInvocationQuota

from ..persistence.pg_capability_fixture import isolated_capability_pools
from .test_invocation_quota_boundary import binding, budget, invocation, terminal

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]


@pytest_asyncio.fixture(params=[False, True], ids=["standard-writer", "production-writer"])
async def stores(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[PgInvocationQuota, PgInvocationQuota, Any]]:
    async def estimate(_invocation: Any, _binding: Any) -> QuotaEstimate:
        return QuotaEstimate(principal_id="principal-a", tokens=60, micro_usd=50_000)

    async with isolated_capability_pools(
        production_codecs=request.param, peer_production_codecs=not request.param
    ) as (pool, peer):
        first = PgInvocationQuota(pool, estimate=estimate, clock=lambda: 100)
        second = PgInvocationQuota(peer, estimate=estimate, clock=lambda: 100)
        await first.ensure_schema()
        yield first, second, pool


async def test_budget_identity_survives_a_different_pool_codec(
    stores: tuple[PgInvocationQuota, PgInvocationQuota, Any],
) -> None:
    first, second, pool = stores
    original = budget()
    await first.register_budget(original)
    await second.register_budget(original)
    with pytest.raises(QuotaEvidenceConflict, match="immutable"):
        await second.register_budget(replace(original, limit=original.limit + 1))
    await first.register_budget(original)
    assert (
        await pool.fetchval(
            "SELECT jsonb_typeof(definition) FROM invocation_quota_budgets WHERE budget_id=$1",
            original.budget_id,
        )
        == "object"
    )


async def test_reservation_and_evidence_replay_across_pool_codecs_charge_once(
    stores: tuple[PgInvocationQuota, PgInvocationQuota, Any],
) -> None:
    first, second, pool = stores
    await first.register_budget(budget())
    await first.register_budget(budget("money", unit="micro_usd", limit=50_000))
    await first.register_budget(budget("requests", unit="requests", limit=1))
    inv = invocation()
    await asyncio.gather(first.reserve(inv, binding()), second.reserve(inv, binding()))
    assert (
        await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_allocations WHERE invocation_id=$1",
            inv.invocation_id,
        )
        == 3
    )
    complete = terminal(
        inv,
        InvocationStatus.COMPLETED,
        InvocationUsage(input_units=10, output_units=20, cost_cents=0.12345),
    )
    await first.observe(complete)
    await second.observe(complete)
    rows = await pool.fetch(
        "SELECT budget_id, held, spent FROM invocation_quota_allocations WHERE invocation_id=$1",
        inv.invocation_id,
    )
    assert {row["budget_id"]: (row["held"], row["spent"]) for row in rows} == {
        "tokens": (0, 30),
        "money": (0, 1235),
        "requests": (0, 1),
    }
    assert (
        await pool.fetchval(
            "SELECT COUNT(*) FROM invocation_quota_evidence WHERE invocation_id=$1",
            inv.invocation_id,
        )
        == 1
    )
    assert (
        await pool.fetchval(
            "SELECT jsonb_typeof(identity) FROM invocation_quota_reservations WHERE invocation_id=$1",
            inv.invocation_id,
        )
        == "object"
    )
    assert (
        await pool.fetchval(
            "SELECT jsonb_typeof(payload) FROM invocation_quota_evidence WHERE invocation_id=$1",
            inv.invocation_id,
        )
        == "object"
    )
    with pytest.raises(QuotaEvidenceConflict, match="identity"):
        await second.reserve(inv.model_copy(update={"effect_key": "another-effect"}), binding())
