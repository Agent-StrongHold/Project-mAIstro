"""Super Planner: decomposes a high-level goal into parallel-safe work waves.

Takes a goal (e.g. "Port all Stronghold subsystems into maistro-engine"),
a subsystem inventory, and dependency graph. Produces a list of waves
where each wave contains work items that can run concurrently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from maistro.orchestrator.master import MasterOrchestrator, WorkItem
from maistro.orchestrator.validation import (
    PlanValidationFinding,
    PlanValidationReport,
    validate_plan,
)
from maistro.orchestrator.waves.ensemble import (
    CheckpointStore,
    EmitFn,
    ResultComparator,
    SuperPlannerConfig,
    WaveExpander,
    WaveOrchestrator,
    WaveResult,
    WaveRunner,
    WaveTask,
)

if TYPE_CHECKING:
    from maistro.security.sentinel.authz_types import Principal
    from maistro.security.sentinel.policy import Sentinel

logger = logging.getLogger("maistro.orchestrator.planner")


class PlanValidationError(Exception):
    """Raised when a plan fails pre-execution validation (SPEC-062126-a05f)."""

    def __init__(self, report: PlanValidationReport) -> None:
        self.report = report
        messages = "; ".join(f.message for f in report.findings if f.severity == "error")
        super().__init__(f"Plan validation failed: {messages}")


@dataclass
class SubsystemDef:
    task_id: str
    group: str
    description: str
    agent_role: str = "mason"
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanTemplate:
    name: str
    description: str
    subsystems: list[SubsystemDef] = field(default_factory=list)


CONSOLIDATION_TEMPLATE = PlanTemplate(
    name="stronghold-consolidation",
    description="Port Stronghold subsystems into maistro-engine",
    subsystems=[
        # Wave 0: Foundation
        SubsystemDef("A1", "foundation", "Port protocols + types", "mason"),
        SubsystemDef("A2", "foundation", "Port DI container pattern", "mason", ["A1"]),
        SubsystemDef("A3", "foundation", "Port config loader", "mason", ["A1"]),
        # Wave 1: Memory
        SubsystemDef("B1", "memory", "Port types/memory.py", "mason", ["A1"]),
        SubsystemDef("B2", "memory", "Port memory/scopes.py", "mason", ["A1"]),
        SubsystemDef(
            "B3", "memory", "Port memory/learnings/{store,extractor,promoter}", "mason", ["B1"]
        ),
        SubsystemDef(
            "B4", "memory", "Port memory/episodic/{store,tiers,retrieval}", "mason", ["B1", "B2"]
        ),
        SubsystemDef("B5", "memory", "Port memory/outcomes.py", "mason", ["B1"]),
        SubsystemDef(
            "B6",
            "memory",
            "Port persistence/pg_learnings, pg_outcomes",
            "mason",
            ["B3", "B4", "B5"],
        ),
        SubsystemDef("B7", "memory", "Wire get_engine() + Alembic migrations", "frank", ["B6"]),
        # Wave 1: Security
        SubsystemDef("C1", "security", "Port warden/patterns.py", "mason", ["A1"]),
        SubsystemDef("C2", "security", "Port warden/heuristics.py", "mason", ["C1"]),
        SubsystemDef(
            "C3", "security", "Port warden/sanitizer.py + flag_response.py", "mason", ["C1"]
        ),
        SubsystemDef("C4", "security", "Port warden/detector.py", "mason", ["C2", "C3"]),
        SubsystemDef("C5", "security", "Port warden/semantic.py (LLM fallback)", "mason", ["C4"]),
        SubsystemDef("C6", "security", "Port sentinel/{policy,validator,audit}", "mason", ["A1"]),
        SubsystemDef(
            "C7", "security", "Port sentinel/pii_filter + token_optimizer", "mason", ["A1"]
        ),
        SubsystemDef(
            "C8", "security", "Wire security into maistro security/", "frank", ["C5", "C6", "C7"]
        ),
        # Wave 1: Classifier
        SubsystemDef("D1", "classifier", "Port types/intent.py", "mason", ["A1"]),
        SubsystemDef("D2", "classifier", "Port classifier/keyword.py", "mason", ["D1"]),
        SubsystemDef("D3", "classifier", "Port classifier/llm_fallback.py", "mason", ["D1"]),
        SubsystemDef("D4", "classifier", "Port classifier/complexity.py", "mason", ["D1"]),
        SubsystemDef(
            "D5", "classifier", "Port classifier/engine.py (3-phase)", "mason", ["D2", "D3", "D4"]
        ),
        SubsystemDef("D6", "classifier", "Port classifier/multi_intent.py", "mason", ["D5"]),
        # Wave 1: Router
        SubsystemDef("E1", "router", "Port router/scoring.py (pure functions)", "mason", ["A1"]),
        SubsystemDef("E2", "router", "Port router/scarcity.py", "mason", ["A1"]),
        SubsystemDef("E3", "router", "Port router/speed.py", "mason", ["A1"]),
        SubsystemDef("E4", "router", "Port router/filter.py", "mason", ["A1"]),
        SubsystemDef(
            "E5",
            "router",
            "Port router/selector.py (RouterEngine)",
            "mason",
            ["E1", "E2", "E3", "E4"],
        ),
        SubsystemDef("E6", "router", "Port types/model.py", "mason", ["A1"]),
        # Wave 1: Agents
        SubsystemDef("F1", "agents", "Port agents/base.py", "mason", ["A1"]),
        SubsystemDef("F2", "agents", "Port agents/factory.py", "mason", ["F1"]),
        SubsystemDef("F3", "agents", "Port agents/identity.py", "mason", ["A1"]),
        SubsystemDef(
            "F4", "agents", "Port strategies/{react,plan_execute,direct,delegate}", "mason", ["F1"]
        ),
        SubsystemDef("F5", "agents", "Port strategies/builders_learning.py", "mason", ["F4", "B3"]),
        SubsystemDef("F6", "agents", "Port strategies/tool_http.py", "mason", ["F4"]),
        SubsystemDef(
            "F7", "agents", "Port agent roster (artificer, scribe, forge, etc.)", "frank", ["F4"]
        ),
        SubsystemDef("F8", "agents", "Create default agent.yaml files", "frank", ["F7"]),
        # Wave 2: Builders
        SubsystemDef("G1", "builders", "Port builders/contracts.py", "mason", ["A1"]),
        SubsystemDef("G2", "builders", "Port builders/runtime.py", "mason", ["G1", "F4"]),
        SubsystemDef(
            "G3", "builders", "Port builders/orchestrator.py (stage machine)", "mason", ["G1"]
        ),
        SubsystemDef("G4", "builders", "Port builders/spec_emitter.py", "mason", ["G1"]),
        SubsystemDef("G5", "builders", "Port builders/spec_templates.py", "mason", ["G1"]),
        SubsystemDef("G6", "builders", "Port builders/property_gen.py", "mason", ["G1"]),
        SubsystemDef("G7", "builders", "Port builders/verifier.py", "mason", ["G1"]),
        SubsystemDef("G8", "builders", "Port builders/spec_coverage.py", "mason", ["G1"]),
        SubsystemDef("G9", "builders", "Port builders/logger.py", "mason", ["G1"]),
        SubsystemDef("G10", "builders", "Port builders/services.py", "mason", ["G1"]),
        # Wave 2: A2A
        SubsystemDef("H1", "a2a", "Port a2a/delegate.py", "mason", ["A1"]),
        SubsystemDef("H2", "a2a", "Port a2a/lifecycle.py", "mason", ["H1"]),
        SubsystemDef("H3", "a2a", "Port a2a/guest_peers.py", "mason", ["H1"]),
        # Wave 2: Skills
        SubsystemDef(
            "I1", "skills", "Port skills/parser.py + security_scan", "mason", ["A1", "C5"]
        ),
        SubsystemDef("I2", "skills", "Port skills/registry.py", "mason", ["I1"]),
        SubsystemDef("I3", "skills", "Port skills/catalog.py", "mason", ["I1"]),
        SubsystemDef("I4", "skills", "Port skills/marketplace.py (SSRF-safe)", "mason", ["I1"]),
        SubsystemDef("I5", "skills", "Port skills/forge.py", "mason", ["I1"]),
        SubsystemDef("I6", "skills", "Port skills/canary.py", "mason", ["I1"]),
        SubsystemDef("I7", "skills", "Port skills/fixer.py", "mason", ["I1"]),
        SubsystemDef("I8", "skills", "Port skills/connectors.py", "mason", ["I2"]),
        SubsystemDef("I9", "skills", "Port skills/loader.py", "mason", ["I2"]),
        SubsystemDef("I10", "skills", "Port types/skill.py", "mason", ["A1"]),
        # Wave 2: Persistence
        SubsystemDef("K1", "persistence", "Port persistence/pg_agents.py", "mason", ["F3", "B6"]),
        SubsystemDef("K2", "persistence", "Port persistence/pg_learnings.py", "mason", ["B3"]),
        SubsystemDef("K3", "persistence", "Port persistence/pg_outcomes.py", "mason", ["B5"]),
        SubsystemDef("K4", "persistence", "Port persistence/pg_audit.py", "mason", ["A1"]),
        SubsystemDef("K5", "persistence", "Port persistence/pg_sessions.py", "mason", ["A1"]),
        SubsystemDef("K6", "persistence", "Port persistence/pg_quota.py", "mason", ["A1"]),
        SubsystemDef("K7", "persistence", "Port persistence/pg_prompts.py", "mason", ["A1"]),
        # Wave 3: Master Orchestrator + Super Planner
        SubsystemDef("J1", "orchestrator", "Design Master Orchestrator protocol", "frank", ["A1"]),
        SubsystemDef("J2", "orchestrator", "Implement Super Planner", "mason", ["J1", "F4"]),
        SubsystemDef(
            "J3", "orchestrator", "Implement Master Orchestrator dispatch", "mason", ["J1", "G3"]
        ),
        SubsystemDef("J4", "orchestrator", "Implement Progress Monitor", "mason", ["J1"]),
        SubsystemDef(
            "J5", "orchestrator", "Implement Security Scanner gate", "mason", ["J1", "C5"]
        ),
        SubsystemDef(
            "J6", "orchestrator", "Wire Master Orchestrator into server API", "frank", ["J3"]
        ),
        # Wave 4: Integration
        SubsystemDef(
            "L1",
            "integration",
            "Update conductor-router to import maistro-core",
            "frank",
            ["B7", "C8", "D6", "E5", "F8"],
        ),
        SubsystemDef(
            "L2",
            "integration",
            "Update Project Turing to import maistro-core + turing",
            "frank",
            ["B7", "C8", "D6", "E5", "F8"],
        ),
        SubsystemDef(
            "L3",
            "integration",
            "Update maistro-server to use all ported subsystems",
            "frank",
            ["B7", "C8", "D6", "E5", "F8", "G10", "H3", "I9", "K7"],
        ),
        SubsystemDef("L4", "integration", "Update ADRs for new layout", "frank", ["L3"]),
        SubsystemDef("L5", "integration", "Write CLAUDE.md for maistro-engine", "frank", ["L4"]),
    ],
)


def _topological_sort(items: list[SubsystemDef]) -> list[list[SubsystemDef]]:
    """Group items into waves based on dependency depth.

    Wave 0 = no dependencies. Wave N = max dependency depth N.
    Items in the same wave have no dependency on each other → can run in parallel.
    """
    depths: dict[str, int] = {}
    item_map = {s.task_id: s for s in items}
    in_progress: set[str] = set()

    def get_depth(tid: str) -> int:
        if tid in depths:
            return depths[tid]
        if tid in in_progress:
            raise ValueError(f"Dependency cycle detected involving task {tid!r}")
        item = item_map.get(tid)
        if item is None or not item.depends_on:
            depths[tid] = 0
            return 0
        in_progress.add(tid)
        try:
            max_dep_depth = max(get_depth(d) for d in item.depends_on)
        finally:
            in_progress.discard(tid)
        depths[tid] = max_dep_depth + 1
        return depths[tid]

    for item in items:
        get_depth(item.task_id)

    max_depth = max(depths.values()) if depths else 0
    waves: list[list[SubsystemDef]] = [[] for _ in range(max_depth + 1)]
    for item in items:
        waves[depths[item.task_id]].append(item)

    return waves


class SuperPlanner:
    """Decomposes a goal into parallel-safe waves for the Master Orchestrator."""

    def __init__(self, template: PlanTemplate | None = None) -> None:
        self._template = template or CONSOLIDATION_TEMPLATE

    def plan(self) -> list[list[WorkItem]]:
        """Produce waves of WorkItems from the template."""
        raw_waves = _topological_sort(self._template.subsystems)
        result: list[list[WorkItem]] = []

        for wave_items in raw_waves:
            work_items = [
                WorkItem(
                    group=item.group,
                    task_id=item.task_id,
                    description=item.description,
                    agent_role=item.agent_role,
                    depends_on=list(item.depends_on),
                    metadata=dict(item.metadata),
                )
                for item in wave_items
            ]
            result.append(work_items)

        return result

    def build_orchestrator(
        self,
        *,
        max_concurrent: int = 5,
        max_retries: int = 2,
    ) -> MasterOrchestrator:
        """Create a MasterOrchestrator loaded with this plan."""
        orchestrator = MasterOrchestrator(
            max_concurrent_per_wave=max_concurrent,
            max_retries=max_retries,
        )
        orchestrator.load_plan(self.plan())
        return orchestrator

    async def build_validated_orchestrator(
        self,
        *,
        max_concurrent: int = 5,
        max_retries: int = 2,
        max_total_cost: float | None = None,
        principal: Principal | None = None,
        sentinel: Sentinel | None = None,
    ) -> MasterOrchestrator:
        """Validate the plan (SPEC-062126-a05f) before building a MasterOrchestrator.

        Raises PlanValidationError if the plan fails validation (cycle, over-budget,
        or authority-exceeded) — refuses to hand back an orchestrator for an invalid plan.
        """
        try:
            waves = self.plan()
        except ValueError as exc:
            finding = PlanValidationFinding(code="cycle", severity="error", message=str(exc))
            raise PlanValidationError(PlanValidationReport(findings=(finding,))) from exc

        report = await validate_plan(
            waves,
            max_total_cost=max_total_cost,
            principal=principal,
            sentinel=sentinel,
        )
        if not report.is_valid:
            raise PlanValidationError(report)

        orchestrator = MasterOrchestrator(
            max_concurrent_per_wave=max_concurrent,
            max_retries=max_retries,
        )
        orchestrator.load_plan(waves)
        return orchestrator

    def build_wave_orchestrator(
        self,
        runner: WaveRunner,
        *,
        expander: WaveExpander | None = None,
        comparator: ResultComparator | None = None,
        checkpoint_store: CheckpointStore | None = None,
        config: SuperPlannerConfig | None = None,
        emit: EmitFn | None = None,
    ) -> WaveOrchestrator:
        """Create a wave-ensemble orchestrator (SPEC-070226-b624 / ADR-071)."""
        return WaveOrchestrator(
            runner,
            expander=expander,
            comparator=comparator,
            checkpoint_store=checkpoint_store,
            config=config,
            emit=emit,
        )

    async def execute_ensemble(
        self,
        task: WaveTask,
        runner: WaveRunner,
        *,
        expander: WaveExpander | None = None,
        comparator: ResultComparator | None = None,
        checkpoint_store: CheckpointStore | None = None,
        config: SuperPlannerConfig | None = None,
        emit: EmitFn | None = None,
    ) -> WaveResult:
        """Execute ``task`` as a Repertoire wave ensemble; return the best result.

        Expands the task into parallel isolated waves, runs them concurrently
        with per-wave timeouts, checkpoints before/after (ADR-056), and picks
        one winner via the comparator (ADR-070/071).
        """
        orchestrator = self.build_wave_orchestrator(
            runner,
            expander=expander,
            comparator=comparator,
            checkpoint_store=checkpoint_store,
            config=config,
            emit=emit,
        )
        return await orchestrator.execute(task)

    def summary(self) -> dict[str, Any]:
        """Return a summary of the plan without executing it."""
        waves = self.plan()
        groups: dict[str, int] = {}
        total_deps = 0
        for wave in waves:
            for item in wave:
                groups[item.group] = groups.get(item.group, 0) + 1
                total_deps += len(item.depends_on)

        return {
            "template": self._template.name,
            "total_items": sum(len(w) for w in waves),
            "total_waves": len(waves),
            "groups": groups,
            "total_dependencies": total_deps,
            "wave_sizes": [len(w) for w in waves],
        }
