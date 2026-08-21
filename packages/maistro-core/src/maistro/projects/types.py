"""Project model — a per-user workspace that scopes outcomes, DAGs, and
integration resources.

A `Project` is the smallest unit a user might work in: it carries the
profile prompt (what the AI should know about this work), the integration
resource bindings (which Jira projects, Airtable bases, repos belong to it),
and the per-project optimizer settings (eval cadence, budget cap, etc.).

Outcomes and durable runs are tagged with project_id so a thumbs-down on
DAG run in Project A never pollutes Project B's experience-context.

Capped at 10 projects per user by default (configurable via
MAISTRO_MAX_PROJECTS_PER_USER) — prevents accidental sprawl.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProjectMemberRole(StrEnum):
    """Role of a user within a project."""

    OWNER = "owner"  # full control + can add/remove members
    EDITOR = "editor"  # can mutate DAGs + credentials + run pulses
    VIEWER = "viewer"  # read-only (sees runs, can submit thumbs)


class ProjectMember(BaseModel):
    """A user's membership in a project."""

    user_id: str
    role: ProjectMemberRole = ProjectMemberRole.OWNER
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JiraResourceBinding(BaseModel):
    """One Jira project bound to this Maistro project."""

    project_key: str  # e.g. "PROJ"
    flavor: str = "server"  # "server" | "cloud"
    site_url: str = ""  # https://jira.example.com or https://acme.atlassian.net


class AirtableResourceBinding(BaseModel):
    """One Airtable base bound to this Maistro project.

    `table_descriptions` is the user-supplied "what does this table track?"
    text — injected into LLM prompts as project context so the AI knows what
    each table means.
    """

    base_id: str
    base_name: str = ""
    table_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="table_name → user-supplied description (one line)",
    )


class RepoResourceBinding(BaseModel):
    """One GitHub or GitLab repo bound to this Maistro project."""

    host: str = "github_enterprise"  # github_enterprise | gitlab_enterprise | github | gitlab
    owner: str = ""
    name: str = ""
    description: str = ""  # what this repo is in this project's context


class ProjectSettings(BaseModel):
    """Per-project tunables.

    Each project may set its own optimizer cadence / budget. Defaults are
    safe-conservative; the user dials them up as they trust the optimizer.
    """

    model_config = ConfigDict(extra="ignore")

    eval_judge_cadence_runs: int = Field(
        default=5,
        ge=1,
        le=100,
        description="External eval-judge fires every N DAG runs",
    )
    monthly_budget_usd: float = Field(
        default=100.0,
        ge=0.0,
        description="Project-level $ cap; intended to halt non-critical runs at 100%. "
        "NOT YET ENFORCED: no spend ledger consults it, so the cap does not "
        "bound anything today.",
    )
    edit_lock_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="How long user-edited params are locked from auto-mutation",
    )
    auto_apply_topology_changes: bool = Field(
        default=False,
        description="If True, optimizer applies topology mutations directly; "
        "if False, they go to the OptimizationInbox for approval.",
    )


