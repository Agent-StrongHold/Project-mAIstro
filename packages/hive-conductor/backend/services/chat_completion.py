"""PM Fleet chat completion — real PM agent with real tools.

This is not a generic chatbot. It knows your program, has access to your
Jira/Confluence via stored credentials, and can take real actions.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from adapters.llm_http import HttpOpenAIProtocolLLM, StubLLMPort
from config import get_settings
from models.schemas import ChatCompletionRequest
from protocols.llm import LLMPort

from maistro.http import shared_client
from services.airtable_cache import get_airtable_base_tables_json, get_airtable_records_json
from services.secrets import litellm_api_key as _resolve_litellm_api_key
from services.tool_primitives import (
    AIRTABLE_PROVIDER_IDS,
    CONFLUENCE_PROVIDER_IDS,
    JIRA_PROVIDER_IDS,
    ToolCallContext,
    ToolCredentialResolver,
)

logger = logging.getLogger("hive.chat")


def build_llm_port() -> LLMPort:
    s = get_settings()
    base = os.environ.get("LITELLM_API_BASE") or (s.litellm_api_base or "").strip()
    key = _resolve_litellm_api_key(s) or os.environ.get("LITELLM_PROXY_KEY")
    if not base:
        base = os.environ.get("LITELLM_PROXY_URL")
    if not base or not key:
        return StubLLMPort()
    return HttpOpenAIProtocolLLM(base_url=base, api_key=key, variant=s.llm_http_variant)


def conversation_only(req: ChatCompletionRequest) -> ChatCompletionRequest:
    """Return a request that cannot advertise or carry tool capabilities.

    `ChatCompletionRequest` allows extra fields because several UIs attach
    presentation metadata such as `tools_scope`. Those extras are intentionally
    discarded at this trust boundary so a caller cannot smuggle a tool-enabled
    mode into the raw LLM request. The user's messages/sampling controls remain
    intact, and an omitted model resolves through the configured deployment
    default just as it did before containment.

    It lives beside `build_llm_port` rather than in a route module because two
    routes need it: chat's `/complete` and `/stream`, and voice's `/intent`
    (#440). A containment rule that each caller restates is a containment rule
    that eventually differs between callers.
    """
    return ChatCompletionRequest(
        messages=req.messages,
        model=req.model or get_settings().chat_default_model,
        stream=False,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        tools=None,
    )


def _get_program_context(user_id: str) -> dict[str, Any]:
    """Load the user's program context for system prompt injection."""
    try:
        from services import program_store as prog

        ctx = prog.get_context(user_id)
        return {
            "program_name": ctx.program_name,
            "goals": ctx.goals,
            "tools": ctx.tools,
            "constraints": ctx.constraints,
            "stakeholders": ctx.stakeholders,
            "summary": ctx.summary,
            "recent_guidance": ctx.guidance_log[-3:],
        }
    except Exception:
        return {}


def _get_jira_pat(user_id: str) -> str | None:
    """Pull Jira PAT from env (CI/CD) or encrypted credential store."""
    import os

    env_pat = os.environ.get("JIRA_PAT") or os.environ.get("ATLASSIAN_API_TOKEN")
    if env_pat:
        return env_pat
    try:
        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if store is None:
            return None
        resolver = ToolCredentialResolver(store)
        return resolver.first_secret(ToolCallContext(user_id), JIRA_PROVIDER_IDS)
    except Exception:
        return None


def _get_airtable_creds(user_id: str) -> tuple[str | None, str | None]:  # noqa: C901  layered credential fallbacks
    """Pull Airtable token + base_id from env (CI/CD) or credential store."""
    import os

    env_token = os.environ.get("AIRTABLE_TOKEN") or os.environ.get("AIRTABLE_API_KEY")
    env_base = os.environ.get("AIRTABLE_BASE_ID")
    if env_token:
        return env_token, env_base or ""
    try:
        import stores

        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if store is None:
            return None, None
        context = ToolCallContext(user_id)
        resolver = ToolCredentialResolver(store)
        token = resolver.first_secret(context, AIRTABLE_PROVIDER_IDS, include_dev_fallback=True)
        if not token:
            return None, None
        # base_id is in user_provider_config — try multiple user_id patterns
        base_id = ""
        for uid in context.candidate_user_ids(include_dev_fallback=True):
            config_raw = stores.user_provider_config.get(f"{uid}:airtable")
            if isinstance(config_raw, dict) and config_raw.get("base_id"):
                base_id = config_raw["base_id"]
                break
        # If still not found, scan all keys for any airtable config
        if not base_id:
            for key in stores.user_provider_config:
                if key.endswith(":airtable"):
                    val = stores.user_provider_config.get(key)
                    if isinstance(val, dict) and val.get("base_id"):
                        base_id = val["base_id"]
                        break
        return token, base_id.split("/")[0] if base_id else ""
    except Exception:
        return None, None


def _build_system_prompt(user_id: str) -> str:  # noqa: C901  many optional prompt sections
    """Build a PM-specific system prompt with program context."""
    from datetime import UTC, datetime

    ctx = _get_program_context(user_id)
    today = datetime.now(UTC).strftime("%A, %B %d, %Y")
    base = (
        f"Today's date is {today}. Your training data has a knowledge cutoff well before this date — "
        "treat anything you'd otherwise call 'upcoming' or 'in the future' as something that may have already "
        "happened, and use web_search to check rather than assuming your training data is current. "
        "You are a Fantasia orchestration assistant — an AI that helps conduct agent workflows. "
        "You have general-purpose tools: web_search and browse_url (live web — use these for anything that "
        "could be outdated: current events, recent results, prices, schedules, fast-moving docs), "
        "agent management (create/modify/remove/list_agent_buttons), "
        "runtime metrics (query_metrics — latency p50/p95/p99, TTFT, tokens, cost, success rate), "
        "memory (memory_add, memory_search, memory_delete — persistent knowledge base), "
        "profile (profile_get, profile_set, profile_delete — structured user profile), "
        "workflows (list_workflows, create_workflow, run_workflow, update_eval — DAG execution and hill-climbing), "
        "and dashboard widgets (create_dashboard_widget). "
        "You ALSO have integration tools — Jira (poll_jira, search_jira, get_issue, check_blockers), "
        "Confluence (search_confluence), and Airtable (airtable_query) — but these only work if the user has "
        "connected those services under Credentials; if a call returns a 'not configured' error, tell the user "
        "plainly and move on instead of retrying. Only reach for Jira/Confluence/Airtable when the user's "
        "question is actually about their connected project-tracking data (sprints, tickets, blockers, a "
        "specific Airtable base) — for general research or open-ended questions, use web_search instead, or "
        "memory_search if it's something you'd have saved earlier. "
        "When the user asks about performance, latency, TTFT, cost, or runtime data — use query_metrics. "
        "When they tell you something about themselves, their project, or preferences — use profile_set to save it. "
        "When you need context about the user or project — use profile_get first. "
        "For freeform notes/facts that don't fit profile fields — use memory_add. "
        "When they ask to forget something — use memory_delete or profile_delete. "
        "When they correct you — infer the preference and update the profile. "
        "When they ask about Jira issues or blockers — use the Jira tools. "
        "When they ask to create or modify agents — use the agent tools. "
        "Be agent/DAG/workflow-forward: chat is the entry point, not the destination. When a request is "
        "multi-step, will recur, or could be handed off, don't just answer once — propose wrapping it as a "
        "reusable agent (create_agent_button) or a DAG workflow (create_workflow, then run_workflow), and do it "
        "if the user agrees. Check list_agent_buttons / list_workflows first so you reuse or extend what "
        "already exists instead of duplicating it. "
        "Be concise and actionable. Never say you can't do something if you have a tool for it, "
        "unless that tool requires a connection the user hasn't configured. "
        "You ARE the dashboard — you can read and surface any data the system tracks."
    )
    # Inject cached profile
    profile = _PROFILE_CACHE.get(user_id)
    if profile:
        filled = {k: v for k, v in profile.items() if v}
        if filled:
            base += "\n\nUser profile:"
            for k, v in filled.items():
                base += f"\n- {k}: {v}"
    if ctx.get("program_name"):
        base += f"\n\nProgram: {ctx['program_name']}"
    if ctx.get("goals"):
        base += f"\nGoals: {', '.join(ctx['goals'])}"
    if ctx.get("tools"):
        base += f"\nTeam tools: {', '.join(ctx['tools'])}"
    if ctx.get("stakeholders"):
        base += f"\nStakeholders: {', '.join(ctx['stakeholders'])}"
    if ctx.get("constraints"):
        base += f"\nConstraints: {', '.join(ctx['constraints'])}"
    if ctx.get("recent_guidance"):
        base += "\n\nRecent PM guidance (use this to shape priorities):"
        for g in ctx["recent_guidance"]:
            base += f"\n- {g}"
    return base


PM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "poll_jira",
            "description": "Get issues assigned to the current user from Jira. Use when they ask about their work, sprint, or tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Max issues to return (default 20)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_jira",
            "description": "Search Jira with a JQL query or text. Use for specific queries like blockers, sprint issues, or project-scoped searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "jql": {
                        "type": "string",
                        "description": "JQL query (e.g. 'status = Blocked AND assignee = currentUser()')",
                    },
                    "text": {
                        "type": "string",
                        "description": "Free text search (alternative to JQL)",
                    },
                    "max_results": {"type": "integer", "description": "Max results (default 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_issue",
            "description": "Get full details of a specific Jira issue by key (e.g. PROJ-123).",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key like PROJ-123"},
                },
                "required": ["issue_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_blockers",
            "description": "Find blocked or at-risk issues. Use when user asks about blockers, risks, or what's stuck.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max results (default 25)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_confluence",
            "description": "Search Confluence for documentation, specs, or meeting notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_as_action",
            "description": "Save the current action as a reusable agent. Use when the user says 'save that', 'do this again', 'every morning', etc. Pass the capability that was just used (e.g. poll_jira, check_blockers, search_jira, search_confluence, generate_exec_summary).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for the button (e.g. 'Morning Standup Poll', 'Blocker Alert')",
                    },
                    "description": {
                        "type": "string",
                        "description": "What this button does when clicked",
                    },
                    "capability": {
                        "type": "string",
                        "description": "The tool to run when clicked: poll_jira, check_blockers, search_jira, search_confluence, or generate_exec_summary",
                    },
                },
                "required": ["name", "capability"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_agent_button",
            "description": "Create a new agent. Use when the user wants to add a new capability, save a workflow as a reusable agent, or create a recurring action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name (e.g. 'Sprint Check', 'Blocker Alert')",
                    },
                    "description": {"type": "string", "description": "What this agent does"},
                    "capability": {
                        "type": "string",
                        "description": "The tool to run: poll_jira, search_jira, check_blockers, search_confluence",
                    },
                    "payload": {
                        "type": "object",
                        "description": 'Default arguments (e.g. {"jql": "project = DEMO AND status = Blocked"})',
                    },
                },
                "required": ["name", "capability"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_agent_button",
            "description": "Modify an existing agent. Use when user says 'rename it', 'change the query', 'update the description'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to modify (use list_agents to find it)",
                    },
                    "name": {"type": "string", "description": "New name (optional)"},
                    "description": {"type": "string", "description": "New description (optional)"},
                    "capability": {"type": "string", "description": "New capability (optional)"},
                    "payload": {
                        "type": "object",
                        "description": "New default arguments (optional)",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_agent_button",
            "description": "Remove an agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "ID of the agent to remove"},
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agent_buttons",
            "description": "List all current agents. Use to find IDs for modification.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "Query runtime metrics from the orchestration engine. Returns latency percentiles (p50/p95/p99), TTFT, token counts, cost, success rate. Use for any observability/performance questions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_dashboard_widget",
            "description": "Add a new widget to the user's dashboard. Types: kpi, jira, agent-orbs, invocations, cost-donut, trace, custom. For jira: config must have {project, status?, days?, assignee?, jql_extra?, jira_display: 'count'|'list'|'status-breakdown'}. For custom: set query for free-form data. For kpi: config has {field, sub}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Widget display title"},
                    "type": {
                        "type": "string",
                        "description": "Widget type: kpi, jira, agent-orbs, invocations, cost-donut, trace, custom",
                    },
                    "size": {"type": "string", "description": "Column span: 1, 2, 3, 4, 5, or 6"},
                    "config": {
                        "type": "object",
                        "description": "Widget config. For jira: {project, status, days, assignee, jql_extra, jira_display}. For kpi: {field, sub}. For custom: {source, table, filter_formula} or {endpoint, params}.",
                    },
                    "tab": {
                        "type": "string",
                        "description": "Tab name to add to. If tab doesn't exist it will be created. Omit to add to current active tab.",
                    },
                },
                "required": ["title", "type", "config"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "airtable_query",
            "description": "Query records from the user's Airtable base. Use when they mention Airtable, tables, records, or bases.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "Table name or ID"},
                    "filter_formula": {
                        "type": "string",
                        "description": "Airtable filter formula (e.g. {Status}='Active')",
                    },
                    "max_records": {"type": "integer", "description": "Max records (default 10)"},
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "airtable_describe",
            "description": "List all tables and their fields in the user's Airtable base. Use this FIRST before querying Airtable to understand the schema and suggest meaningful widgets.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Save a new memory/fact/note to the user's knowledge base. Use when user says to remember something, or when you learn something worth retaining.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory content to save"},
                    "namespace": {
                        "type": "string",
                        "description": "Category: general, project, user, preferences, team",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for retrieval",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web (Google/DuckDuckGo, or a search API if configured) for current "
            "information. Your training data has a knowledge cutoff — use this for anything that may have "
            "changed since then: current events, recent results, prices, schedules, who-won-what, "
            "documentation for fast-moving libraries, etc. Prefer this over answering from memory whenever "
            "the question depends on something that could be outdated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_url",
            "description": "Fetch a specific URL and extract/summarize its content. Use after web_search "
            "returns a promising link and you need the full page, or when the user gives you a URL directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "task": {
                        "type": "string",
                        "description": "What to extract (default: key facts and quotes)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search/recall memories related to a topic. Use when user asks 'what do you know about X' or when you need context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or topic"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_delete",
            "description": "Delete a memory entry by ID. Use when user says to forget something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "The memory entry ID to delete"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_edit",
            "description": "Edit/update an existing memory entry. Use when user wants to correct or refine a saved memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "The memory entry ID to edit"},
                    "value": {"type": "string", "description": "New content for the memory"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated tags (optional)",
                    },
                },
                "required": ["entry_id", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_workflow",
            "description": "Execute a DAG workflow by ID. Runs all nodes, records results, triggers eval-judge scoring. Returns the run_id and score.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dag_id": {"type": "string", "description": "The DAG workflow ID to run"},
                    "goal": {
                        "type": "string",
                        "description": "Optional goal/context to pass to the DAG nodes",
                    },
                },
                "required": ["dag_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": "Create a new DAG workflow with nodes and edges. Each node has a role (llm, tool, transform) and a prompt/config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                    "description": {"type": "string", "description": "What this workflow does"},
                    "nodes": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of {id, label, role, config: {prompt, model?}}",
                    },
                    "edges": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of {source, target}",
                    },
                },
                "required": ["name", "nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_eval",
            "description": "Update the evaluation rubric for a DAG. The eval-judge uses this rubric to score run outputs. You can change criteria, weights, examples.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dag_id": {"type": "string", "description": "The DAG to update eval for"},
                    "rubric": {
                        "type": "string",
                        "description": "The full eval rubric text (criteria, weights, examples of good/bad)",
                    },
                },
                "required": ["dag_id", "rubric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_dashboard",
            "description": "Take a SCREENSHOT of the current dashboard and analyze it with a vision model. Use this to see what the dashboard actually LOOKS like — identify visual issues, bad layouts, broken widgets, wrong chart types. Always use this before suggesting layout changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What to analyze in the screenshot (default: full layout review)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_widgets",
            "description": "Search the widget template database for templates that match the user's data. Returns exact config schemas to use with create_dashboard_widget. Call this BEFORE creating widgets to get the correct format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Data source: airtable, jira, metrics, system",
                    },
                    "display": {
                        "type": "string",
                        "description": "Desired display: bar, donut, list, count, kpi, multi",
                    },
                    "table": {
                        "type": "string",
                        "description": "Airtable table name (if applicable)",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Available field names to match against",
                    },
                },
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_workflows",
            "description": "Search 100+ verified DAG workflow templates. Returns proven configs for common patterns (linear, parallel, quality-loop, debate, persona-panel, tool-augmented). Call this BEFORE creating workflows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter: linear-3, linear-4, linear-5, parallel, quality-loop, debate, persona-panel, tool-augmented, model-variation, temp-variation",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Search by name/description keyword",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "List all available DAG workflows.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


