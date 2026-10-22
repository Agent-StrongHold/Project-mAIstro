"""Coverage for skills/forge.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro.skills.forge import SkillForge
from maistro.skills.import_pipeline import InMemoryPolicyAttachmentStore
from maistro.skills.registry import InMemorySkillRegistry
from maistro.types.memory import Learning
from maistro.types.skill import SkillDefinition

VALID_SKILL_CONTENT = """---
name: my_skill
description: Does a thing
parameters:
  type: object
  properties: {}
---
Body text here.
"""

DANGEROUS_SKILL_CONTENT = """---
name: bad_skill
description: Bad
parameters:
  type: object
  properties: {}
---
exec(user_input)
"""

UNPARSEABLE_CONTENT = "no frontmatter here"


class _StubLLMClient:
    def __init__(
        self, response: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response


def _llm_response(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    return tmp_path / "skills"


async def test_forge_success_creates_skill_file(skills_dir: Path) -> None:
    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    skill = await forge.forge("make me a skill")

    assert skill.name == "my_skill"
    assert skill.trust_tier == "t3"
    assert skill.source == "forge"
    filepath = skills_dir / "my_skill.md"
    assert filepath.exists()
    assert filepath.read_text(encoding="utf-8") == VALID_SKILL_CONTENT
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "auto"


async def test_forge_strips_markdown_code_fences(skills_dir: Path) -> None:
    fenced = f"```markdown\n{VALID_SKILL_CONTENT}```\n"
    llm = _StubLLMClient(response=_llm_response(fenced))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    skill = await forge.forge("make me a skill")
    assert skill.name == "my_skill"


async def test_forge_raises_on_empty_llm_response(skills_dir: Path) -> None:
    llm = _StubLLMClient(response=_llm_response(""))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    with pytest.raises(ValueError, match="empty response"):
        await forge.forge("make me a skill")


async def test_forge_raises_when_llm_call_fails(skills_dir: Path) -> None:
    llm = _StubLLMClient(error=RuntimeError("backend down"))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    with pytest.raises(ValueError, match="empty response"):
        await forge.forge("make me a skill")


async def test_forge_raises_on_security_scan_rejection(skills_dir: Path) -> None:
    llm = _StubLLMClient(response=_llm_response(DANGEROUS_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    with pytest.raises(ValueError, match="rejected by security scan"):
        await forge.forge("make me a dangerous skill")


async def test_forge_raises_on_parse_failure(skills_dir: Path) -> None:
    llm = _StubLLMClient(response=_llm_response(UNPARSEABLE_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    with pytest.raises(ValueError, match="failed to parse"):
        await forge.forge("make me a skill")


async def test_forge_raises_on_path_traversal_name(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import maistro.skills.forge as forge_mod
    from maistro.types.skill import SkillDefinition

    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)

    traversal_skill = SkillDefinition(name="../../etc/passwd", description="d")
    monkeypatch.setattr(forge_mod, "parse_skill_file", lambda content, source="": traversal_skill)
    with pytest.raises(ValueError, match="path traversal"):
        await forge.forge("make me a skill")


async def test_forge_raises_when_skill_already_exists(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text("existing", encoding="utf-8")
    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    with pytest.raises(ValueError, match="already exists"):
        await forge.forge("make me a skill")


async def test_mutate_blocked_for_t0_tier(skills_dir: Path) -> None:
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"), skill_tier="t0")
    assert result["status"] == "blocked"
    assert "t0" in result["reason"]


async def test_mutate_blocked_for_t1_tier(skills_dir: Path) -> None:
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"), skill_tier="t1")
    assert result["status"] == "blocked"


async def test_mutate_rejects_path_traversal_before_llm(skills_dir: Path) -> None:
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("../../outside", Learning(learning="be careful"))
    assert result["status"] == "blocked"
    assert llm.calls == []


async def test_mutate_skipped_when_skill_file_missing(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("ghost_skill", Learning(learning="be careful"))
    assert result["status"] == "skipped"
    assert "No SKILL.md" in result["reason"]


async def test_mutate_finds_skill_in_community_subdir(skills_dir: Path) -> None:
    community_dir = skills_dir / "community"
    community_dir.mkdir(parents=True)
    (community_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    mutated_content = VALID_SKILL_CONTENT.replace("Body text here.", "Body text here. Be careful.")
    llm = _StubLLMClient(response=_llm_response(mutated_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "mutated"


async def test_mutate_skipped_for_empty_learning_text(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning=""))
    assert result["status"] == "skipped"
    assert result["reason"] == "Empty learning text"


async def test_mutate_uses_str_of_learning_when_no_learning_attribute(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    mutated_content = VALID_SKILL_CONTENT.replace("Body text here.", "Body text here. Note this.")
    llm = _StubLLMClient(response=_llm_response(mutated_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", "a plain string learning")
    assert result["status"] == "mutated"
    assert llm.calls[0]["messages"][0]["content"].count("a plain string learning") == 1


async def test_mutate_error_on_dangerous_learning_text(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="exec(os.system('rm -rf /'))"))
    assert result["status"] == "error"
    assert "rejected by security scan" in result["error"]


async def test_mutate_error_on_high_instruction_density_learning(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    dense_text = "ignore skip bypass always never instead actually really you must you should"
    result = await forge.mutate("my_skill", Learning(learning=dense_text))
    assert result["status"] == "error"
    assert "instruction density" in result["error"]


async def test_mutate_error_on_empty_llm_response(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient(response=_llm_response(""))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "error"
    assert result["error"] == "LLM returned empty response"


async def test_mutate_error_on_dangerous_mutation_output(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient(
        response=_llm_response(DANGEROUS_SKILL_CONTENT.replace("bad_skill", "my_skill"))
    )
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "error"
    assert "Mutation rejected" in result["error"]


async def test_mutate_error_on_unparseable_mutation_output(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    llm = _StubLLMClient(response=_llm_response(UNPARSEABLE_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "error"
    assert result["error"] == "Mutated content failed to parse"


async def test_mutate_error_when_mutation_changes_skill_name(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    renamed_content = VALID_SKILL_CONTENT.replace("name: my_skill", "name: renamed_skill")
    llm = _StubLLMClient(response=_llm_response(renamed_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "error"
    assert "changed name" in result["error"]


async def test_mutate_success_writes_new_content_and_returns_hashes(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    filepath = skills_dir / "my_skill.md"
    filepath.write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    mutated_content = VALID_SKILL_CONTENT.replace(
        "Body text here.", "Body text here. Be extra careful."
    )
    fenced = f"```\n{mutated_content}```\n"
    llm = _StubLLMClient(response=_llm_response(fenced))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be extra careful"))
    assert result["status"] == "mutated"
    assert result["skill_name"] == "my_skill"
    assert len(result["old_hash"]) == 16
    assert len(result["new_hash"]) == 16
    assert result["old_hash"] != result["new_hash"]
    assert filepath.read_text(encoding="utf-8") == mutated_content.rstrip("\n")


async def test_call_llm_returns_none_on_missing_choices(skills_dir: Path) -> None:
    llm = _StubLLMClient(response={"choices": []})
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge._call_llm("prompt")
    assert result is None


async def test_call_llm_returns_none_on_exception(skills_dir: Path) -> None:
    llm = _StubLLMClient(error=RuntimeError("boom"))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge._call_llm("prompt")
    assert result is None


# ------------------------------------------------- the governed forge gate


async def test_forge_refuses_when_the_trust_policy_rejects_the_registration(
    skills_dir: Path,
) -> None:
    registry = InMemorySkillRegistry()
    # The host already holds this name at a tier a forged body may not
    # replace: the forge is refused instead of the forged content inheriting
    # an approval the host never gave it.
    registry.register(
        SkillDefinition(
            name="my_skill",
            description="Operator vetted",
            trust_tier="t0",
            source="host",
        )
    )
    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir, registry=registry)

    with pytest.raises(ValueError, match="Skill trust policy rejected registration"):
        await forge.forge("make me a skill")
    assert not (skills_dir / "my_skill.md").exists()


async def test_forge_records_the_host_policy_attachment(skills_dir: Path) -> None:
    policy_store = InMemoryPolicyAttachmentStore()
    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir, policy_store=policy_store)

    skill = await forge.forge("make me a skill")
    attachment = policy_store.get("my_skill")
    assert attachment is not None
    assert attachment.provenance == "forge"
    assert attachment.content_hash == skill.content_hash


async def test_forge_refuses_to_overwrite_a_symlinked_skill_file(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    # A symlink that points at a path inside the root but names no file yet:
    # the write path refuses it instead of following it.
    (skills_dir / "my_skill.md").symlink_to(skills_dir / "pending.md")
    llm = _StubLLMClient(response=_llm_response(VALID_SKILL_CONTENT))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)

    with pytest.raises(ValueError, match="Refusing to overwrite symlink"):
        await forge.forge("make me a skill")


async def test_mutate_registers_the_rewritten_body_at_the_forge_tier(skills_dir: Path) -> None:
    registry = InMemorySkillRegistry()
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    mutated_content = VALID_SKILL_CONTENT.replace("Body text here.", "Body text here. Be careful.")
    llm = _StubLLMClient(response=_llm_response(mutated_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir, registry=registry)

    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "mutated"
    stored = registry.get("my_skill")
    assert stored is not None
    # A rewritten body starts at the forge's tier, not at whatever the parser
    # defaults to: the mutation has to earn its trust again.
    assert stored.trust_tier == "t3"
    assert stored.provenance == "forge"


async def test_mutate_is_blocked_when_the_registry_refuses_the_rewritten_body(
    skills_dir: Path,
) -> None:
    registry = InMemorySkillRegistry()
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    # The host holds this skill at a tier the rewrite may not replace.
    registry.register(
        SkillDefinition(
            name="my_skill",
            description="Operator vetted",
            trust_tier="t0",
            source="host",
        )
    )
    mutated_content = VALID_SKILL_CONTENT.replace("Body text here.", "Body text here. Be careful.")
    llm = _StubLLMClient(response=_llm_response(mutated_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir, registry=registry)

    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "blocked"
    assert "trust policy" in result["reason"]
    # A refused mutation writes nothing: the file on disk is untouched.
    assert (skills_dir / "my_skill.md").read_text(encoding="utf-8") == VALID_SKILL_CONTENT


async def test_mutate_records_the_host_policy_attachment(skills_dir: Path) -> None:
    policy_store = InMemoryPolicyAttachmentStore()
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    mutated_content = VALID_SKILL_CONTENT.replace("Body text here.", "Body text here. Be careful.")
    llm = _StubLLMClient(response=_llm_response(mutated_content))
    forge = SkillForge(llm=llm, skills_dir=skills_dir, policy_store=policy_store)

    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "mutated"
    attachment = policy_store.get("my_skill")
    assert attachment is not None
    assert attachment.provenance == "forge"


async def test_mutate_refuses_a_skill_that_resolves_outside_the_skills_directory(
    skills_dir: Path, tmp_path: Path
) -> None:
    # A community directory that is a symlink resolves the skill file outside
    # the authorized root: the mutation is refused before the file is read.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    skills_dir.mkdir(parents=True)
    (skills_dir / "community").symlink_to(outside, target_is_directory=True)

    llm = _StubLLMClient()
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "blocked"
    assert "escapes skills directory" in result["reason"]
    assert llm.calls == []


async def test_mutate_reports_an_empty_body_after_the_fences_are_stripped(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True)
    (skills_dir / "my_skill.md").write_text(VALID_SKILL_CONTENT, encoding="utf-8")
    # Fenced output that is empty once the fences are stripped.
    llm = _StubLLMClient(response=_llm_response("```\n\n```"))
    forge = SkillForge(llm=llm, skills_dir=skills_dir)
    result = await forge.mutate("my_skill", Learning(learning="be careful"))
    assert result["status"] == "error"
    assert result["error"] == "LLM returned empty response"
