"""DAG shape review — the security-review-team gate for synthesized DAG width.

Peer to `warden/` (threat detection) and `delegability/` (agent-facing
authorization): judges whether a synthesized DAG's *shape* is justified
across safety, budget/pragmatism, and need, rather than capping width with
an arbitrary node-count ceiling. Recursion *depth* is the orthogonal,
non-negotiable hard cap — see `maistro.graph.depth`.

Warden and Sentinel are the hard gates; the proportionality critic is
advisory, and its failures surface as the explicit ``approved_degraded``
status / ``unavailable`` disposition (#1191), never as a silent allow.
Degraded proceeds are logged and counted in
``maistro_security_advisory_degraded_total``.
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
    ProportionalityDisposition,
    ProposedDagShape,
    ShapeRevision,
)

__all__ = [
    "DEFAULT_PRINCIPAL",
    "DagShapeStatus",
    "DagShapeVerdict",
    "LLMProportionalityJudge",
    "ProportionalityDisposition",
    "ProportionalityJudge",
    "ProportionalityVerdict",
    "ProposedDagShape",
    "RuleProportionalityJudge",
    "ShapeRevision",
    "evaluate_dag_shape",
]
