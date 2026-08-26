"""Pydantic models for Hive Conductor API (stub)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    title: str
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatSessionSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    title: str
    message_count: int
    updated_at: datetime


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]]
    model: str | None = None
    stream: bool = False
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None


class Mission(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    name: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "paused"]
    priority: Literal["low", "medium", "high", "critical"]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    steps_total: int = 0
    steps_completed: int = 0
    assigned_agents: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    mission_id: str
    name: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    order: int
    agent_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: str | None = None
    error: str | None = None


class Schedule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    name: str
    description: str
    cron_expression: str
    mission_template_id: str
    enabled: bool = True
    # The zone `cron_expression` is read in. Defaulted rather than required so
    # a row persisted before the column keeps loading and keeps firing, in UTC
    # exactly as it did — `services/scheduler.py` used to hardcode that.
    timezone: str = "UTC"
    # Bounded recurrence: fire this many times, then disable. `None` is
    # unbounded, which is what every schedule predating this column was.
    # Enforced on the canonical cursor (`maistro.scheduling`), not here.
    max_runs: int | None = None
    last_run: datetime | None = None
    # The Run that claimed the most recent occurrence. A projection of the
    # canonical cursor's `last_run_id`, so a caller holding a schedule can
    # reach the Run it produced (#46) instead of only a timestamp.
    last_run_id: str | None = None
    next_run: datetime | None = None
    created_at: datetime
    updated_at: datetime


class Skill(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    name: str
    description: str
    version: str
    category: str
    author: str
    enabled: bool = True
    usage_count: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    tags: list[str] = Field(default_factory=list)
    parameters: list[dict[str, Any]] = Field(default_factory=list)


class Agent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    # Persona/Workspace system: which workspace this agent was materialized
    # for (maistro.personas.expander.expand_persona(), via
    # services/agent_materialization.py). None means a global agent not
    # tied to any workspace -- every agent before this field existed.
    workspace_id: str | None = None
    name: str
    description: str
    model: str
    status: Literal["idle", "busy", "offline", "error"]
    capabilities: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tagline: str = ""
    primary_capability: str = ""
    primary_action_label: str = ""
    current_mission: str | None = None
    tasks_completed: int = 0
    avg_response_time_ms: float = 0.0
    last_active: datetime | None = None
    created_at: datetime
    config: dict[str, Any] = Field(default_factory=dict)


class MCPServer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    name: str
    description: str
    url: str
    status: Literal["connected", "disconnected", "error", "connecting"]
    #: Why the last health check ended the way it did, when the answer is not
    #: obvious from `status` alone (#368).
    #:
    #: A server blocked by the outbound SSRF policy and a server that is simply
    #: down both fail the health check, and both used to report `disconnected`.
    #: They need opposite responses -- start the server, versus authorize the
    #: origin or correct the URL -- so the operator has to be able to tell them
    #: apart. A block is now `error` and carries the reason here.
    last_error: str | None = None
    tools_count: int = 0
    last_ping: datetime | None = None
    version: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class MCPTool(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    server_id: str
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    category: str = "general"


class Container(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    name: str
    image: str
    status: Literal["running", "stopped", "starting", "stopping", "error", "restarting"]
    ports: list[dict[str, Any]] = Field(default_factory=list)
    cpu_usage: float = 0.0
    memory_usage_mb: float = 0.0
    memory_limit_mb: float = 0.0
    network_rx_mb: float = 0.0
    network_tx_mb: float = 0.0
    created_at: datetime
    started_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    key: str
    value: str
    namespace: str = "default"
    tags: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
    created_at: datetime
    updated_at: datetime
    accessed_count: int = 0
    ttl_seconds: int | None = None


class MemoryNamespace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    entry_count: int
    size_bytes: int


class CapabilitySetting(BaseModel):
    """Operator-chosen state for one capability slot (SPEC-184).

    The registry holds *what is installed*; this holds *what is active* — kept in
    settings so toggles survive restart and ride the existing PATCH path.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    active_provider: str | None = None
    provider_settings: dict[str, Any] = Field(default_factory=dict)


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_base_url: str = "http://127.0.0.1:8101"
    default_model: str = "cerebras-qwen-3-235b-a22b-2507"
    temperature: float = 0.2
    max_tokens: int = 8192
    stream_responses: bool = True
    theme: Literal["dark", "light", "system"] = "system"
    notifications_enabled: bool = False
    auto_save_sessions: bool = True
    telemetry_enabled: bool = False
    log_level: Literal["debug", "info", "warn", "error"] = "debug"
    capabilities: dict[str, CapabilitySetting] = Field(default_factory=dict)


class HiveUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    username: str
    password_hash: str
    role: Literal["admin", "user"]
    is_active: bool = True
    permissions: list[str] = Field(default_factory=list)
    did: str | None = None
    created_at: datetime

    def verify_password(self, plain: str) -> bool:
        from maistro.security.passwords import verify_password

        return verify_password(plain, self.password_hash)

    def has_permission(self, perm: str) -> bool:
        if self.role == "admin":
            return True
        return perm in self.permissions


class SessionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    username: str
    role: Literal["admin", "user"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    version: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ready: bool
    checks: dict[str, bool]
