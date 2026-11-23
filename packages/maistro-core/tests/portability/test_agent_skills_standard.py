"""Agent Skills directory interchange, distinct from legacy tool SKILL.md (#2499)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from maistro.portability import (
    AgentSkillPackage,
    AgentSkillValidationError,
    export_agent_skill_directory,
    load_agent_skill_directory,
)
from maistro.skills.parser import parse_skill_file


def _skill(tmp_path, name="pdf-processing", content=None):
    root = tmp_path / name
    root.mkdir()
    text = content or (
        f"---\nname: {name}\ndescription: Extracts PDF content\n---\n"
        "Read a PDF carefully.\n"
    )
    (root / "SKILL.md").write_text(text, encoding="utf-8")
    return root


def test_minimal_upstream_skill_round_trips_with_identity_and_resources(tmp_path):
    root = _skill(tmp_path)
    (root / "references").mkdir()
    (root / "references" / "manual.txt").write_text("Reference only")
    (root / "scripts").mkdir()
    (root / "scripts" / "extract.py").write_text("print('this is never executed')")
    imported = load_agent_skill_directory(root)
    assert imported.name == "pdf-processing"
    assert imported.description == "Extracts PDF content"
    assert imported.instructions == "Read a PDF carefully.\n"
    assert imported.declared_allowed_tools == ""
    assert len(imported.files) == 3
    assert len(imported.content_sha256) == 64
    target = tmp_path / "destination"
    target.mkdir()
    exported = export_agent_skill_directory(imported, target)
    assert exported == target / "pdf-processing"
    assert load_agent_skill_directory(exported) == imported


def test_allowed_tools_metadata_is_not_a_runtime_grant(tmp_path):
    root = _skill(
        tmp_path,
        content=(
            "---\nname: pdf-processing\ndescription: Examines documents\n"
            "allowed-tools: Bash(*:*)\nmetadata:\n  author: example\n"
            "---\nReview a document.\n"
        ),
    )
    imported = load_agent_skill_directory(root)
    assert isinstance(imported, AgentSkillPackage)
    assert imported.declared_allowed_tools == "Bash(*:*)"
    assert imported.metadata == (("author", "example"),)
    assert not hasattr(imported, "tools_allowed")
    assert not hasattr(imported, "granted_permissions")
    assert not hasattr(imported, "endpoint")


@pytest.mark.parametrize(
    "name", ["-bad", "bad-", "bad--name", "Upper", "bad_name", "x" * 65],
)
def test_invalid_upstream_names_refused(tmp_path, name):
    with pytest.raises(AgentSkillValidationError):
        load_agent_skill_directory(_skill(tmp_path, name=name))


def test_parent_directory_must_match_upstream_skill_name(tmp_path):
    root = _skill(
        tmp_path,
        content="---\nname: other-skill\ndescription: Valid\n---\nWork.\n",
    )
    with pytest.raises(AgentSkillValidationError, match="mismatch"):
        load_agent_skill_directory(root)


@pytest.mark.parametrize(
    "content",
    [
        "---\nname: pdf-processing\ndescription: Valid\nparameters: {}\n---\nWork\n",
        "---\nname: pdf-processing\nname: other\ndescription: Valid\n---\nWork\n",
        "---\nname: pdf-processing\ndescription: ''\n---\nWork\n",
        "---\nname: pdf-processing\ndescription: Valid\nmetadata:\n  count: 8\n---\nWork\n",
        "---\nname: pdf-processing\ndescription: Valid\nallowed-tools: [Bash]\n---\nWork\n",
        "---\nname: pdf-processing\ndescription: Valid\nmetadata: {author: &a alpha}\nlicense: *a\n---\nWork\n",
        "name: pdf-processing\ndescription: Valid\n",
    ],
)
def test_invalid_metadata_refused(tmp_path, content):
    with pytest.raises(AgentSkillValidationError):
        load_agent_skill_directory(_skill(tmp_path, content=content))


def test_symlink_resource_and_root_are_refused(tmp_path):
    root = _skill(tmp_path)
    (root / "scripts").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(AgentSkillValidationError, match="symlinks"):
        load_agent_skill_directory(root)
    alias = tmp_path / "another"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(AgentSkillValidationError):
        load_agent_skill_directory(alias)


def test_oversize_input_refused_before_yaml_parse(tmp_path):
    root = _skill(tmp_path)
    with (root / "SKILL.md").open("ab") as f:
        f.write(b"x" * (256 * 1024))
    with pytest.raises(AgentSkillValidationError, match="size"):
        load_agent_skill_directory(root)


def test_export_does_not_overwrite_existing_skill(tmp_path):
    root = _skill(tmp_path)
    imported = load_agent_skill_directory(root)
    with pytest.raises(FileExistsError):
        export_agent_skill_directory(imported, tmp_path)


@pytest.mark.parametrize("bad_path", ["../secret", "/tmp/secret", "scripts/../../x", "scripts\\evil.py"])
def test_export_rejects_unsafe_resource_paths(tmp_path, bad_path):
    imported = load_agent_skill_directory(_skill(tmp_path))
    poisoned = replace(imported, files=(*imported.files, (bad_path, b"evil")))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(AgentSkillValidationError):
        export_agent_skill_directory(poisoned, dest)
    assert not (dest / imported.name).exists()


def test_legacy_host_specific_skill_parser_is_unchanged():
    legacy = (
        "---\nname: web_search\ndescription: Searches\n"
        "parameters:\n  type: object\n---\nRun search.\n"
    )
    parsed = parse_skill_file(legacy)
    assert parsed is not None
    assert parsed.name == "web_search"


def test_crlf_input_is_parsed_without_modifying_bundle_bytes(tmp_path):
    root = _skill(tmp_path)
    data = (root / "SKILL.md").read_bytes().replace(b"\n", b"\r\n")
    (root / "SKILL.md").write_bytes(data)
    imported = load_agent_skill_directory(root)
    assert imported.name == "pdf-processing"
    assert dict(imported.files)["SKILL.md"] == data


def test_standard_minimal_skill_with_closing_delimiter_at_eof(tmp_path):
    root = _skill(
        tmp_path,
        content="---\nname: pdf-processing\ndescription: A standard skill\n---",
    )
    imported = load_agent_skill_directory(root)
    assert imported.name == "pdf-processing"
    assert imported.instructions == ""


def test_empty_declared_compatibility_refused(tmp_path):
    root = _skill(
        tmp_path,
        content=(
            "---\nname: pdf-processing\ndescription: A standard skill\n"
            "compatibility: ''\n---\n"
        ),
    )
    with pytest.raises(AgentSkillValidationError):
        load_agent_skill_directory(root)


def test_forged_package_exceeding_export_file_count_is_rejected(tmp_path):
    imported = load_agent_skill_directory(_skill(tmp_path))
    forged = replace(imported, files=imported.files * 257)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(AgentSkillValidationError):
        export_agent_skill_directory(forged, destination)
    assert not (destination / imported.name).exists()
