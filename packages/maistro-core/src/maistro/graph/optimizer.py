from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from maistro.graph.types import (
    DEFAULT_SYSTEM_PROMPTS,
    AgentRole,
    GraphConfig,
    HyperagentOutput,
    NodeConfig,
    NodePerformanceMetrics,
    OptimizationSignal,
    ReviewOutput,
)

logger = logging.getLogger(__name__)

_ROLE_UPSTREAM = {
    AgentRole.PLANNER: "A task description, workspace path, and optional constraints.",
    AgentRole.CODER: (
        "A PlanOutput: summary string and a list of subtasks each with "
        "title, description, and file_paths."
    ),
    AgentRole.REVIEWER: (
        "A CodeOutput: list of files_changed, implementation description, tests_added flag."
    ),
    AgentRole.SCOUT: "A task description and workspace path.",
    AgentRole.CONDUCTOR: "Outputs from all completed sub-agent nodes.",
}

_ROLE_OUTPUT_SPEC = {
    AgentRole.PLANNER: (
        "PlanOutput — summary: str, subtasks: list[{title, description, "
        "file_paths}], estimated_files: list[str]"
    ),
    AgentRole.CODER: ("CodeOutput — files_changed: list[str], description: str, tests_added: bool"),
    AgentRole.REVIEWER: (
        "ReviewOutput — approved: bool, score: float (0-10), "
        "issues: list[str], suggestions: list[str]"
    ),
    AgentRole.SCOUT: "ScoutOutput — findings: str, relevant_files: list[str]",
    AgentRole.CONDUCTOR: "Routing decision: which node to activate next.",
}

_ROLE_DOWNSTREAM = {
    AgentRole.PLANNER: ("CODER — needs specific, actionable subtasks with file paths."),
    AgentRole.CODER: ("REVIEWER — evaluates correctness, quality, security, and completeness."),
    AgentRole.REVIEWER: "CONDUCTOR — uses approved/score to decide routing.",
    AgentRole.SCOUT: "PLANNER or CODER — provides research context.",
    AgentRole.CONDUCTOR: ("All nodes — routing decisions determine which node runs next."),
}


def _compute_bottleneck_score(
    success_rate: float,
    avg_review_score: float | None,
    avg_tokens: float,
    max_avg_tokens: float,
) -> float:
    failure = 1.0 - success_rate
    quality_gap = (10.0 - avg_review_score) / 10.0 if avg_review_score is not None else 0.5
    token_waste = (avg_tokens / max(max_avg_tokens, 1.0)) * failure
    return min(1.0, 0.5 * failure + 0.4 * quality_gap + 0.1 * token_waste)


def _role_name(role: AgentRole | str | None) -> str:
    """Render a role (enum or raw kind string) as its string identifier."""
    if role is None:
        return ""
    return role.value if isinstance(role, AgentRole) else role


def _describe_pipeline(config: GraphConfig) -> str:
    if not config.edges:
        return " -> ".join(_role_name(n) for n in config.nodes)
    parts = []
    for edge in config.edges:
        arrow = ">>" if edge.parallel else "->"
        cond = f" [{edge.condition}]" if edge.condition else ""
        to = _role_name(edge.to_role) if edge.to_role else "END"
        parts.append(f"{_role_name(edge.from_role)} {arrow} {to}{cond}")
    return ", ".join(parts)


def _node_metric_values(
    signal: OptimizationSignal, role: AgentRole | str
) -> tuple[float, int, float]:
    """Look up (success_rate, run_count, bottleneck_score) for role, with defaults."""
    node_metric = next((m for m in signal.node_metrics if m.role == role), None)
    success_rate = node_metric.success_rate if node_metric else 1.0
    run_count = node_metric.run_count if node_metric else 0
    bottleneck = node_metric.bottleneck_score if node_metric else 0.0
    return success_rate, run_count, bottleneck


def _rank_with_suffix(signal: OptimizationSignal, role: AgentRole | str) -> tuple[int, str]:
    """1-based rank of role within signal.node_metrics, plus its ordinal suffix."""
    rank = next((i + 1 for i, m in enumerate(signal.node_metrics) if m.role == role), 1)
    rank_suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank, "th")
    return rank, rank_suffix


