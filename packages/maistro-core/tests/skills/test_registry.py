"""Coverage for skills/registry.py."""

from __future__ import annotations

from maistro.skills.registry import InMemorySkillRegistry
from maistro.types.skill import SkillDefinition


def _skill(
    name: str = "s1", trust_tier: str = "t2", groups: tuple[str, ...] = ()
) -> SkillDefinition:
    return SkillDefinition(name=name, description="d", trust_tier=trust_tier, groups=groups)


def test_register_adds_new_skill_and_version() -> None:
    registry = InMemorySkillRegistry()
    skill = _skill()
    registry.register(skill)
    assert registry.get("s1") is skill
    assert registry.get_versions("s1") == [skill]


def test_register_overwrites_existing_skill_at_same_tier() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(trust_tier="t2"))
    new_skill = _skill(trust_tier="t2")
    registry.register(new_skill)
    assert registry.get("s1") is new_skill
    assert len(registry.get_versions("s1")) == 2


def test_register_blocks_overwrite_of_t0_skill_by_lower_tier() -> None:
    registry = InMemorySkillRegistry()
    original = _skill(trust_tier="t0")
    registry.register(original)
    registry.register(_skill(trust_tier="t2"))
    assert registry.get("s1") is original
    assert len(registry.get_versions("s1")) == 1


def test_register_blocks_overwrite_of_t1_skill_by_lower_tier() -> None:
    registry = InMemorySkillRegistry()
    original = _skill(trust_tier="t1")
    registry.register(original)
    registry.register(_skill(trust_tier="t3"))
    assert registry.get("s1") is original


def test_register_allows_t0_skill_to_overwrite_t0_skill() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(trust_tier="t0"))
    new_skill = _skill(trust_tier="t0")
    registry.register(new_skill)
    assert registry.get("s1") is new_skill


def test_get_returns_none_for_unknown_skill() -> None:
    registry = InMemorySkillRegistry()
    assert registry.get("ghost") is None


def test_list_all_returns_all_registered_skills() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(name="a"))
    registry.register(_skill(name="b"))
    names = {s.name for s in registry.list_all()}
    assert names == {"a", "b"}


def test_list_by_group_filters_by_membership() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(name="a", groups=("admin",)))
    registry.register(_skill(name="b", groups=("user",)))
    result = registry.list_by_group("admin")
    assert [s.name for s in result] == ["a"]


def test_list_by_trust_tier_filters_by_tier() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(name="a", trust_tier="t0"))
    registry.register(_skill(name="b", trust_tier="t3"))
    result = registry.list_by_trust_tier("t3")
    assert [s.name for s in result] == ["b"]


def test_update_returns_false_when_skill_not_found() -> None:
    registry = InMemorySkillRegistry()
    assert registry.update(_skill()) is False


def test_update_replaces_existing_skill_and_returns_true() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill())
    updated = _skill(trust_tier="t3")
    assert registry.update(updated) is True
    assert registry.get("s1") is updated


def test_delete_returns_false_when_not_found() -> None:
    registry = InMemorySkillRegistry()
    assert registry.delete("ghost") is False


def test_delete_removes_skill_and_returns_true() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill())
    assert registry.delete("s1") is True
    assert registry.get("s1") is None


def test_get_versions_returns_empty_list_when_none() -> None:
    registry = InMemorySkillRegistry()
    assert registry.get_versions("ghost") == []


def test_get_version_returns_none_for_out_of_range_index() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill())
    assert registry.get_version("s1", 5) is None
    assert registry.get_version("s1", -1) is None


def test_get_version_returns_skill_at_index() -> None:
    registry = InMemorySkillRegistry()
    v0 = _skill(trust_tier="t2")
    registry.register(v0)
    v1 = _skill(trust_tier="t2")
    registry.register(v1)
    assert registry.get_version("s1", 0) is v0
    assert registry.get_version("s1", 1) is v1


def test_rollback_returns_false_when_no_versions() -> None:
    registry = InMemorySkillRegistry()
    assert registry.rollback("ghost", 0) is False


def test_rollback_returns_false_for_out_of_range_index() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill())
    assert registry.rollback("s1", 5) is False
    assert registry.rollback("s1", -1) is False


def test_rollback_restores_previous_version_and_appends_history() -> None:
    registry = InMemorySkillRegistry()
    v0 = _skill(trust_tier="t2")
    registry.register(v0)
    v1 = _skill(trust_tier="t2")
    registry.register(v1)
    assert registry.rollback("s1", 0) is True
    assert registry.get("s1") is v0
    assert registry.get_versions("s1") == [v0, v1, v0]


def test_len_returns_skill_count() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill(name="a"))
    registry.register(_skill(name="b"))
    assert len(registry) == 2


def test_contains_checks_membership() -> None:
    registry = InMemorySkillRegistry()
    registry.register(_skill())
    assert "s1" in registry
    assert "ghost" not in registry
