"""Coverage for memory/learnings/promoter.py (auto-promotion + skill mutation path).

Gate-based promotion is covered separately in test_promoter_gate.py.
"""

from __future__ import annotations

from typing import Any

from maistro.memory.learnings.approval import LearningApprovalGate
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.mutations import InMemorySkillMutationStore
from maistro.memory.types import Learning


class _StubForge:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[tuple[str, Learning]] = []

    async def forge(self, request: str) -> Any:
        raise NotImplementedError

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        self.calls.append((skill_name, learning))
        return self._result


class _RaisingForge:
    async def forge(self, request: str) -> Any:
        raise NotImplementedError

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        raise RuntimeError("forge exploded")


async def test_check_and_promote_without_gate_auto_promotes() -> None:
    store = InMemoryLearningStore()
    learning = Learning(trigger_keys=["deploy"], learning="snapshot first", hit_count=10)
    await store.store(learning)

    promoter = LearningPromoter(store, threshold=5)
    promoted = await promoter.check_and_promote()

    assert [p.learning for p in promoted] == ["snapshot first"]


async def test_auto_promote_skips_skill_mutation_when_no_tool_name() -> None:
    store = InMemoryLearningStore()
    await store.store(Learning(trigger_keys=["x"], learning="no tool here", hit_count=10))
    forge = _StubForge({"status": "mutated"})

    promoter = LearningPromoter(store, threshold=5, skill_forge=forge)
    await promoter.check_and_promote()

    assert forge.calls == []


async def test_auto_promote_skips_skill_mutation_when_no_forge_configured() -> None:
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    )
    promoter = LearningPromoter(store, threshold=5)
    promoted = await promoter.check_and_promote()
    assert len(promoted) == 1


async def test_try_mutate_skill_records_mutation_on_success() -> None:
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    )
    forge = _StubForge({"status": "mutated", "old_hash": "aaa", "new_hash": "bbb"})
    mutation_store = InMemorySkillMutationStore()

    promoter = LearningPromoter(
        store, threshold=5, skill_forge=forge, mutation_store=mutation_store
    )
    await promoter.check_and_promote()

    assert len(forge.calls) == 1
    mutations = await mutation_store.list_mutations()
    assert len(mutations) == 1
    assert mutations[0].skill_name == "search"
    assert mutations[0].old_prompt_hash == "aaa"
    assert mutations[0].new_prompt_hash == "bbb"


async def test_try_mutate_skill_no_record_when_mutation_store_absent() -> None:
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    )
    forge = _StubForge({"status": "mutated", "old_hash": "aaa", "new_hash": "bbb"})

    promoter = LearningPromoter(store, threshold=5, skill_forge=forge)
    promoted = await promoter.check_and_promote()

    assert len(promoted) == 1
    assert len(forge.calls) == 1


async def test_try_mutate_skill_logs_warning_on_error_status() -> None:
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    )
    forge = _StubForge({"status": "error", "error": "boom"})

    promoter = LearningPromoter(store, threshold=5, skill_forge=forge)
    promoted = await promoter.check_and_promote()

    assert len(promoted) == 1
    assert len(forge.calls) == 1


async def test_try_mutate_skill_swallows_exception_from_forge() -> None:
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    )
    promoter = LearningPromoter(store, threshold=5, skill_forge=_RaisingForge())

    promoted = await promoter.check_and_promote()
    assert len(promoted) == 1


async def test_gate_approved_promotion_triggers_skill_mutation() -> None:
    store = InMemoryLearningStore()
    learning = Learning(trigger_keys=["x"], learning="has tool", tool_name="search", hit_count=10)
    lid = await store.store(learning)

    forge = _StubForge({"status": "mutated", "old_hash": "aaa", "new_hash": "bbb"})
    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, skill_forge=forge, approval_gate=gate)

    await promoter.check_and_promote()
    gate.approve(lid, reviewer="admin")
    promoted = await promoter.check_and_promote()

    assert [p.id for p in promoted] == [lid]
    assert len(forge.calls) == 1


async def test_try_mutate_skill_noop_when_no_forge_called_directly() -> None:
    store = InMemoryLearningStore()
    promoter = LearningPromoter(store, threshold=5)
    learning = Learning(trigger_keys=["x"], learning="x", tool_name="search")
    await promoter._try_mutate_skill(learning)
