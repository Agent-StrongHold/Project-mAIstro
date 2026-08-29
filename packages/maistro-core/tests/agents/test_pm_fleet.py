"""Tests for maistro.agents.pm_fleet — PM fleet agent definitions."""

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace
from typing import Any

import pytest

import maistro.agents.pm_fleet as pm_fleet
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


class TestCanonicalPersonaAuthority:
    def test_routing_def_does_not_store_reusable_definition_fields(self) -> None:
        stored = {field.name for field in fields(pm_fleet.PmAgentDef)}
        assert "tagline" not in stored
        assert "capabilities" not in stored
        assert "tools" not in stored
        assert "reasoning_strategy" not in stored

    def test_packaged_persona_matches_transitional_routing(self) -> None:
        template = pm_fleet._pm_fleet_persona()
        assert template.kind == "workspace"
        assert template.id == "pm_fleet"
        assert {spawn.agent for spawn in template.spawns} == {defn.name for defn in PM_FLEET}
        for defn in PM_FLEET:
            assert defn.primary_capability in defn.capabilities

    def test_properties_read_reusable_values_from_persona(self) -> None:
        defn = get_pm_def("delivery")
        assert defn is not None
        spawn = next(s for s in pm_fleet._pm_fleet_persona().spawns if s.agent == "delivery")
        assert defn.tagline == spawn.role
        assert defn.capabilities == tuple(spawn.skills)
        assert defn.tools == tuple(spawn.tools)
        assert defn.reasoning_strategy == spawn.reasoning_strategy

    def test_registration_consumes_persona_spawn_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        template = pm_fleet._pm_fleet_persona()
        replacements = []
        for spawn in template.spawns:
            if spawn.agent == "delivery":
                spawn = spawn.model_copy(
                    update={
                        "role": "Canonical delivery role",
                        "reasoning_strategy": "react",
                        "tools": ["canonical_tool"],
                        "skills": ["poll_jira", "canonical_skill"],
                    }
                )
            replacements.append(spawn)
        canonical = template.model_copy(update={"spawns": replacements})
        monkeypatch.setattr(pm_fleet, "_pm_fleet_persona", lambda: canonical)

        catalog = AgentCatalog()
        register_pm_fleet(catalog)
        card = catalog.resolve("delivery")
        assert card is not None
        assert card.description == "Canonical delivery role"
        assert card.reasoning_strategy == "react"
        assert card.tools == ("canonical_tool",)
        assert card.skills == ("poll_jira", "canonical_skill")

    def test_validator_rejects_wrong_persona_identity(self) -> None:
        template = pm_fleet._pm_fleet_persona().model_copy(update={"id": "other"})
        with pytest.raises(RuntimeError, match=r"kind='workspace'.*id='pm_fleet'"):
            pm_fleet._validate_pm_fleet_persona(template)

    def test_validator_rejects_duplicate_spawns(self) -> None:
        template = pm_fleet._pm_fleet_persona()
        duplicate = template.model_copy(update={"spawns": [*template.spawns, template.spawns[0]]})
        with pytest.raises(RuntimeError, match="duplicate agent spawns"):
            pm_fleet._validate_pm_fleet_persona(duplicate)

    def test_validator_rejects_roster_drift(self) -> None:
        template = pm_fleet._pm_fleet_persona()
        drifted = template.model_copy(update={"spawns": template.spawns[:-1]})
        with pytest.raises(RuntimeError, match="roster drift"):
            pm_fleet._validate_pm_fleet_persona(drifted)

    def test_validator_rejects_missing_primary_capability(self) -> None:
        template = pm_fleet._pm_fleet_persona()
        replacements = []
        for spawn in template.spawns:
            if spawn.agent == "delivery":
                spawn = spawn.model_copy(
                    update={"skills": [skill for skill in spawn.skills if skill != "poll_jira"]}
                )
            replacements.append(spawn)
        drifted = template.model_copy(update={"spawns": replacements})
        with pytest.raises(RuntimeError, match="primary capability 'poll_jira'"):
            pm_fleet._validate_pm_fleet_persona(drifted)

    def test_loader_failure_is_not_silently_replaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pm_fleet._pm_fleet_persona.cache_clear()

        def fail_load(_path: object) -> object:
            raise ValueError("bad template")

        monkeypatch.setattr(pm_fleet, "load_template", fail_load)
        with pytest.raises(RuntimeError, match="Cannot load canonical PM Fleet Persona template"):
            pm_fleet._pm_fleet_persona()
        pm_fleet._pm_fleet_persona.cache_clear()


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
            assert card.tools == defn.tools
            assert card.reasoning_strategy == defn.reasoning_strategy

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