def _review_context_line(signal: OptimizationSignal) -> str:
    if signal.avg_review_score is None:
        return ""
    return f"- Pipeline average review score: {signal.avg_review_score:.1f}/10"


def _format_failures(failure_examples: list[str]) -> str:
    if not failure_examples:
        return "  No recorded failures."
    return "\n\n".join(f"  [{i + 1}] {f}" for i, f in enumerate(failure_examples))


def _other_nodes_text(config: GraphConfig, role: AgentRole | str) -> str:
    other_roles = [r for r in config.nodes if r != role]
    if not other_roles:
        return "none"
    return ", ".join(_role_name(r) for r in other_roles)


def _role_context(role: AgentRole | str) -> tuple[str, str, str]:
    """Resolve the (upstream, output_spec, downstream) description strings for a role."""
    try:
        role_enum: AgentRole | None = role if isinstance(role, AgentRole) else AgentRole(role)
    except ValueError:
        role_enum = None
    upstream = _ROLE_UPSTREAM.get(role_enum, "task inputs") if role_enum else "task inputs"
    output_spec = (
        _ROLE_OUTPUT_SPEC.get(role_enum, "structured output") if role_enum else "structured output"
    )
    downstream = (
        _ROLE_DOWNSTREAM.get(role_enum, "next pipeline node") if role_enum else "next pipeline node"
    )
    return upstream, output_spec, downstream


