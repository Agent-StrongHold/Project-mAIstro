"""Acceptance coverage for retiring the PM-Fleet POC authority (#129).

The useful PM product data survives as the canonical Workspace Persona. The
old importable fleet/runner modules must not survive beside it as another
reusable identity or execution authority.
"""

from __future__ import annotations

from pathlib import Path

from maistro.personas.expander import expand_persona
from maistro.personas.rubric import load_template

_CORE = Path(__file__).resolve().parents[2]
_AGENTS = _CORE / "src" / "maistro" / "agents"
_TEMPLATE = _CORE / "src" / "maistro" / "personas" / "templates" / "pm_fleet.yaml"

_EXPECTED_SPAWNS = {
    "intake",
    "program_manager",
    "research",
    "delivery",
    "risk_dependency",
    "reporting",
}


def test_pm_fleet_reusable_identity_is_owned_by_workspace_persona() -> None:
    template = load_template(_TEMPLATE)
    assert template.kind == "workspace"
    assert template.id == "pm_fleet"
    assert {spawn.agent for spawn in template.spawns} == _EXPECTED_SPAWNS

    expanded = expand_persona(template)
    assert {agent.recipe.name.rsplit(".", 1)[-1] for agent in expanded.agents} == _EXPECTED_SPAWNS
    assert all(agent.skills for agent in expanded.agents)


def test_pm_fleet_template_keeps_legacy_definition_provenance() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "maistro.agents.pm_fleet.PM_FLEET" in text
    assert "src/lib/pmBranding.ts" in text
    assert "migrated here verbatim" in text


def test_legacy_pm_agent_authority_modules_are_removed() -> None:
    # Deleting the modules, rather than leaving compatibility imports, proves a
    # restart/import cannot recreate the retired POC roster or executor.
    assert not (_AGENTS / "pm_fleet.py").exists()
    assert not (_AGENTS / "pm_runner.py").exists()