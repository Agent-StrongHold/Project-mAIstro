"""DesignOrchestrateNode — DAG node wrapping DesignEngine.generate().

Registered under kind "design.orchestrate" so design workflows compose
with the maistro-core graph executor (ADR-042 / ADR-061).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from maistro.graph.nodes import register_node
from maistro.graph.nodes.base import BaseNode, NodeContext
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
    idempotent: ClassVar[bool] = False
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
