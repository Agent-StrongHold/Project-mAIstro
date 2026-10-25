"""Coverage for skills/catalog.py."""

from __future__ import annotations

import time
from pathlib import Path

from maistro.skills.catalog import SkillCatalog, SkillCatalogEntry, _is_visible
from maistro.types.skill import SkillDefinition

VALID_SKILL_MD = """---
name: my_skill
description: Does a thing
parameters:
  type: object
  properties: {}
---
Body text here.
"""


def _make_entry(
    name: str = "skill1", scope: str = "builtin", tenant_id: str = "", user_id: str = ""
) -> SkillCatalogEntry:
    return SkillCatalogEntry(
        definition=SkillDefinition(name=name, description="d"),
        scope=scope,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def test_is_visible_builtin_always_visible() -> None:
    entry = _make_entry(scope="builtin")
    assert _is_visible(entry, tenant_id="", user_id="") is True


def test_is_visible_tenant_visible_for_matching_tenant() -> None:
    entry = _make_entry(scope="tenant", tenant_id="t1")
    assert _is_visible(entry, tenant_id="t1", user_id="") is True


def test_is_visible_tenant_not_visible_for_different_tenant() -> None:
    entry = _make_entry(scope="tenant", tenant_id="t1")
    assert _is_visible(entry, tenant_id="t2", user_id="") is False


def test_is_visible_tenant_not_visible_when_no_tenant_id_given() -> None:
    entry = _make_entry(scope="tenant", tenant_id="t1")
    assert _is_visible(entry, tenant_id="", user_id="") is False


def test_is_visible_user_visible_for_matching_user() -> None:
    entry = _make_entry(scope="user", user_id="u1")
    assert _is_visible(entry, tenant_id="", user_id="u1") is True


def test_is_visible_user_not_visible_for_different_user() -> None:
    entry = _make_entry(scope="user", user_id="u1")
    assert _is_visible(entry, tenant_id="", user_id="u2") is False


def test_register_and_resolve_returns_entry() -> None:
    catalog = SkillCatalog()
    entry = _make_entry(name="skill1")
    catalog.register(entry)
    assert catalog.resolve("skill1") is entry


def test_resolve_returns_none_when_no_match() -> None:
    catalog = SkillCatalog()
    assert catalog.resolve("ghost") is None


def test_resolve_returns_none_when_entry_not_visible() -> None:
    catalog = SkillCatalog()
    catalog.register(_make_entry(name="skill1", scope="tenant", tenant_id="t1"))
    assert catalog.resolve("skill1", tenant_id="t2") is None


def test_resolve_cascade_prefers_user_over_tenant_over_builtin() -> None:
    catalog = SkillCatalog()
    builtin = _make_entry(name="skill1", scope="builtin")
    tenant = _make_entry(name="skill1", scope="tenant", tenant_id="t1")
    user = _make_entry(name="skill1", scope="user", user_id="u1")
    catalog.register(builtin)
    catalog.register(tenant)
    catalog.register(user)
    resolved = catalog.resolve("skill1", tenant_id="t1", user_id="u1")
    assert resolved is user


def test_resolve_cascade_falls_back_to_tenant_when_user_not_visible() -> None:
    catalog = SkillCatalog()
    tenant = _make_entry(name="skill1", scope="tenant", tenant_id="t1")
    user = _make_entry(name="skill1", scope="user", user_id="u1")
    catalog.register(tenant)
    catalog.register(user)
    resolved = catalog.resolve("skill1", tenant_id="t1", user_id="other-user")
    assert resolved is tenant


def test_list_skills_deduplicates_by_name_preferring_higher_scope() -> None:
    catalog = SkillCatalog()
    builtin = _make_entry(name="skill1", scope="builtin")
    user = _make_entry(name="skill1", scope="user", user_id="u1")
    catalog.register(builtin)
    catalog.register(user)
    skills = catalog.list_skills(user_id="u1")
    assert len(skills) == 1
    assert skills[0] is user


def test_list_skills_excludes_not_visible_entries() -> None:
    catalog = SkillCatalog()
    catalog.register(_make_entry(name="skill1", scope="tenant", tenant_id="t1"))
    skills = catalog.list_skills(tenant_id="other")
    assert skills == []


def test_list_skills_returns_sorted_by_name() -> None:
    catalog = SkillCatalog()
    catalog.register(_make_entry(name="zeta"))
    catalog.register(_make_entry(name="alpha"))
    skills = catalog.list_skills()
    assert [e.definition.name for e in skills] == ["alpha", "zeta"]


def test_load_directory_returns_zero_for_nonexistent_dir(tmp_path: Path) -> None:
    catalog = SkillCatalog()
    assert catalog.load_directory(tmp_path / "missing") == 0


def test_load_directory_loads_valid_skill_files(tmp_path: Path) -> None:
    (tmp_path / "skill1.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    count = catalog.load_directory(tmp_path, scope="tenant", tenant_id="t1")
    assert count == 1
    entry = catalog.resolve("my_skill", tenant_id="t1")
    assert entry is not None
    assert entry.scope == "tenant"
    assert entry.tenant_id == "t1"


def test_load_directory_skips_invalid_skill_file(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("not a valid skill", encoding="utf-8")
    catalog = SkillCatalog()
    assert catalog.load_directory(tmp_path) == 0


def test_load_directory_skips_file_raising_exception(tmp_path: Path, monkeypatch) -> None:
    bad_file = tmp_path / "bad.md"
    bad_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == bad_file:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    catalog = SkillCatalog()
    assert catalog.load_directory(tmp_path) == 0


def test_start_watching_is_idempotent_when_already_running(tmp_path: Path) -> None:
    catalog = SkillCatalog()
    catalog.start_watching(tmp_path, poll_interval=0.05)
    first_thread = catalog._watcher_thread
    catalog.start_watching(tmp_path, poll_interval=0.05)
    assert catalog._watcher_thread is first_thread
    catalog.stop_watching()


def test_stop_watching_without_start_is_a_noop() -> None:
    catalog = SkillCatalog()
    catalog.stop_watching()
    assert catalog._watcher_thread is None


def test_check_for_changes_returns_early_for_nonexistent_dir(tmp_path: Path) -> None:
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path / "missing")


def test_check_for_changes_loads_new_file(tmp_path: Path) -> None:
    skill_file = tmp_path / "skill1.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path)
    entry = catalog.resolve("my_skill")
    assert entry is not None
    assert entry.scope == "builtin"


def test_check_for_changes_skips_unmodified_file(tmp_path: Path) -> None:
    skill_file = tmp_path / "skill1.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path)
    first_entries = list(catalog._entries)
    catalog._check_for_changes(tmp_path)
    assert catalog._entries == first_entries


def test_check_for_changes_reloads_modified_file_replacing_old_entry(tmp_path: Path) -> None:
    skill_file = tmp_path / "skill1.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path)
    assert len(catalog._entries) == 1

    time.sleep(0.01)
    updated = VALID_SKILL_MD.replace("Does a thing", "Does a different thing")
    new_mtime = time.time() + 10
    skill_file.write_text(updated, encoding="utf-8")
    import os

    os.utime(skill_file, (new_mtime, new_mtime))

    catalog._check_for_changes(tmp_path)
    assert len(catalog._entries) == 1
    entry = catalog.resolve("my_skill")
    assert entry is not None
    assert entry.definition.description == "Does a different thing"


def test_check_for_changes_skips_when_reparsed_file_invalid(tmp_path: Path) -> None:
    skill_file = tmp_path / "skill1.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path)

    new_mtime = time.time() + 10
    skill_file.write_text("now invalid", encoding="utf-8")
    import os

    os.utime(skill_file, (new_mtime, new_mtime))

    catalog._check_for_changes(tmp_path)
    assert len(catalog._entries) == 1
    assert catalog._entries[0].definition.description == "Does a thing"


def test_check_for_changes_swallows_exception_on_reload(tmp_path: Path, monkeypatch) -> None:
    skill_file = tmp_path / "skill1.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog()
    catalog._check_for_changes(tmp_path)

    new_mtime = time.time() + 10
    import os

    os.utime(skill_file, (new_mtime, new_mtime))

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == skill_file:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    catalog._check_for_changes(tmp_path)
    assert len(catalog._entries) == 1


def test_watch_loop_swallows_exception_and_continues(tmp_path: Path, monkeypatch) -> None:
    catalog = SkillCatalog()
    calls = []

    def fake_check(directory: Path) -> None:
        calls.append(directory)
        raise RuntimeError("boom")

    monkeypatch.setattr(catalog, "_check_for_changes", fake_check)
    catalog.start_watching(tmp_path, poll_interval=0.01)
    time.sleep(0.05)
    catalog.stop_watching()
    assert len(calls) >= 1