_JIRA_BASE = "https://jira.example.com"


def _jira_headers(jira_pat: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jira_pat}", "Accept": "application/json"}


async def _tool_poll_jira(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    if not jira_pat:
        return {"error": "No Jira PAT configured. Go to Credentials and add your Jira PAT."}
    import httpx

    max_results = min(args.get("max_results", 10), 15)
    jql = "project = DEMO AND updated >= -7d ORDER BY updated DESC"
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{_JIRA_BASE}/rest/api/2/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,assignee,issuetype,priority,updated",
                },
                headers=_jira_headers(jira_pat),
            )
            r.raise_for_status()
            data = r.json()
            issues = [
                {
                    "key": i.get("key"),
                    "summary": (f := i.get("fields", {})).get("summary"),
                    "status": (f.get("status") or {}).get("name"),
                    "type": (f.get("issuetype") or {}).get("name"),
                    "priority": (f.get("priority") or {}).get("name"),
                    "updated": f.get("updated"),
                }
                for i in data.get("issues", [])
            ]
            return {"total": data.get("total", 0), "issues": issues, "jql": jql}
    except httpx.HTTPStatusError as e:
        return {"error": f"Jira returned {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Jira connection failed: {e}"}


async def _tool_search_jira(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    if not jira_pat:
        return {"error": "No Jira PAT configured."}
    import httpx

    jql = args.get("jql") or ""
    text = args.get("text") or ""
    if not jql and text:
        jql = f'text ~ "{text}" ORDER BY updated DESC'
    if not jql:
        return {"error": "Provide 'jql' or 'text' to search"}
    max_results = min(args.get("max_results", 10), 15)
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{_JIRA_BASE}/rest/api/2/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,assignee,issuetype,priority,updated",
                },
                headers=_jira_headers(jira_pat),
            )
            r.raise_for_status()
            data = r.json()
            issues = [
                {
                    "key": i.get("key"),
                    "summary": (f := i.get("fields", {})).get("summary"),
                    "status": (f.get("status") or {}).get("name"),
                    "type": (f.get("issuetype") or {}).get("name"),
                    "assignee": ((f.get("assignee") or {}).get("displayName")),
                    "updated": f.get("updated"),
                }
                for i in data.get("issues", [])
            ]
            return {"total": data.get("total", 0), "issues": issues, "jql": jql}
    except httpx.HTTPStatusError as e:
        return {"error": f"Jira returned {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Jira search failed: {e}"}


