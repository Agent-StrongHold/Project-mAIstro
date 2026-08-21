"""Renderer capability substrate — SPEC-070426-a22b.

Covers the absence-vs-failure split: an absent provider silently removes its skills,
a discovered-but-failing provider is circuit-broken, and the canvas-native FIXED_PAGE
floor is always present.
"""

from __future__ import annotations

import pytest

from maistro_design.renderers import (
    NATIVE_SLOTS,
    RendererDiscovery,
    RendererRegistry,
    RenderProviderError,
    RenderSlotUnavailableError,
    available_skills,
)
from maistro_design.skills.registry import InMemoryDesignSkillRegistry
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignSkill,
    OutputFormat,
    RenderSlot,
    SkillMode,
)


class _FakeProvider:
    """Configurable provider for the two states under test."""

    def __init__(
        self,
        slots: tuple[RenderSlot, ...],
        *,
        up: bool = True,
        discover_raises: bool = False,
        render_raises: bool = False,
    ) -> None:
        self.slots = slots
        self._up = up
        self._discover_raises = discover_raises
        self._render_raises = render_raises
        self.render_calls = 0

    async def discover(self) -> RendererDiscovery:
        if self._discover_raises:
            raise RuntimeError("boom in discover")
        return RendererDiscovery.up(self.slots) if self._up else RendererDiscovery.down()

    async def render(self, prompt_stack: str, skill: DesignSkill) -> ArtifactNode:
        self.render_calls += 1
        if self._render_raises:
            raise RuntimeError("boom in render")
        return ArtifactNode(
            key=skill.slug, kind=ArtifactKind.FILE, format=OutputFormat.HTML, value=prompt_stack
        )


def _skill(slug: str, slot: RenderSlot | None) -> DesignSkill:
    return DesignSkill(
        slug=slug, name=slug, mode=SkillMode.PROTOTYPE, description="", render_slot=slot
    )


# ─── the native floor ──────────────────────────────────────────────────────────


def test_empty_registry_exposes_only_the_native_floor() -> None:
    reg = RendererRegistry()
    assert reg.filled_slots() == NATIVE_SLOTS
    # canvas exporters serve both fixed pages and decks with zero plugins
    assert RenderSlot.FIXED_PAGE in reg.filled_slots()
    assert RenderSlot.DECK in reg.filled_slots()
    assert RenderSlot.REFLOWABLE_WEB not in reg.filled_slots()  # external, absent


@pytest.mark.asyncio
async def test_discover_all_with_no_providers_returns_native() -> None:
    reg = RendererRegistry()
    assert await reg.discover_all() == NATIVE_SLOTS


# ─── absence: silent filtering ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_up_fills_its_slots() -> None:
    reg = RendererRegistry()
    reg.register(_FakeProvider((RenderSlot.REFLOWABLE_WEB,)))
    filled = await reg.discover_all()
    assert RenderSlot.REFLOWABLE_WEB in filled
    assert RenderSlot.FIXED_PAGE in filled  # floor still there


@pytest.mark.asyncio
async def test_provider_down_fills_nothing() -> None:
    reg = RendererRegistry()
    reg.register(_FakeProvider((RenderSlot.REFLOWABLE_WEB,), up=False))
    filled = await reg.discover_all()
    assert RenderSlot.REFLOWABLE_WEB not in filled
    assert filled == NATIVE_SLOTS


@pytest.mark.asyncio
async def test_discover_raising_is_treated_as_down() -> None:
    reg = RendererRegistry()
    reg.register(_FakeProvider((RenderSlot.VIDEO,), discover_raises=True))
    assert await reg.discover_all() == NATIVE_SLOTS  # no propagation, slot absent


def test_available_skills_filters_by_filled_slots() -> None:
    native = _skill("flyer", None)  # canvas-native, always available
    deck = _skill("pitch-deck", RenderSlot.DECK)  # DECK is in the native floor
    web = _skill("landing-page", RenderSlot.REFLOWABLE_WEB)  # external
    video = _skill("promo", RenderSlot.VIDEO)  # external

    only_floor = {s.slug for s in available_skills([native, deck, web, video], NATIVE_SLOTS)}
    assert only_floor == {"flyer", "pitch-deck"}  # deck is native; web/video hidden

    with_web = {
        s.slug
        for s in available_skills(
            [native, deck, web, video], NATIVE_SLOTS | {RenderSlot.REFLOWABLE_WEB}
        )
    }
    assert "landing-page" in with_web and "promo" not in with_web


