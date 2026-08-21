"""PM fleet agent definitions for research/pm-fleet-poc."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.catalog import AgentCard, AgentCatalog

PM_AGENT_NAMES = frozenset(
    {"intake", "program_manager", "delivery", "risk_dependency", "reporting", "research"}
)


@dataclass(frozen=True)
class PmAgentDef:
    name: str
    display_name: str
    tagline: str
    capabilities: tuple[str, ...]
    primary_capability: str
    primary_action_label: str
    task_type: str
    sub_agents: tuple[str, ...] = ()

    @property
    def agent_id(self) -> str:
        return self.name


PM_FLEET: tuple[PmAgentDef, ...] = (
    PmAgentDef(
        name="intake",
        display_name="Intake Agent",
        tagline="The Front Door to Structured Execution",
        capabilities=("create_initiative", "route_to_pm_agent"),
        primary_capability="route_to_pm_agent",
        primary_action_label="Propose Initiative",
        task_type="intake",
        sub_agents=("program_manager",),
    ),
    PmAgentDef(
        name="program_manager",
        display_name="Program Manager Agent",
        tagline="Staff-Level TPM That Never Sleeps",
        capabilities=(
            "decompose_initiative",
            "create_epic",
            "create_story",
            "create_dev_task",
            "poll_airtable",
            "link_dependency",
            "fetch_program_state",
        ),
        primary_capability="fetch_program_state",
        primary_action_label="Fetch Program State",
        task_type="program_management",
        sub_agents=("delivery", "risk_dependency", "research"),
    ),
    PmAgentDef(
        name="research",
        display_name="Research Agent",
        tagline="Web search for program background, market context, and technical landscape",
        capabilities=(
            "web_search_background",
            "summarize_research",
            "fetch_program_state",
        ),
        primary_capability="web_search_background",
        primary_action_label="Search Background",
        task_type="research",
    ),
    PmAgentDef(
        name="delivery",
        display_name="Delivery Agent",
        tagline="Execution Engine for Sprint Velocity",
        capabilities=(
            "poll_jira",
            "sync_jira",
            "create_jira_ticket",
            "create_subtask",
            "detect_blockers",
        ),
        primary_capability="poll_jira",
        primary_action_label="Poll Jira",
        task_type="delivery",
    ),
    PmAgentDef(
        name="risk_dependency",
        display_name="Risk & Dependency Agent",
        tagline="Your Always-On RAID Brain",
        capabilities=(
            "create_raid_entry",
            "scan_risks",
            "map_dependency",
            "fetch_dependency_graph",
            "escalate_issue",
        ),
        primary_capability="scan_risks",
        primary_action_label="Scan Risks",
        task_type="risk",
    ),
    PmAgentDef(
        name="reporting",
        display_name="Reporting Agent",
        tagline="Executive Visibility in Under 30 Seconds",
        capabilities=(
            "generate_exec_summary",
            "fetch_program_metrics",
            "publish_dashboard",
        ),
        primary_capability="generate_exec_summary",
        primary_action_label="Generate Summary",
        task_type="reporting",
    ),
)

_CAPABILITY_TO_AGENT: dict[str, str] = {}
for _defn in PM_FLEET:
    for cap in _defn.capabilities:
        _CAPABILITY_TO_AGENT[cap] = _defn.name


def get_pm_def(agent_id: str) -> PmAgentDef | None:
    for defn in PM_FLEET:
        if defn.name == agent_id or agent_id.startswith(defn.name):
            return defn
    return None


def build_task_description(
    agent_id: str, capability: str, payload: dict[str, Any]
) -> tuple[str, str]:
    """Return (task_type, description) for TaskCreate."""
    defn = get_pm_def(agent_id)
    if defn is None:
        raise ValueError(f"Unknown PM agent: {agent_id}")
    if capability not in defn.capabilities:
        raise ValueError(f"Capability {capability!r} not valid for {agent_id}")
    title = str(payload.get("title", capability.replace("_", " ")))
    summary = str(payload.get("summary", ""))
    program = payload.get("program") or {}
    if isinstance(program, dict) and program.get("program_name") and not title:
        title = str(program["program_name"])
    desc = f"[{defn.display_name}] {capability}: {title}"
    if summary:
        desc = f"{desc} — {summary}"
    elif isinstance(program, dict) and program.get("summary"):
        desc = f"{desc} — {program['summary']}"
    reason = payload.get("hyperagent_reason")
    if reason:
        desc = f"{desc} (why: {reason})"
    return defn.task_type, desc


def register_pm_fleet(catalog: AgentCatalog) -> None:
    for defn in PM_FLEET:
        catalog.register(
            AgentCard(
                id=defn.name,
                name=defn.display_name,
                description=defn.tagline,
                reasoning_strategy="direct",
                tools=(),
                skills=defn.capabilities,
                delegation_mode="selective" if defn.sub_agents else "none",
                sub_agents=defn.sub_agents,
                scope="builtin",
            )
        )


def fleet_card_dict(defn: PmAgentDef, status: str = "idle") -> dict[str, Any]:
    return {
        "id": defn.name,
        "name": defn.display_name,
        "tagline": defn.tagline,
        "status": status,
        "capabilities": list(defn.capabilities),
        "primary_capability": defn.primary_capability,
        "primary_action_label": defn.primary_action_label,
    }


def agent_status_for_user(
    defn: PmAgentDef,
    tasks: list[Any],
) -> str:
    """Derive idle/running/error from in-flight tasks matching agent task_type."""
    matching = [
        t
        for t in tasks
        if getattr(t, "task_type", None) == defn.task_type
        or defn.name in (getattr(t, "description", "") or "")
    ]
    terminal = frozenset({"completed", "failed", "cancelled"})
    for t in matching:
        st = getattr(t.status, "value", str(t.status))
        if st not in terminal:
            return "running"
    for t in matching:
        st = getattr(t.status, "value", str(t.status))
        if st == "failed":
            return "error"
    return "idle"
