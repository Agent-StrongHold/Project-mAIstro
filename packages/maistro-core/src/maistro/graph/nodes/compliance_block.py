"""`compliance.block` — emit a negative signal that downstream nodes subtract.

A `negative_signal` node doesn't pass data forward; it writes a structured
*cost* onto the run blackboard under `metadata['penalties']`. Downstream
nodes (or the optimizer) read this list when scoring outcomes.

Use cases (Phase 2 vision):
  - Block a Jira write if the draft mentions PII patterns.
  - Penalize a research summary that cites a denylisted source.
  - Downgrade a recommendation that violates a policy gate.

In Phase 1 the node is opt-in (not part of the daily-status DAG by default).
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext


class ComplianceBlockIn(BaseModel):
    rule_id: str = Field(description="Stable identifier for this policy rule")
    severity: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Magnitude of the negative signal (downstream weights subtract this)",
    )
    reason: str = Field(default="", description="Human-readable explanation of why this fired")
    evidence: dict[str, Any] = Field(default_factory=dict)
    halt_run: bool = Field(
        default=False,
        description="If True, the executor treats this as a fatal block; default just emits the signal",
    )


class ComplianceBlockOut(BaseModel):
    rule_id: str
    severity: float
    halt_run: bool
    penalty_id: str = ""


@register_node
class ComplianceBlockNode(BaseNode[ComplianceBlockIn, ComplianceBlockOut]):
    kind: ClassVar[str] = "compliance.block"
    kind_category: ClassVar = "negative_signal"
    input_schema: ClassVar[type[BaseModel]] = ComplianceBlockIn
    output_schema: ClassVar[type[BaseModel]] = ComplianceBlockOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Compliance: block"
    description: ClassVar[str] = (
        "Emit a negative signal into the run blackboard. Optionally halts "
        "the run when triggered. Used by policy gates."
    )

    async def _execute(self, inputs: ComplianceBlockIn, ctx: NodeContext) -> ComplianceBlockOut:
        bb = ctx.blackboard
        metadata = bb.metadata if (bb is not None and hasattr(bb, "metadata")) else ctx.metadata
        penalties: list[dict[str, Any]] = list(metadata.get("penalties") or [])
        penalty_id = f"penalty:{ctx.run_id}:{ctx.node_id}:{len(penalties)}"
        penalties.append(
            {
                "id": penalty_id,
                "node_id": ctx.node_id,
                "rule_id": inputs.rule_id,
                "severity": inputs.severity,
                "reason": inputs.reason,
                "evidence": inputs.evidence,
                "halt_run": inputs.halt_run,
            }
        )
        metadata["penalties"] = penalties
        if inputs.halt_run:
            # Mark a halt request the executor will honor.
            metadata["halt_requested"] = True
            metadata["halt_reason"] = inputs.reason or inputs.rule_id

        return ComplianceBlockOut(
            rule_id=inputs.rule_id,
            severity=inputs.severity,
            halt_run=inputs.halt_run,
            penalty_id=penalty_id,
        )