def test_registry_list_available_hides_unbacked_skills() -> None:
    skills = InMemoryDesignSkillRegistry()
    skills.register(_skill("flyer", None))  # native
    skills.register(_skill("pitch-deck", RenderSlot.DECK))  # native deck floor
    skills.register(_skill("landing-page", RenderSlot.REFLOWABLE_WEB))  # external

    available = skills.list_available(NATIVE_SLOTS)
    slugs = {s.slug for s in available}
    assert slugs == {"flyer", "pitch-deck"}  # web hidden: no provider => no error, just absent


def test_shipped_builtins_are_gated_by_render_slot() -> None:
    """The silent-absence contract must bite for the real catalog, not just fixtures."""
    from maistro_design.skills.builtins import load_builtins

    reg = InMemoryDesignSkillRegistry()
    load_builtins(reg)

    native_only = {s.slug for s in reg.list_available(NATIVE_SLOTS)}
    # decks (native PPTX/HTML export), images, and design-system docs need no plugin
    assert {"pitch-deck", "product-demo-deck", "hero-image", "social-card"} <= native_only
    # reflowable-web skills are hidden until an external provider is discovered
    assert {"landing-page", "login-flow", "agent-browser", "email-template"}.isdisjoint(native_only)

    with_web = {s.slug for s in reg.list_available(NATIVE_SLOTS | {RenderSlot.REFLOWABLE_WEB})}
    assert "landing-page" in with_web


# ─── failure: circuit breaker ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_success_returns_artifact() -> None:
    reg = RendererRegistry()
    reg.register(_FakeProvider((RenderSlot.REFLOWABLE_WEB,)))
    await reg.discover_all()
    node = await reg.render(
        RenderSlot.REFLOWABLE_WEB, "PROMPT", _skill("pitch-deck", RenderSlot.REFLOWABLE_WEB)
    )
    assert node.value == "PROMPT"


@pytest.mark.asyncio
async def test_render_failure_trips_breaker_and_empties_slot() -> None:
    reg = RendererRegistry()
    reg.register(_FakeProvider((RenderSlot.REFLOWABLE_WEB,), render_raises=True))
    await reg.discover_all()
    assert RenderSlot.REFLOWABLE_WEB in reg.filled_slots()

    with pytest.raises(RenderProviderError):
        await reg.render(
            RenderSlot.REFLOWABLE_WEB, "PROMPT", _skill("pitch-deck", RenderSlot.REFLOWABLE_WEB)
        )

    # breaker open: slot no longer offered until a fresh discovery
    assert RenderSlot.REFLOWABLE_WEB not in reg.filled_slots()
    with pytest.raises(RenderSlotUnavailableError):
        await reg.render(
            RenderSlot.REFLOWABLE_WEB, "PROMPT", _skill("pitch-deck", RenderSlot.REFLOWABLE_WEB)
        )


@pytest.mark.asyncio
async def test_rediscovery_clears_the_breaker() -> None:
    provider = _FakeProvider((RenderSlot.REFLOWABLE_WEB,), render_raises=True)
    reg = RendererRegistry()
    reg.register(provider)
    await reg.discover_all()
    with pytest.raises(RenderProviderError):
        await reg.render(RenderSlot.REFLOWABLE_WEB, "P", _skill("d", RenderSlot.REFLOWABLE_WEB))
    assert RenderSlot.REFLOWABLE_WEB not in reg.filled_slots()

    provider._render_raises = False  # provider recovers
    await reg.discover_all()  # fresh discovery clears the breaker
    assert RenderSlot.REFLOWABLE_WEB in reg.filled_slots()


@pytest.mark.asyncio
async def test_render_on_unfilled_slot_raises() -> None:
    reg = RendererRegistry()
    await reg.discover_all()
    with pytest.raises(RenderSlotUnavailableError):
        await reg.render(RenderSlot.REFLOWABLE_WEB, "P", _skill("x", RenderSlot.REFLOWABLE_WEB))
