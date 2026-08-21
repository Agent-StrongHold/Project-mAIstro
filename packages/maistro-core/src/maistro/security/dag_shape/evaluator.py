"""DAG shape evaluator — safety (Warden) + budget/pragmatism (Sentinel) + need (proportionality).

Combines three independent judgments into one verdict:

  1. Safety   — Warden scans the synthesizer's rationale text at a new
     boundary. The rationale is LLM-generated text that later gets read by
     other agents/humans, exactly the shape Warden's L3 classifier already
     guards against (a compromised or adversarially-steered synthesizer
     smuggling an instruction into "why I need 40 nodes").
  2. Budget   — modeled as a `ProposedAction` through the existing
     delegability/Sentinel authorization path, not a bespoke node-count
     check. Reuses ADR-068's tier ladder instead of inventing a parallel one.
  3. Need     — a lightweight proportionality critic (see `proportionality.py`)
     judges whether the shape is proportional to the objective, and if not,
     names specific nodes to add or drop.

A safety failure is a hard `blocked` — not retried, since a manipulated
synthesizer isn't fixed by asking it to try again. Budget/proportionality
failures are `needs_revision` with a concrete `ShapeRevision` the caller can
feed back into one bounded re-synthesis pass.
"""

from __future__ import annotations

from maistro.security.dag_shape.proportionality import (
    ProportionalityJudge,
    RuleProportionalityJudge,
)
from maistro.security.dag_shape.types import DagShapeVerdict, ProposedDagShape, ShapeRevision
from maistro.security.delegability import DelegabilityContext, ProposedAction, evaluate_delegability
from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden

DEFAULT_PRINCIPAL = Principal(id="dag-synthesizer", kind="agent", owner="system")


async def evaluate_dag_shape(
    shape: ProposedDagShape,
    *,
    warden: Warden,
    sentinel: Sentinel,
    principal: Principal | None = None,
    proportionality_judge: ProportionalityJudge | None = None,
    budget_context: DelegabilityContext | None = None,
) -> DagShapeVerdict:
    principal = principal or DEFAULT_PRINCIPAL
    judge = proportionality_judge or RuleProportionalityJudge()

    warden_verdict = await warden.scan(shape.rationale, "dag_rationale")
    if not warden_verdict.clean:
        return DagShapeVerdict(status="blocked", safety_flags=warden_verdict.flags)
    # Only reachable when clean=True, so there are no safety flags left to carry
    # forward into the budget/proportionality verdicts below.
    safety_flags: tuple[str, ...] = ()

    action = ProposedAction(
        name=f"synth_dag:{len(shape.node_kinds)}_nodes",
        reversibility="internal",
        args={"node_count": len(shape.node_kinds), "estimated_cost": shape.estimated_cost},
    )
    decision = await evaluate_delegability(
        action, principal, sentinel, context=budget_context or DelegabilityContext()
    )
    if decision.status == "blocked":
        return DagShapeVerdict(status="blocked", safety_flags=safety_flags)
    if not decision.can_execute:
        return DagShapeVerdict(
            status="needs_revision",
            safety_flags=safety_flags,
            within_budget=False,
            revision=ShapeRevision(
                reason=(
                    "shape exceeds the delegated budget — reduce total node count "
                    "or use cheaper node kinds"
                ),
            ),
        )

    proportionality = await judge.judge(shape)
    if not proportionality.justified:
        return DagShapeVerdict(
            status="needs_revision",
            safety_flags=safety_flags,
            revision=ShapeRevision(
                add=proportionality.add,
                drop=proportionality.drop,
                reason=proportionality.reason,
            ),
        )

    return DagShapeVerdict(
        status="approved",
        safety_flags=safety_flags,
        proportionality_reason=proportionality.reason,
        confidence=decision.confidence,
    )
