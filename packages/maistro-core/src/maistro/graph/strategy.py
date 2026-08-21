from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphTask,
    HarnessOutput,
    PlanOutput,
    PMRoleOutput,
    ReviewOutput,
    ScoutContext,
    ScoutOutput,
)


@runtime_checkable
class NodeStrategy(Protocol):
    @property
    def role(self) -> AgentRole: ...

    @property
    def output_type(self) -> type[BaseModel]: ...

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str: ...

    def score_output(self, output: BaseModel) -> float: ...

    def update_blackboard(
        self,
        output: BaseModel,
        blackboard: GraphBlackboard,
    ) -> GraphBlackboard: ...


class PlannerStrategy:
    role: AgentRole = AgentRole.PLANNER
    output_type: type[BaseModel] = PlanOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        constraints = "\n".join(f"- {c}" for c in task.constraints) if task.constraints else "None"
        return (
            f"Task: {task.description}\n\nWorkspace: {task.workspace}\nConstraints:\n{constraints}"
        )

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, PlanOutput):
            return float(len(output.subtasks))
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        return blackboard


class CoderStrategy:
    role: AgentRole = AgentRole.CODER
    output_type: type[BaseModel] = CodeOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        if plan:
            subtasks = "\n".join(
                f"{i + 1}. {s.title}: {s.description}" for i, s in enumerate(plan.subtasks)
            )
            return (
                f"Task: {task.description}\n\n"
                f"Workspace: {task.workspace}\n\n"
                f"Plan: {plan.summary}\n\n"
                f"Subtasks:\n{subtasks}"
            )
        return f"Task: {task.description}\n\nWorkspace: {task.workspace}"

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, CodeOutput):
            return float(len(output.files_changed)) + (2.0 if output.tests_added else 0.0)
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        return blackboard


class ReviewerStrategy:
    role: AgentRole = AgentRole.REVIEWER
    output_type: type[BaseModel] = ReviewOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        if code is None:
            return f"Task: {task.description}\n\nNo code output available to review."
        plan_summary = plan.summary if plan else "N/A"
        files = ", ".join(code.files_changed) or "none"
        return (
            f"Task: {task.description}\n\n"
            f"Plan summary: {plan_summary}\n"
            f"Files changed: {files}\n"
            f"Description: {code.description}\n"
            f"Tests added: {code.tests_added}"
        )

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, ReviewOutput):
            return output.score
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        return blackboard


class ScoutStrategy:
    role: AgentRole = AgentRole.SCOUT
    output_type: type[BaseModel] = ScoutOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        history_summary = ""
        if blackboard.optimization_history:
            last = blackboard.optimization_history[-1]
            weakest = getattr(last, "weakest_node", None)
            avg_score = getattr(last, "avg_review_score", None)
            if weakest:
                score_str = f", avg review {avg_score:.1f}/10" if avg_score else ""
                history_summary = (
                    f"\nOptimization history: iteration {blackboard.iteration}, "
                    f"weakest node was {weakest}{score_str}. "
                    f"Focus especially on context relevant to {weakest}."
                )
        return (
            f"Task: {task.description}\n\n"
            f"Workspace: {blackboard.workspace}\n"
            f"Iteration: {blackboard.iteration}{history_summary}\n\n"
            "Survey the workspace and provide a briefing for the engineering team."
        )

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, ScoutOutput):
            return float(len(output.relevant_files))
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        if isinstance(output, ScoutOutput):
            scout_context = ScoutContext(
                relevant_files=output.relevant_files,
                patterns=output.patterns,
                dependency_map=output.dependency_map,
                similar_implementations=output.similar_implementations,
                raw_findings=output.summary,
            )
            return blackboard.model_copy(update={"scout_context": scout_context})
        return blackboard


class ConductorStrategy:
    role: AgentRole = AgentRole.CONDUCTOR
    output_type: type[BaseModel] = PlanOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        return f"Task: {task.description}\nWorkspace: {task.workspace}"

    def score_output(self, output: BaseModel) -> float:
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        return blackboard


