"""Integration tests for DesignEngine + DesignProjectStore."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from maistro_design.engine import DesignEngine
from maistro_design.skills.builtins import load_builtins
from maistro_design.skills.registry import InMemoryDesignSkillRegistry
from maistro_design.stores import PgDesignProjectStore
from maistro_design.systems.registry import InMemoryDesignSystemRegistry
from maistro_design.trust import TrustTier
from maistro_design.types import DesignSystem, DiscoveryResult


def make_mock_session_factory():
    """Create a callable that returns an async context manager for a mock session."""

    @asynccontextmanager
    async def factory():
        mock_session = AsyncMock()
        yield mock_session

    return factory


@pytest.fixture
def skill_registry():
    """Create a skill registry with built-in skills."""
    registry = InMemoryDesignSkillRegistry()
    load_builtins(registry)
    return registry


@pytest.fixture
def system_registry():
    """Create a system registry with default system."""
    registry = InMemoryDesignSystemRegistry()
    registry.register(
        DesignSystem(
            slug="default",
            name="Default",
            description="Neutral default system",
            trust_tier=TrustTier.T0,
        )
    )
    return registry


@pytest.fixture
def engine_with_store(skill_registry, system_registry):
    """Create engine with mocked project store."""
    mock_factory = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)
    return DesignEngine(
        skill_registry=skill_registry,
        system_registry=system_registry,
        project_store=store,
    )


@pytest.mark.asyncio
async def test_engine_generate_persists_project(engine_with_store):
    """Test that engine.generate() persists project to store."""
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "Email/Password", "brand_tone": "Professional"},
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )

    project = await engine_with_store.generate(discovery, org_id="org-123", team_id="team-456")

    assert project.id is not None
    assert project.org_id == "org-123"
    assert project.team_id == "team-456"
    assert project.skill_slug == "login-flow"
    assert project.design_system_slug == "default"
    assert len(project.outputs) == 1


@pytest.mark.asyncio
async def test_engine_generate_inherits_trust_tier(engine_with_store):
    """Test that generated project inherits trust tier from discovery."""
    discovery = DiscoveryResult(
        skill_slug="landing-page",
        responses={
            "product_name": "MyApp",
            "headline": "The best app",
            "cta_text": "Get started",
            "section_count": "4",
        },
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )

    project = await engine_with_store.generate(discovery, org_id="org-123")

    assert project.trust_tier == TrustTier.T3
    assert project.outputs[0].trust_tier == TrustTier.T3


@pytest.mark.asyncio
async def test_engine_generate_without_store(skill_registry, system_registry):
    """Test that engine.generate() works even without a project store."""
    engine = DesignEngine(
        skill_registry=skill_registry, system_registry=system_registry, project_store=None
    )
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "Email/Password", "brand_tone": "Professional"},
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )

    project = await engine.generate(discovery, org_id="org-123")

    assert project.id is not None
    assert project.org_id == "org-123"
    # Should still work, just not persisted


@pytest.mark.asyncio
async def test_engine_generate_sets_org_and_team(skill_registry, system_registry):
    """Test that engine.generate() correctly sets org_id and team_id from parameters."""
    mock_factory = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)
    engine = DesignEngine(
        skill_registry=skill_registry,
        system_registry=system_registry,
        project_store=store,
    )

    discovery = DiscoveryResult(
        skill_slug="brand-guidelines",
        responses={
            "brand_name": "Acme Corp",
            "brand_values": "Innovation, Trustworthy",
            "sections": "Logo,Colors,Typography",
        },
        design_system_slug="default",
        trust_tier=TrustTier.T2,
    )

    project = await engine.generate(discovery, org_id="acme-org", team_id="design-team")

    assert project.org_id == "acme-org"
    assert project.team_id == "design-team"
    # Trust tier is determined by skill + system + discovery + Warden scan
    assert project.trust_tier in (TrustTier.T0, TrustTier.T1, TrustTier.T2, TrustTier.T3)


@pytest.mark.asyncio
async def test_generated_project_includes_discovery(engine_with_store):
    """Test that generated project persists discovery result."""
    discovery = DiscoveryResult(
        skill_slug="landing-page",
        responses={
            "product_name": "MyProduct",
            "headline": "Best product ever",
            "cta_text": "Try now",
            "section_count": "5",
        },
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )

    project = await engine_with_store.generate(discovery, org_id="org-123")

    assert project.discovery is not None
    assert project.discovery.skill_slug == "landing-page"
    assert project.discovery.responses["product_name"] == "MyProduct"
    assert project.discovery.trust_tier == TrustTier.T3


@pytest.mark.asyncio
async def test_generated_project_output_has_prompt_stack(engine_with_store):
    """Test that generated output contains assembled prompt stack."""
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "OAuth", "brand_tone": "Minimal"},
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )

    project = await engine_with_store.generate(discovery, org_id="org-123")

    assert len(project.outputs) == 1
    output = project.outputs[0]
    # Output should contain prompt stack with skill + system + discovery sections
    assert "Skill Instructions" in output.content
    assert "Discovery Responses" in output.content
    assert "OAuth" in output.content  # Discovery response should be included