async def _tool_get_issue(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    if not jira_pat:
        return {"error": "No Jira PAT configured."}
    import httpx

    issue_key = args.get("issue_key") or args.get("key") or ""
    if not issue_key:
        return {"error": "issue_key is required"}
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{_JIRA_BASE}/rest/api/2/issue/{issue_key}",
                headers=_jira_headers(jira_pat),
            )
            r.raise_for_status()
            data = r.json()
            f = data.get("fields", {})
            return {
                "key": data.get("key"),
                "summary": f.get("summary"),
                "status": (f.get("status") or {}).get("name"),
                "assignee": ((f.get("assignee") or {}).get("displayName")),
                "type": (f.get("issuetype") or {}).get("name"),
                "priority": (f.get("priority") or {}).get("name"),
                "description": (f.get("description") or "")[:2000],
                "labels": f.get("labels", []),
                "created": f.get("created"),
                "updated": f.get("updated"),
            }
    except httpx.HTTPStatusError as e:
        return {"error": f"Jira returned {e.response.status_code}"}
    except Exception as e:
        return {"error": f"Get issue failed: {e}"}


async def _tool_generate_exec_summary(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    # Chain: pull Jira state + blockers, format as text for LLM
    jira_state = await _execute_tool("poll_jira", {"max_results": 10}, user_id)
    blockers = await _execute_tool("check_blockers", {}, user_id)
    # Format as readable text so LLM doesn't try to call more tools
    lines = [f"Sprint: {jira_state.get('total', 0)} active issues"]
    for i in (jira_state.get("issues") or [])[:5]:
        lines.append(f"  • {i.get('key')} [{i.get('status')}] {i.get('summary')}")
    lines.append(f"\nBlockers: {blockers.get('total', 0)}")
    for i in (blockers.get("issues") or [])[:5]:
        lines.append(f"  ⚠ {i.get('key')} [{i.get('status')}] {i.get('summary')}")
    return {
        "summary": "\n".join(lines),
        "sprint_total": jira_state.get("total", 0),
        "blockers_total": blockers.get("total", 0),
    }


async def _tool_check_blockers(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    if not jira_pat:
        return {"error": "No Jira PAT configured."}
    import httpx

    jql = (
        "project = DEMO AND resolution = Unresolved AND "
        "(status = Blocked OR flagged is not EMPTY) ORDER BY priority DESC"
    )
    max_results = min(args.get("max_results", 10), 15)
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{_JIRA_BASE}/rest/api/2/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,assignee,issuetype,priority,flagged",
                },
                headers=_jira_headers(jira_pat),
            )
            r.raise_for_status()
            data = r.json()
            issues = [
                {
                    "key": i.get("key"),
                    "summary": (f := i.get("fields", {})).get("summary"),
                    "status": (f.get("status") or {}).get("name"),
                    "priority": (f.get("priority") or {}).get("name"),
                }
                for i in data.get("issues", [])
            ]
            return {"total": data.get("total", 0), "issues": issues, "jql": jql}
    except httpx.HTTPStatusError as e:
        # Fallback JQL if the flagged field doesn't exist
        if e.response.status_code == 400:
            return await _execute_tool(
                "search_jira",
                {"jql": "assignee = currentUser() AND status = Blocked ORDER BY updated DESC"},
                user_id,
            )
        return {"error": f"Blocker check failed: {e.response.status_code}"}
    except Exception as e:
        return {"error": f"Blocker check failed: {e}"}


def _get_confluence_pat(user_id: str) -> str | None:
    try:
        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if not store:
            return None
        resolver = ToolCredentialResolver(store)
        return resolver.first_secret(ToolCallContext(user_id), CONFLUENCE_PROVIDER_IDS)
    except Exception:
        return None


