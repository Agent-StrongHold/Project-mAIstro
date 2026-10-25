"""Tests for InMemoryLearningStore (ADR-015)."""

from __future__ import annotations

from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning, MemoryScope


def _lr(
    tool: str = "shell",
    keys: list[str] | None = None,
    org: str = "org-1",
    agent: str | None = "agent-1",
    status: str = "active",
    learning: str = "do X not Y",
) -> Learning:
    return Learning(
        tool_name=tool,
        trigger_keys=keys or ["foo", "bar"],
        learning=learning,
        org_id=org,
        agent_id=agent,
        scope=MemoryScope.AGENT,
        status=status,
    )


class TestStore:
    async def test_store_returns_id(self) -> None:
        store = InMemoryLearningStore()
        lr = _lr()
        id_ = await store.store(lr)
        assert id_ > 0

    async def test_store_dedup_same_org_same_tool_overlapping_keys(self) -> None:
        store = InMemoryLearningStore()
        lr1 = _lr(keys=["foo", "bar"])
        lr2 = _lr(keys=["foo", "bar"], learning="updated")
        await store.store(lr1)
        id2 = await store.store(lr2)
        all_lr = await store.list_all()
        assert len(all_lr) == 1
        assert all_lr[0].learning == "updated"
        assert all_lr[0].id == id2

    async def test_store_no_dedup_different_org(self) -> None:
        store = InMemoryLearningStore()
        lr1 = _lr(org="org-A", keys=["foo", "bar"])
        lr2 = _lr(org="org-B", keys=["foo", "bar"])
        await store.store(lr1)
        await store.store(lr2)
        all_lr = await store.list_all(org_id="__system__")
        assert len(all_lr) == 2

    async def test_store_eviction_at_cap(self) -> None:
        store = InMemoryLearningStore(max_learnings=3)
        for i in range(4):
            lr = _lr(keys=[f"key{i}"])
            lr.tool_name = f"tool{i}"
            await store.store(lr)
        all_lr = await store.list_all(org_id="__system__")
        assert len(all_lr) == 3


class TestFindRelevant:
    async def test_finds_by_trigger_key(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["python", "import"]))
        results = await store.find_relevant("fix the python import error", org_id="org-1")
        assert len(results) == 1

    async def test_no_match_returns_empty(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["docker", "build"]))
        results = await store.find_relevant("python import error", org_id="org-1")
        assert results == []

    async def test_org_isolation(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["python"], org="org-A"))
        await store.store(_lr(keys=["python"], org="org-B"))
        results = await store.find_relevant("python error", org_id="org-A")
        assert len(results) == 1
        assert results[0].org_id == "org-A"

    async def test_skips_inactive(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["python"], status="promoted"))
        # find_relevant only returns "active" status
        results = await store.find_relevant("python error", org_id="org-1")
        assert results == []


class TestMarkUsed:
    async def test_increments_hit_count(self) -> None:
        store = InMemoryLearningStore()
        id_ = await store.store(_lr(keys=["key"]))
        await store.mark_used([id_])
        all_lr = await store.list_all()
        assert all_lr[0].hit_count == 1

    async def test_mark_multiple(self) -> None:
        store = InMemoryLearningStore()
        id1 = await store.store(_lr(keys=["a"], tool="t1"))
        id2 = await store.store(_lr(keys=["b"], tool="t2"))
        await store.mark_used([id1, id2])
        all_lr = await store.list_all()
        assert all(lr.hit_count == 1 for lr in all_lr)


class TestPromotion:
    async def test_auto_promotion_at_threshold(self) -> None:
        store = InMemoryLearningStore()
        id_ = await store.store(_lr(keys=["key"]))
        for _ in range(5):
            await store.mark_used([id_])
        promoted = await store.check_auto_promotions(threshold=5, org_id="org-1")
        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    async def test_get_promoted_returns_only_promoted(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["active"]))
        id2 = await store.store(_lr(keys=["will-promote"], tool="t2"))
        for _ in range(5):
            await store.mark_used([id2])
        await store.check_auto_promotions(threshold=5, org_id="org-1")
        results = await store.get_promoted(org_id="org-1")
        assert len(results) == 1
        assert results[0].tool_name == "t2"