class Project(BaseModel):
    """A user-owned (or team-shared) workspace.

    The `profile_markdown` is the most important field — it's injected as a
    prelude into every fleet LLM call's system prompt so the AI knows what
    this project is about. Set during the onboarding wizard.

    DOMAIN-NEUTRAL: PM Fleet is one *use case* riding on maistro; this
    record is shaped so a different use case (engineering RFC review,
    customer-support triage, marketing-campaign planning) plugs in by
    setting a different `use_case` value + composing different DAGs.
    The frontend reads `use_case` to pick which page set + nav label to
    render. No PM-specific fields live here.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    owner_user_id: str
    name: str
    summary: str = ""
    profile_markdown: str = Field(
        default="",
        description=(
            "One-paragraph project profile injected into every fleet agent's "
            "system prompt. Set during onboarding; user can edit any time."
        ),
    )
    use_case: str = Field(
        default="generic",
        description=(
            "Use-case tag that lets the frontend pick page set + nav labels. "
            "Examples: "
            "'pm_fleet' (current POC; program-management), "
            "'canvas_creative' (creative teams composing ad art via the "
            "maistro-canvas image-gen substrate — same DAG executor, "
            "different node kinds image.generate / image.composite / "
            "human.approve_draft for art-director review), "
            "'engineering_rfc' (code review / RFC drafting), "
            "'support_triage', 'marketing_campaign', 'generic'. "
            "The maistro substrate is identical across all of them; only "
            "the UI shell + default DAG templates + which node kinds are "
            "in the catalog differ per use case."
        ),
    )
    members: list[ProjectMember] = Field(default_factory=list)
    jira_bindings: list[JiraResourceBinding] = Field(default_factory=list)
    airtable_bindings: list[AirtableResourceBinding] = Field(default_factory=list)
    repo_bindings: list[RepoResourceBinding] = Field(default_factory=list)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    # === Hyperagent-shaped meta-DAG (each project IS one) ================
    # A project's central artifact is a single hyperagent-shaped DAG. Its
    # nodes can be atomic kinds (jira.poll, llm.summarize, …), composite
    # sub-DAGs (registered as callable agents under agent_dag_ids), or
    # invocations of project-enabled skills. The meta-DAG itself is just
    # another DAG row in stores.dags — `meta_dag_id` is the pointer.
    meta_dag_id: str | None = Field(
        default=None,
        description=(
            "ID of the project's top-level hyperagent meta-DAG. When the user "
            "clicks 'Run' on the project, this DAG executes. None until the "
            "onboarding wizard finishes."
        ),
    )
    agent_dag_ids: list[str] = Field(
        default_factory=list,
        description=(
            "DAG IDs that the meta-DAG may invoke as sub-agents. Each is a "
            "saved DAG registered under dag:<id> in the agent catalog. "
            "Per-project so use cases don't see each other's agents."
        ),
    )
    enabled_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skill IDs (from maistro.skills.registry) available inside this "
            "project's DAGs. Per-project allowlist — a PM project might "
            "enable 'jira_search', 'web_research'; an art project enables "
            "'image_describe', 'color_palette_pick'. NOT YET ENFORCED: "
            "Project never reaches the graph executor, so nothing consults "
            "this list and every registered skill is reachable. Do not treat "
            "it as a security boundary until skill dispatch reads it."
        ),
    )
    enabled_mcp_servers: list[str] = Field(
        default_factory=list,
        description=(
            "MCP server IDs this project's DAGs may invoke (from the "
            "platform MCP catalog: 'mcp-atlassian-server', "
            "'mcp-atlassian-rovo', 'mcp-filesystem-local', etc.). Intended "
            "semantics: empty list = no outbound MCP calls allowed, explicit "
            "allowlist required. NOT YET ENFORCED: nothing reads this field, "
            "so the default empty list currently denies nothing. Do not treat "
            "it as a security boundary until MCP dispatch reads it."
        ),
    )
    dashboard_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Dashboard IDs registered for this project. Each dashboard is the "
            "accumulator that `dashboard.append_section` nodes write into "
            "(per-meta-DAG). The UI lifts these to render the project's "
            "rendered output panels (Daily Report being PM's first one; "
            "Asset Board being canvas_creative's; RFC Verdicts being "
            "engineering_rfc's, etc.)."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def has_member(self, user_id: str) -> bool:
        return any(m.user_id == user_id for m in self.members) or self.owner_user_id == user_id

    def role_of(self, user_id: str) -> ProjectMemberRole | None:
        """Effective role for a given user in this project. Owner > member role."""
        if self.owner_user_id == user_id:
            return ProjectMemberRole.OWNER
        for m in self.members:
            if m.user_id == user_id:
                return m.role
        return None

    def can_mutate(self, user_id: str) -> bool:
        """Owner or editor can mutate. Viewer cannot."""
        role = self.role_of(user_id)
        return role in (ProjectMemberRole.OWNER, ProjectMemberRole.EDITOR)


class ProjectQuotaExceeded(Exception):
    """Raised when a user tries to create a project past their cap."""


class ProjectNotFound(KeyError):
    """Raised when a project_id doesn't exist."""


class ProjectAccessDenied(PermissionError):
    """Raised when a user tries to access a project they don't belong to."""
