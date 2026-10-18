"""Fence service composition — mint revisions, derive gate evidence, settle.

The durable stores take a fence decision with its revisions already minted
(:func:`stores.redirect_record`) and its gate evidence already derived. This
module is the composition layer that does that work through the revisions'
canonical owners before requesting the durable write, so no caller can
redirect to a revision nobody minted or accept on gate evidence nobody
scored:

- **Goal lineage** moves through the :class:`GoalRevisionRedirector` port.
  Canonical Goal persistence (#458) implements the port; the in-memory
  implementation here is a boot/test stand-in that keeps the fence from
  owning Goal identity storage.
- **Rubric revisions** are minted by the caller's ``RubricStore``
  (:mod:`maistro.projects.rubric_store`) through the structural
  :class:`RubricReviser` protocol — a redirect-rubric rebinds scoring to the
  *same* Goal revision, and a redirect-goal re-binds the Rubric onto the new
  Goal revision, both as new immutable revisions.
- **CreativeBrief versions** are projected counters on the Run's binding
  until #774's durable brief surface lands; a redirect bumps the version and
  never touches Goal or Rubric identity.
- **Accept evidence** is derived from the Run's persisted eval records via
  :func:`maistro.runs.eval.eval_summary` — never from caller-asserted UI
  state. A failing gate therefore cannot be accepted without the recorded
  rationale the decision model demands, and accept still grants no
  Capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from maistro.runs.eval import eval_summary
from maistro.runs.fence import (
    FenceError,
    FenceRedirectTarget,
    brief_version_at_least,
)

from .hitl import HitlAuthorization
from .stores import fence_binding
from .types import DurableRunRecord


class GoalRevisionRedirector(Protocol):
    """The Goal-lineage port a redirect-goal mints through (#458 seam)."""

    def mint_revision(
        self,
        goal_id: str,
        *,
        prior_revision: int,
        workspace_id: str,
        project_id: str,
    ) -> int:
        """Mint and publish the next live revision of ``goal_id``."""
        ...


class InMemoryGoalRevisionRedirector:
    """Boot/test Goal-lineage stand-in.

    Deliberately minimal: it answers exactly the redirect question — what is
    the next live revision of this Goal in this Project — and never becomes a
    Goal store. Canonical Goal persistence (#458) replaces it by implementing
    :class:`GoalRevisionRedirector`.
    """

    def __init__(self) -> None:
        self._goals: dict[tuple[str, int], tuple[str, str]] = {}

    def register_goal(
        self, goal_id: str, *, revision: int, workspace_id: str, project_id: str
    ) -> None:
        """Publish one live Goal revision (test/boot helper)."""
        if revision < 1:
            raise ValueError("goal revisions start at 1")
        self._goals[(goal_id, revision)] = (workspace_id, project_id)

    def mint_revision(
        self,
        goal_id: str,
        *,
        prior_revision: int,
        workspace_id: str,
        project_id: str,
    ) -> int:
        if self._goals.get((goal_id, prior_revision)) != (workspace_id, project_id):
            raise FenceError(
                f"goal {goal_id!r} revision {prior_revision} is not live in "
                f"workspace={workspace_id!r} project={project_id!r}; a redirect-goal "
                "mints from a live revision"
            )
        next_revision = prior_revision + 1
        self._goals[(goal_id, next_revision)] = (workspace_id, project_id)
        return next_revision


@runtime_checkable
class RubricReviser(Protocol):
    """The subset of ``RubricStore`` a fence redirect needs."""

    async def get(self, rubric_id: str) -> Any | None:
        """Latest revision of a Rubric, or ``None``."""
        ...

    async def update_dimensions(
        self,
        rubric_id: str,
        *,
        dimensions: list[Any],
        goal_revision: int | None = None,
    ) -> Any:
        """Mint the next immutable revision, bound to ``goal_revision``."""
        ...


@dataclass(frozen=True)
class _RedirectPlan:
    new_goal_revision: int | None
    new_rubric_revision: int | None
    new_brief_version: int | None


async def _plan_redirect(
    record: DurableRunRecord,
    *,
    target: FenceRedirectTarget,
    binding: dict[str, Any],
    goals: GoalRevisionRedirector | None,
    rubrics: RubricReviser | None,
    dimensions: list[Any] | None,
) -> _RedirectPlan:
    """Mint the revisions one redirect target implies — and only those."""
    if target is FenceRedirectTarget.GOAL:
        if goals is None:
            raise FenceError("redirect-goal requires a GoalRevisionRedirector")
        if rubrics is None:
            raise FenceError("redirect-goal re-binds the Rubric and requires a RubricReviser")
        new_goal = goals.mint_revision(
            str(binding["goal_id"]),
            prior_revision=int(binding["goal_revision"]),
            workspace_id=record.run.workspace_id,
            project_id=record.run.project_id,
        )
        current = await rubrics.get(str(binding["rubric_id"]))
        if current is None:
            raise FenceError(f"no rubric {binding['rubric_id']!r} to re-bind")
        revised = await rubrics.update_dimensions(
            str(binding["rubric_id"]),
            dimensions=list(dimensions) if dimensions is not None else list(current.dimensions),
            goal_revision=new_goal,
        )
        return _RedirectPlan(
            new_goal_revision=new_goal,
            new_rubric_revision=int(revised.revision),
            new_brief_version=brief_version_at_least(int(binding.get("brief_version", 1))),
        )
    if target is FenceRedirectTarget.RUBRIC:
        if rubrics is None:
            raise FenceError("redirect-rubric requires a RubricReviser")
        current = await rubrics.get(str(binding["rubric_id"]))
        if current is None:
            raise FenceError(f"no rubric {binding['rubric_id']!r} to revise")
        revised = await rubrics.update_dimensions(
            str(binding["rubric_id"]),
            dimensions=list(dimensions) if dimensions is not None else list(current.dimensions),
            # Default: the same Goal revision. Scoring changed, not the outcome.
            goal_revision=None,
        )
        return _RedirectPlan(
            new_goal_revision=None,
            new_rubric_revision=int(revised.revision),
            new_brief_version=None,
        )
    # BRIEF: creative guidance only — Goal and Rubric identity untouched.
    return _RedirectPlan(
        new_goal_revision=None,
        new_rubric_revision=None,
        new_brief_version=brief_version_at_least(int(binding.get("brief_version", 1))),
    )


async def redirect_fence(
    store: Any,
    run_id: str,
    node_id: str,
    *,
    target: FenceRedirectTarget | str,
    authorization: HitlAuthorization,
    goals: GoalRevisionRedirector | None = None,
    rubrics: RubricReviser | None = None,
    dimensions: list[Any] | None = None,
    at: datetime | None = None,
    workspace_id: str | None = None,
) -> DurableRunRecord:
    """Mint the target's revisions through their owners, then redirect the fence.

    The durable store still validates everything (:func:`stores.redirect_record`):
    exactly the target's revisions moved, the waiting NodeRun is resolved toward
    the new eligibility, and no prior revision is rewritten.
    """
    target_kind = target if isinstance(target, FenceRedirectTarget) else FenceRedirectTarget(target)
    record = await store.get(run_id)
    if record is None:
        raise KeyError(f"no such run: {run_id!r}")
    binding = fence_binding(record)
    plan = await _plan_redirect(
        record,
        target=target_kind,
        binding=binding,
        goals=goals,
        rubrics=rubrics,
        dimensions=dimensions,
    )
    settled: DurableRunRecord = await store.redirect_hitl(
        run_id,
        node_id,
        target=target_kind.value,
        authorization=authorization,
        at=at,
        workspace_id=workspace_id,
        new_goal_revision=plan.new_goal_revision,
        new_rubric_revision=plan.new_rubric_revision,
        new_brief_version=plan.new_brief_version,
    )
    return settled


async def accept_fence(
    store: Any,
    run_id: str,
    node_id: str,
    *,
    authorization: HitlAuthorization,
    rubrics: RubricReviser,
    run_store: Any,
    rationale: str = "",
    at: datetime | None = None,
    workspace_id: str | None = None,
) -> DurableRunRecord:
    """Derive the Rubric gate from persisted eval evidence, then accept.

    ``gate_passed`` and ``failing_dimensions`` come from the Run's own eval
    records at the binding's exact Rubric revision. A caller — including a UI
    — cannot assert a passing gate the records do not show, and a failing
    gate cannot pass the decision model without a recorded rationale.
    """
    record = await store.get(run_id)
    if record is None:
        raise KeyError(f"no such run: {run_id!r}")
    binding = fence_binding(record)
    rubric_id = str(binding["rubric_id"])
    rubric_revision = int(binding["rubric_revision"])
    current = await rubrics.get(rubric_id)
    if current is None:
        raise FenceError(f"no rubric {rubric_id!r} to cite on accept")
    summary = await eval_summary(
        run_store,
        run_id,
        rubric_id=rubric_id,
        rubric_revision=rubric_revision,
        dimension_ids=[dimension.id for dimension in current.dimensions],
    )
    # A dimension with no passing record — failed OR unscored — did not pass.
    # "Complete and green" is the only thing that accepts without a cited
    # override, so a UI cannot assert a passing gate the records never showed.
    not_passed = tuple(sorted(set(summary.failed_dimensions) | set(summary.missing_dimensions)))
    settled: DurableRunRecord = await store.accept_hitl(
        run_id,
        node_id,
        gate_passed=summary.passed,
        failing_dimensions=not_passed,
        authorization=authorization,
        rationale=rationale,
        at=at,
        workspace_id=workspace_id,
    )
    return settled


__all__ = [
    "GoalRevisionRedirector",
    "InMemoryGoalRevisionRedirector",
    "RubricReviser",
    "accept_fence",
    "redirect_fence",
]
