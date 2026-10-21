from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from maistro.agents.importers.pi import PiAgentImporter
from maistro.capabilities.discovery import discover_into
from maistro.capabilities.registry import CapabilityRegistry, ProviderReplacementDecision
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.security.trust import _UNKNOWN_TIER_RANK, trust_rank
from maistro.skills.catalog import SkillCatalog
from maistro.skills.forge import SkillForge
from maistro.types.memory import Learning

VALID_SKILL = """---
name: safe_skill
description: A safe skill
parameters:
  type: object
  properties: {}
---
Use factual instructions only.
"""


@pytest.mark.asyncio
async def test_mutation_rejects_traversal_before_reading_outside_root(tmp_path: Path) -> None:
    class _LLM:
        async def complete(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("traversal must be rejected before the LLM call")

    result = await SkillForge(_LLM(), tmp_path).mutate(
        "../../etc/passwd", Learning(learning="irrelevant")
    )
    assert result["status"] == "blocked"


def test_catalog_register_rejects_malicious_in_memory_entries() -> None:
    from maistro.skills.catalog import SkillCatalogEntry
    from maistro.types.skill import SkillDefinition

    entry = SkillCatalogEntry(
        definition=SkillDefinition(name="unsafe_skill", description="d", system_prompt="exec(x)")
    )
    catalog = SkillCatalog()
    assert catalog.register(entry) is False
    assert catalog.resolve("unsafe_skill") is None


def test_catalog_register_scan_covers_frontmatter_shaped_prompt_prefix() -> None:
    # A direct entry's system_prompt is the raw prompt body. If the scan
    # stripped a frontmatter-shaped prefix, the prefix's payload would be
    # registered as a resolvable skill while never being pattern-scanned.
    from maistro.skills.catalog import SkillCatalogEntry
    from maistro.types.skill import SkillDefinition

    entry = SkillCatalogEntry(
        definition=SkillDefinition(
            name="frontmatter_skill",
            description="d",
            system_prompt="---\nexec(x)\n---\nsafe instructions",
        )
    )
    catalog = SkillCatalog()
    assert catalog.register(entry) is False
    assert catalog.resolve("frontmatter_skill") is None


def test_catalog_security_scans_initial_and_hot_reload_content(tmp_path: Path) -> None:
    path = tmp_path / "safe.md"
    path.write_text(VALID_SKILL, encoding="utf-8")
    catalog = SkillCatalog()
    assert catalog.load_directory(tmp_path) == 1

    malicious = VALID_SKILL.replace("Use factual instructions only.", "exec(payload)")
    path.write_text(malicious, encoding="utf-8")
    future = time.time() + 10
    os.utime(path, (future, future))
    catalog._check_for_changes(tmp_path)

    entry = catalog.resolve("safe_skill")
    assert entry is not None
    assert entry.definition.system_prompt == "Use factual instructions only."


def test_capability_rediscovery_preserves_existing_provider_and_state() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    original = FakeProvider("provider", "tool", tier="t0")
    rediscovered = FakeProvider("provider", "tool", tier="t3")
    assert registry.register(original) is True
    registry.activate("tool", "provider")
    registry.set_enabled("tool", False)

    assert registry.register(rediscovered) is False
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    assert registry.provider("tool", "provider") is original
    assert registry.active_name("tool") == "provider"
    assert registry.is_enabled("tool") is False


def test_capability_replacement_requires_explicit_governance() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    original = FakeProvider("provider", "tool", tier="t0")
    replacement = FakeProvider("provider", "tool", tier="t3")
    registry.register(original)

    with pytest.raises(TypeError):
        registry.replace(replacement)  # type: ignore[call-arg]
    registry.replace(
        replacement,
        decision=ProviderReplacementDecision(approved_by="operator", reason="scheduled rotation"),
    )
    assert registry.provider("tool", "provider") is replacement


@pytest.mark.asyncio
async def test_unknown_provider_tier_is_fail_closed_in_auto_selection() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    unknown = FakeProvider("attacker", "tool", tier="")
    known = FakeProvider("trusted", "tool", tier="t2")
    registry.register(unknown)
    registry.register(known)
    assert await registry.resolve("tool") is known
    assert trust_rank("") > trust_rank("t4")
    assert trust_rank("t-1") > trust_rank("t0")


@pytest.mark.asyncio
async def test_baseline_fallback_validates_tier_before_returning() -> None:
    # A declared baseline is provider-controlled metadata too. When the live
    # resolution refuses an unknown-tier provider, the fallback path must not
    # hand back the same malformed metadata under another name.
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.BASELINE, baseline_provider="baseline"))
    registry.register(FakeProvider("attacker", "tool", tier=""))
    registry.register(FakeProvider("baseline", "tool", tier="  "))

    # Unknown-tier chosen -> _baseline() must refuse the unknown-tier baseline.
    assert await registry.resolve("tool") is None
    # The disabled-slot path reaches the same baseline: same refusal.
    registry.set_enabled("tool", False)
    assert await registry.resolve("tool") is None


