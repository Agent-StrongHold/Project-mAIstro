"""Stub PM tool responses for fleet POC demos (no external Jira/RAID calls)."""

from __future__ import annotations

from typing import Any


def stub_sync_jira(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return stub_poll_jira(payload)


def stub_poll_jira(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "status": "ok",
        "synced": 5,
        "blockers_found": 1,
        "sprints_active": 2,
        "source": "stub",
        "payload": payload,
    }


def stub_poll_airtable(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "status": "ok",
        "records_synced": 12,
        "tables": ["Roadmap", "Capacity", "RAID"],
        "source": "stub",
        "payload": payload,
    }


def stub_scan_risks(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "risks": [
            {"id": "R-101", "title": "Vendor API latency", "severity": "medium"},
            {"id": "R-102", "title": "Cross-team dependency slip", "severity": "high"},
        ],
        "source": "stub",
    }


def stub_fetch_program_metrics(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "velocity": 42,
        "burn_down_pct": 68,
        "open_blockers": 2,
        "source": "stub",
    }


def stub_web_search_background(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Simulate web search for program background (POC — no live HTTP)."""
    payload = payload or {}
    program = payload.get("program") or {}
    if not isinstance(program, dict):
        program = {}
    name = str(program.get("program_name") or payload.get("title") or "program initiative")
    goals = program.get("goals") or []
    goal_hint = str(goals[0]) if goals else "delivery outcomes"
    query = f"{name} {goal_hint} industry context risks best practices"
    return {
        "status": "ok",
        "query": query[:200],
        "results_count": 3,
        "sources": [
            {
                "title": f"{name}: market and delivery patterns",
                "url": "https://example.com/research/background-1",
                "snippet": "Peer programs emphasize phased rollout and explicit dependency mapping.",
            },
            {
                "title": f"Risks relevant to {goal_hint[:60]}",
                "url": "https://example.com/research/risks",
                "snippet": "Common blockers include vendor lead times and cross-team API contracts.",
            },
            {
                "title": "Regulatory and security considerations",
                "url": "https://example.com/research/compliance",
                "snippet": "Enterprise programs typically require audit trails on external integrations.",
            },
        ],
        "summary": (
            f"Background scan for '{name}': three relevant themes — delivery patterns, "
            "dependency risks, and compliance expectations. Use before drafting initiatives."
        ),
        "source": "stub",
    }


def stub_summarize_research(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    prior = payload.get("research") or payload.get("sources") or []
    count = len(prior) if isinstance(prior, list) else 0
    return {
        "status": "ok",
        "bullets": [
            "Align initiative scope with proven phased-delivery patterns.",
            "Track vendor and API dependencies in RAID early.",
            "Document integration touchpoints for audit readiness.",
        ],
        "sources_used": count or 3,
        "source": "stub",
    }


def stub_fetch_program_state(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    program = payload.get("program") or {}
    name = program.get("program_name") or payload.get("program") or "Program"
    goals = program.get("goals") or []
    return {
        "status": "ok",
        "program": name,
        "goals_tracked": len(goals) or 3,
        "initiatives": max(1, len(goals)),
        "epics_in_flight": 12,
        "stories_done": 87,
        "learned_from_user": bool(program),
        "source": "stub",
    }


def stub_create_work_item(
    work_type: str,
    fields: dict[str, Any],
    capability: str,
) -> dict[str, Any]:
    """Simulate Jira POST after user-confirmed draft."""
    project = fields.get("project_key") or "PM"
    parent = fields.get("parent_key")
    seq = abs(hash(fields.get("summary", work_type))) % 900 + 100
    key = f"{project}-{seq}"
    return {
        "status": "ok",
        "issue_key": key,
        "work_type": work_type,
        "capability": capability,
        "parent_key": parent,
        "summary": fields.get("summary"),
        "posted_to": "jira",
        "source": "stub",
    }


PM_STUB_HANDLERS: dict[str, Any] = {
    "poll_jira": stub_poll_jira,
    "sync_jira": stub_sync_jira,
    "poll_airtable": stub_poll_airtable,
    "scan_risks": stub_scan_risks,
    "fetch_program_metrics": stub_fetch_program_metrics,
    "fetch_program_state": stub_fetch_program_state,
    "web_search_background": stub_web_search_background,
    "summarize_research": stub_summarize_research,
    "detect_blockers": lambda p: {"status": "ok", "blockers": [], "source": "stub"},
    "generate_exec_summary": lambda p: {
        "status": "ok",
        "summary": "Program on track; two medium risks under review.",
        "source": "stub",
    },
    "create_initiative": lambda p: stub_create_work_item(
        "initiative", p or {}, "create_initiative"
    ),
    "create_epic": lambda p: stub_create_work_item("epic", p or {}, "create_epic"),
    "create_story": lambda p: stub_create_work_item("user_story", p or {}, "create_story"),
    "create_dev_task": lambda p: stub_create_work_item("dev_task", p or {}, "create_dev_task"),
    "create_subtask": lambda p: stub_create_work_item("subtask", p or {}, "create_subtask"),
}
