"""Tests for maistro.agents.pm_fleet — PM fleet agent definitions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.agents.catalog import AgentCatalog
from maistro.agents.pm_fleet import (
    PM_FLEET,
    agent_status_for_user,
    build_task_description,
    fleet_card_dict,
    get_pm_def,
    register_pm_fleet,
)


class TestPmAgentDefAgentId:
    def test_agent_id_returns_name(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        assert defn.agent_id == "delivery"


class TestGetPmDef:
    def test_exact_match(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        assert defn.name == "delivery"

    def test_prefix_match(self) -> None:
        defn = get_pm_def("delivery_subagent_x")
        assert defn is not None
        assert defn.name == "delivery"

    def test_no_match_returns_none(self) -> None:
        assert get_pm_def("unknown_agent") is None


class TestBuildTaskDescription:
    def test_raises_for_unknown_agent(self) -> None:
        with pytest.raises(ValueError, match="Unknown PM agent"):
            build_task_description("nope", "scan_risks", {})

    def test_raises_for_invalid_capability(self) -> None:
        with pytest.raises(ValueError, match="not valid for"):
            build_task_description("delivery", "scan_risks", {})

    def test_uses_title_from_payload(self) -> None:
        task_type, desc = build_task_description("delivery", "poll_jira", {"title": "Custom Title"})
        assert task_type == "delivery"
        assert "Custom Title" in desc

    def test_defaults_title_to_capability_label(self) -> None:
        _task_type, desc = build_task_description("delivery", "poll_jira", {})
        assert "poll jira" in desc

    def test_includes_summary_when_present(self) -> None:
        _task_type, desc = build_task_description(
            "delivery", "poll_jira", {"summary": "summary text"}
        )
        assert "summary text" in desc

    def test_falls_back_to_program_summary_when_no_summary(self) -> None:
        payload: dict[str, Any] = {
            "title": "x",
            "program": {"summary": "program summary"},
        }
        _task_type, desc = build_task_description("delivery", "poll_jira", payload)
        assert "program summary" in desc

    def test_uses_program_name_when_no_title(self) -> None:
        payload: dict[str, Any] = {"title": "", "program": {"program_name": "Atlas"}}
        _task_type, desc = build_task_description("delivery", "poll_jira", payload)
        assert "Atlas" in desc

    def test_non_dict_program_ignored(self) -> None:
        payload: dict[str, Any] = {"program": "not-a-dict"}
        _task_type, desc = build_task_description("delivery", "poll_jira", payload)
        assert desc  # does not raise

    def test_includes_hyperagent_reason(self) -> None:
        payload = {"hyperagent_reason": "escalated by user"}
        _task_type, desc = build_task_description("delivery", "poll_jira", payload)
        assert "why: escalated by user" in desc

    def test_no_reason_omits_why_clause(self) -> None:
        _task_type, desc = build_task_description("delivery", "poll_jira", {})
        assert "why:" not in desc


class TestRegisterPmFleet:
    def test_registers_all_fleet_agents(self) -> None:
        catalog = AgentCatalog()
        register_pm_fleet(catalog)
        for defn in PM_FLEET:
            card = catalog.resolve(defn.name)
            assert card is not None
            assert card.name == defn.display_name
            assert card.description == defn.tagline
            assert card.skills == defn.capabilities

    def test_delegation_mode_selective_when_sub_agents(self) -> None:
        catalog = AgentCatalog()
        register_pm_fleet(catalog)
        card = catalog.resolve("program_manager")
        assert card is not None
        assert card.delegation_mode == "selective"

    def test_delegation_mode_none_without_sub_agents(self) -> None:
        catalog = AgentCatalog()
        register_pm_fleet(catalog)
        card = catalog.resolve("reporting")
        assert card is not None
        assert card.delegation_mode == "none"


class TestFleetCardDict:
    def test_returns_expected_shape(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        card = fleet_card_dict(defn)
        assert card["id"] == "delivery"
        assert card["name"] == defn.display_name
        assert card["status"] == "idle"
        assert card["capabilities"] == list(defn.capabilities)

    def test_accepts_custom_status(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        card = fleet_card_dict(defn, status="running")
        assert card["status"] == "running"


class TestAgentStatusForUser:
    def test_idle_when_no_matching_tasks(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        assert agent_status_for_user(defn, []) == "idle"

    def test_running_when_matching_non_terminal_task(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        task = SimpleNamespace(task_type="delivery", description="", status="in_progress")
        assert agent_status_for_user(defn, [task]) == "running"

    def test_error_when_matching_failed_task(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        task = SimpleNamespace(task_type="delivery", description="", status="failed")
        assert agent_status_for_user(defn, [task]) == "error"

    def test_idle_when_matching_completed_task(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        task = SimpleNamespace(task_type="delivery", description="", status="completed")
        assert agent_status_for_user(defn, [task]) == "idle"

    def test_matches_by_description_when_task_type_differs(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        task = SimpleNamespace(
            task_type="other", description="[Delivery Agent] delivery: x", status="in_progress"
        )
        assert agent_status_for_user(defn, [task]) == "running"

    def test_status_with_value_attribute_is_unwrapped(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        status_obj = SimpleNamespace(value="in_progress")
        task = SimpleNamespace(task_type="delivery", description="", status=status_obj)
        assert agent_status_for_user(defn, [task]) == "running"

    def test_running_takes_priority_over_error(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        running_task = SimpleNamespace(task_type="delivery", description="", status="in_progress")
        failed_task = SimpleNamespace(task_type="delivery", description="", status="failed")
        assert agent_status_for_user(defn, [failed_task, running_task]) == "running"

    def test_non_matching_tasks_ignored(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        task = SimpleNamespace(task_type="reporting", description="unrelated", status="failed")
        assert agent_status_for_user(defn, [task]) == "idle"
