"""The canonical Goal and its immutable revisions (`maistro.goals`, #1572).

`INTEROP_ONTOLOGY_V1` names this module the one owner of the shared ``Goal``
concept — ``goal_id``, parented on a Project, revisioned by ``goal_revision``
(`maistro.interop.contract`). Every Goal-consuming surface projects from here;
none of them redefines the concept or keeps a product-private Goal lifecycle.

The Goal is **desired state and accountability, not work**. It owns what is
wanted, when it is satisfied, and when to stop; the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` spine owns the doing. Nothing on
a Run's outcome writes Goal state implicitly — the only writer of a lifecycle
transition is an explicit, authorized :meth:`GoalStore.transition_goal` call —
and no execution state (running, queued, failed attempt) appears in the
vocabulary below on purpose.

Revisions are **append-only**: an accepted update appends a new immutable
:class:`GoalRevision` and moves the Goal's ``current_revision`` pointer onto
it. Nothing rewrites or deletes a revision, so the desired state a consumer
acted on stays readable after the Goal moved on — the same rule
``RunEvalScore`` holds its eval evidence to. Every mutation is a
compare-and-set on ``current_revision``: a caller that read revision N may
only mutate while the Goal still sits at N, and two concurrent mutators
produce exactly one winner.

Lifecycle states are **domain state, deliberately not a work lifecycle**:
``active`` is the only mutable state, and every other state is terminal and
final — a satisfied, cancelled, failed or superseded Goal never mutates again.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


def _require_non_empty(value: str, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


class GoalStatus(StrEnum):
    """The domain lifecycle of a Goal. ``ACTIVE`` is the only state a Goal can
    leave; the rest are terminal, and a terminal Goal is immutable."""

    ACTIVE = "active"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUPERSEDED = "superseded"


#: The states a Goal may never leave. "Terminal states are final" is enforced
#: by every store backend and by the conformance suite, not by convention.
TERMINAL_GOAL_STATUSES: frozenset[GoalStatus] = frozenset(
    {
        GoalStatus.SATISFIED,
        GoalStatus.CANCELLED,
        GoalStatus.FAILED,
        GoalStatus.SUPERSEDED,
    }
)

#: Where a lifecycle transition may go. Keys are the only states a mutation
#: can start from; terminal states have no row, so any transition out of one
#: is illegal by construction rather than by a second check to keep in step.
_ALLOWED_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.ACTIVE: frozenset(TERMINAL_GOAL_STATUSES),
}


def transition_is_legal(current: GoalStatus, target: GoalStatus) -> bool:
    """Whether a Goal in ``current`` may move to ``target``."""
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


# The condition-list fields carrying inline vulture ``V107`` markers below are
# the Goal revision's serialization surface: the store writes the record once
# via ``model_dump``/payload, and consumers (the conformance suite, then the
# Goal-enumeration and interview-commit consumers #805/#806/#1823) read them
# back through the payload round-trip. Vulture cannot see framework-driven
# serialization reads, so the declarations carry inline vulture markers
# instead of ledger debt — the same disposition the #779 result contract uses.


class GoalRevisionDraft(BaseModel):
    """The desired state a proposer appends — everything a revision carries
    except the pointer number and its acceptance time, which the store stamps
    under the compare-and-set so two proposers cannot claim one number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    desired_state: str
    success_conditions: tuple[str, ...] = ()  # noqa: V107
    stop_conditions: tuple[str, ...] = ()  # noqa: V107
    author: str

    @model_validator(mode="after")  # noqa: V105
    def _validate_draft(self) -> GoalRevisionDraft:
        _require_non_empty(self.desired_state, "GoalRevisionDraft.desired_state")
        _require_non_empty(self.author, "GoalRevisionDraft.author")
        return self