class GraphOptimizer:
    def __init__(
        self,
        task_description: str,
        model: str = "default",
        llm_call: Callable[..., Awaitable[str]] | None = None,
        task_type: str = "default",
    ) -> None:
        self.task_description = task_description
        self.model = model
        self.llm_call = llm_call
        self.task_type = task_type

    def extract_signal(self, traces: list[HyperagentOutput]) -> OptimizationSignal:
        if not traces:
            raise ValueError("At least one trace is required to extract signal.")

        run_counts: dict[AgentRole | str, int] = defaultdict(int)
        success_counts: dict[AgentRole | str, int] = defaultdict(int)
        token_sums: dict[AgentRole | str, float] = defaultdict(float)
        review_scores: list[float] = []

        for trace in traces:
            if trace.review and isinstance(trace.review, ReviewOutput):
                review_scores.append(trace.review.score)
            for nr in trace.node_results:
                run_counts[nr.role] += 1
                if nr.success:
                    success_counts[nr.role] += 1
                token_sums[nr.role] += nr.tokens_used

        avg_tokens_per_role = {
            role: token_sums[role] / max(run_counts[role], 1) for role in run_counts
        }
        max_avg_tokens = max(avg_tokens_per_role.values(), default=1.0)

        pipeline_avg_review = sum(review_scores) / len(review_scores) if review_scores else None

        metrics: list[NodePerformanceMetrics] = []
        for role in run_counts:
            success_rate = success_counts[role] / run_counts[role]
            avg_tokens = avg_tokens_per_role[role]
            avg_review = pipeline_avg_review if role == AgentRole.REVIEWER else None
            bottleneck = _compute_bottleneck_score(
                success_rate, avg_review, avg_tokens, max_avg_tokens
            )
            metrics.append(
                NodePerformanceMetrics(
                    role=role,
                    run_count=run_counts[role],
                    success_rate=success_rate,
                    avg_tokens=avg_tokens,
                    avg_review_score=avg_review,
                    bottleneck_score=bottleneck,
                )
            )

        metrics.sort(key=lambda m: m.bottleneck_score, reverse=True)
        weakest = metrics[0].role

        return OptimizationSignal(
            node_metrics=metrics,
            weakest_node=weakest,
            total_runs=len(traces),
            avg_review_score=pipeline_avg_review,
        )

    def _current_prompt(self, config: GraphConfig, role: AgentRole | str) -> str:
        nc = config.node_configs.get(_role_name(role))
        if nc and nc.system_prompt:
            return nc.system_prompt
        try:
            role_enum = role if isinstance(role, AgentRole) else AgentRole(role)
        except ValueError:
            return ""
        return DEFAULT_SYSTEM_PROMPTS.get(role_enum, "")

    def _collect_failures(self, traces: list[HyperagentOutput], role: AgentRole | str) -> list[str]:
        failures = []
        for trace in traces:
            for nr in trace.node_results:
                if nr.role == role and not nr.success and nr.output:
                    failures.append(nr.output[:300])
                    if len(failures) >= 5:
                        return failures
        return failures

    async def _propose_prompt(
        self,
        config: GraphConfig,
        signal: OptimizationSignal,
        role: AgentRole | str,
        current_prompt: str,
        failure_examples: list[str],
    ) -> str:
        if self.llm_call is None:
            raise RuntimeError("llm_call is required for prompt optimization")

        success_rate, run_count, bottleneck = _node_metric_values(signal, role)
        rank, rank_suffix = _rank_with_suffix(signal, role)
        review_context = _review_context_line(signal)
        failures_text = _format_failures(failure_examples)
        other_nodes_text = _other_nodes_text(config, role)
        upstream, output_spec, downstream = _role_context(role)

        meta_prompt = (
            f"## Pipeline Objective\n{self.task_description}\n\n"
            f"## Pipeline Topology\n{_describe_pipeline(config)}\n\n"
            f"## Node Being Optimized: [{_role_name(role).upper()}]\n"
            f"Receives from upstream: {upstream}\n"
            f"Must produce: {output_spec}\n"
            f"Downstream consumer: {downstream}\n"
            f"Other nodes: {other_nodes_text}\n\n"
            f"## Current System Prompt\n```\n{current_prompt}\n```\n\n"
            f"## Performance Signal ({run_count} runs across {signal.total_runs} total)\n"
            f"- Success rate: {success_rate:.0%}\n"
            f"{review_context}\n"
            f"- Bottleneck score: {bottleneck:.2f}/1.0 "
            f"({rank}{rank_suffix} most impactful)\n\n"
            f"## Observed Failure Patterns\n{failures_text}\n\n"
            "## Rewrite Instructions\n"
            "Write an improved system prompt for this node so it acts as a "
            "coordinated team member. The improved prompt MUST:\n"
            "1. Open with the shared pipeline objective\n"
            "2. State what input it receives and in what format\n"
            "3. State what it must produce and in what format\n"
            "4. Describe what the downstream node needs from its output\n"
            "5. Address the specific failure patterns with concrete guidance\n"
            "6. Be actionable and specific\n\n"
            "Return ONLY the new system prompt text, nothing else."
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert prompt engineer specializing in multi-agent AI pipelines."
                ),
            },
            {"role": "user", "content": meta_prompt},
        ]

        result = await self.llm_call(messages, model=self.model)
        return result.strip()

    async def optimize(
        self,
        config: GraphConfig,
        traces: list[HyperagentOutput],
    ) -> GraphConfig:
        if not traces:
            logger.warning("optimizer_no_traces", extra={"task_type": self.task_type})
            return config

        signal = self.extract_signal(traces)
        target_role = signal.weakest_node

        current_prompt = self._current_prompt(config, target_role)
        failure_examples = self._collect_failures(traces, target_role)

        logger.info(
            "optimizer_start",
            extra={
                "target_role": _role_name(target_role),
                "bottleneck_score": signal.node_metrics[0].bottleneck_score,
                "total_runs": signal.total_runs,
            },
        )

        improved_prompt = await self._propose_prompt(
            config, signal, target_role, current_prompt, failure_examples
        )

        new_node_config = NodeConfig(role=target_role, system_prompt=improved_prompt)
        new_node_configs = dict(config.node_configs)
        new_node_configs[_role_name(target_role)] = new_node_config

        logger.info(
            "optimizer_complete",
            extra={
                "target_role": _role_name(target_role),
                "prompt_length_before": len(current_prompt),
                "prompt_length_after": len(improved_prompt),
            },
        )

        return config.model_copy(update={"node_configs": new_node_configs})
