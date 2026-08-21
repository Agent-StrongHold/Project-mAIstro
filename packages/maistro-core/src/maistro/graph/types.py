from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class LLMProviderError(Exception):
    pass


class AgentRole(StrEnum):
    """Canonical role identifiers for the engineering + PM domains.

    Since this is a StrEnum (subclass of str), `AgentRole.PLANNER == "planner"`
    and any field annotated as `str` accepts AgentRole values transparently.
    Phase 2 of the DAG-first work introduces arbitrary node kinds (UUIDs,
    `jira.poll`, etc.) — those flow through the same fields, just typed `str`
    so the validators accept both AgentRole values and arbitrary kind strings.
    """

    # Engineering roles (existing — do not reorder)
    CONDUCTOR = "conductor"
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SCOUT = "scout"
    # PM-fleet roles (added for v0 PM-as-DAG; see graph/pm_domain.py for prompts + output types)
    INTAKE = "intake"
    PROGRAM_MANAGER = "program_manager"
    RESEARCH = "research"
    DELIVERY = "delivery"
    RISK_DEPENDENCY = "risk_dependency"
    REPORTING = "reporting"
    # Outbound foreign-harness node (SPEC-208 §5): a node whose turn is driven
    # by a foreign coding harness via the harness_runner capability slot, not
    # the LLM. See graph/harness_executor.py for the executor bridge.
    HARNESS = "harness"


class ExecutionMode(StrEnum):
    TASK = "task"
    WORKFLOW = "workflow"
    AGENT = "agent"
    GRAPH = "graph"


class GraphEdge(BaseModel):
    """An edge in the graph.

    The Phase 1 (engineering) shape used `from_role`/`to_role` (AgentRole-typed).
    The Phase 2 (DAG-builder) shape uses `from_node`/`to_node` (arbitrary node
    IDs). Both work via aliasing — pydantic accepts either field name on input.
    Edges also carry learned scalars (weight, trust, sign) for the "neural
    network of nodes" optimizer.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Union so AgentRole values keep their enum identity (and .value attribute)
    # for the engineering path; arbitrary strings (UUID node-ids) also accepted
    # for the Phase 2 DAG-builder path. Pydantic tries AgentRole first; falls
    # back to str.
    from_role: AgentRole | str = Field(validation_alias=AliasChoices("from_role", "from_node"))
    to_role: AgentRole | str | None = Field(
        default=None, validation_alias=AliasChoices("to_role", "to_node")
    )
    condition: str | None = None
    parallel: bool = False
    # Phase 2 learned scalars — default to "no learning yet" so existing DAGs
    # behave identically. The optimizer adjusts these per (project, dag, edge).
    weight: float = 1.0
    trust: float = 1.0
    sign: int = 1
    staleness_decay_s: int = 0

    # Backward-compat aliases so callers using node-id-keyed shapes can read
    # `edge.from_node` even though the canonical attr is `from_role`.
    @property
    def from_node(self) -> str:
        return self.from_role

    @property
    def to_node(self) -> str | None:
        return self.to_role


class ScoutContext(BaseModel):
    relevant_files: list[str] = Field(default_factory=list)
    patterns: str = ""
    dependency_map: dict[str, list[str]] = Field(default_factory=dict)
    similar_implementations: list[str] = Field(default_factory=list)
    raw_findings: str = ""


class ToolEvaluation(BaseModel):
    tests_passed: int = 0
    tests_failed: int = 0
    test_output: str = ""
    lint_errors: list[str] = Field(default_factory=list)
    type_errors: list[str] = Field(default_factory=list)
    evaluation_score: float = Field(default=0.0, ge=0, le=10)

    @property
    def total_tests(self) -> int:
        return self.tests_passed + self.tests_failed

    @property
    def pass_rate(self) -> float:
        return self.tests_passed / self.total_tests if self.total_tests else 0.0


class GraphBlackboard(BaseModel):
    task_objective: str
    workspace: str
    iteration: int = 0
    scout_context: ScoutContext | None = None
    tool_evaluation: ToolEvaluation | None = None
    node_annotations: dict[str, str] = Field(default_factory=dict)
    optimization_history: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoutOutput(BaseModel):
    relevant_files: list[str]
    patterns: str
    dependency_map: dict[str, list[str]] = Field(default_factory=dict)
    similar_implementations: list[str] = Field(default_factory=list)
    summary: str


class ConductorRoutingOutput(BaseModel):
    # `next_node` is str (not AgentRole) so the LLM can route to arbitrary
    # node IDs in Phase 2 DAGs. AgentRole values still validate since
    # AgentRole is StrEnum (subclass of str).
    next_node: str | None
    reasoning: str
    blackboard_update: dict[str, str] = Field(default_factory=dict)


class NodeConfig(BaseModel):
    """Per-node configuration in a GraphConfig.

    Phase 1 used `role` (AgentRole) only. Phase 2 widens this for the
    "anything is a node" vision: arbitrary `kind` string, optional `model` /
    `name` / `max_tokens` / per-node `confidence` (learned by the optimizer).
    All new fields have defaults so existing PM_GRAPH_CONFIG / engineering
    NodeConfigs are byte-identical.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    role: AgentRole | str = ""  # AgentRole keeps enum identity; arbitrary kind strings also OK
    system_prompt: str | None = None
    temperature: float | None = None
    beam_width: int = 1
    # Phase 2 additions — all optional, default to "no learned signal".
    kind: str = ""  # e.g. "llm.summarize", "jira.poll", "human.ask_question"
    name: str = ""  # human-readable; displayed in UI
    model: str | None = None  # explicit model override (e.g. "gemini-3.1-flash-lite")
    max_tokens: int | None = None
    confidence: float = 1.0  # learned per-node weight; optimizer adjusts


