import os

import pytest

os.environ.setdefault("MAISTRO_DRY_RUN", "1")


@pytest.fixture()
def skill_registry():
    from maistro_design.skills.builtins import load_builtins
    from maistro_design.skills.registry import InMemoryDesignSkillRegistry

    r = InMemoryDesignSkillRegistry()
    load_builtins(r)
    return r


@pytest.fixture()
def system_registry():
    from maistro_design.systems.registry import InMemoryDesignSystemRegistry
    from maistro_design.trust import TrustTier
    from maistro_design.types import DesignSystem

    r = InMemoryDesignSystemRegistry()
    r.register(
        DesignSystem(
            slug="default",
            name="Default",
            description="Neutral default system",
            trust_tier=TrustTier.T0,
        )
    )
    return r


@pytest.fixture()
def engine(skill_registry, system_registry):
    from maistro_design.engine import DesignEngine

    return DesignEngine(skill_registry=skill_registry, system_registry=system_registry)
