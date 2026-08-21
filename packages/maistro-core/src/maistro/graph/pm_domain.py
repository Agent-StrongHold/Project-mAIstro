"""PM-fleet DAG domain — the v0 hyperagent shape.

Defines `PM_GRAPH_CONFIG`: a 6-node DAG `intake → program_manager →
(research ∥ risk_dependency ∥ delivery) → reporting`. Each capability is
a node; cross-agent data flow goes through `GraphBlackboard`. Built on
the maistro.graph substrate (conductor.py is left alone — engineering
keeps using it).

Per-capability prompt templates live here too, so the agent.yaml +
SOUL.md authoring can be iterated independently of node wiring. Day 5
adds `outcome_store.get_experience_context()` injection for the
self-improvement loop.
"""

from __future__ import annotations

from typing import Any

from maistro.graph.types import (
    DEFAULT_SYSTEM_PROMPTS,
    JSON_OUTPUT_SCHEMAS,
    AgentRole,
    GraphConfig,
    GraphEdge,
    NodeConfig,
)

PM_ROLES: tuple[AgentRole, ...] = (
    AgentRole.INTAKE,
    AgentRole.PROGRAM_MANAGER,
    AgentRole.RESEARCH,
    AgentRole.DELIVERY,
    AgentRole.RISK_DEPENDENCY,
    AgentRole.REPORTING,
)

# Per-capability prompt templates. The `{payload_json}` placeholder is
# filled at runtime with the user's request payload (initiative
# description, jira filters, etc). One node = one (role, capability)
# invocation; the role's DEFAULT_SYSTEM_PROMPT covers persona, the
# capability prompt covers what THIS turn produces.
PM_CAPABILITY_PROMPTS: dict[str, str] = {
    "create_initiative": (
        "Capability: create_initiative\n"
        "Produce an Initiative from the user request below. Required result fields:\n"
        "  title, summary, goals (list[str]), success_metrics (list[str]),\n"
        "  stakeholders (list[str]), draft_status: 'needs_confirm'.\n"
        "Unknown fields -> null. Never fabricate stakeholders or metrics.\n"
        "Payload:\n{payload_json}"
    ),
    "route_to_pm_agent": (
        "Capability: route_to_pm_agent\n"
        "Decide which PM sub-agent should handle this initiative next.\n"
        "Result fields: target_agent (one of program_manager|research|delivery|risk_dependency|reporting),\n"
        "  rationale (str), urgent (bool).\n"
        "Payload:\n{payload_json}"
    ),
    "decompose_initiative": (
        "Capability: decompose_initiative\n"
        "Break the initiative into epics + stories + dev_tasks. Result fields:\n"
        "  epics: list of {title, description, dependencies: list[str], stories: list[{title, description}]}\n"
        "Do not invent dependencies; if unknown, return [].\n"
        "Payload:\n{payload_json}"
    ),
    "web_search_background": (
        "Capability: web_search_background\n"
        "Identify the 3-5 most useful queries for understanding this initiative's\n"
        "context (industry, technical landscape, competitors). Result fields:\n"
        "  queries: list[str], hypotheses: list[str], note: str.\n"
        "If the browser tool is unavailable, return source='no_data' and explain in 'note'.\n"
        "Payload:\n{payload_json}"
    ),
    "summarize_research": (
        "Capability: summarize_research\n"
        "Synthesize the research findings from the blackboard into a 3-paragraph\n"
        "summary with citations. Result fields: summary (str), key_findings: list[str],\n"
        "citations: list[{title, url}]. Citations only from blackboard.scout_context;\n"
        "never invent URLs.\n"
        "Payload:\n{payload_json}"
    ),
    "poll_jira": (
        "Capability: poll_jira\n"
        "Return real Jira issues from the blackboard's tool-call result. Result fields:\n"
        "  issues: list[{key, summary, status, assignee}], total (int).\n"
        "If blackboard has no Jira data, return source='no_data' — never invent issues.\n"
        "Payload:\n{payload_json}"
    ),
    "sync_jira": (
        "Capability: sync_jira (DRAFT — does NOT post)\n"
        "Produce a Jira ticket draft. draft_status='needs_confirm' always.\n"
        "Result fields: project_key, issuetype, summary, description, labels.\n"
        "Payload:\n{payload_json}"
    ),
    "create_jira_ticket": (
        "Capability: create_jira_ticket (DRAFT — does NOT post)\n"
        "Same as sync_jira. draft_status='needs_confirm'. Human reviews before posting.\n"
        "Payload:\n{payload_json}"
    ),
    "detect_blockers": (
        "Capability: detect_blockers\n"
        "Identify blockers from the Jira data on the blackboard. Result fields:\n"
        "  blockers: list[{title, evidence, owner_guess, severity}].\n"
        "Each blocker must cite the Jira issue key it came from; no blocker without evidence.\n"
        "Payload:\n{payload_json}"
    ),
    "scan_risks": (
        "Capability: scan_risks\n"
        "Scan the blackboard (initiative + epics + Jira + research) for risks.\n"
        "Result fields: risks: list[{id, title, severity (low|med|high), mitigation, source}].\n"
        "'source' must reference a blackboard field — never a fabricated source.\n"
        "Payload:\n{payload_json}"
    ),
    "map_dependency": (
        "Capability: map_dependency\n"
        "Construct a dependency map between epics from the decomposition.\n"
        "Result fields: edges: list[{from_epic, to_epic, reason}].\n"
        "Payload:\n{payload_json}"
    ),
    "fetch_program_state": (
        "Capability: fetch_program_state\n"
        "Return the current program state as visible on the blackboard.\n"
        "Result fields: initiative (object), epics (list), open_jira_count (int|null),\n"
        "open_risks_count (int|null). Use null where data isn't available — never zero.\n"
        "Payload:\n{payload_json}"
    ),
    "fetch_program_metrics": (
        "Capability: fetch_program_metrics\n"
        "Return metrics extracted from the blackboard. Result fields:\n"
        "  metrics: list[{name, value, source}]. Each metric must cite source.\n"
        "If no data, return source='no_data' and an empty list.\n"
        "Payload:\n{payload_json}"
    ),
    "generate_exec_summary": (
        "Capability: generate_exec_summary\n"
        "Synthesize a 30-second executive summary from the blackboard.\n"
        "Result fields: headline (str, <12 words), status_color (green|amber|red),\n"
        "key_wins (list[str]), blockers (list[str]), next_actions (list[str]).\n"
        "Cite evidence for status_color (must point at blackboard data).\n"
        "Payload:\n{payload_json}"
    ),
    "publish_dashboard": (
        "Capability: publish_dashboard (DRAFT — does NOT publish)\n"
        "Build the dashboard payload. Result fields: title, sections (list), source_links.\n"
        "draft_status='needs_confirm'.\n"
        "Payload:\n{payload_json}"
    ),
}

