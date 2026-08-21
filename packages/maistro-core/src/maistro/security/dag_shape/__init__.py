"""DAG shape review — the security-review-team gate for synthesized DAG width.

Peer to `warden/` (threat detection) and `delegability/` (agent-facing
authorization): judges whether a synthesized DAG's *shape* is justified
across safety, budget/pragmatism, and need, rather than capping width with
an arbitrary node-count ceiling. Recursion *depth* is the orthogonal,
non-negotiable hard cap — see `maistro.graph.depth`.
"""

from maistro.security.dag_shape.evaluator import DEFAULT_PRINCIPAL, evaluate_dag_shape
from maistro.security.dag_shape.proportionality import (
    LLMProportionalityJudge,
    ProportionalityJudge,
    ProportionalityVerdict,
    RuleProportionalityJudge,
)
from maistro.security.dag_shape.types import (
    DagShapeStatus,
    DagShapeVerdict,
    ProposedDagShape,
    ShapeRevision,
)

__all__ = [
    "DEFAULT_PRINCIPAL",
    "DagShapeStatus",
    "DagShapeVerdict",
    "LLMProportionalityJudge",
    "ProportionalityJudge",
    "ProportionalityVerdict",
    "ProposedDagShape",
    "RuleProportionalityJudge",
    "ShapeRevision",
    "evaluate_dag_shape",
]
