"""Tests for maistro.agents.hyperagent — proactive proposals + interview gating."""

from __future__ import annotations

from pathlib import Path

import pytest

import maistro.agents.hyperagent as hyperagent_mod
from maistro.agents.hyperagent import (
    ProposedAction,
    RosterAgent,
    WorkItemSuggestion,
    build_suggestion_draft,
    interview_status,
    propose_actions,
    propose_autonomous_actions,
    propose_work_item_suggestions,
)
from maistro.agents.program_context import ProgramContext
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


def _ctx(**kwargs: object) -> ProgramContext:
    return ProgramContext(user_id="u1", **kwargs)  # type: ignore[arg-type]


class TestProposedActionAsDict:
    def test_as_dict_includes_autonomous_flag(self) -> None:
        action = ProposedAction(
            agent_id="delivery", capability="poll_jira", reason="r", payload={"k": "v"}
        )
        result = action.as_dict()
        assert result["agent_id"] == "delivery"
        assert result["capability"] == "poll_jira"
        assert result["reason"] == "r"
        assert result["payload"] == {"k": "v"}
        assert result["autonomous"] is True

    def test_as_dict_gated_capability_is_not_autonomous(self) -> None:
        action = ProposedAction(
            agent_id="delivery", capability="create_story", reason="r", payload={}
        )
        assert action.as_dict()["autonomous"] is False


class TestWorkItemSuggestionAsDict:
    def test_as_dict_shape(self) -> None:
        suggestion = WorkItemSuggestion(work_type="epic", reason="why", draft_id="d1")
        result = suggestion.as_dict()
        assert result == {
            "work_type": "epic",
            "label": "Epic",
            "reason": "why",
            "draft_id": "d1",
        }

    def test_as_dict_default_draft_id_is_none(self) -> None:
        suggestion = WorkItemSuggestion(work_type="initiative", reason="why")
        assert suggestion.as_dict()["draft_id"] is None


class TestInterviewStatus:
    def test_complete_interview_reports_complete(self) -> None:
        ctx = _ctx(interview_complete=True, interview_step=5)
        result = interview_status(ctx)
        assert result["complete"] is True
        assert result["step"] == 5
        assert result["total_steps"] == 5
        assert "Autonomous polls" in result["message"]

    def test_incomplete_with_question_reports_progress(self) -> None:
        ctx = _ctx(interview_complete=False, interview_step=0)
        result = interview_status(ctx)
        assert result["complete"] is False
        assert result["step"] == 1
        assert result["total_steps"] == 5
        assert result["agent"] == "intake"
        assert "program or initiative" in result["question"]

    def test_incomplete_but_no_question_left_reports_complete_zero_step(self) -> None:
        ctx = _ctx(interview_complete=False, interview_step=99)
        result = interview_status(ctx)
        assert result["complete"] is True
        assert result["step"] == 0
        assert result["total_steps"] == 5
        assert result["message"] == ""

    def test_custom_steps_override_total_steps_and_the_next_question(self) -> None:
        custom = (
            {"field": "program_name", "agent": "host", "question": "What's this for?"},
            {"field": "vibe", "agent": "host", "question": "What vibe?"},
        )
        ctx = _ctx(interview_complete=False, interview_step=0)
        result = interview_status(ctx, use_case="brand_new_persona", custom_steps=custom)
        assert result["total_steps"] == 2
        assert result["agent"] == "host"
        assert result["question"] == "What's this for?"


def _pm_fleet_roster() -> list[RosterAgent]:
    """PM Fleet's agents, derived from the canonical Workspace Persona.

    Order still matters because the pulse takes the first agent declaring a
    capability, and `fetch_program_state` is declared by both
    `program_manager` and `research`. The test therefore characterizes the
    shipped Persona without recreating the retired hardcoded fleet tuple.
    """
    expanded = expand_persona(load_template(_PM_FLEET_TEMPLATE))
    return [
        RosterAgent(
            name=agent.recipe.name.rsplit(".", 1)[-1],
            capabilities=frozenset(agent.skills),
        )
        for agent in expanded.agents
    ]


