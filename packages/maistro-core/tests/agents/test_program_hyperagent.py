"""Program context and hyperagent tests."""

from __future__ import annotations

from pathlib import Path

from maistro.agents.hyperagent import (
    RosterAgent,
    propose_actions,
    propose_work_item_suggestions,
)
from maistro.agents.pm_capabilities import is_autonomous
from maistro.agents.program_context import (
    ProgramContext,
    apply_guidance,
    apply_interview_answer,
)
from maistro.personas.expander import expand_persona
from maistro.personas.rubric import load_template

_PM_FLEET_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "maistro"
    / "personas"
    / "templates"
    / "pm_fleet.yaml"
)


def _pm_fleet_roster() -> list[RosterAgent]:
    expanded = expand_persona(load_template(_PM_FLEET_TEMPLATE))
    return [
        RosterAgent(
            name=agent.recipe.name.rsplit(".", 1)[-1],
            capabilities=frozenset(agent.skills),
        )
        for agent in expanded.agents
    ]


def test_interview_advances_and_completes() -> None:
    ctx = ProgramContext.empty("alice")
    for answer in (
        "Platform Modernization",
        "Ship SSO\nReduce incidents",
        "Jira, GitHub",
        "Vendor API dependency",
        "VP Engineering",
    ):
        ctx = apply_interview_answer(ctx, answer)
    assert ctx.interview_complete is True
    assert ctx.program_name == "Platform Modernization"
    assert len(ctx.goals) >= 1


def test_guidance_appends_facts() -> None:
    ctx = ProgramContext.empty("bob")
    ctx = apply_guidance(ctx, "Watch the Jira epic PROJ-42 for slip risk")
    assert any("Guidance" in f for f in ctx.facts)


def test_propose_actions_after_interview() -> None:
    ctx = ProgramContext.empty("carol")
    for answer in ("Prog A", "Goal 1", "Jira", "Dep X", "Lead"):
        ctx = apply_interview_answer(ctx, answer)
    actions = propose_actions(ctx, roster=_pm_fleet_roster(), max_actions=4)
    assert len(actions) >= 2
    agents = {a.agent_id for a in actions}
    assert "program_manager" in agents
    assert all(is_autonomous(a.capability) for a in actions)
    assert not any(a.capability.startswith("create_") for a in actions)


def test_work_item_suggestions_never_auto_create() -> None:
    ctx = ProgramContext.empty("dana")
    for answer in ("Prog B", "Ship feature", "Jira", "Vendor risk", "TPM"):
        ctx = apply_interview_answer(ctx, answer)
    suggestions = propose_work_item_suggestions(ctx, "dana")
    assert len(suggestions) >= 1
    assert suggestions[0].work_type == "initiative"