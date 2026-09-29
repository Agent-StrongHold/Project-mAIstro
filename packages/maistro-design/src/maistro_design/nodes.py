"""Design domain nodes for the canonical maistro-core graph executor.

Registered under the shared graph node registry (ADR-042 / ADR-061) so design
work composes with — and carries the Run/NodeRun/Attempt provenance of — the
canonical executor rather than a side execution path.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from maistro.graph.nodes import register_node
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro_design.consistency import (
    ConsistencyEvaluation,
    CreativeProjectSnapshot,
    evaluate_project_snapshot,
)
from maistro_design.engine import DesignEngine
from maistro_design.skills.builtins import load_builtins
from maistro_design.skills.registry import InMemoryDesignSkillRegistry
from maistro_design.systems.importer import load_bundled
from maistro_design.systems.registry import InMemoryDesignSystemRegistry
from maistro_design.trust import TrustTier
from maistro_design.types import DiscoveryResult


class DesignOrchestrateIn(BaseModel):
    skill_slug: str = Field(description="Slug of the design skill to run, e.g. 'pitch-deck'")
    design_system_slug: str = Field(
        default="default",
        description="Slug of the design system to apply",
    )
    responses: dict[str, str] = Field(
        default_factory=dict,
        description="Discovery form responses keyed by field key",
    )


class DesignOrchestrateOut(BaseModel):
    project_id: str
    skill_slug: str
    design_system_slug: str
    trust_tier: str
    prompt_stack: str = Field(description="Assembled prompt stack ready for LLM consumption")
    canvas_id: str | None = None
    output_count: int = 0


class ConsistencyEvalOut(BaseModel):
    """Output of one cross-artifact consistency evaluation run."""

    passed: bool
    evaluation: ConsistencyEvaluation = Field(
        description="Full result contract: provenance, per-dimension verdicts, findings, refinement proposal",
    )
    proposed_refinement_artifact_ids: tuple[str, ...] = Field(default_factory=tuple)


@register_node
class DesignOrchestrateNode(BaseNode[DesignOrchestrateIn, DesignOrchestrateOut]):
    """Runs a design skill workflow: discovery validation → Warden scan → prompt-stack assembly.

    One engine instance is created per node execution (session-scoped trust isolation).
    """

    kind: ClassVar[str] = "design.orchestrate"
    # Bare ClassVar (not [str]) to inherit BaseNode's KindCategory literal type.
    kind_category: ClassVar = "composite"
    input_schema: ClassVar[type[BaseModel]] = DesignOrchestrateIn
    output_schema: ClassVar[type[BaseModel]] = DesignOrchestrateOut
    cost_hint: ClassVar[float] = 1.0
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Design: orchestrate skill"
    description: ClassVar[str] = (
        "Run a design skill workflow — validates discovery responses, applies "
        "Warden trust scanning, assembles the prompt stack. Does not call an LLM."
    )

    async def _execute(
        self,
        inputs: DesignOrchestrateIn,
        ctx: NodeContext,
    ) -> DesignOrchestrateOut:
        skill_registry = InMemoryDesignSkillRegistry()
        load_builtins(skill_registry)
        system_registry = InMemoryDesignSystemRegistry()
        load_bundled(system_registry)

        engine = DesignEngine(
            skill_registry=skill_registry,
            system_registry=system_registry,
        )

        discovery = DiscoveryResult(
            skill_slug=inputs.skill_slug,
            responses=inputs.responses,
            design_system_slug=inputs.design_system_slug,
            trust_tier=TrustTier.T3,
        )
        project = await engine.generate(discovery)

        prompt_stack = project.outputs[0].content if project.outputs else ""
        return DesignOrchestrateOut(
            project_id=project.id,
            skill_slug=project.skill_slug,
            design_system_slug=project.design_system_slug,
            trust_tier=str(project.trust_tier),
            prompt_stack=prompt_stack,
            canvas_id=project.canvas_id,
            output_count=len(project.outputs),
        )


@register_node
class ConsistencyEvalNode(BaseNode[CreativeProjectSnapshot, ConsistencyEvalOut]):
    """Cross-artifact consistency evaluation as a canonical graph node (#779).

    Wraps :func:`maistro_design.consistency.evaluate_project_snapshot` so an
    evaluation is one NodeRun with real Attempt evidence inside a Run — the
    same provenance universe as generation, refinement, and everything else.
    Deterministic and external-io-free: the verdict is computed from the
    snapshot alone, and the node proposes refinement targets without writing
    any project state.
    """

    kind: ClassVar[str] = "design.consistency_eval"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CreativeProjectSnapshot
    output_schema: ClassVar[type[BaseModel]] = ConsistencyEvalOut
    cost_hint: ClassVar[float] = 0.1
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Design: cross-artifact consistency evaluation"
    description: ClassVar[str] = (
        "Evaluate a frozen creative project snapshot for cross-artifact "
        "consistency (persona, claims, terminology, coverage, accessibility, "
        "locked decisions) and propose targeted refinement. Proposal only — "
        "this node never mutates project state."
    )

    async def _execute(
        self,
        inputs: CreativeProjectSnapshot,
        ctx: NodeContext,
    ) -> ConsistencyEvalOut:
        evaluation = evaluate_project_snapshot(inputs)
        return ConsistencyEvalOut(
            passed=evaluation.passed,
            evaluation=evaluation,
            proposed_refinement_artifact_ids=tuple(
                target.artifact_id
                for target in (evaluation.refinement.targets if evaluation.refinement else ())
            ),
        )