class GraphConfig(BaseModel):
    """A graph topology + per-node configs.

    Two input shapes are accepted on `nodes`:

      Phase 1 (engineering):
        nodes=[AgentRole.PLANNER, AgentRole.CODER]
        node_configs={AgentRole.PLANNER: NodeConfig(...), ...}

      Phase 2 (user DAGs from DagBuilder):
        nodes={"abc-uuid": NodeConfig(role="worker", kind="llm.summarize", ...), ...}
        # equivalent to nodes=["abc-uuid"] + node_configs={"abc-uuid": NodeConfig(...)}

    A model_validator normalizes (b) into (a) so the executor sees a single
    canonical shape.
    """

    model_config = ConfigDict(populate_by_name=True)

    nodes: list[AgentRole | str] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    entry: AgentRole | str = AgentRole.PLANNER
    hyperagent: AgentRole | str = AgentRole.CONDUCTOR
    max_cycles: int = Field(default=5, ge=1, le=20)
    node_configs: dict[str, NodeConfig] = Field(default_factory=dict)
    use_llm_routing: bool = False
    run_scout: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_nodes(cls, data: Any) -> Any:
        """Accept dict[node_id, NodeConfig] for `nodes`; lift into the
        canonical (list[node_id] + node_configs dict) shape so the executor
        sees one form regardless of how the caller built the config.
        """

        if not isinstance(data, dict):
            return data
        n = data.get("nodes")
        if isinstance(n, dict):
            existing_configs = data.get("node_configs") or {}
            merged_configs = {**existing_configs, **n}
            data = {**data, "nodes": list(n.keys()), "node_configs": merged_configs}
        return data