def test_boot_validation_requires_an_admissible_hard_required_provider() -> None:
    # A HARD_REQUIRED slot whose every provider declares an unknown tier can
    # never resolve; boot must refuse it, not complete and fail later.
    registry = CapabilityRegistry()
    registry.define(SlotSpec("llm", FallbackPolicy.HARD_REQUIRED))
    registry.register(FakeProvider("attacker", "llm", tier=""))
    with pytest.raises(RuntimeError, match="known trust tier"):
        registry.validate_boot()

    registry.register(FakeProvider("real", "llm", tier="t1"))
    registry.validate_boot()  # one admissible provider is enough


def test_pi_import_clamps_privileged_foreign_trust_claim() -> None:
    agent = PiAgentImporter().to_agent_config(
        {"kind": "pi.agent", "name": "foreign", "trust_tier": "t0"}
    )
    assert agent.trust_tier == "t3"


def test_pi_import_rejects_malicious_instructions() -> None:
    with pytest.raises(ValueError, match="security scan"):
        PiAgentImporter().to_agent_config(
            {"kind": "pi.agent", "name": "foreign", "instructions": "exec(x)"}
        )


def test_pi_import_scan_covers_frontmatter_shaped_instruction_prefix() -> None:
    # Instructions are a raw prompt body, not a frontmatter document. A
    # frontmatter-shaped prefix must be scanned as content, not stripped as
    # metadata: the payload below is retained verbatim in model_constraints,
    # so scanning only the part after the pseudo-frontmatter would admit it.
    instructions = "---\nexec(payload)\n---\nbenign instructions"
    with pytest.raises(ValueError, match="security scan"):
        PiAgentImporter().to_agent_config(
            {"kind": "pi.agent", "name": "foreign", "instructions": instructions}
        )


def test_replacement_decision_rejects_blank_actor_and_reason() -> None:
    # A governed replacement must name who approved it and why; whitespace-only
    # values are the same refusal, not a formality to pass through.
    with pytest.raises(ValueError, match="approved_by"):
        ProviderReplacementDecision(approved_by="   ", reason="rotation")
    with pytest.raises(ValueError, match="reason"):
        ProviderReplacementDecision(approved_by="operator", reason="  ")


def test_define_rejects_conflicting_redefinition_but_preserves_state() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    original = FakeProvider("provider", "tool", tier="t0")
    registry.register(original)
    registry.activate("tool", "provider")

    with pytest.raises(ValueError, match="already defined differently"):
        registry.define(SlotSpec("tool", FallbackPolicy.HARD_REQUIRED))
    assert registry.provider("tool", "provider") is original
    assert registry.active_name("tool") == "provider"


def test_replace_unknown_provider_is_rejected() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    decision = ProviderReplacementDecision(approved_by="operator", reason="rotation")
    with pytest.raises(KeyError, match="not installed"):
        registry.replace(FakeProvider("ghost", "tool"), decision=decision)


def test_non_string_tier_ranks_below_every_known_tier() -> None:
    # Provider metadata is not guaranteed to be a string at all; a non-string
    # tier must land in the unknown bucket, never ahead of a known tier.
    assert trust_rank(None) == _UNKNOWN_TIER_RANK
    assert trust_rank(7) == _UNKNOWN_TIER_RANK
    assert trust_rank(None) > trust_rank("t4")


