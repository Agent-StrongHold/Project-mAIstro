"""PM capability policy tests."""

from __future__ import annotations

from maistro.agents.pm_capabilities import (
    autonomous_pulse_candidates,
    capability_for_work_item,
    is_autonomous,
    is_gated,
    normalize_capability,
)


def test_autonomous_vs_gated() -> None:
    assert is_autonomous("poll_jira")
    assert is_autonomous("poll_airtable")
    assert is_autonomous("scan_risks")
    assert is_autonomous("web_search_background")
    assert is_autonomous("summarize_research")
    assert not is_autonomous("create_initiative")
    assert is_gated("create_initiative")
    assert is_gated("create_epic")
    assert is_gated("create_subtask")


def test_normalize_sync_jira() -> None:
    assert normalize_capability("sync_jira") == "poll_jira"
    assert is_autonomous("sync_jira")


def test_work_item_capabilities() -> None:
    assert capability_for_work_item("user_story") == "create_story"
    assert capability_for_work_item("dev_task") == "create_dev_task"


def test_pulse_candidates_include_jira_when_configured() -> None:
    with_jira = autonomous_pulse_candidates(["Jira", "Confluence"])
    caps = {c for c, _ in with_jira}
    assert "poll_jira" in caps
    assert "web_search_background" in caps
    with_air = autonomous_pulse_candidates(["Airtable"])
    assert any(c == "poll_airtable" for c, _ in with_air)


def test_a_candidate_names_work_and_not_an_agent() -> None:
    """Since #221 the pulse proposes a capability and the caller's roster says
    who does it. Carrying an agent name here is what made every workspace get
    PM Fleet's roster regardless of the persona it runs."""
    for candidate in autonomous_pulse_candidates([]):
        assert len(candidate) == 2
    assert all(is_autonomous(cap) for cap, _ in autonomous_pulse_candidates(["Jira"]))
