"""Coverage for InMemorySkillMutationStore."""

from __future__ import annotations

from maistro.memory.mutations import InMemorySkillMutationStore
from maistro.types.memory import SkillMutation


def make_mutation(**kwargs: object) -> SkillMutation:
    defaults: dict[str, object] = {
        "skill_name": "git-commit",
        "learning_id": 1,
        "old_prompt_hash": "abc",
        "new_prompt_hash": "def",
    }
    defaults.update(kwargs)
    return SkillMutation(**defaults)  # type: ignore[arg-type]


async def test_record_assigns_sequential_ids_starting_at_one() -> None:
    store = InMemorySkillMutationStore()
    first_id = await store.record(make_mutation())
    second_id = await store.record(make_mutation())
    assert first_id == 1
    assert second_id == 2


async def test_record_sets_id_on_the_mutation_instance() -> None:
    store = InMemorySkillMutationStore()
    mutation = make_mutation()
    returned_id = await store.record(mutation)
    assert mutation.id == returned_id


async def test_list_mutations_returns_empty_for_no_records() -> None:
    store = InMemorySkillMutationStore()
    assert await store.list_mutations() == []


async def test_list_mutations_returns_all_when_under_limit() -> None:
    store = InMemorySkillMutationStore()
    m1 = make_mutation(skill_name="a")
    m2 = make_mutation(skill_name="b")
    await store.record(m1)
    await store.record(m2)
    result = await store.list_mutations(limit=50)
    assert [m.skill_name for m in result] == ["a", "b"]


async def test_list_mutations_respects_limit_returning_most_recent() -> None:
    store = InMemorySkillMutationStore()
    for i in range(5):
        await store.record(make_mutation(skill_name=f"skill-{i}"))
    result = await store.list_mutations(limit=2)
    assert [m.skill_name for m in result] == ["skill-3", "skill-4"]