# Each PM role's primary capability — used when the runtime hasn't been
# told a specific capability (e.g. early in a graph run).
PM_PRIMARY_CAPABILITY: dict[AgentRole, str] = {
    AgentRole.INTAKE: "create_initiative",
    AgentRole.PROGRAM_MANAGER: "decompose_initiative",
    AgentRole.RESEARCH: "web_search_background",
    AgentRole.DELIVERY: "poll_jira",
    AgentRole.RISK_DEPENDENCY: "scan_risks",
    AgentRole.REPORTING: "generate_exec_summary",
}


def build_capability_prompt(capability: str, payload: dict[str, Any]) -> str:
    """Inject payload into the capability prompt template.

    Templates use the literal sentinel ``{payload_json}`` (str.replace,
    not str.format) so that JSON-shape examples inside the templates —
    which contain unescaped curly braces — don't blow up the formatter.
    """
    import json as _json

    template = PM_CAPABILITY_PROMPTS.get(capability)
    payload_json = _json.dumps(payload, indent=2)
    if template is None:
        return (
            f"Capability: {capability} (no template registered)\n"
            "Produce a PMRoleOutput JSON for this capability based on the payload.\n"
            f"Payload:\n{payload_json}"
        )
    return template.replace("{payload_json}", payload_json)


def build_pm_graph_config(
    *,
    max_cycles: int = 1,
    per_role_temperature: dict[AgentRole, float] | None = None,
) -> GraphConfig:
    """Construct the PM v0 DAG.

    Topology:
        INTAKE → PROGRAM_MANAGER ─┬→ RESEARCH ─────┐
                                  ├→ RISK_DEPENDENCY ┤→ REPORTING
                                  └→ DELIVERY ─────┘
    """
    per_role_temperature = per_role_temperature or {}
    node_configs = {
        role: NodeConfig(
            role=role,
            system_prompt=DEFAULT_SYSTEM_PROMPTS[role] + JSON_OUTPUT_SCHEMAS[role],
            temperature=per_role_temperature.get(role, 0.2),
            beam_width=1,
        )
        for role in PM_ROLES
    }
    edges = [
        GraphEdge(from_role=AgentRole.INTAKE, to_role=AgentRole.PROGRAM_MANAGER),
        GraphEdge(from_role=AgentRole.PROGRAM_MANAGER, to_role=AgentRole.RESEARCH, parallel=True),
        GraphEdge(
            from_role=AgentRole.PROGRAM_MANAGER, to_role=AgentRole.RISK_DEPENDENCY, parallel=True
        ),
        GraphEdge(from_role=AgentRole.PROGRAM_MANAGER, to_role=AgentRole.DELIVERY, parallel=True),
        GraphEdge(from_role=AgentRole.RESEARCH, to_role=AgentRole.REPORTING),
        GraphEdge(from_role=AgentRole.RISK_DEPENDENCY, to_role=AgentRole.REPORTING),
        GraphEdge(from_role=AgentRole.DELIVERY, to_role=AgentRole.REPORTING),
    ]
    return GraphConfig(
        nodes=list(PM_ROLES),
        edges=edges,
        entry=AgentRole.INTAKE,
        hyperagent=AgentRole.INTAKE,
        max_cycles=max_cycles,
        node_configs=node_configs,
        use_llm_routing=False,
        run_scout=False,
    )


__all__ = [
    "PM_CAPABILITY_PROMPTS",
    "PM_PRIMARY_CAPABILITY",
    "PM_ROLES",
    "build_capability_prompt",
    "build_pm_graph_config",
]
