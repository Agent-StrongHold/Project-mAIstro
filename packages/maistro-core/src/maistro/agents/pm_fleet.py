"""PM Fleet routing metadata backed by the canonical Persona template (#39).

Reusable agent-definition data lives in ``personas/templates/pm_fleet.yaml``.
This module retains only PM-product routing/presentation facts that do not yet
have a canonical owner, and projects the Persona spawns into ``AgentCard`` at
the existing catalog boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from maistro.agents.catalog import AgentCard, AgentCatalog
from maistro.personas.rubric import load_template
from maistro.personas.schema import PersonaTemplate, SpawnSpec

_PM_FLEET_TEMPLATE_PATH = Path(__file__).parents[1] / "personas" / "templates" / "pm_fleet.yaml"


@dataclass(frozen=True)
class PmAgentDef:
    """PM-product routing/presentation data for one canonical Persona spawn.

    Role/tagline, capabilities, tools and reasoning strategy are intentionally
    not stored here. They are reusable agent-definition facts and therefore
    come from the canonical ``pm_fleet`` Persona template.
    """

    name: str
    display_name: str
    primary_capability: str
    primary_action_label: str
    task_type: str
    sub_agents: tuple[str, ...] = ()

    @property
    def agent_id(self) -> str:
        return self.name

    @property
    def tagline(self) -> str:
        return _spawn_for(self.name).role

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(_spawn_for(self.name).skills)

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(_spawn_for(self.name).tools)

    @property
    def reasoning_strategy(self) -> str:
        return _spawn_for(self.name).reasoning_strategy


PM_FLEET: tuple[PmAgentDef, ...] = (
    PmAgentDef(
        name="intake",
        display_name="Intake Agent",
        primary_capability="route_to_pm_agent",
        primary_action_label="Propose Initiative",
        task_type="intake",
        sub_agents=("program_manager",),
    ),
    PmAgentDef(
        name="program_manager",
        display_name="Program Manager Agent",
        primary_capability="fetch_program_state",
        primary_action_label="Fetch Program State",
        task_type="program_management",
        sub_agents=("delivery", "risk_dependency", "research"),
    ),
    PmAgentDef(
        name="research",
        display_name="Research Agent",
        primary_capability="web_search_background",
        primary_action_label="Search Background",
        task_type="research",
    ),
    PmAgentDef(
        name="delivery",
        display_name="Delivery Agent",
        primary_capability="poll_jira",
        primary_action_label="Poll Jira",
        task_type="delivery",
    ),
    PmAgentDef(
        name="risk_dependency",
        display_name="Risk & Dependency Agent",
        primary_capability="scan_risks",
        primary_action_label="Scan Risks",
        task_type="risk",
    ),
    PmAgentDef(
        name="reporting",
        display_name="Reporting Agent",
        primary_capability="generate_exec_summary",
        primary_action_label="Generate Summary",
        task_type="reporting",
    ),
)

_ROUTE_BY_NAME = {defn.name: defn for defn in PM_FLEET}
PM_AGENT_NAMES = frozenset(_ROUTE_BY_NAME)


def _validate_pm_fleet_persona(template: PersonaTemplate) -> PersonaTemplate:
    """Fail closed when canonical Persona data and transitional routing drift."""
    if template.kind != "workspace" or template.id != "pm_fleet":
        raise RuntimeError("Canonical PM Fleet Persona must be kind='workspace' with id='pm_fleet'")

    spawn_names = [spawn.agent for spawn in template.spawns]
    if len(spawn_names) != len(set(spawn_names)):
        raise RuntimeError("Canonical PM Fleet Persona contains duplicate agent spawns")

    canonical_names = set(spawn_names)
    routing_names = set(_ROUTE_BY_NAME)
    if canonical_names != routing_names:
        missing_routing = sorted(canonical_names - routing_names)
        missing_persona = sorted(routing_names - canonical_names)
        raise RuntimeError(
            "PM Fleet Persona/routing roster drift: "
            f"missing routing={missing_routing}, missing persona={missing_persona}"
        )

    spawns = {spawn.agent: spawn for spawn in template.spawns}
    for name, defn in _ROUTE_BY_NAME.items():
        if defn.primary_capability not in spawns[name].skills:
            raise RuntimeError(
                f"PM Fleet primary capability {defn.primary_capability!r} for {name!r} "
                "is absent from the canonical Persona spawn skills"
            )
    return template


@lru_cache(maxsize=1)
def _pm_fleet_persona() -> PersonaTemplate:
    """Load the one reusable PM Fleet definition authority once per process."""
    try:
        template = load_template(_PM_FLEET_TEMPLATE_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot load canonical PM Fleet Persona template: {_PM_FLEET_TEMPLATE_PATH}"
        ) from exc
    return _validate_pm_fleet_persona(template)


def _spawn_for(agent_id: str) -> SpawnSpec:
    for spawn in _pm_fleet_persona().spawns:
        if spawn.agent == agent_id:
            return spawn
    raise RuntimeError(f"Canonical PM Fleet Persona has no spawn for {agent_id!r}")


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
    agent_id: str,
    capability: str,
    payload: dict[str, Any],
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
    """Register the Persona-defined PM roster through the existing catalog."""
    for spawn in _pm_fleet_persona().spawns:
        defn = _ROUTE_BY_NAME[spawn.agent]
        catalog.register(
            AgentCard(
                id=spawn.agent,
                name=defn.display_name,
                description=spawn.role,
                reasoning_strategy=spawn.reasoning_strategy,
                tools=tuple(spawn.tools),
                skills=tuple(spawn.skills),
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


def agent_status_for_user(defn: PmAgentDef, tasks: list[Any]) -> str:
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