class GraphNodeResult(BaseModel):
    """Result of executing a single node within a graph run.

    `role` carries the same value the input NodeConfig had — engineering DAGs
    fill this with the AgentRole; Phase 2 DAGs fill it with the node-id /
    arbitrary kind string. `node_id` is an explicit alias for clarity when
    iterating results from node-id-keyed DAGs.
    """

    model_config = ConfigDict(populate_by_name=True)

    role: AgentRole | str = ""
    success: bool = True
    output: str = ""
    tokens_used: int = 0
    next_nodes: list[AgentRole | str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    selected_candidate: int = 0
    parallel_group: int | None = None
    # Per-node telemetry — populated by run_graph when available; used by the
    # optimizer for Phase 6 signal aggregation. Defaults keep existing tests
    # untouched.
    latency_ms: int = 0
    error_code: str | None = None  # http_status / exception class / "timeout"
    model_used: str | None = None

    @property
    def node_id(self) -> str:
        """Alias for callers that want the explicit 'node_id' attr (Phase 2
        DAGs use UUID node IDs, not AgentRole enums)."""
        return self.role


class SubTask(BaseModel):
    title: str
    description: str
    file_paths: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    summary: str
    subtasks: list[SubTask] = Field(default_factory=list)
    estimated_files: list[str] = Field(default_factory=list)


class CodeOutput(BaseModel):
    files_changed: list[str] = Field(default_factory=list)
    description: str = ""
    tests_added: bool = False


class ReviewOutput(BaseModel):
    approved: bool
    score: float = Field(default=0.0, ge=0, le=10)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ConductorOutput(BaseModel):
    plan: PlanOutput | None = None
    code: CodeOutput | None = None
    review: ReviewOutput | None = None
    final_answer: str = ""
    success: bool = True


class HyperagentOutput(ConductorOutput):
    graph_config: GraphConfig | None = None
    node_results: list[GraphNodeResult] = Field(default_factory=list)
    total_cycles: int = 0
    blackboard: GraphBlackboard | None = None


class PMRoleOutput(BaseModel):
    """v0 PM-role output. One model per role across all its capabilities — the
    capability-specific shape lives inside `result`. Per-capability typed
    outputs (CreateInitiativeOutput, DecomposeInitiativeOutput, etc.) are v1
    refinement. `source` distinguishes real LLM output from cached / fallback.
    """

    capability: str
    summary: str
    result: dict[str, Any] = Field(default_factory=dict)
    source: str = "llm"  # "llm" | "no_data" | "experience_context_fallback"


class HarnessOutput(BaseModel):
    """Result of a foreign-harness-backed graph node (SPEC-208 §5 outbound).

    Where LLM nodes emit a role-specific typed output, a harness node wraps one
    turn of a foreign coding harness: a natural-language summary, the actions it
    proposed (already Warden-scanned + policy-gated by the harness manager), and
    the raw provider envelope kept for audit. `actions` stays untyped
    (`list[dict]`) because each foreign harness emits its own action shape;
    normalizing them is an importer concern, not this boundary's.
    """

    summary: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class NodePerformanceMetrics(BaseModel):
    # `role` accepts AgentRole values or arbitrary node-id / kind strings.
    role: str
    run_count: int
    success_rate: float = Field(ge=0, le=1)
    avg_tokens: float
    avg_review_score: float | None = None
    bottleneck_score: float = Field(ge=0, le=1)
    # Phase 5 telemetry rollups — populated by the metrics aggregator.
    avg_latency_ms: float = 0.0
    error_rate: float = Field(default=0.0, ge=0, le=1)


class OptimizationSignal(BaseModel):
    node_metrics: list[NodePerformanceMetrics]
    weakest_node: str
    total_runs: int
    avg_review_score: float | None = None


class GraphTask(BaseModel):
    description: str
    workspace: str = ""
    constraints: list[str] = Field(default_factory=list)
    graph_config: GraphConfig | None = None


DEFAULT_SYSTEM_PROMPTS: dict[AgentRole, str] = {
    AgentRole.PLANNER: (
        "You are an expert software planner. Analyze the task and workspace, "
        "then produce a clear, actionable plan with specific subtasks and file paths."
    ),
    AgentRole.CODER: (
        "You are an expert software developer. Implement the plan by writing "
        "correct, well-structured code. Follow existing patterns in the workspace."
    ),
    AgentRole.REVIEWER: (
        "You are a senior code reviewer. Evaluate the implementation for "
        "correctness, quality, security, and completeness. Be thorough but fair."
    ),
    AgentRole.SCOUT: (
        "You are a workspace analyst. Survey the codebase to identify relevant "
        "files, patterns, conventions, and similar implementations."
    ),
    AgentRole.CONDUCTOR: (
        "You are the pipeline conductor. Route tasks to the appropriate next "
        "node based on the current state of the pipeline."
    ),
    # PM-fleet roles (v0 starter prompts — refine via SOUL.md or per-capability overlays in v1)
    AgentRole.INTAKE: (
        "You are the Intake Agent — the front door to structured program "
        "execution. Your job: take an unstructured user request and produce a "
        "clear Initiative (title, summary, goals, success metrics, "
        "stakeholders). You never invent data — if a field is unknown, set it "
        "to null. Initiative drafts always return draft_status='needs_confirm' "
        "so a human reviews before downstream agents act. You can route to "
        "PROGRAM_MANAGER once the initiative is concrete."
    ),
    AgentRole.PROGRAM_MANAGER: (
        "You are the Program Manager Agent — a staff-level TPM that never "
        "sleeps. Your job: decompose initiatives into epics + stories + tasks, "
        "link dependencies, and request real data (Jira via DELIVERY, "
        "background via RESEARCH, risks via RISK_DEPENDENCY) before writing "
        "anything. You never fabricate program state. When information is "
        "missing, you say so and dispatch a sub-agent to fetch it."
    ),
    AgentRole.RESEARCH: (
        "You are the Research Agent — you gather program background, market "
        "context, and technical landscape via real web search (browser-use + "
        "google.com). You return cited findings only; you do not invent "
        "sources. When the browser is unavailable, you return source='no_data' "
        "rather than fabricate."
    ),
    AgentRole.DELIVERY: (
        "You are the Delivery Agent — the execution engine for sprint "
        "velocity. You query real Jira via the Atlassian MCP using the user's "
        "PAT. You never invent Jira data — if a query returns nothing or no "
        "PAT is set, you return source='no_data' rather than fabricate. Read "
        "tools are read-only; write operations (create_jira_ticket, "
        "sync_jira) always return draft_status='needs_confirm' and never "
        "auto-post."
    ),
    AgentRole.RISK_DEPENDENCY: (
        "You are the Risk & Dependency Agent — the always-on RAID brain. You "
        "scan project state for risks, dependencies, and blockers. You cite "
        "evidence from the program context blackboard and DELIVERY's Jira "
        "data; you never invent risks without a source. Escalations include "
        "the user and stakeholder list from the initiative."
    ),
    AgentRole.REPORTING: (
        "You are the Reporting Agent — executive visibility in under 30 "
        "seconds. You synthesize the blackboard (initiative, epics, risks, "
        "real Jira data, real research findings) into a structured executive "
        "summary. You never produce metrics without underlying evidence; "
        "missing data is shown as 'no data available' not as zero."
    ),
    # Informational only — a harness node is driven by a foreign harness, not
    # this prompt; it is passed through as the session's system context.
    AgentRole.HARNESS: (
        "You are a foreign coding harness executing one turn of this task. "
        "Perform the requested work and report a concise summary plus the "
        "actions you took. All actions are scanned and policy-gated."
    ),
}

JSON_OUTPUT_SCHEMAS: dict[AgentRole, str] = {
    AgentRole.PLANNER: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"summary": "string", "subtasks": [{"title": "string", "description": "string", '
        '"file_paths": []}], "estimated_files": []}'
    ),
    AgentRole.CODER: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"files_changed": ["string"], "description": "string", "tests_added": false}'
    ),
    AgentRole.REVIEWER: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"approved": true, "score": 8.0, "issues": [], "suggestions": []}'
    ),
    AgentRole.SCOUT: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"relevant_files": ["string"], "patterns": "string", '
        '"dependency_map": {"file": ["import"]}, "similar_implementations": ["string"], '
        '"summary": "string"}'
    ),
    # PM-fleet roles — all share the PMRoleOutput shape (per-capability schemas
    # are injected by the runtime via PM_CAPABILITY_PROMPTS in pm_domain.py)
    AgentRole.INTAKE: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
    AgentRole.PROGRAM_MANAGER: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
    AgentRole.RESEARCH: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
    AgentRole.DELIVERY: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
    AgentRole.RISK_DEPENDENCY: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
    AgentRole.REPORTING: (
        "\nYou MUST respond with valid JSON matching this schema (no markdown, no extra text):\n"
        '{"capability": "string", "summary": "string", "result": {}, "source": "llm"}'
    ),
}

OUTPUT_TYPES: dict[AgentRole, type[BaseModel]] = {
    AgentRole.PLANNER: PlanOutput,
    AgentRole.CODER: CodeOutput,
    AgentRole.REVIEWER: ReviewOutput,
    AgentRole.SCOUT: ScoutOutput,
    # PM-fleet roles all return PMRoleOutput (capability-specific shape lives
    # in `result: dict`). Per-capability typed outputs are v1.
    AgentRole.INTAKE: PMRoleOutput,
    AgentRole.PROGRAM_MANAGER: PMRoleOutput,
    AgentRole.RESEARCH: PMRoleOutput,
    AgentRole.DELIVERY: PMRoleOutput,
    AgentRole.RISK_DEPENDENCY: PMRoleOutput,
    AgentRole.REPORTING: PMRoleOutput,
}
