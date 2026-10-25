"""Types for judging synthesized DAG shape — width is justified, not capped.

Recursion depth is a hard, structural cap (`maistro.graph.depth`) because
recursion is easy to get wrong and expensive to get wrong. Width is the
opposite: a large DAG can be exactly the right shape for a task (many small
focused nodes standing in for one giant model), so instead of a blind
node-count ceiling, width is judged on three axes and, when it falls short,
told specifically what would fix it rather than just refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DagShapeStatus = Literal["approved", "needs_revision", "blocked"]


@dataclass(frozen=True)
class ProposedDagShape:
    """A synthesized DAG shape, as judged before it's allowed to execute."""

    objective: str
    node_kinds: tuple[str, ...]
    rationale: str
    estimated_cost: float = 0.0


@dataclass(frozen=True)
class ShapeRevision:
    """Actionable correction for a shape that wasn't quite justified.

    A bare "blocked" wastes the tokens and turnaround already spent on
    synthesis; this tells the synthesizer exactly what to add or drop so one
    corrective pass has a real chance of landing.
    """

    add: tuple[str, ...] = ()
    drop: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class DagShapeVerdict:
    """Combined verdict across safety, budget/pragmatism, and need.

    - ``blocked``: safety failed (Warden flagged the rationale itself as
      hostile/manipulative). Not retried — a compromised or adversarially
      steered synthesizer isn't fixed by asking it to try again.
    - ``needs_revision``: safety is clean but budget or proportionality
      didn't clear. ``revision`` carries the specific fix.
    - ``approved``: all three axes cleared.
    """

    status: DagShapeStatus
    safety_flags: tuple[str, ...] = field(default_factory=tuple)
    within_budget: bool = True
    proportionality_reason: str = ""
    revision: ShapeRevision | None = None
    confidence: float | None = None

    @property
    def can_execute(self) -> bool:
        return self.status == "approved"
