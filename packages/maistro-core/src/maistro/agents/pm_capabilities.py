"""PM capability policy — autonomous polls/scans vs gated Jira writes."""

from __future__ import annotations

from typing import Literal

WorkItemType = Literal["initiative", "epic", "user_story", "dev_task", "subtask"]

# Read-only / sync — hyperagent may queue without user approval.
AUTONOMOUS_CAPABILITIES: frozenset[str] = frozenset(
    {
        "poll_jira",
        "sync_jira",  # alias
        "poll_airtable",
        "scan_risks",
        "fetch_program_state",
        "fetch_program_metrics",
        "fetch_dependency_graph",
        "detect_blockers",
        "generate_exec_summary",
        "map_dependency",
        "route_to_pm_agent",
        "web_search_background",
        "summarize_research",
    }
)

# Writes to external systems — suggest → clarify → edit → confirm only.
GATED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "create_initiative",
        "create_epic",
        "create_story",
        "create_user_story",
        "create_dev_task",
        "create_subtask",
        "create_jira_ticket",
        "create_raid_entry",
        "decompose_initiative",
        "link_dependency",
        "escalate_issue",
        "publish_dashboard",
    }
)

WORK_ITEM_TO_CAPABILITY: dict[WorkItemType, str] = {
    "initiative": "create_initiative",
    "epic": "create_epic",
    "user_story": "create_story",
    "dev_task": "create_dev_task",
    "subtask": "create_subtask",
}

CAPABILITY_TO_WORK_ITEM: dict[str, WorkItemType] = {
    "create_initiative": "initiative",
    "create_epic": "epic",
    "create_story": "user_story",
    "create_user_story": "user_story",
    "create_dev_task": "dev_task",
    "create_subtask": "subtask",
}

WORK_ITEM_PARENT: dict[WorkItemType, WorkItemType | None] = {
    "initiative": None,
    "epic": "initiative",
    "user_story": "epic",
    "dev_task": "user_story",
    "subtask": "dev_task",
}

WORK_ITEM_LABELS: dict[WorkItemType, str] = {
    "initiative": "Initiative",
    "epic": "Epic",
    "user_story": "User Story",
    "dev_task": "Development Task",
    "subtask": "Sub-task",
}


def normalize_capability(capability: str) -> str:
    if capability == "sync_jira":
        return "poll_jira"
    if capability == "create_user_story":
        return "create_story"
    return capability


def is_autonomous(capability: str) -> bool:
    return normalize_capability(capability) in AUTONOMOUS_CAPABILITIES


def is_gated(capability: str) -> bool:
    cap = normalize_capability(capability)
    return cap in GATED_CAPABILITIES or cap in CAPABILITY_TO_WORK_ITEM


def capability_for_work_item(work_type: WorkItemType) -> str:
    return WORK_ITEM_TO_CAPABILITY[work_type]


def agent_for_work_item(work_type: WorkItemType) -> str:
    mapping = {
        "initiative": "intake",
        "epic": "program_manager",
        "user_story": "program_manager",
        "dev_task": "delivery",
        "subtask": "delivery",
    }
    return mapping[work_type]


def autonomous_pulse_candidates(ctx_tools: list[str]) -> list[tuple[str, str, str]]:
    """Return (agent_id, capability, reason) tuples safe to auto-run."""
    candidates: list[tuple[str, str, str]] = [
        ("program_manager", "fetch_program_state", "Refresh program state from context"),
        ("risk_dependency", "scan_risks", "Continuous RAID scan"),
        ("reporting", "generate_exec_summary", "Exec visibility snapshot"),
    ]
    tools_lower = " ".join(ctx_tools).lower()
    if "jira" in tools_lower:
        candidates.insert(0, ("delivery", "poll_jira", "Poll Jira for execution updates"))
    if "airtable" in tools_lower:
        candidates.insert(
            1 if "jira" in tools_lower else 0,
            ("program_manager", "poll_airtable", "Poll Airtable for planning data"),
        )
    candidates.append(
        (
            "research",
            "web_search_background",
            "Gather web background on program domain, goals, and risks",
        )
    )
    return candidates
