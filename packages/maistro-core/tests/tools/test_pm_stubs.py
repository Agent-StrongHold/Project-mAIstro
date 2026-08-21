"""Tests for maistro.tools.pm_stubs — stub PM tool responses for fleet POC demos."""

from __future__ import annotations

import pytest

from maistro.tools.pm_stubs import (
    PM_STUB_HANDLERS,
    stub_create_work_item,
    stub_fetch_program_metrics,
    stub_fetch_program_state,
    stub_poll_airtable,
    stub_poll_jira,
    stub_scan_risks,
    stub_summarize_research,
    stub_sync_jira,
    stub_web_search_background,
)


class TestStubSyncJira:
    def test_delegates_to_poll_jira(self) -> None:
        result = stub_sync_jira({"x": 1})
        assert result["status"] == "ok"
        assert result["payload"] == {"x": 1}


class TestStubPollJira:
    def test_returns_expected_fields(self) -> None:
        result = stub_poll_jira({"team": "core"})
        assert result == {
            "status": "ok",
            "synced": 5,
            "blockers_found": 1,
            "sprints_active": 2,
            "source": "stub",
            "payload": {"team": "core"},
        }

    def test_defaults_payload_to_empty_dict(self) -> None:
        result = stub_poll_jira(None)
        assert result["payload"] == {}

    def test_defaults_payload_when_omitted(self) -> None:
        result = stub_poll_jira()
        assert result["payload"] == {}


class TestStubPollAirtable:
    def test_returns_expected_fields(self) -> None:
        result = stub_poll_airtable({"x": 1})
        assert result == {
            "status": "ok",
            "records_synced": 12,
            "tables": ["Roadmap", "Capacity", "RAID"],
            "source": "stub",
            "payload": {"x": 1},
        }

    def test_defaults_payload_to_empty_dict(self) -> None:
        result = stub_poll_airtable(None)
        assert result["payload"] == {}


class TestStubScanRisks:
    def test_returns_risks(self) -> None:
        result = stub_scan_risks()
        assert result["status"] == "ok"
        assert len(result["risks"]) == 2


class TestStubFetchProgramMetrics:
    def test_returns_metrics(self) -> None:
        result = stub_fetch_program_metrics()
        assert result == {
            "status": "ok",
            "velocity": 42,
            "burn_down_pct": 68,
            "open_blockers": 2,
            "source": "stub",
        }


class TestStubWebSearchBackground:
    def test_uses_program_name_and_goals(self) -> None:
        payload = {"program": {"program_name": "Atlas", "goals": ["reduce latency"]}}
        result = stub_web_search_background(payload)
        assert "Atlas" in result["query"]
        assert "reduce latency" in result["query"]
        assert result["results_count"] == 3
        assert len(result["sources"]) == 3
        assert "Atlas" in result["summary"]

    def test_falls_back_to_title_when_no_program_name(self) -> None:
        payload = {"title": "Project X"}
        result = stub_web_search_background(payload)
        assert "Project X" in result["query"]

    def test_defaults_name_when_nothing_provided(self) -> None:
        result = stub_web_search_background()
        assert "program initiative" in result["query"]

    def test_defaults_goal_hint_when_no_goals(self) -> None:
        payload = {"program": {"program_name": "Atlas"}}
        result = stub_web_search_background(payload)
        assert "delivery outcomes" in result["query"]

    def test_non_dict_program_treated_as_empty(self) -> None:
        payload = {"program": "not-a-dict", "title": "Fallback Title"}
        result = stub_web_search_background(payload)
        assert "Fallback Title" in result["query"]

    def test_query_truncated_to_200_chars(self) -> None:
        long_name = "x" * 300
        payload = {"program": {"program_name": long_name}}
        result = stub_web_search_background(payload)
        assert len(result["query"]) <= 200


class TestStubSummarizeResearch:
    def test_counts_research_list(self) -> None:
        result = stub_summarize_research({"research": [1, 2]})
        assert result["sources_used"] == 2

    def test_counts_sources_list_when_no_research_key(self) -> None:
        result = stub_summarize_research({"sources": [1, 2, 3, 4]})
        assert result["sources_used"] == 4

    def test_non_list_prior_defaults_count_to_zero_then_three(self) -> None:
        result = stub_summarize_research({"research": "not-a-list"})
        assert result["sources_used"] == 3

    def test_defaults_to_three_when_empty(self) -> None:
        result = stub_summarize_research()
        assert result["sources_used"] == 3
        assert len(result["bullets"]) == 3


