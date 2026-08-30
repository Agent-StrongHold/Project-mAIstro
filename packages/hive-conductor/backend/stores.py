"""In-memory stores with optional SQLite persistence for the Hive Conductor API.

When a PersistedStore is configured via ``configure_persistence()``, all
mutable stores (missions, chat_sessions, memory_entries, etc.) are backed
by SQLite. Read-only stores (agents, skills, containers, mcp_servers,
mcp_tools, schedules) stay in-memory since they reflect live system state.

Seed data is loaded when the store is empty and no persisted data exists.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from models.persona_feedback import PersonaFeedback
from models.schemas import (
    Agent,
    ChatMessage,
    ChatSession,
    Container,
    HiveUser,
    MCPServer,
    MCPTool,
    MemoryEntry,
    MemoryNamespace,
    Mission,
    MissionStep,
    Schedule,
    Skill,
)
from models.workspace import Workspace
from services.model_store import JsonStore, ModelStore

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


_persisted: Any | None = None


def _mission(
    id: str,
    name: str,
    status: Literal["pending", "running", "completed", "failed", "paused"] = "running",
    progress: float = 0.5,
) -> Mission:
    t = now()
    return Mission(
        id=id,
        name=name,
        description=f"Stub mission: {name}",
        status=status,
        priority="medium",
        created_at=t,
        updated_at=t,
        progress=progress,
        steps_total=4,
        steps_completed=2,
        assigned_agents=["agent-1"],
        tags=["demo"],
        metadata={},
    )


missions: ModelStore = ModelStore("missions", Mission)
mission_steps: JsonStore = JsonStore("mission_steps")
schedules: ModelStore = ModelStore("schedules", Schedule)
skills: ModelStore = ModelStore("skills", Skill)
agents: ModelStore = ModelStore("agents", Agent)
mcp_servers: ModelStore = ModelStore("mcp_servers", MCPServer)
mcp_tools: ModelStore = ModelStore("mcp_tools", MCPTool)
containers: ModelStore = ModelStore("containers", Container)
memory_entries: ModelStore = ModelStore("memory_entries", MemoryEntry)
memory_namespaces: dict[str, MemoryNamespace] = {
    "default": MemoryNamespace(name="default", entry_count=1, size_bytes=1024)
}
# Persona/Workspace system — a user's live instantiations of adopted personas.
workspaces: ModelStore = ModelStore("workspaces", Workspace)
# Phase I: thumbs +/- + comment feedback, persisted per-persona (see
# services/persona_feedback.py for aggregation across workspaces).
persona_feedback: ModelStore = ModelStore("persona_feedback", PersonaFeedback)


# `settings` is deliberately absent from this module. It used to be a
# module-level `SettingsModel` that every write rebound and nothing persisted
# (#334). `services.settings_store` owns the record now, and removing the name
# rather than wrapping it is what makes a missed call site an AttributeError at
# import time instead of a write that quietly does not land — including
# `routes/setup.py`'s in-place `stores.settings.default_model = ...`, which no
# write-through wrapper could have observed. See ADR-082926-0b72.
chat_sessions: ModelStore = ModelStore("chat_sessions", ChatSession)
cli_sessions: JsonStore = JsonStore("cli_sessions")
users: ModelStore = ModelStore("users", HiveUser)
sessions: JsonStore = JsonStore("sessions")
program_contexts: JsonStore = JsonStore("program_contexts")
work_item_drafts: JsonStore = JsonStore("work_item_drafts")
dags: JsonStore = JsonStore("dags")
messages: JsonStore = JsonStore("messages")
audit_log: JsonStore = JsonStore("audit_log")
# Phase 5 Signal #3 — eval-judge verdicts keyed by run_id.
eval_verdicts: JsonStore = JsonStore("eval_verdicts")
# Phase 6 — optimizer proposals keyed by proposal_id.
optimizer_proposals: JsonStore = JsonStore("optimizer_proposals")
# Task #27 — per-user, per-provider non-secret config (e.g. Airtable base_id).
# Key shape: f"{user_id}:{provider_id}" → dict[str, str].
user_provider_config: JsonStore = JsonStore("user_provider_config")
#: One entry per principal, holding that principal's dashboard layout record.
#: Here rather than beside the route because this is the boundary the
#: deployment configures for durability (#340, ADR-082926-3b80); the route
#: used to keep its own file inside the image.
dashboard_layouts: JsonStore = JsonStore("dashboard_layouts")

_all_model_stores: list[ModelStore] = [
    missions,
    schedules,
    skills,
    agents,
    mcp_servers,
    mcp_tools,
    containers,
    memory_entries,
    chat_sessions,
    users,
    workspaces,
    persona_feedback,
]
_all_json_stores: list[JsonStore] = [
    mission_steps,
    cli_sessions,
    sessions,
    program_contexts,
    work_item_drafts,
    dags,
    messages,
    audit_log,
    eval_verdicts,
    optimizer_proposals,
    user_provider_config,
    dashboard_layouts,
]


def configure_persistence(persisted_store: Any) -> None:
    """Wire a PersistedStore into all mutable stores."""
    global _persisted
    _persisted = persisted_store
    for store in _all_model_stores:
        store._persisted = persisted_store
    for store in _all_json_stores:
        store._persisted = persisted_store


def purge_all_sessions() -> int:
    """Invalidate every authenticated session. Returns the number revoked.

    Post-disclosure remediation (see ``docs/CREDENTIAL-ROTATION-RUNBOOK.md``):
    any session id an attacker read out of the session store stops resolving.
    Every user must log in again. Elevation grants live inside the session
    records, so they are revoked with them.
    """
    revoked = sessions.clear()
    logger.warning("sessions_purged count=%d", revoked)
    return revoked


def initialize_stores() -> None:
    """Load persisted data, then seed if empty."""
    for store in _all_model_stores:
        store.initialize()
    for store in _all_json_stores:
        store.initialize()
    _seed_if_empty()
    logger.info("Stores initialized (persisted=%s)", _persisted is not None)


def _seed_platform_mcp() -> None:
    """Register platform MCP catalog (multi-server) for all Hive modes."""
    from services.mcp_defaults import merge_manifest_catalog, platform_mcp_catalog

    servers, tools = merge_manifest_catalog(*platform_mcp_catalog())
    for server in servers:
        if server.id not in mcp_servers:
            mcp_servers[server.id] = server
    existing_tool_ids = {t.id for t in mcp_tools.values()}
    for tool in tools:
        if tool.id not in existing_tool_ids:
            mcp_tools[tool.id] = tool


def _seed_if_empty() -> None:
    _seed_platform_mcp()
    from settings_defaults import is_pm_poc_mode

    if is_pm_poc_mode():
        return
    _seed_missions()
    _seed_mission_steps()
    _seed_schedules()
    _seed_skills()
    _seed_agents()
    _seed_mcp_servers()
    _seed_mcp_tools()
    _seed_containers()
    _seed_memory_entries_a()
    _seed_dags()
    _seed_messages()
    # Audit log is intentionally NOT seeded: fabricating security events (logins,
    # gate_blocks, elevations) into a fresh instance's audit trail is misleading.
    # An empty audit log renders as "no records".
    _seed_memory_entries_b()


def _seed_missions() -> None:
    if len(missions) == 0:
        missions["m-1"] = _mission("m-1", "Deploy canary", "running", 0.6)
        missions["m-2"] = _mission("m-2", "Backfill embeddings", "pending", 0.0)


def _seed_mission_steps() -> None:
    if len(mission_steps) == 0:
        t = now()
        mission_steps["m-1"] = [
            MissionStep(
                id="s-1",
                mission_id="m-1",
                name="Validate config",
                description="Check env",
                status="completed",
                order=0,
                agent_id="agent-1",
                started_at=t,
                completed_at=t,
                output="ok",
                error=None,
            ),
            MissionStep(
                id="s-2",
                mission_id="m-1",
                name="Rollout",
                description="Apply change",
                status="running",
                order=1,
                agent_id="agent-1",
                started_at=t,
                completed_at=None,
                output=None,
                error=None,
            ),
        ]


def _seed_schedules() -> None:
    if len(schedules) == 0:
        t = now()
        schedules["sch-1"] = Schedule(
            id="sch-1",
            name="Nightly eval",
            description="Run benchmark suite",
            cron_expression="0 3 * * *",
            mission_template_id="tpl-eval",
            enabled=True,
            last_run=None,
            next_run=None,
            created_at=t,
            updated_at=t,
        )


def _seed_skills() -> None:
    if len(skills) == 0:
        skills["sk-1"] = Skill(
            id="sk-1",
            name="web_fetch",
            description="HTTP GET with guardrails",
            version="1.2.0",
            category="tools",
            author="hive",
            enabled=True,
            usage_count=42,
            avg_latency_ms=120.0,
            success_rate=0.98,
            tags=["network"],
            parameters=[{"name": "url", "type": "string", "required": True}],
        )


def _seed_agents() -> None:
    if len(agents) == 0:
        t = now()
        _real_agents = [
            (
                "queen",
                "Conductor",
                "Orchestrates agents, routes intents, dispatches tools",
                "cerebras-qwen-3-235b-a22b-2507",
                ["missions", "tools", "routing", "chat"],
                ["sk-1"],
                234,
                42.0,
                {"strategy": "react", "role": "queen"},
            ),
            (
                "worker",
                "Coder",
                "Writes, reviews, and refactors code",
                "mistral-codestral",
                ["code", "reasoning", "tools"],
                ["sk-1"],
                189,
                1200.0,
                {"strategy": "plan_execute", "role": "worker"},
            ),
            (
                "worker",
                "Researcher",
                "Web search, document analysis, summarization",
                "gemini-3-flash",
                ["research", "tools", "summarize"],
                ["sk-1"],
                156,
                210.0,
                {"strategy": "react", "role": "worker"},
            ),
            (
                "worker",
                "Abra",
                "Home Assistant control, IoT device management",
                "gemini-flash-lite",
                ["ha_control", "tools"],
                ["sk-1"],
                142,
                180.0,
                {"strategy": "react", "role": "worker"},
            ),
            (
                "scout",
                "Phantom",
                "Exploratory research, competitive analysis, trend detection",
                "perplexity-sonar-deep-research",
                ["research", "exploration"],
                [],
                37,
                4500.0,
                {"strategy": "react", "role": "scout"},
            ),
            (
                "drone",
                "Heartbeat",
                "System health checks, uptime monitoring, maintenance",
                "cerebras-llama8b",
                ["monitoring", "maintenance"],
                [],
                89,
                35.0,
                {"strategy": "react", "role": "drone"},
            ),
            (
                "drone",
                "DreamLoop",
                "Background memory consolidation, pattern mining, embedding backfill",
                "gemma-27b",
                ["memory", "patterns"],
                [],
                37,
                3200.0,
                {"strategy": "react", "role": "drone"},
            ),
            (
                "guard",
                "Bouncer",
                "Security gate, intent validation, privilege enforcement",
                "mistral-small",
                ["security", "gate"],
                [],
                312,
                55.0,
                {"strategy": "react", "role": "guard"},
            ),
            (
                "guard",
                "RedTeam",
                "Adversarial testing, vulnerability scanning, penetration testing",
                "mistral-devstral",
                ["security", "testing"],
                [],
                89,
                2800.0,
                {"strategy": "plan_execute", "role": "guard"},
            ),
        ]
        for i, (_role, name, desc, model, caps, _skills, _tasks, _latency, _config) in enumerate(
            _real_agents
        ):
            agents[f"agent-{i + 1}"] = Agent(
                id=f"agent-{i + 1}",
                name=name,
                description=desc,
                model=model,
                status="idle",
                capabilities=caps,
                skills=_skills,
                current_mission=None,
                tasks_completed=_tasks,
                avg_response_time_ms=_latency,
                last_active=t,
                created_at=t,
                config=_config,
            )


def _seed_mcp_servers() -> None:
    if len(mcp_servers) == 0:
        t = now()
        mcp_servers["mcp-1"] = MCPServer(
            id="mcp-1",
            name="Filesystem",
            description="Local workspace tools",
            url="http://127.0.0.1:9999/mcp",
            status="connected",
            tools_count=6,
            last_ping=t,
            version="0.4.0",
            capabilities=["tools"],
        )


def _seed_mcp_tools() -> None:
    if len(mcp_tools) == 0:
        mcp_tools["t-1"] = MCPTool(
            id="t-1",
            server_id="mcp-1",
            name="read_file",
            description="Read a UTF-8 file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            category="fs",
        )


def _seed_containers() -> None:
    if len(containers) == 0:
        t = now()
        containers["c-1"] = Container(
            id="c-1",
            name="hive-api",
            image="hive-conductor:local",
            status="running",
            ports=[{"host": 8101, "container": 8101}],
            cpu_usage=4.2,
            memory_usage_mb=256.0,
            memory_limit_mb=1024.0,
            network_rx_mb=1.2,
            network_tx_mb=0.4,
            created_at=t,
            started_at=t,
            labels={"app": "hive"},
        )


def _seed_memory_entries_a() -> None:
    # No-op placeholder retained from the original seed flow; memory_entries are
    # seeded later by _seed_memory_entries_b.
    return


def _seed_dags() -> None:
    if len(dags) == 0:
        from routes.dags import DAGEdge, DAGFile, DAGNode

        t = now()
        n1 = str(uuid4())
        n2 = str(uuid4())
        n3 = str(uuid4())
        e1 = str(uuid4())
        e2 = str(uuid4())
        dag_id = str(uuid4())
        dags[dag_id] = DAGFile(
            id=dag_id,
            name="Security Audit Pipeline",
            description="Automated security audit with Bouncer, Conductor, and RedTeam",
            nodes=[
                DAGNode(id=n1, role="guard", name="Bouncer"),
                DAGNode(id=n2, role="queen", name="Conductor"),
                DAGNode(id=n3, role="drone", name="RedTeam"),
            ],
            edges=[
                DAGEdge(id=e1, from_node=n1, to_node=n2),
                DAGEdge(id=e2, from_node=n2, to_node=n3),
            ],
            entry_node=n1,
            max_cycles=10,
            run_scout=False,
            status="draft",
            created_at=t,
            updated_at=t,
        ).model_dump(mode="json")


def _seed_messages() -> None:
    if len(messages) == 0:
        from routes.messages import Message

        t = now()
        m1_id = str(uuid4())
        m2_id = str(uuid4())
        m3_id = str(uuid4())
        messages[m1_id] = Message(
            id=m1_id,
            from_agent="RedTeam",
            to="admin",
            subject="Vulnerability found in auth flow",
            body="XSS in /v1/auth/callback",
            priority="critical",
            read=False,
            category="security",
            created_at=t,
        ).model_dump(mode="json")
        messages[m2_id] = Message(
            id=m2_id,
            from_agent="DreamLoop",
            to="all",
            subject="DreamLoop cycle 47 complete",
            body="Generated 12 new patterns from overnight analysis",
            priority="info",
            read=False,
            category="mission",
            created_at=t,
        ).model_dump(mode="json")
        messages[m3_id] = Message(
            id=m3_id,
            from_agent="Conductor",
            to="admin",
            subject="Anthropic quota at 25%",
            body="125K of 500K tokens used this billing cycle",
            priority="warning",
            read=True,
            category="quota",
            created_at=t,
        ).model_dump(mode="json")


def _seed_memory_entries_b() -> None:
    if len(memory_entries) == 0:
        t = now()
        memory_entries["mem-1"] = MemoryEntry(
            id="mem-1",
            key="default/welcome",
            value="Hive Conductor stub memory",
            namespace="default",
            tags=["seed"],
            embedding=None,
            created_at=t,
            updated_at=t,
            accessed_count=0,
            ttl_seconds=None,
        )


#: Ids of the starter session handed to a user who has none. Seeds are real
#: rows a user can read and delete, but they are not something *they* wrote,
#: so anything asking "has this person used chat yet" has to be able to tell
#: them apart (`routes/setup_checklist.py`).
SEED_SESSION_PREFIX = "chat-seed-"


def seed_chat_for(user_id: str) -> None:
    """Give `user_id` a starter session if they have none of their own.

    Was `seed_chat_if_empty()`, seeding one unowned row for the whole
    deployment. Once sessions are scoped to their owner (#312) that row belongs
    to nobody and is visible to nobody, so the welcome chat has to be seeded per
    user or it is not seeded at all.
    """
    if not user_id:
        return
    if any(s.user_id == user_id for s in chat_sessions.values()):
        return
    sid = f"{SEED_SESSION_PREFIX}{user_id}"
    t = now()
    chat_sessions[sid] = ChatSession(
        id=sid,
        user_id=user_id,
        title="Welcome",
        messages=[
            ChatMessage(
                id=str(uuid4()),
                role="user",
                content="Hello Hive",
                timestamp=t,
            ),
            ChatMessage(
                id=str(uuid4()),
                role="assistant",
                content="Hi — this is stub data from the Hive Conductor API.",
                timestamp=t,
            ),
        ],
        created_at=t,
        updated_at=t,
    )
