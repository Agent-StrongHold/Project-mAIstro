"""Coverage for skills/loader.py."""

from __future__ import annotations

from pathlib import Path

from maistro.skills.loader import FilesystemSkillLoader
from maistro.types.skill import SkillDefinition
from maistro.types.tool import ToolDefinition

VALID_SKILL_MD = """---
name: my_skill
description: Does a thing
parameters:
  type: object
  properties: {}
---
Body text here.
"""


def test_load_all_returns_empty_list_when_dir_does_not_exist(tmp_path: Path) -> None:
    loader = FilesystemSkillLoader(tmp_path / "missing")
    assert loader.load_all() == []


def test_load_all_skips_symlinks(tmp_path: Path) -> None:
    real_file = tmp_path / "real.md"
    real_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    symlink = tmp_path / "link.md"
    symlink.symlink_to(real_file)
    loader = FilesystemSkillLoader(tmp_path)
    skills = loader.load_all()
    assert len(skills) == 1
    assert skills[0].source == str(real_file)


def test_load_all_skips_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    bad_file = tmp_path / "bad.md"
    bad_file.write_text(VALID_SKILL_MD, encoding="utf-8")

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == bad_file:
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    loader = FilesystemSkillLoader(tmp_path)
    assert loader.load_all() == []


def test_load_all_skips_parse_failure(tmp_path: Path) -> None:
    invalid_file = tmp_path / "invalid.md"
    invalid_file.write_text("not a valid skill file", encoding="utf-8")
    loader = FilesystemSkillLoader(tmp_path)
    assert loader.load_all() == []


def test_load_all_loads_valid_skill(tmp_path: Path) -> None:
    skill_file = tmp_path / "my_skill.md"
    skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
    loader = FilesystemSkillLoader(tmp_path)
    skills = loader.load_all()
    assert len(skills) == 1
    assert skills[0].name == "my_skill"
    assert skills[0].source == str(skill_file)


def test_load_all_loads_community_skills(tmp_path: Path) -> None:
    community_dir = tmp_path / "community"
    community_dir.mkdir()
    community_file = community_dir / "extra_skill.md"
    community_file.write_text(VALID_SKILL_MD.replace("my_skill", "extra_skill"), encoding="utf-8")
    loader = FilesystemSkillLoader(tmp_path)
    skills = loader.load_all()
    assert len(skills) == 1
    assert skills[0].name == "extra_skill"


def test_load_all_silently_skips_unreadable_community_file(tmp_path: Path, monkeypatch) -> None:
    community_dir = tmp_path / "community"
    community_dir.mkdir()
    bad_file = community_dir / "bad.md"
    bad_file.write_text(VALID_SKILL_MD, encoding="utf-8")

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == bad_file:
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    loader = FilesystemSkillLoader(tmp_path)
    assert loader.load_all() == []


def test_load_all_silently_skips_invalid_community_skill(tmp_path: Path) -> None:
    community_dir = tmp_path / "community"
    community_dir.mkdir()
    invalid_file = community_dir / "invalid.md"
    invalid_file.write_text("not valid", encoding="utf-8")
    loader = FilesystemSkillLoader(tmp_path)
    assert loader.load_all() == []


def test_merge_into_tools_skips_skill_when_name_already_exists() -> None:
    loader = FilesystemSkillLoader(Path("/nonexistent"))
    existing = [ToolDefinition(name="my_skill", description="existing tool")]
    skill = SkillDefinition(name="my_skill", description="from skill")
    merged = loader.merge_into_tools([skill], existing)
    assert len(merged) == 1
    assert merged[0].description == "existing tool"


def test_merge_into_tools_adds_new_skill_as_tool() -> None:
    loader = FilesystemSkillLoader(Path("/nonexistent"))
    skill = SkillDefinition(
        name="new_skill",
        description="desc",
        parameters={"type": "object", "properties": {"x": {}}},
        groups=("admin",),
        endpoint="https://x",
        auth_key_env="KEY",
    )
    merged = loader.merge_into_tools([skill], [])
    assert len(merged) == 1
    tool = merged[0]
    assert tool == ToolDefinition(
        name="new_skill",
        description="desc",
        parameters={"type": "object", "properties": {"x": {}}},
        groups=("admin",),
        endpoint="https://x",
        auth_key_env="KEY",
    )


def test_merge_into_tools_returns_existing_unchanged_when_no_skills() -> None:
    loader = FilesystemSkillLoader(Path("/nonexistent"))
    existing = [ToolDefinition(name="t1")]
    merged = loader.merge_into_tools([], existing)
    assert merged == existing
    assert merged is not existing