async def _tool_search_confluence(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    confluence_pat = _get_confluence_pat(user_id)
    if not confluence_pat:
        return {"error": "No Confluence PAT configured."}
    query = args.get("query", "")
    if not query:
        return {"error": "query is required"}

    confluence_base = "https://wiki.example.com"
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{confluence_base}/rest/api/content/search",
                params={"cql": f'text ~ "{query}"', "limit": args.get("max_results", 10)},
                headers={"Authorization": f"Bearer {confluence_pat}", "Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            results = [
                {
                    "title": p.get("title"),
                    "id": p.get("id"),
                    "type": p.get("type"),
                    "url": p.get("_links", {}).get("webui"),
                }
                for p in data.get("results", [])
            ]
            return {"total": data.get("size", 0), "results": results}
    except Exception as e:
        return {"error": f"Confluence search failed: {e}"}


async def _tool_save_as_action(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    # Save as a real agent button on the Program page
    from datetime import UTC, datetime
    from uuid import uuid4

    import stores
    from models.schemas import Agent as AgentModel

    agent_id = str(uuid4())[:8]
    name = args.get("name", "Saved Action")
    # Infer capability from conversation context
    capability = args.get("capability", "poll_jira")
    stores.agents[agent_id] = AgentModel(
        id=agent_id,
        name=name,
        description=args.get("description", "Saved from chat"),
        status="idle",
        model="gemini-3.5-flash",
        capabilities=[capability],
        primary_capability=capability,
        primary_action_label=name,
        created_at=datetime.now(UTC),
        config={},
    )
    return {"saved": True, "agent_id": agent_id, "name": name}


async def _tool_create_agent_button(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    from datetime import UTC, datetime
    from uuid import uuid4

    import stores
    from models.schemas import Agent as AgentModel

    agent_id = str(uuid4())[:8]
    capability = args.get("capability", "poll_jira")
    agent = AgentModel(
        id=agent_id,
        name=args.get("name", "New Agent"),
        description=args.get("description", ""),
        status="idle",
        model="gemini-3.5-flash",
        capabilities=[capability],
        primary_capability=capability,
        primary_action_label=args.get("name", "Run"),
        created_at=datetime.now(UTC),
        config={"default_payload": args.get("payload", {})},
    )
    stores.agents[agent_id] = agent
    return {
        "created": True,
        "agent": {"id": agent_id, "name": agent.name, "capability": capability},
    }


async def _tool_modify_agent_button(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    import stores

    agent_id = args.get("agent_id", "")
    if agent_id not in stores.agents:
        return {
            "error": f"Agent '{agent_id}' not found. Use list_agent_buttons to see available IDs."
        }
    agent = stores.agents[agent_id]
    updates = {}
    if args.get("name"):
        updates["name"] = args["name"]
    if args.get("description"):
        updates["description"] = args["description"]
    if args.get("capability"):
        updates["capabilities"] = [args["capability"]]
        updates["primary_capability"] = args["capability"]
    if hasattr(agent, "model_copy"):
        agent = agent.model_copy(update=updates)
    else:
        for k, v in updates.items():
            if isinstance(agent, dict):
                agent[k] = v
    stores.agents[agent_id] = agent
    return {"modified": True, "agent_id": agent_id, "updates": updates}


async def _tool_remove_agent_button(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    import stores

    agent_id = args.get("agent_id", "")
    if agent_id not in stores.agents:
        return {"error": f"Agent '{agent_id}' not found."}
    removed = stores.agents.pop(agent_id)
    return {"removed": True, "agent_id": agent_id, "name": removed.get("name", "")}


async def _tool_list_agent_buttons(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    import stores

    agents = []
    for aid, a in stores.agents.items():
        if isinstance(a, dict):
            agents.append(
                {"id": aid, "name": a.get("name"), "capabilities": a.get("capabilities", [])}
            )
        else:
            agents.append(
                {
                    "id": aid,
                    "name": getattr(a, "name", "?"),
                    "capabilities": getattr(a, "capabilities", []),
                }
            )
    return {"agents": agents}


async def _tool_query_metrics(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Pull runtime metrics from chat completions (every chat IS a DAG)."""
    return get_chat_metrics_summary()


async def _tool_airtable_query(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Query Airtable using stored credentials."""
    token, base_id = _get_airtable_creds(user_id)
    if not token:
        return {"error": "Airtable not configured. Go to Credentials and add your Airtable PAT."}
    if not base_id:
        return {"error": "Airtable base_id not configured. Set it in Credentials → Airtable."}

    table = args.get("table_name", "")
    formula = args.get("filter_formula", "")
    max_rec = args.get("max_records", 10)
    refresh = bool(args.get("refresh", False))

    params: dict[str, str] = {"maxRecords": str(max_rec)}
    if formula:
        params["filterByFormula"] = formula

    try:
        data = await get_airtable_records_json(
            token=token, base_id=base_id, table=table, params=params, force_refresh=refresh
        )
        records = [{"id": rec["id"], **rec.get("fields", {})} for rec in data.get("records", [])]
        return {"records": records, "count": len(records), "table": table}
    except Exception as e:
        return {"error": f"Airtable request failed: {str(e)[:100]}"}


async def _tool_airtable_describe(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Introspect Airtable base schema — tables and fields."""
    token, base_id = _get_airtable_creds(user_id)
    if not token:
        return {"error": "Airtable not configured."}
    if not base_id:
        return {"error": "Airtable base_id not configured."}
    try:
        data = await get_airtable_base_tables_json(
            token=token, base_id=base_id, force_refresh=bool(args.get("refresh", False))
        )
        tables = data.get("tables", [])
        schema = []
        for t in tables:
            fields = [{"name": f["name"], "type": f["type"]} for f in t.get("fields", [])]
            schema.append({"table": t["name"], "id": t["id"], "fields": fields})
        return {"base_id": base_id, "tables": schema}
    except Exception as e:
        return {"error": f"Airtable metadata request failed: {str(e)[:100]}"}


async def _tool_memory_add(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Save a memory entry."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.schemas import MemoryEntry

    content = args.get("content", "")
    if not content:
        return {"error": "content is required"}
    eid = str(uuid4())
    t = datetime.now(UTC)
    ns = args.get("namespace", "general")
    tags = args.get("tags", [])
    entry = MemoryEntry(
        id=eid,
        user_id=user_id,
        key=content[:60],
        value=content,
        namespace=ns,
        tags=tags,
        embedding=None,
        created_at=t,
        updated_at=t,
    )
    import stores

    stores.memory_entries[eid] = entry
    return {"saved": True, "id": eid, "content": content}


async def _tool_web_search(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Search the live web."""
    query = args.get("query", "")
    if not query:
        return {"error": "query is required"}
    max_results = args.get("max_results", 5)
    try:
        from services.tool_executor import web_search as _web_search

        return await _web_search(query, max_results=max_results)
    except Exception as e:
        return {"error": f"web_search failed: {e}"}


async def _tool_browse_url(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Fetch and summarize a URL."""
    url = args.get("url", "")
    if not url:
        return {"error": "url is required"}
    task = args.get("task", "Extract key facts and quotes")
    try:
        from services.tool_executor import browse_url as _browse_url

        return await _browse_url(url, task)
    except Exception as e:
        return {"error": f"browse_url failed: {e}"}


async def _tool_memory_search(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Search memories."""
    import stores

    query = args.get("query", "").lower()
    entries = [e for e in stores.memory_entries.values() if e.user_id == user_id]
    if query:
        entries = [
            e
            for e in entries
            if query in e.value.lower()
            or query in e.key.lower()
            or query in " ".join(e.tags).lower()
        ]
    return {
        "results": [
            {"id": e.id, "key": e.key, "value": e.value, "namespace": e.namespace, "tags": e.tags}
            for e in entries[:10]
        ],
        "count": len(entries),
    }


async def _tool_memory_delete(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Delete a memory entry."""
    import stores

    entry_id = args.get("entry_id", "")
    if not entry_id:
        return {"error": "entry_id required"}
    if entry_id in stores.memory_entries and stores.memory_entries[entry_id].user_id == user_id:
        del stores.memory_entries[entry_id]
        return {"deleted": True, "id": entry_id}
    return {"error": "not found"}


async def _tool_memory_edit(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Edit a memory entry."""
    import stores

    entry_id = args.get("entry_id", "")
    value = args.get("value", "")
    if not entry_id or not value:
        return {"error": "entry_id and value required"}
    if entry_id not in stores.memory_entries or stores.memory_entries[entry_id].user_id != user_id:
        return {"error": "not found"}
    from datetime import UTC, datetime

    entry = stores.memory_entries[entry_id]
    updates: dict[str, Any] = {"value": value, "key": value[:60], "updated_at": datetime.now(UTC)}
    if "tags" in args:
        updates["tags"] = args["tags"]
    stores.memory_entries[entry_id] = entry.model_copy(update=updates)
    return {"updated": True, "id": entry_id, "value": value}


async def _tool_create_dashboard_widget(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Add a widget to the user's dashboard, and say so only if it was stored.

    This used to write `routes.dashboard_layout._LAYOUTS` and call
    `_save_to_disk()` inside `except Exception: pass`, then return
    `{"created": True}` whatever happened — so a chat that could not persist a
    widget still told the user it had made one. It now goes through the same
    durable path the API does (#340), and reports the failure it gets.
    """
    from uuid import uuid4

    from services import dashboard_layouts

    if not user_id:
        # The old `user_id or "dev"` pooled every unidentified caller into one
        # layout. A widget with nowhere to go is not a widget that was created.
        return {"created": False, "error": "no principal to attach the widget to"}

    widget_id = f"w-{str(uuid4())[:8]}"
    title = args.get("title", "New Widget")
    widget_type = args.get("type", "kpi")
    size = args.get("size", "2")
    config = args.get("config", {})
    tab_name = args.get("tab", "")

    layout = dict(dashboard_layouts.load(user_id).layout)
    widget = {
        "id": widget_id,
        "type": widget_type,
        "title": title,
        "size": size,
        "config": config,
    }

    if layout.get("tabs"):
        tabs = [dict(tab) for tab in layout["tabs"]]
        target_idx = layout.get("activeTab", 0)
        if tab_name:
            for i, tab in enumerate(tabs):
                if tab.get("name", "").lower() == tab_name.lower():
                    target_idx = i
                    break
            else:
                tabs.append({"name": tab_name, "widgets": []})
                target_idx = len(tabs) - 1
        tabs[target_idx]["widgets"] = [*tabs[target_idx].get("widgets", []), widget]
        layout["tabs"] = tabs
    else:
        existing = layout.get("widgets", [])
        layout["tabs"] = [{"name": tab_name or "Overview", "widgets": [*existing, widget]}]
        layout["activeTab"] = 0
        layout.pop("widgets", None)

    try:
        dashboard_layouts.save(user_id, layout)
    except dashboard_layouts.LayoutError as exc:
        logger.error("dashboard widget was not persisted for %s: %s", user_id, exc)
        return {"created": False, "error": f"the widget was not saved: {exc}"}

    return {
        "created": True,
        "widget_id": widget_id,
        "title": title,
        "type": widget_type,
        "size": size,
        "tab": tab_name or "(active tab)",
    }


# Tool name (and aliases) → handler. Unknown tools fall back to poll_jira.
async def _tool_suggest_widgets(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Search 1500+ verified widget configs that match the user's needs."""
    import json as _json
    from pathlib import Path

    source = args.get("source", "")
    display = args.get("display", "")
    table = args.get("table", "")

    configs_path = Path(__file__).parent.parent / "data" / "verified_widget_configs.json"
    try:
        all_configs = _json.loads(configs_path.read_text())
    except Exception:
        return {"error": "Config database not found"}

    matches = []
    for c in all_configs:
        cfg = c.get("config", {})
        ctype = c.get("type", "")
        if source and (
            (source == "jira" and ctype != "jira")
            or (source == "airtable" and cfg.get("source") != "airtable")
            or (source == "metrics" and cfg.get("source") != "metrics")
            or (source not in ("jira", "airtable", "metrics") and ctype != source)
        ):
            continue
        if display and c.get("display") != display and cfg.get("jira_display") != display:
            continue
        if table and cfg.get("table") != table:
            continue
        matches.append(c)

    samples = (
        matches[:5] if len(matches) <= 5 else [matches[i * len(matches) // 5] for i in range(5)]
    )
    return {
        "total_matches": len(matches),
        "configs": [
            {"title": s["title"], "type": s["type"], "size": s["size"], "config": s["config"]}
            for s in samples
        ],
        "note": "VERIFIED configs (100% test pass rate). Use create_dashboard_widget with any config exactly as shown.",
    }


async def _tool_list_workflows(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """List all DAGs."""
    import stores

    dags = list(stores.dags.values())
    return {
        "workflows": [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "nodes": len(d.get("nodes", [])),
                "status": d.get("status", "draft"),
            }
            for d in dags[:20]
        ],
        "count": len(dags),
    }


async def _tool_run_workflow(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Run a DAG and eval-score it."""
    from uuid import uuid4

    import stores

    dag_id = args.get("dag_id", "")
    if dag_id not in stores.dags:
        return {"error": f"DAG '{dag_id}' not found. Use list_workflows to see available DAGs."}

    dag_data = stores.dags[dag_id]
    goal = args.get("goal", "")
    if goal:
        dag_data = {**dag_data, "description": goal}

    try:
        from services.dag_run_store import get_dag_run_store
        from services.graph_runner import execute_dag

        exec_id = str(uuid4())
        store = get_dag_run_store()
        await store.start_run(run_id=exec_id)
        result = await execute_dag(dag_data, user_id=user_id)

        # Store events
        for nid, nr in result.get("node_results", {}).items():
            await store.append_event(
                exec_id,
                event_type="pm_node_completed",
                role=nr.get("role", ""),
                capability=nid,
                payload={"source": "llm", "response": nr.get("response", "")[:2000]},
            )

        # Trigger eval-judge
        score_result = {}
        try:
            from services.eval_judge import score_run

            class _Adapter:
                def __init__(self):
                    self.run_id = exec_id
                    self.dag_id = dag_id
                    self.project_id = ""
                    self.status = "completed"
                    self.node_records = []
                    for nid, nr in result.get("node_results", {}).items():

                        class _NR:
                            pass

                        n = _NR()
                        n.node_id = nid
                        n.kind = nr.get("role", "llm")
                        n.phase = "completed"
                        n.latency_ms = nr.get("latency_ms", 0)
                        n.tokens_in = nr.get("tokens_in", 0)
                        n.tokens_out = nr.get("tokens_out", 0)
                        n.error_code = None
                        n.error_message = None
                        n.response_preview = nr.get("response", "")[:500]
                        self.node_records.append(n)

            score_result = await score_run(_Adapter())
        except Exception as e:
            score_result = {"score": 0, "error": str(e)[:100]}

        return {
            "run_id": exec_id,
            "dag_id": dag_id,
            "status": "completed",
            "nodes_completed": len(result.get("node_results", {})),
            "score": score_result.get("score", 0),
            "rationale": score_result.get("rationale", ""),
            "topology_proposal": score_result.get("topology_proposal"),
            "output_preview": {
                nid: nr.get("response", "")[:200]
                for nid, nr in list(result.get("node_results", {}).items())[:3]
            },
        }
    except Exception as e:
        return {"error": f"DAG execution failed: {e}"}


async def _tool_analyze_dashboard(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Capture screenshot of dashboard and analyze with vision model."""

    # Capture screenshot via internal endpoint
    try:
        async with shared_client(timeout=30) as client:
            r = await client.post(
                "http://127.0.0.1:8101/v1/widgets/screenshot",
                cookies={"hive_session": "24f30b74-d535-4263-a2d4-8a773b07803d"},
            )
            data = r.json()
            if data.get("error"):
                return {"error": f"Screenshot failed: {data['error']}"}
            b64 = data.get("screenshot", "")
            if not b64:
                return {"error": "No screenshot captured"}
    except Exception as e:
        return {"error": f"Screenshot capture failed: {e}"}

    # Send to vision model
    try:
        from config import get_settings

        s = get_settings()
        base = s.litellm_api_base or ""
        key = _resolve_litellm_api_key(s) or ""
        if not base or not key:
            return {"error": "LLM not configured"}

        vision_model = args.get("model", "gpt-4o-mini")
        prompt = args.get(
            "prompt",
            "Analyze this dashboard screenshot. Identify: 1) Widgets that look broken or show useless data, 2) Poor sizing choices, 3) Bad chart type choices for the data shown, 4) Missing widgets that would add value, 5) Layout improvements for better visual flow. Be specific and actionable.",
        )

        async with shared_client(timeout=60) as client:
            resp = await client.post(
                f"{base.rstrip('/')}/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": vision_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            analysis = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"analysis": analysis, "model": vision_model}
    except Exception as e:
        return {"error": f"Vision analysis failed: {e}"}


async def _tool_suggest_workflows(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Search 100+ verified DAG workflow configs."""
    import json as _json
    from pathlib import Path

    category = args.get("category", "")
    keyword = args.get("keyword", "").lower()

    path = Path(__file__).parent.parent / "data" / "verified_dag_configs.json"
    try:
        all_dags = _json.loads(path.read_text())
    except Exception:
        return {"error": "DAG config database not found"}

    matches = []
    for d in all_dags:
        if category and d.get("category") != category:
            continue
        if (
            keyword
            and keyword not in d.get("name", "").lower()
            and keyword not in d.get("description", "").lower()
        ):
            continue
        matches.append(d)

    samples = (
        matches[:5] if len(matches) <= 5 else [matches[i * len(matches) // 5] for i in range(5)]
    )
    return {
        "total_matches": len(matches),
        "configs": [
            {
                "name": s["name"],
                "description": s["description"],
                "category": s["category"],
                "nodes": len(s["nodes"]),
                "edges": len(s["edges"]),
                "node_summary": [{"id": n["id"], "role": n["role"]} for n in s["nodes"]],
            }
            for s in samples
        ],
        "categories": list({d["category"] for d in all_dags}),
        "note": "Use create_workflow with the nodes/edges from any of these verified configs.",
    }


async def _tool_create_workflow(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Create a new DAG."""
    from uuid import uuid4

    import stores

    dag_id = str(uuid4())
    nodes = args.get("nodes", [])
    edges = args.get("edges", [])
    # Ensure nodes have IDs
    for i, n in enumerate(nodes):
        if "id" not in n:
            n["id"] = f"node-{i}"

    dag = {
        "id": dag_id,
        "name": args.get("name", "Untitled Workflow"),
        "description": args.get("description", ""),
        "nodes": nodes,
        "edges": edges,
        "status": "active",
        "created_by": user_id,
    }
    stores.dags[dag_id] = dag
    return {
        "created": True,
        "dag_id": dag_id,
        "name": dag["name"],
        "nodes": len(nodes),
        "edges": len(edges),
    }


async def _tool_update_eval(
    args: dict[str, Any], user_id: str, jira_pat: str | None
) -> dict[str, Any]:
    """Update the eval rubric for a DAG."""
    import stores

    dag_id = args.get("dag_id", "")
    rubric = args.get("rubric", "")
    if dag_id not in stores.dags:
        return {"error": "DAG not found"}
    stores.dags[dag_id]["eval_rubric"] = rubric
    return {"updated": True, "dag_id": dag_id, "rubric_length": len(rubric)}


_TOOL_HANDLERS: dict[str, Any] = {
    "poll_jira": _tool_poll_jira,
    "fetch_program_state": _tool_poll_jira,
    "search_jira": _tool_search_jira,
    "get_issue": _tool_get_issue,
    "get_jira_issue": _tool_get_issue,
    "generate_exec_summary": _tool_generate_exec_summary,
    "check_blockers": _tool_check_blockers,
    "detect_blockers": _tool_check_blockers,
    "scan_risks": _tool_check_blockers,
    "search_confluence": _tool_search_confluence,
    "web_search": _tool_web_search,
    "browse_url": _tool_browse_url,
    "save_as_action": _tool_save_as_action,
    "create_agent_button": _tool_create_agent_button,
    "modify_agent_button": _tool_modify_agent_button,
    "remove_agent_button": _tool_remove_agent_button,
    "list_agent_buttons": _tool_list_agent_buttons,
    "query_metrics": _tool_query_metrics,
    "create_dashboard_widget": _tool_create_dashboard_widget,
    "airtable_query": _tool_airtable_query,
    "airtable_describe": _tool_airtable_describe,
    "memory_add": _tool_memory_add,
    "memory_search": _tool_memory_search,
    "memory_delete": _tool_memory_delete,
    "memory_edit": _tool_memory_edit,
    "run_workflow": _tool_run_workflow,
    "create_workflow": _tool_create_workflow,
    "update_eval": _tool_update_eval,
    "list_workflows": _tool_list_workflows,
    "suggest_widgets": _tool_suggest_widgets,
    "suggest_workflows": _tool_suggest_workflows,
    "analyze_dashboard": _tool_analyze_dashboard,
}

# Add hill-climbing and structural mutation from substrate tools
from services.substrate_tools import tool_hill_climb, tool_mutate_workflow  # noqa: E402

_TOOL_HANDLERS["hill_climb"] = tool_hill_climb
_TOOL_HANDLERS["mutate_workflow"] = tool_mutate_workflow


async def _execute_tool(tool_name: str, args: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Execute a PM tool for real. No stubs. Calls Jira REST API directly."""
    jira_pat = _get_jira_pat(user_id)
    handler = _TOOL_HANDLERS.get(tool_name, _tool_poll_jira)
    return await handler(args, user_id, jira_pat)


# ─── Chat metrics (every chat IS a DAG run) ─────────────────────────────────

_chat_metrics: list[dict[str, Any]] = []


def _record_chat_metric(
    user_id: str, model: str, elapsed_ms: float, tokens_in: int = 0, tokens_out: int = 0
) -> None:
    _chat_metrics.append(
        {
            "user": user_id,
            "model": model,
            "latency_ms": elapsed_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "ts": __import__("time").time(),
        }
    )
    if len(_chat_metrics) > 10000:
        _chat_metrics.pop(0)


def get_chat_metrics_summary() -> dict[str, Any]:
    """Aggregate chat metrics for the dashboard."""
    if not _chat_metrics:
        return {
            "count": 0,
            "latency_ms_p50": 0,
            "latency_ms_p95": 0,
            "tokens_in_total": 0,
            "tokens_out_total": 0,
            "cost_usd_total": 0.0,
        }
    lats = sorted(m["latency_ms"] for m in _chat_metrics)
    n = len(lats)
    return {
        "count": n,
        "latency_ms_p50": lats[n // 2] if n else 0,
        "latency_ms_p95": lats[int(n * 0.95)] if n else 0,
        "latency_ms_mean": sum(lats) / n if n else 0,
        "tokens_in_total": sum(m["tokens_in"] for m in _chat_metrics),
        "tokens_out_total": sum(m["tokens_out"] for m in _chat_metrics),
        "cost_usd_total": sum(
            m["tokens_out"] * 0.000003 + m["tokens_in"] * 0.000001 for m in _chat_metrics
        ),  # rough estimate
    }


async def run_chat_completion(
    req: ChatCompletionRequest,
    user_id: str = "",
    _llm: LLMPort | None = None,
) -> dict[str, Any]:
    """PM Fleet chat — real tools, real data, real LLM synthesis."""
    try:
        return await _run_chat_completion_inner(req, user_id, _llm)
    except Exception as exc:
        logger.exception("run_chat_completion crashed: %s", exc)
        return {
            "choices": [
                {"message": {"role": "assistant", "content": f"Error: {type(exc).__name__}: {exc}"}}
            ],
            "model": "error",
        }


async def _run_chat_completion_inner(
    req: ChatCompletionRequest,
    user_id: str = "",
    _llm: LLMPort | None = None,
) -> dict[str, Any]:
    """Inner implementation."""
    import time as _time

    _t0 = _time.perf_counter()

    s = get_settings()
    model = req.model or os.environ.get("CHAT_DEFAULT_MODEL") or s.chat_default_model
    llm = _llm or build_llm_port()

    # Build messages with PM system prompt
    messages: list[dict[str, Any]] = list(req.messages)
    if not any(m.get("role") == "system" for m in messages):
        await hydrate_profile_cache(user_id)
        system_prompt = _build_system_prompt(user_id)
        messages.insert(0, {"role": "system", "content": system_prompt})

    # Tool-use loop (max 5 iterations)
    for _ in range(5):
        tool_req = ChatCompletionRequest(
            messages=messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            tools=get_scoped_tools(getattr(req, "tools_scope", None)),
        )
        out = await llm.complete(tool_req)

        choice = (out.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            # Ensure content exists before returning
            content = msg.get("content")
            if not content:
                out["choices"][0]["message"]["content"] = "(Processing complete)"
            return out

        # Execute tool calls
        messages.append(
            {"role": "assistant", "content": msg.get("content") or None, "tool_calls": tool_calls}
        )
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            logger.info("tool_call name=%s args=%s user=%s", name, args, user_id)
            try:
                result = await _execute_tool(name, args, user_id)
            except Exception as tool_exc:
                logger.warning("tool_execution_error name=%s error=%s", name, tool_exc)
                result = {"error": f"Tool '{name}' failed: {type(tool_exc).__name__}: {tool_exc}"}
            logger.info(
                "tool_result name=%s keys=%s",
                name,
                list(result.keys()) if isinstance(result, dict) else "?",
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result),
                }
            )

    # Final synthesis after tool loop exhausted — call WITHOUT tools to force content
    final_req = ChatCompletionRequest(messages=messages, model=model, temperature=req.temperature)
    final_out = await llm.complete(final_req)
    # Ensure we never return raw tool_calls to the frontend
    choice = (final_out.get("choices") or [{}])[0]
    content = choice.get("message", {}).get("content")
    if not content:
        synth = _synthesize_fallback_content(messages)
        final_out = {
            "choices": [{"message": {"role": "assistant", "content": synth}}],
            "model": model,
        }
    # Record metrics from this chat completion (it IS a DAG execution)
    _elapsed_ms = (_time.perf_counter() - _t0) * 1000
    _usage = final_out.get("usage", {})
    _record_chat_metric(
        user_id,
        model,
        _elapsed_ms,
        tokens_in=_usage.get("prompt_tokens", 0),
        tokens_out=_usage.get("completion_tokens", 0),
    )
    return final_out


def _synthesize_fallback_content(messages: list[dict[str, Any]]) -> str:
    """Format the most recent tool results as readable bullet points for the user."""
    tool_results = [m.get("content", "") for m in messages if m.get("role") == "tool"]
    lines: list[str] = []
    for tr in tool_results[-2:]:
        try:
            d = json.loads(tr)
        except Exception:
            continue
        for issue in (d.get("issues") or [])[:10]:
            lines.append(f"• **{issue.get('key')}** [{issue.get('status')}] {issue.get('summary')}")
        total = d.get("total", 0)
        if total:
            lines.insert(0, f"**{total} issues** (showing first {min(total, 10)})\n")

    if not lines:
        return (
            "Request completed but no summary was generated. Try asking a more specific question."
        )
    content = "\n".join(lines)
    content += (
        "\n\n---\n**Summary:** "
        + f"{len(lines) - 1} issues shown. Use chat to drill into specific items "
        "or ask follow-up questions."
    )
    return content


class _ToolCallAccumulator:
    """Assembles OpenAI streaming ``tool_calls`` fragments into complete tool calls.

    Providers stream a tool call across chunks: the first delta carries ``index``,
    ``id`` and ``function.name``; later deltas append ``function.arguments`` pieces
    (and may omit id/name). We accumulate by ``index`` and concatenate arguments.
    Pure/stateful — unit-tested in ``tests`` so the streaming generator stays simple.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}

    def add_deltas(self, tool_call_deltas: list[dict[str, Any]]) -> None:
        for d in tool_call_deltas or []:
            idx = d.get("index", 0)
            slot = self._by_index.setdefault(
                idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if d.get("id"):
                slot["id"] = d["id"]
            if d.get("type"):
                slot["type"] = d["type"]
            fn = d.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]

    def finalize(self) -> list[dict[str, Any]]:
        return [self._by_index[i] for i in sorted(self._by_index)]

    def __bool__(self) -> bool:
        return bool(self._by_index)


async def _stream_turn(
    llm: LLMPort,
    turn_req: ChatCompletionRequest,
    tools_acc: _ToolCallAccumulator | None,
    content_out: list[str],
):
    """One llm.stream() turn: yield delta/thinking events, accumulate content
    into ``content_out`` and tool-call fragments into ``tools_acc`` (if given)."""
    async for chunk in llm.stream(turn_req):
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if piece:
            content_out.append(piece)
            yield {"type": "delta", "content": piece}
        think = delta.get("reasoning_content")
        if think:
            yield {"type": "thinking", "content": think}
        if tools_acc is not None and delta.get("tool_calls"):
            tools_acc.add_deltas(delta["tool_calls"])


async def run_chat_completion_streaming(  # noqa: C901  streaming state machine
    req: ChatCompletionRequest,
    user_id: str = "",
):
    """Streaming version — yields SSE events with real status updates."""
    import os

    from adapters.telemetry_langfuse import trace_llm

    s = get_settings()
    model = req.model or os.environ.get("CHAT_DEFAULT_MODEL") or s.chat_default_model
    llm = build_llm_port()

    messages: list[dict[str, Any]] = list(req.messages)
    if not any(m.get("role") == "system" for m in messages):
        await hydrate_profile_cache(user_id)
        system_prompt = _build_system_prompt(user_id)
        messages.insert(0, {"role": "system", "content": system_prompt})

    for iteration in range(5):
        yield {
            "type": "status",
            "message": "Sending to LLM…" if iteration == 0 else "Processing tool results…",
        }

        tool_req = ChatCompletionRequest(
            messages=messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            tools=get_scoped_tools(getattr(req, "tools_scope", None)),
        )

        # Stream tokens + tool calls: consume raw llm.stream() deltas, emitting
        # the delta/thinking events the frontend renders, while assembling
        # fragmented tool calls (the port has .stream(), not pre-assembled chunks).
        collected_content = ""
        collected_tool_calls = None

        acc = _ToolCallAccumulator()
        content_parts: list[str] = []
        try:
            async for evt in _stream_turn(llm, tool_req, acc, content_parts):
                yield evt
            collected_content = "".join(content_parts)
            collected_tool_calls = acc.finalize() if acc else None
        except Exception:
            # Fall back to non-streaming
            out = await llm.complete(tool_req)
            choice = (out.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            collected_content = msg.get("content", "")
            collected_tool_calls = msg.get("tool_calls")

        # If streaming yielded nothing, fall back to non-streaming
        if not collected_content and not collected_tool_calls:
            out = await llm.complete(tool_req)
            choice = (out.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            collected_content = msg.get("content", "")
            collected_tool_calls = msg.get("tool_calls")

        if not collected_tool_calls:  # noqa: SIM102  keep detection comment attached to inner condition
            # Detect model outputting tool calls as text instead of structured tool_calls
            if (
                collected_content
                and not collected_tool_calls
                and any(
                    (t.get("function") or {}).get("name", "") in collected_content
                    for t in PM_TOOLS
                    if (t.get("function") or {}).get("name")
                )
            ):
                logger.warning("Model leaked tool calls as text — retrying non-streaming")
                out = await llm.complete(tool_req)
                choice = (out.get("choices") or [{}])[0]
                msg = choice.get("message", {})
                collected_content = msg.get("content", "")
                collected_tool_calls = msg.get("tool_calls")

        if not collected_tool_calls:
            if collected_content:
                with trace_llm("chat_completion", model=model, user_id=user_id) as t:
                    t["input"] = str(req.messages[-1:])[:1000]
                    t["output"] = collected_content[:1000]
                yield {"type": "done", "content": collected_content, "model": model}
            else:
                yield {"type": "done", "content": "", "model": model}
            return

        # Process tool calls
        messages.append(
            {
                "role": "assistant",
                "content": collected_content or None,
                "tool_calls": collected_tool_calls,
            }
        )

        for tc in collected_tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_call", "tool": name, "args": args}
            with trace_llm(
                f"tool:{name}",
                model=model,
                user_id=user_id,
                metadata={"tool_args": str(args)[:500]},
            ) as t:
                result = await _execute_tool(name, args, user_id)
                t["output"] = str(result)[:1000]
            yield {"type": "tool_result", "tool": name, "summary": _summarize_result(result)}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result),
                }
            )

        # Continue to next iteration — the loop will send messages back to LLM
        # for synthesis after tool results are appended

    # Final synthesis
    yield {"type": "status", "message": "Finalizing…"}
    final_req = ChatCompletionRequest(messages=messages, model=model, temperature=req.temperature)
    final_out = await llm.complete(final_req)
    content = (final_out.get("choices") or [{}])[0].get("message", {}).get("content", "")
    yield {"type": "done", "content": content, "model": model}


def _summarize_result(result: dict[str, Any]) -> str:
    """Short summary of a tool result for the status stream."""
    if "error" in result:
        return f"Error: {result['error'][:80]}"
    if "issues" in result:
        return f"Got {result.get('total', len(result['issues']))} issues"
    if "results" in result:
        return f"Got {result.get('total', len(result['results']))} results"
    if "created" in result:
        return "Created"
    if "saved" in result:
        return "Saved"
    return "Done"


# ── User profile tools ──
PROFILE_SCHEMA = {
    "identity": ["name", "role", "team", "department", "location", "timezone"],
    "work_context": [
        "projects",
        "tools",
        "languages",
        "platforms",
        "recurring_tasks",
        "stakeholders",
    ],
    "preferences": [
        "response_style",
        "interaction_style",
        "model_preferences",
        "topics_to_avoid",
        "assumptions_to_avoid",
    ],
    "goals": ["current_focus", "okrs", "blockers", "definition_of_done"],
    "communication": ["challenge_style", "presentation_format", "terminology"],
}

_PROFILE_CACHE: dict[str, dict] = {}


async def hydrate_profile_cache(user_id: str) -> None:
    """Load profile from DB into cache. Called on first chat request."""
    if user_id in _PROFILE_CACHE:
        return
    try:
        from services.pg_store import pg_get

        rows = await pg_get("user_profiles", {"id": f"eq.{user_id}"})
        row = rows[0] if rows else None
        _PROFILE_CACHE[user_id] = (row or {}).get("preferences", {})
    except Exception:
        _PROFILE_CACHE[user_id] = {}


async def _tool_profile_get(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Get profile fields. No args = full profile. section= filters by category."""
    from services.pg_store import pg_get

    rows = await pg_get("user_profiles", {"id": f"eq.{user_id}"})
    row = rows[0] if rows else None
    profile = (row or {}).get("preferences", {})
    section = args.get("section")
    if section and section in PROFILE_SCHEMA:
        return {
            "section": section,
            "fields": {k: profile.get(k) for k in PROFILE_SCHEMA[section] if profile.get(k)},
        }
    return {"profile": {k: v for k, v in profile.items() if v}, "schema": PROFILE_SCHEMA}


async def _tool_profile_set(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Set a profile field. e.g. field='name', value='Blake'"""
    from services.pg_store import pg_get, pg_upsert

    rows = await pg_get("user_profiles", {"id": f"eq.{user_id}"})
    row = rows[0] if rows else None
    profile = (row or {}).get("preferences", {})
    field = args.get("field", "")
    value = args.get("value", "")
    if not field or not value:
        return {"error": "field and value required"}
    profile[field] = value
    await pg_upsert("user_profiles", {"id": user_id, "preferences": profile})
    _PROFILE_CACHE[user_id] = profile
    return {"updated": True, "field": field, "value": value}


async def _tool_profile_delete(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Remove a profile field."""
    from services.pg_store import pg_get, pg_upsert

    rows = await pg_get("user_profiles", {"id": f"eq.{user_id}"})
    row = rows[0] if rows else None
    profile = (row or {}).get("preferences", {})
    field = args.get("field", "")
    if not field:
        return {"error": "field required"}
    removed = profile.pop(field, None)
    if removed is None:
        return {"error": f"field '{field}' not found"}
    await pg_upsert("user_profiles", {"id": user_id, "preferences": profile})
    _PROFILE_CACHE.pop(user_id, None)
    return {"deleted": True, "field": field}


_TOOL_HANDLERS["profile_get"] = _tool_profile_get
_TOOL_HANDLERS["profile_set"] = _tool_profile_set
_TOOL_HANDLERS["profile_delete"] = _tool_profile_delete

PROFILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "profile_get",
            "description": "Get the user's profile. Use before asking questions to check what's already known. Returns filled fields + schema of what can be filled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": [
                            "identity",
                            "work_context",
                            "preferences",
                            "goals",
                            "communication",
                        ],
                        "description": "Optional: filter to one section",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_set",
            "description": "Set a profile field. Use when user shares info about themselves, their preferences, or corrections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field name (e.g. 'name', 'role', 'response_style', 'current_focus')",
                    },
                    "value": {"type": "string", "description": "The value to store"},
                },
                "required": ["field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_delete",
            "description": "Remove a profile field.",
            "parameters": {
                "type": "object",
                "properties": {"field": {"type": "string", "description": "Field name to remove"}},
                "required": ["field"],
            },
        },
    },
]

PM_TOOLS.extend(PROFILE_TOOLS)


# ── Tool scoping ──
TOOL_SCOPES: dict[str, list[str] | None] = {
    "memory": [
        "memory_add",
        "memory_search",
        "memory_delete",
        "memory_edit",
        "profile_get",
        "profile_set",
        "profile_delete",
    ],
    "deck": ["airtable_query", "airtable_describe", "query_metrics", "memory_search"],
    "dashboard_view": [
        "poll_jira",
        "search_jira",
        "check_blockers",
        "search_confluence",
        "airtable_query",
        "query_metrics",
        "memory_search",
        "profile_get",
    ],
    "dashboard_edit": [
        "poll_jira",
        "search_jira",
        "check_blockers",
        "search_confluence",
        "airtable_query",
        "query_metrics",
        "memory_search",
        "profile_get",
        "create_widget",
        "remove_widget",
        "explain_widget",
        "create_dashboard_widget",
        "suggest_widgets",
        "analyze_dashboard",
    ],
    "chat": None,  # None = all tools
}


def get_scoped_tools(scope: str | None) -> list[dict]:
    """Return tool definitions filtered by scope. None scope = all tools."""
    if scope is None or scope == "chat":
        return PM_TOOLS
    allowed = TOOL_SCOPES.get(scope)
    if allowed is None:
        return PM_TOOLS
    return [t for t in PM_TOOLS if t.get("function", {}).get("name") in allowed]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Optional: PG persistence for memory tools on the external deploy target
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if os.environ.get("DEPLOY_TARGET_APP_ENV"):
    _orig_memory_add = _tool_memory_add
    _orig_memory_delete = _tool_memory_delete

    async def _pg_memory_add(args, user_id, jira_pat=None):
        result = await _orig_memory_add(args, user_id, jira_pat)
        if result.get("saved") and result.get("id"):
            try:
                from services.pg_store import pg_upsert

                await pg_upsert(
                    "hive_memory_entries",
                    {
                        "id": result["id"],
                        "user_id": user_id,
                        "key": args.get("content", "")[:60],
                        "value": args.get("content", ""),
                        "namespace": args.get("namespace", "general"),
                        "tags": args.get("tags", []),
                    },
                )
            except Exception:
                pass
        return result

    async def _pg_memory_delete(args, user_id, jira_pat=None):
        result = await _orig_memory_delete(args, user_id, jira_pat)
        if result.get("deleted"):
            try:
                from services.pg_store import pg_delete

                await pg_delete("hive_memory_entries", result["id"])
            except Exception:
                pass
        return result

    _TOOL_HANDLERS["memory_add"] = _pg_memory_add
    _TOOL_HANDLERS["memory_delete"] = _pg_memory_delete


# -- Model curation tools --
async def _tool_favorite_model(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Add/remove a model from favorites, or set a per-task default."""
    from services.pg_store import pg_get, pg_upsert

    rows = await pg_get("user_profiles", {"id": f"eq.{user_id}"})
    row = rows[0] if rows else None
    profile = (row or {}).get("preferences", {})
    model = args.get("model", "")
    action = args.get("action", "add")  # add, remove, hide, unhide, set_task
    task = args.get("task", "")  # chat, widget_wizard, biographer

    if not model:
        return {"error": "model required"}

    favorites = profile.get("favorite_models", [])
    hidden = profile.get("hidden_models", [])
    task_models = profile.get("task_models", {})

    if action == "add" and model not in favorites:
        favorites.append(model)
    elif action == "remove" and model in favorites:
        favorites.remove(model)
    elif action == "hide" and model not in hidden:
        hidden.append(model)
    elif action == "unhide" and model in hidden:
        hidden.remove(model)
    elif action == "set_task" and task:
        task_models[task] = model

    profile["favorite_models"] = favorites
    profile["hidden_models"] = hidden
    profile["task_models"] = task_models
    await pg_upsert("user_profiles", {"id": user_id, "preferences": profile})
    _PROFILE_CACHE[user_id] = profile
    return {"updated": True, "favorites": favorites, "hidden": hidden, "task_models": task_models}


_TOOL_HANDLERS["favorite_model"] = _tool_favorite_model

PM_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "favorite_model",
            "description": "Manage model preferences: favorite, hide, or set per-task defaults.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g. gpt-5.5, claude-haiku-4-5)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "hide", "unhide", "set_task"],
                        "description": "What to do",
                    },
                    "task": {
                        "type": "string",
                        "enum": ["chat", "widget_wizard", "biographer"],
                        "description": "Task context (only for set_task)",
                    },
                },
                "required": ["model", "action"],
            },
        },
    }
)
TOOL_SCOPES["memory"].append("favorite_model")