class GoalRevision(GoalRevisionDraft):
    """One immutable desired state. ``revision`` is the 1-based pointer value
    the Goal names while this is current; the chain ``[1, 2, ...]`` is
    append-only and every earlier entry stays exactly as accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int = Field(ge=1)
    created_at: datetime = Field(default_factory=_now)


class Goal(BaseModel):
    """The canonical Goal (`maistro.goals`): stable identity, Project scope,
    an accountable Agent, optional Subgoal lineage, and a lifecycle state.

    ``current_revision`` is the explicit pointer into the append-only revision
    chain; it is also the compare-and-set token every mutation is guarded by.
    """

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(default_factory=_new_id)
    workspace_id: str
    project_id: str
    agent_id: str
    parent_goal_id: str | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    current_revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")  # noqa: V105
    def _validate_goal(self) -> Goal:
        _require_non_empty(self.goal_id, "Goal.goal_id")
        _require_non_empty(self.workspace_id, "Goal.workspace_id")
        _require_non_empty(self.project_id, "Goal.project_id")
        _require_non_empty(self.agent_id, "Goal.agent_id")
        if self.parent_goal_id is not None:
            _require_non_empty(self.parent_goal_id, "Goal.parent_goal_id")
            if self.parent_goal_id == self.goal_id:
                raise ValueError("Goal cannot be its own parent")
        return self


class GoalTransitionKind(StrEnum):
    """The two explicit, recorded mutations that are not revision appends.

    A status move is the lifecycle transition itself; an agent reassign is how
    accountability changes hands. Both are attributed records, never in-place
    edits — the history below is what makes "changing the owning Agent is an
    explicit, recorded transition" auditable rather than asserted.
    """

    STATUS = "status"
    AGENT_REASSIGN = "agent-reassign"


class GoalTransitionRecord(BaseModel):
    """One recorded, attributed Goal mutation (audit surface #805/#806 read).

    The fields a kind does not use stay ``None`` rather than growing per-kind
    shapes: one append-only record type, one read path. The fields below are
    written once here and read back through the stores' payload round-trip;
    they are the record's contract, not dead weight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_id: str
    kind: GoalTransitionKind
    at: datetime = Field(default_factory=_now)
    actor: str
    #: The Goal's revision pointer after the recorded mutation — the state the
    #: actor had to hold for the compare-and-set to accept the change.
    revision: int = Field(ge=1)
    from_status: GoalStatus | None = None  # noqa: V107
    to_status: GoalStatus | None = None  # noqa: V107
    from_agent_id: str | None = None  # noqa: V107
    to_agent_id: str | None = None  # noqa: V107

    @model_validator(mode="after")  # noqa: V105
    def _validate_record(self) -> GoalTransitionRecord:
        _require_non_empty(self.goal_id, "GoalTransitionRecord.goal_id")
        _require_non_empty(self.actor, "GoalTransitionRecord.actor")
        if self.kind is GoalTransitionKind.STATUS and (
            self.from_status is None or self.to_status is None
        ):
            raise ValueError("a status transition records both sides of the move")
        if self.kind is GoalTransitionKind.AGENT_REASSIGN and (
            self.from_agent_id is None or self.to_agent_id is None
        ):
            raise ValueError("an agent reassignment records both sides of the move")
        return self


class GoalNotFound(KeyError):
    """No Goal carries this id."""

    def __init__(self, goal_id: str) -> None:
        super().__init__(goal_id)
        self.goal_id = goal_id


class GoalRevisionConflict(LookupError):
    """The compare-and-set lost: the Goal moved before this caller's write
    landed. ``expected_revision`` is what the caller held; ``current_revision``
    is what the store has now. A stale update and the loser of a concurrent
    race are the same refusal — neither says whether the other writer was
    another process or another principal."""

    def __init__(self, goal_id: str, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            f"{goal_id}: holding revision {expected_revision}, current is {current_revision}"
        )
        self.goal_id = goal_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class GoalTransitionError(ValueError):
    """A lifecycle move the vocabulary refuses: out of a terminal state, into
    the state already held, or a reassignment that reassigns nothing."""


class GoalParentInvalid(ValueError):
    """A Subgoal lineage that would not preserve the parent Goal's scope: the
    parent does not exist, or lives in another Workspace or Project."""


__all__ = [
    "TERMINAL_GOAL_STATUSES",
    "Goal",
    "GoalNotFound",
    "GoalParentInvalid",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalRevisionDraft",
    "GoalStatus",
    "GoalTransitionError",
    "GoalTransitionKind",
    "GoalTransitionRecord",
    "transition_is_legal",
]