def test_discovery_counts_only_newly_admitted_providers() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec("tool", FallbackPolicy.SAFE_NOOP))
    installed = FakeProvider("provider", "tool", tier="t2")
    assert registry.register(installed) is True

    class _RediscoveredEP:
        name = "rediscovered"

        def load(self) -> object:
            # A later discovery run shipping a different build of the same
            # logical provider must not silently replace the installed one.
            return lambda: FakeProvider("provider", "tool", tier="t0")

    class _FreshEP:
        name = "fresh"

        def load(self) -> object:
            return lambda: FakeProvider("fresh", "tool", tier="t2")

    assert discover_into(registry, entry_points=[_RediscoveredEP(), _FreshEP()]) == 1
    assert registry.provider("tool", "provider") is installed
    assert registry.provider("tool", "fresh") is not None


def test_load_directory_skips_symlinked_and_unscanned_skill_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text(VALID_SKILL.replace("safe_skill", "secret_skill"), encoding="utf-8")

    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "safe.md").write_text(VALID_SKILL, encoding="utf-8")
    (skills / "linked.md").symlink_to(secret)
    (skills / "evil.md").write_text(
        VALID_SKILL.replace("safe_skill", "evil_skill").replace(
            "Use factual instructions only.", "exec(payload)"
        ),
        encoding="utf-8",
    )

    catalog = SkillCatalog()
    assert catalog.load_directory(skills) == 1
    assert catalog.resolve("safe_skill") is not None
    # The symlink must not become a usable entry, under either name.
    assert catalog.resolve("linked_skill") is None
    assert catalog.resolve("secret_skill") is None
    assert catalog.resolve("evil_skill") is None


def test_hot_reload_skips_symlinked_skill_path(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(VALID_SKILL, encoding="utf-8")
    skill_path = skills / "safe.md"
    skill_path.write_text(VALID_SKILL, encoding="utf-8")

    catalog = SkillCatalog()
    assert catalog.load_directory(skills) == 1

    # Swap the loaded file for a symlink whose target carries new content, and
    # bump the mtime so the watcher sees a change.
    skill_path.unlink()
    skill_path.symlink_to(outside)
    outside.write_text(
        VALID_SKILL.replace("Use factual instructions only.", "Updated instructions."),
        encoding="utf-8",
    )
    future = time.time() + 10
    os.utime(skill_path, (future, future))
    catalog._check_for_changes(skills)

    entry = catalog.resolve("safe_skill")
    assert entry is not None
    assert entry.definition.system_prompt == "Use factual instructions only."


@pytest.mark.asyncio
async def test_mutation_rejects_symlinked_skill_file(tmp_path: Path) -> None:
    class _LLM:
        async def complete(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("symlinked skill must be rejected before the LLM call")

    outside = tmp_path / "outside.md"
    outside.write_text(VALID_SKILL.replace("safe_skill", "linked_skill"), encoding="utf-8")
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "linked_skill.md").symlink_to(outside)

    result = await SkillForge(_LLM(), skills).mutate(
        "linked_skill", Learning(learning="irrelevant")
    )
    assert result["status"] == "blocked"
    assert "symlink" in result["reason"]


@pytest.mark.asyncio
async def test_mutation_rejects_mutation_target_that_is_not_a_file(tmp_path: Path) -> None:
    class _LLM:
        async def complete(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("non-file target must be rejected before the LLM call")

    skills = tmp_path / "skills"
    (skills / "directory_skill.md").mkdir(parents=True)

    result = await SkillForge(_LLM(), skills).mutate(
        "directory_skill", Learning(learning="irrelevant")
    )
    assert result["status"] == "blocked"
    assert "authorized root" in result["reason"]


@pytest.mark.asyncio
async def test_mutation_blocks_skill_whose_existing_content_fails_scan(tmp_path: Path) -> None:
    class _LLM:
        async def complete(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("a failing existing scan must stop the mutation")

    skills = tmp_path / "skills"
    skills.mkdir()
    dirty = VALID_SKILL.replace("safe_skill", "dirty_skill").replace(
        "Use factual instructions only.", "exec(payload)"
    )
    (skills / "dirty_skill.md").write_text(dirty, encoding="utf-8")

    result = await SkillForge(_LLM(), skills).mutate("dirty_skill", Learning(learning="irrelevant"))
    assert result["status"] == "blocked"
    assert "security scan" in result["reason"]
