"""Eval-on-Run: scoring as evidence on the execution spine (M7-A3, #792).

Scoring a design artifact is part of the same execution that produced it. The
score is a `RunEvalScore` row on the producing `Run` — naming the NodeRun and
Attempt that produced the scored evidence, the exact Goal revision, and the
exact Rubric revision — never a sidecar job, never a client-side critic, and
never a second execution identity (`EvalRun`/`EvalJob` would read as one).

This module is the seam over the store for the two things a consumer needs
beyond append:

`eval_summary`
    Derives completeness and pass/fail **only** from persisted Run evidence.
    There is no in-memory flag and no setter: a Run whose eval records were
    never written cannot report "eval complete", because complete is a
    property of the queried records, not of anybody's intention. #779
    (cross-artifact consistency) consumes these records; it does not re-implement
    them, and M4 promotion (#21) is a different, Goal-scoring flow.

`open_re_eval_attempt`
    A re-evaluation — including the retry after a failed dimension — is a new
    Attempt on the same NodeRun of the same Run/Graph, never a new anonymous
    generation. Prior records are append-only evidence and stay queryable.

Method dispatch is deliberately not here. Deterministic rubric methods run
in-process at the caller (same spirit as persona `RubricEval.score`); a
model-judge method reaches its judge through Capability → Provider → Binding →
Invocation, which is a caller concern (ADR-061: the engine does not call an
LLM); a human method parks the Run on the HITL fence (M7-A5) and records the
score when the person answers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from maistro.runs.model import Attempt, RunEvalScore
from maistro.runs.store import NodeRunNotFound, RunStore

__all__ = [
    "EvalSummary",
    "eval_summary",
    "open_re_eval_attempt",
]


@dataclass(frozen=True)
class EvalSummary:
    """What the persisted eval evidence for one Run says, for one Rubric revision.

    Every field is a projection of `records` — the durable rows. `complete`
    answers "has every requested dimension been scored on this Run at this
    Rubric revision", and `passed` answers "do the *latest* scores all pass";
    a later record for a dimension supersedes, without deleting, the earlier
    ones.
    """

    run_id: str
    rubric_id: str
    rubric_revision: int
    dimension_ids: tuple[str, ...]
    records: tuple[RunEvalScore, ...]
    latest_by_dimension: Mapping[str, RunEvalScore]
    missing_dimensions: tuple[str, ...]
    failed_dimensions: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Every requested dimension has at least one persisted score record."""
        return not self.missing_dimensions

    @property
    def passed(self) -> bool:
        """Complete, and the latest record of every dimension passed."""
        return self.complete and not self.failed_dimensions


async def eval_summary(
    store: RunStore,
    run_id: str,
    *,
    rubric_id: str,
    rubric_revision: int,
    dimension_ids: Iterable[str],
) -> EvalSummary:
    """Project one Run's persisted eval evidence into a completeness answer.

    Reads the store — nothing else. A caller holding an unscored Run in memory,
    a DesignProject, or UI state has no path to `complete=True` here: the
    records must be on the Run's durable evidence or the dimensions are
    `missing`.
    """
    dimensions = tuple(dimension_ids)
    if not dimensions:
        raise ValueError("dimension_ids must not be empty")
    wanted = frozenset(dimensions)
    if len(wanted) != len(dimensions):
        raise ValueError("dimension_ids must not contain duplicates")
    records = tuple(
        record
        for record in await store.list_eval_scores(run_id)
        if record.rubric_id == rubric_id
        and record.rubric_revision == rubric_revision
        and record.dimension_id in wanted
    )
    latest: dict[str, RunEvalScore] = {}
    for record in sorted(records, key=lambda r: (r.scored_at, r.eval_id)):
        latest[record.dimension_id] = record
    missing = tuple(d for d in dimensions if d not in latest)
    failed = tuple(d for d, record in sorted(latest.items()) if not record.passed)
    return EvalSummary(
        run_id=run_id,
        rubric_id=rubric_id,
        rubric_revision=rubric_revision,
        dimension_ids=dimensions,
        records=records,
        latest_by_dimension=dict(latest),
        missing_dimensions=missing,
        failed_dimensions=failed,
    )


async def open_re_eval_attempt(
    store: RunStore,
    run_id: str,
    node_run_id: str,
) -> Attempt:
    """Open the Attempt a re-evaluation scores under (M7-A3 retry semantics).

    The NodeRun must belong to `run_id` and still be open — a re-evaluation of a
    dimension on a closed spine node is a new NodeRun on the same Graph, not a
    rewrite of history. Either way the prior eval records are untouched: the
    store's eval API is append-only, so the failed record stays queryable after
    the retry that supersedes it.
    """
    node_runs = await store.list_node_runs(run_id)
    node_run = next((n for n in node_runs if n.node_run_id == node_run_id), None)
    if node_run is None:
        raise NodeRunNotFound(node_run_id)
    return await store.create_attempt(node_run_id)
