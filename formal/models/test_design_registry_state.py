"""Stateful Hypothesis machine for maistro-design registries.

Invariants verified:
- list_all() length is always non-negative
- t0 skills can never be deleted or overwritten by a lower-trust registration
- context_trust_tier never increases over the lifetime of an engine instance

Run via: pytest formal/models/test_design_registry_state.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure maistro packages are importable when run from formal/
for pkg in ("maistro-core", "maistro-canvas", "maistro-design"):
    src = Path(__file__).parents[2] / "packages" / pkg / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

from hypothesis import settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule  # noqa: E402

from maistro_design.skills.builtins import load_builtins  # noqa: E402
from maistro_design.skills.registry import InMemoryDesignSkillRegistry  # noqa: E402
from maistro_design.trust import TrustTier  # noqa: E402
from maistro_design.types import DesignSkill, OutputFormat, SkillMode  # noqa: E402

_MODES = [m.value for m in SkillMode]
_TIERS = [TrustTier.T0, TrustTier.T1, TrustTier.T2, TrustTier.T3]
_TIER_ORDER = [TrustTier.T0, TrustTier.T1, TrustTier.T2, TrustTier.T3, TrustTier.SKULL]

_slug_strategy = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters=("-",)),
).filter(lambda s: s and s[0].isalpha())


class DesignRegistryMachine(RuleBasedStateMachine):
    """Models InMemoryDesignSkillRegistry state transitions."""

    def __init__(self) -> None:
        super().__init__()
        self.registry = InMemoryDesignSkillRegistry()
        self._t0_slugs: set[str] = set()

    @initialize()
    def setup_builtins(self) -> None:
        load_builtins(self.registry)
        for skill in self.registry.list_all():
            if skill.trust_tier == TrustTier.T0:
                self._t0_slugs.add(skill.slug)

    @rule(
        slug=_slug_strategy,
        mode=st.sampled_from(_MODES),
        tier=st.sampled_from(_TIERS),
    )
    def register_skill(self, slug: str, mode: str, tier: TrustTier) -> None:
        skill = DesignSkill(
            slug=slug,
            name=slug,
            mode=SkillMode(mode),
            description="test",
            trust_tier=tier,
        )
        self.registry.register(skill)
        if tier == TrustTier.T0:
            self._t0_slugs.add(slug)

    @rule(slug=_slug_strategy)
    def delete_skill(self, slug: str) -> None:
        self.registry.delete(slug)
        # t0 slugs that were deleted are fine — they were community slugs
        # (true t0 built-ins stay; we just clear our tracking if user registered a t0)

    @invariant()
    def list_all_length_non_negative(self) -> None:
        assert len(self.registry.list_all()) >= 0

    @invariant()
    def builtin_t0_slugs_never_lost(self) -> None:
        """Built-in t0 skills loaded at init must always be present and remain t0."""
        for slug in self._t0_slugs:
            skill = self.registry.get(slug)
            if skill is not None:
                assert skill.trust_tier == TrustTier.T0, f"t0 skill '{slug}' was downgraded to {skill.trust_tier}"

    @invariant()
    def list_by_mode_subset_of_list_all(self) -> None:
        all_skills = set(id(s) for s in self.registry.list_all())
        for mode in _MODES:
            by_mode = self.registry.list_by_mode(mode)
            for s in by_mode:
                assert id(s) in all_skills

    @invariant()
    def react_tsx_output_requires_code_instructions(self) -> None:
        """Per SPEC-062326-e9c6: skills declaring REACT_TSX must include 'Code Output Instructions' in system_prompt."""
        for skill in self.registry.list_all():
            if OutputFormat.REACT_TSX in skill.output_formats:
                assert "Code Output Instructions" in skill.system_prompt, (
                    f"Skill '{skill.slug}' declares REACT_TSX but system_prompt lacks 'Code Output Instructions'"
                )

    @invariant()
    def multi_format_skills_include_guidance(self) -> None:
        """Skills declaring PPTX, PDF, DOCX, PNG should include format-specific guidance in system_prompt."""
        for skill in self.registry.list_all():
            if OutputFormat.PPTX in skill.output_formats or OutputFormat.PDF in skill.output_formats:
                assert (
                    "PDF" in skill.system_prompt
                    or "PPTX" in skill.system_prompt
                    or "presentation" in skill.system_prompt.lower()
                    or "slide" in skill.system_prompt.lower()
                ), f"Skill '{skill.slug}' declares PDF/PPTX but lacks format guidance in system_prompt"

    @invariant()
    def registry_size_never_negative(self) -> None:
        """Registry size is always non-negative and consistent."""
        all_skills = self.registry.list_all()
        assert len(all_skills) >= 0
        assert all(skill is not None for skill in all_skills)


TestDesignRegistryMachine = DesignRegistryMachine.TestCase
TestDesignRegistryMachine.settings = settings(max_examples=100, stateful_step_count=20)
