"""Tests for InMemoryOutcomeStore (ADR-017)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import Outcome


def _outcome(
    task_type: str = "coding",
    model: str = "gpt-4",
    success: bool = True,
    org: str = "org-1",
    age_days: int = 0,
) -> Outcome:
    created = datetime.now(UTC) - timedelta(days=age_days)
    return Outcome(
        request_id=f"req-{id(object())}",
        task_type=task_type,
        model_used=model,
        success=success,
        org_id=org,
        created_at=created,
    )


class TestRecord:
    async def test_returns_id(self) -> None:
        store = InMemoryOutcomeStore()
        id_ = await store.record(_outcome())
        assert id_ > 0

    async def test_ids_increment(self) -> None:
        store = InMemoryOutcomeStore()
        id1 = await store.record(_outcome())
        id2 = await store.record(_outcome())
        assert id2 == id1 + 1

    async def test_eviction_at_cap(self) -> None:
        store = InMemoryOutcomeStore(max_outcomes=3)
        for _ in range(4):
            await store.record(_outcome())
        rate = await store.get_task_completion_rate()
        assert rate["total"] == 3


class TestCompletionRate:
    async def test_basic_rate(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(success=True))
        await store.record(_outcome(success=True))
        await store.record(_outcome(success=False))
        rate = await store.get_task_completion_rate()
        assert rate["total"] == 3
        assert rate["succeeded"] == 2
        assert rate["failed"] == 1
        assert abs(rate["rate"] - 2 / 3) < 1e-9

    async def test_day_window_excludes_old(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(age_days=0))
        await store.record(_outcome(age_days=10))  # outside 7-day window
        rate = await store.get_task_completion_rate(days=7)
        assert rate["total"] == 1

    async def test_org_filter(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(org="org-A"))
        await store.record(_outcome(org="org-B"))
        rate = await store.get_task_completion_rate(org_id="org-A")
        assert rate["total"] == 1

    async def test_by_model_breakdown(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(model="gpt-4", success=True))
        await store.record(_outcome(model="claude-3", success=False))
        rate = await store.get_task_completion_rate()
        assert "gpt-4" in rate["by_model"]
        assert "claude-3" in rate["by_model"]
        assert rate["by_model"]["gpt-4"]["rate"] == pytest.approx(1.0)
