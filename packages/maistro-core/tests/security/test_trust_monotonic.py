from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from maistro.agents.importers.pi import PiAgentImporter
from maistro.capabilities.registry import CapabilityRegistry, ProviderReplacementDecision
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.security.trust import trust_rank
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