class PMStrategy:
    """Generic v0 strategy for PM-fleet roles.

    All six PM roles (INTAKE, PROGRAM_MANAGER, RESEARCH, DELIVERY,
    RISK_DEPENDENCY, REPORTING) share this strategy. Per-role behavior comes
    from the role-keyed `DEFAULT_SYSTEM_PROMPTS` + the per-capability prompts
    layered on at runtime via `graph/pm_domain.py` (Day 2). v1 may split into
    per-role strategy classes if their blackboard interactions diverge.
    """

    output_type: type[BaseModel] = PMRoleOutput

    def __init__(self, role: AgentRole) -> None:
        self.role = role

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        # PM nodes consume the blackboard, not the engineering plan/code/review.
        # The blackboard_prefix() in node.py prepends scout_context, annotations,
        # iteration info; this user-prompt body provides the task + (eventually)
        # the per-capability prompt template from pm_domain.py.
        constraints = "\n".join(f"- {c}" for c in task.constraints) if task.constraints else "None"
        return f"Task: {task.description}\nConstraints:\n{constraints}"

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, PMRoleOutput) and output.source == "llm":
            # Score by summary length as a v0 proxy for "the agent produced
            # substantive output." Longer = better (capped softly).
            return min(float(len(output.summary)) / 80.0, 5.0)
        return 0.0

    def update_blackboard(
        self,
        output: BaseModel,
        blackboard: GraphBlackboard,
    ) -> GraphBlackboard:
        if isinstance(output, PMRoleOutput):
            annotations = dict(blackboard.node_annotations)
            annotations[self.role.value] = output.summary
            return blackboard.model_copy(update={"node_annotations": annotations})
        return blackboard


class HarnessStrategy:
    """Prompt/output shaper for an outbound foreign-harness node (SPEC-208 §5).

    The harness itself owns the turn loop (via `graph.harness_executor`), so this
    strategy only shapes the prompt the harness receives and scores/records the
    `HarnessOutput` it returns — it never calls an LLM.
    """

    role: AgentRole = AgentRole.HARNESS
    output_type: type[BaseModel] = HarnessOutput

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        constraints = "\n".join(f"- {c}" for c in task.constraints) if task.constraints else "None"
        return (
            f"Task: {task.description}\n\nWorkspace: {task.workspace}\nConstraints:\n{constraints}"
        )

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, HarnessOutput):
            # A turn that produced actions is worth more than a bare summary.
            return float(len(output.actions)) + (1.0 if output.summary else 0.0)
        return 0.0

    def update_blackboard(self, output: BaseModel, blackboard: GraphBlackboard) -> GraphBlackboard:
        if isinstance(output, HarnessOutput) and output.summary:
            annotations = dict(blackboard.node_annotations)
            annotations[AgentRole.HARNESS.value] = output.summary
            return blackboard.model_copy(update={"node_annotations": annotations})
        return blackboard


STRATEGY_REGISTRY: dict[AgentRole, NodeStrategy] = {
    AgentRole.PLANNER: PlannerStrategy(),
    AgentRole.CODER: CoderStrategy(),
    AgentRole.REVIEWER: ReviewerStrategy(),
    AgentRole.SCOUT: ScoutStrategy(),
    AgentRole.CONDUCTOR: ConductorStrategy(),
    # PM-fleet roles all share PMStrategy with role-specific blackboard updates.
    AgentRole.INTAKE: PMStrategy(AgentRole.INTAKE),
    AgentRole.PROGRAM_MANAGER: PMStrategy(AgentRole.PROGRAM_MANAGER),
    AgentRole.RESEARCH: PMStrategy(AgentRole.RESEARCH),
    AgentRole.DELIVERY: PMStrategy(AgentRole.DELIVERY),
    AgentRole.RISK_DEPENDENCY: PMStrategy(AgentRole.RISK_DEPENDENCY),
    AgentRole.REPORTING: PMStrategy(AgentRole.REPORTING),
    # Outbound foreign-harness node (SPEC-208 §5) — driven by harness_executor.
    AgentRole.HARNESS: HarnessStrategy(),
}


def get_strategy(role: AgentRole | str) -> NodeStrategy:
    try:
        role_enum = role if isinstance(role, AgentRole) else AgentRole(role)
    except ValueError:
        role_enum = None
    strategy = STRATEGY_REGISTRY.get(role_enum) if role_enum is not None else None
    if strategy is None:
        raise ValueError(f"No strategy registered for role {role}")
    return strategy
