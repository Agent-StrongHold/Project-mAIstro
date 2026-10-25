"""Coverage for maistro.persistence.sqlite_learnings.SqliteLearningStore against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning


@pytest.fixture
async def store() -> AsyncIterator[SqliteLearningStore]:
    conn = await aiosqlite.connect(":memory:")
    s = SqliteLearningStore(conn)
    await s.ensure_schema()
    yield s
    await conn.close()


def make_learning(**kwargs: object) -> Learning:
    defaults: dict[str, object] = {
        "category": "tooling",
        "trigger_keys": ["foo", "bar"],
        "learning": "use the right flag",
        "tool_name": "bash",
        "user_id": "u1",
    }
    defaults.update(kwargs)
    return Learning(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_store_inserts_new_learning_returns_id(store: SqliteLearningStore) -> None:
    lid = await store.store(make_learning())
    assert lid == 1


@pytest.mark.asyncio
async def test_store_dedups_on_50pct_trigger_key_overlap(store: SqliteLearningStore) -> None:
    first_id = await store.store(make_learning(trigger_keys=["foo", "bar"]))
    second_id = await store.store(make_learning(trigger_keys=["foo", "baz"]))
    assert second_id == first_id
    all_learnings = await store.list_all()
    assert all_learnings[0].hit_count == 1


@pytest.mark.asyncio
async def test_store_no_dedup_below_overlap_threshold(store: SqliteLearningStore) -> None:
    first_id = await store.store(make_learning(trigger_keys=["foo", "bar", "baz", "qux"]))
    second_id = await store.store(make_learning(trigger_keys=["foo", "zzz", "yyy", "xxx"]))
    assert second_id != first_id


@pytest.mark.asyncio
async def test_store_different_tool_name_no_dedup(store: SqliteLearningStore) -> None:
    first_id = await store.store(make_learning(tool_name="bash", trigger_keys=["foo"]))
    second_id = await store.store(make_learning(tool_name="git", trigger_keys=["foo"]))
    assert second_id != first_id


@pytest.mark.asyncio
async def test_find_relevant_scores_by_keyword_match(store: SqliteLearningStore) -> None:
    await store.store(make_learning(trigger_keys=["docker", "container"], learning="L1"))
    await store.store(make_learning(tool_name="other", trigger_keys=["unrelated"], learning="L2"))
    results = await store.find_relevant("please use docker container here")
    assert len(results) == 1
    assert results[0].learning == "L1"


@pytest.mark.asyncio
async def test_find_relevant_filters_by_agent_id(store: SqliteLearningStore) -> None:
    await store.store(make_learning(agent_id="a1", trigger_keys=["foo"]))
    await store.store(make_learning(tool_name="other", agent_id="a2", trigger_keys=["foo"]))
    results = await store.find_relevant("foo", agent_id="a1")
    assert len(results) == 1
    assert results[0].agent_id == "a1"


@pytest.mark.asyncio
async def test_find_relevant_respects_max_results(store: SqliteLearningStore) -> None:
    for i in range(5):
        await store.store(make_learning(tool_name=f"tool{i}", trigger_keys=["foo"]))
    results = await store.find_relevant("foo", max_results=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_mark_used_increments_hit_count(store: SqliteLearningStore) -> None:
    lid = await store.store(make_learning())
    await store.mark_used([lid])
    all_learnings = await store.list_all()
    assert all_learnings[0].hit_count == 1


@pytest.mark.asyncio
async def test_mark_used_empty_list_is_noop(store: SqliteLearningStore) -> None:
    await store.store(make_learning())
    await store.mark_used([])

    assert (await store.list_all())[0].hit_count == 0


@pytest.mark.asyncio
async def test_mark_outcome_success_increments_success_after_use(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    await store.mark_outcome([lid], success=True)
    all_learnings = await store.list_all()
    assert all_learnings[0].success_after_use == 1
    assert all_learnings[0].failure_after_use == 0


@pytest.mark.asyncio
async def test_mark_outcome_failure_increments_failure_after_use(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    await store.mark_outcome([lid], success=False)
    all_learnings = await store.list_all()
    assert all_learnings[0].failure_after_use == 1
    assert all_learnings[0].success_after_use == 0


@pytest.mark.asyncio
async def test_mark_outcome_empty_list_is_noop(store: SqliteLearningStore) -> None:
    await store.store(make_learning())
    await store.mark_outcome([], success=True)

    learning = (await store.list_all())[0]
    assert learning.success_after_use == 0
    assert learning.failure_after_use == 0


@pytest.mark.asyncio
async def test_check_auto_promotions_promotes_above_threshold(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    await store.mark_used([lid])
    await store.mark_used([lid])
    promoted = await store.check_auto_promotions(threshold=2)
    assert len(promoted) == 1
    assert promoted[0].status == "promoted"


@pytest.mark.asyncio
async def test_check_auto_promotions_none_above_threshold_returns_empty(
    store: SqliteLearningStore,
) -> None:
    await store.store(make_learning())
    promoted = await store.check_auto_promotions(threshold=5)
    assert promoted == []


@pytest.mark.asyncio
async def test_get_promoted_returns_only_promoted_status(store: SqliteLearningStore) -> None:
    lid = await store.store(make_learning())
    await store.store(make_learning(tool_name="other"))
    await store.mark_used([lid])
    await store.check_auto_promotions(threshold=1)
    promoted = await store.get_promoted()
    assert len(promoted) == 1


@pytest.mark.asyncio
async def test_get_promoted_filters_by_task_type(store: SqliteLearningStore) -> None:
    lid1 = await store.store(make_learning(category="chat"))
    lid2 = await store.store(make_learning(tool_name="other", category="code"))
    await store.check_auto_promotions(threshold=0)
    assert lid1 and lid2
    promoted = await store.get_promoted(task_type="chat")
    assert len(promoted) == 1
    assert promoted[0].category == "chat"


@pytest.mark.asyncio
async def test_list_all_orders_newest_first_and_respects_limit(
    store: SqliteLearningStore,
) -> None:
    for i in range(3):
        await store.store(make_learning(tool_name=f"tool{i}"))
    all_learnings = await store.list_all(limit=2)
    assert len(all_learnings) == 2
    assert all_learnings[0].tool_name == "tool2"