class TestProposeAutonomousActions:
    def test_interview_incomplete_returns_empty(self) -> None:
        ctx = _ctx(interview_complete=False)
        assert propose_autonomous_actions(ctx, roster=_pm_fleet_roster()) == []

    def test_complete_interview_returns_actions(self) -> None:
        ctx = _ctx(interview_complete=True, program_name="Apollo", goals=["g1"], tools=["jira"])
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster())
        assert len(actions) > 0
        for a in actions:
            assert a.payload["source"] == "hyperagent"
            assert a.payload["program"] == "Apollo"

    def test_unknown_agent_id_is_skipped(self) -> None:
        ctx = _ctx(interview_complete=True, tools=[])
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster())
        assert all(a.agent_id != "research" or True for a in actions)
        known_ids = {"program_manager", "risk_dependency", "reporting", "delivery", "research"}
        assert all(a.agent_id in known_ids for a in actions)

    def test_max_actions_caps_results(self) -> None:
        ctx = _ctx(interview_complete=True, tools=["jira", "airtable"])
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster(), max_actions=2)
        assert len(actions) <= 2

    def test_dedupes_by_agent_and_capability(self) -> None:
        ctx = _ctx(interview_complete=True, tools=["jira"])
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster(), max_actions=10)
        keys = [(a.agent_id, a.capability) for a in actions]
        assert len(keys) == len(set(keys))

    def test_empty_program_name_falls_back_in_payload(self) -> None:
        ctx = _ctx(interview_complete=True, program_name="", tools=[])
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster())
        assert actions[0].payload["title"] == "program"

    def test_a_capability_no_one_declares_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The roster answers who, so a capability nobody has is skipped."""
        ctx = _ctx(interview_complete=True, tools=[])
        monkeypatch.setattr(
            hyperagent_mod,
            "autonomous_pulse_candidates",
            lambda tools: [("no_such_capability", "reason")],
        )
        assert propose_autonomous_actions(ctx, roster=_pm_fleet_roster()) == []

    def test_an_empty_roster_proposes_nothing(self) -> None:
        ctx = _ctx(interview_complete=True, tools=["jira"])
        assert propose_autonomous_actions(ctx, roster=[]) == []

    def test_a_non_pm_roster_gets_its_own_agents(self) -> None:
        ctx = _ctx(interview_complete=True, tools=[])
        roster = [RosterAgent(name="analyst", capabilities=frozenset({"scan_risks"}))]

        actions = propose_autonomous_actions(ctx, roster=roster, max_actions=10)

        assert [(a.agent_id, a.capability) for a in actions] == [("analyst", "scan_risks")]

    def test_the_first_declarer_in_roster_order_wins(self) -> None:
        ctx = _ctx(interview_complete=True, tools=[])
        caps = frozenset({"fetch_program_state"})
        roster = [
            RosterAgent(name="second", capabilities=caps),
            RosterAgent(name="first", capabilities=caps),
        ]

        actions = propose_autonomous_actions(ctx, roster=roster, max_actions=1)

        assert actions[0].agent_id == "second"

    def test_duplicate_candidates_are_deduped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _ctx(interview_complete=True, tools=[])
        monkeypatch.setattr(
            hyperagent_mod,
            "autonomous_pulse_candidates",
            lambda tools: [
                ("poll_jira", "reason 1"),
                ("poll_jira", "reason 2"),
            ],
        )
        actions = propose_autonomous_actions(ctx, roster=_pm_fleet_roster(), max_actions=10)
        assert len(actions) == 1
        assert actions[0].reason == "reason 1"


class TestProposeWorkItemSuggestions:
    def test_interview_incomplete_returns_empty(self) -> None:
        ctx = _ctx(interview_complete=False)
        assert propose_work_item_suggestions(ctx, "u1") == []

    def test_no_goals_or_program_name_returns_empty(self) -> None:
        ctx = _ctx(interview_complete=True, goals=[], program_name="")
        assert propose_work_item_suggestions(ctx, "u1") == []

    def test_goals_and_program_name_suggest_initiative_and_epic(self) -> None:
        ctx = _ctx(interview_complete=True, goals=["Ship v2"], program_name="Apollo")
        result = propose_work_item_suggestions(ctx, "u1")
        assert [s.work_type for s in result] == ["initiative", "epic"]
        assert "Ship v2" in result[0].reason
        assert "Apollo" in result[1].reason

    def test_program_name_without_goals_suggests_only_epic(self) -> None:
        ctx = _ctx(interview_complete=True, goals=[], program_name="Apollo")
        result = propose_work_item_suggestions(ctx, "u1")
        assert [s.work_type for s in result] == ["epic"]

    def test_goals_without_program_name_suggests_nothing(self) -> None:
        ctx = _ctx(interview_complete=True, goals=["Ship v2"], program_name="")
        assert propose_work_item_suggestions(ctx, "u1") == []


class TestBuildSuggestionDraft:
    def test_builds_draft_and_suggestion(self) -> None:
        ctx = _ctx(interview_complete=True, program_name="Apollo", goals=["g1"])
        suggestion, draft = build_suggestion_draft(
            "u1", "initiative", ctx, reason="because", hint="hint text"
        )
        assert suggestion.work_type == "initiative"
        assert suggestion.reason == "because"
        assert suggestion.draft_id == draft.id
        assert draft.user_id == "u1"
        assert draft.work_type == "initiative"


class TestProposeActions:
    def test_interview_incomplete_with_question_routes_to_intake(self) -> None:
        ctx = _ctx(interview_complete=False, interview_step=0)
        result = propose_actions(ctx, roster=_pm_fleet_roster())
        assert len(result) == 1
        assert result[0].agent_id == "intake"
        assert result[0].capability == "route_to_pm_agent"
        assert result[0].payload["awaiting"] == "interview_answer"

    def test_interview_incomplete_no_question_left_returns_empty(self) -> None:
        ctx = _ctx(interview_complete=False, interview_step=99)
        assert propose_actions(ctx, roster=_pm_fleet_roster()) == []

    def test_include_interview_false_skips_gating(self) -> None:
        ctx = _ctx(interview_complete=False, interview_step=0, tools=[])
        result = propose_actions(ctx, roster=_pm_fleet_roster(), include_interview=False)
        assert result == []

    def test_complete_interview_delegates_to_autonomous_actions(self) -> None:
        ctx = _ctx(interview_complete=True, program_name="Apollo", tools=["jira"])
        result = propose_actions(ctx, roster=_pm_fleet_roster(), max_actions=2)
        assert len(result) <= 2
        assert all(isinstance(a, ProposedAction) for a in result)