class TestStubFetchProgramState:
    def test_uses_program_name_and_goals(self) -> None:
        payload = {"program": {"program_name": "Atlas", "goals": ["a", "b"]}}
        result = stub_fetch_program_state(payload)
        assert result["program"] == "Atlas"
        assert result["goals_tracked"] == 2
        assert result["initiatives"] == 2
        assert result["learned_from_user"] is True

    def test_non_dict_program_raises_attribute_error(self) -> None:
        # Documents a real bug: unlike stub_web_search_background, this function
        # doesn't guard against a non-dict "program" value before calling .get() on it.

        payload = {"program": "Atlas"}
        with pytest.raises(AttributeError):
            stub_fetch_program_state(payload)

    def test_defaults_name_to_program_literal_when_nothing_provided(self) -> None:
        result = stub_fetch_program_state()
        assert result["program"] == "Program"
        assert result["goals_tracked"] == 3
        assert result["initiatives"] == 1
        assert result["learned_from_user"] is False

    def test_defaults_payload_when_none(self) -> None:
        result = stub_fetch_program_state(None)
        assert result["status"] == "ok"


class TestStubCreateWorkItem:
    def test_uses_provided_project_key_and_parent(self) -> None:
        fields = {"project_key": "ENG", "parent_key": "ENG-1", "summary": "Do thing"}
        result = stub_create_work_item("epic", fields, "create_epic")
        assert result["issue_key"].startswith("ENG-")
        assert result["work_type"] == "epic"
        assert result["capability"] == "create_epic"
        assert result["parent_key"] == "ENG-1"
        assert result["summary"] == "Do thing"
        assert result["posted_to"] == "jira"

    def test_defaults_project_key_to_pm(self) -> None:
        result = stub_create_work_item("story", {"summary": "x"}, "create_story")
        assert result["issue_key"].startswith("PM-")

    def test_defaults_parent_key_to_none(self) -> None:
        result = stub_create_work_item("story", {"summary": "x"}, "create_story")
        assert result["parent_key"] is None

    def test_no_summary_uses_work_type_for_hash_seed(self) -> None:
        result = stub_create_work_item("dev_task", {}, "create_dev_task")
        assert result["summary"] is None
        assert result["issue_key"].startswith("PM-")


class TestPmStubHandlers:
    def test_poll_jira_handler(self) -> None:
        assert PM_STUB_HANDLERS["poll_jira"]({})["status"] == "ok"

    def test_sync_jira_handler(self) -> None:
        assert PM_STUB_HANDLERS["sync_jira"]({})["status"] == "ok"

    def test_poll_airtable_handler(self) -> None:
        assert PM_STUB_HANDLERS["poll_airtable"]({})["status"] == "ok"

    def test_scan_risks_handler(self) -> None:
        assert PM_STUB_HANDLERS["scan_risks"]({})["status"] == "ok"

    def test_fetch_program_metrics_handler(self) -> None:
        assert PM_STUB_HANDLERS["fetch_program_metrics"]({})["status"] == "ok"

    def test_fetch_program_state_handler(self) -> None:
        assert PM_STUB_HANDLERS["fetch_program_state"]({})["status"] == "ok"

    def test_web_search_background_handler(self) -> None:
        assert PM_STUB_HANDLERS["web_search_background"]({})["status"] == "ok"

    def test_summarize_research_handler(self) -> None:
        assert PM_STUB_HANDLERS["summarize_research"]({})["status"] == "ok"

    def test_detect_blockers_handler(self) -> None:
        result = PM_STUB_HANDLERS["detect_blockers"]({})
        assert result == {"status": "ok", "blockers": [], "source": "stub"}

    def test_generate_exec_summary_handler(self) -> None:
        result = PM_STUB_HANDLERS["generate_exec_summary"]({})
        assert result["status"] == "ok"
        assert "summary" in result

    def test_create_initiative_handler_defaults_payload(self) -> None:
        result = PM_STUB_HANDLERS["create_initiative"](None)
        assert result["work_type"] == "initiative"
        assert result["capability"] == "create_initiative"

    def test_create_epic_handler(self) -> None:
        result = PM_STUB_HANDLERS["create_epic"]({"summary": "x"})
        assert result["work_type"] == "epic"

    def test_create_story_handler(self) -> None:
        result = PM_STUB_HANDLERS["create_story"]({"summary": "x"})
        assert result["work_type"] == "user_story"

    def test_create_dev_task_handler(self) -> None:
        result = PM_STUB_HANDLERS["create_dev_task"]({"summary": "x"})
        assert result["work_type"] == "dev_task"

    def test_create_subtask_handler(self) -> None:
        result = PM_STUB_HANDLERS["create_subtask"]({"summary": "x"})
        assert result["work_type"] == "subtask"
