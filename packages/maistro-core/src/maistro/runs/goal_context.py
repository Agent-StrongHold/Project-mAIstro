"""The Goal context a goal-driven Run carries in its provenance (#458, #65).

The interoperability ontology (``docs/architecture/INTEROP-ONTOLOGY-v1.md``,
issue #458) names Goal as the desired-outcome owner above execution: a
Project-scoped Goal with an exact revision, exactly one accountable Agent,
and Runs as mere execution evidence. The canonical Goal *store* is #804's and
does not exist yet; until it lands, the one canonical place a goal-driven Run
can name its Goal context is ``Run.provenance`` — the same way a scheduled Run
names its occurrence (``runs.sources``).

This module is the one spelling of those keys. An admission path stamps them
onto the Run it admits; inspection surfaces (Conductor's #65 Goal projection
today, #804/#1046 surfaces later) read them back through
:func:`goal_context_of`. Like ``runs.sources`` it is a leaf: it imports
nothing from the package, so a producer and a reader that cannot import each
other can still agree on the strings.

It owns no lifecycle. It never mints goal ids, never decides Goal state, and
never derives a Goal verdict from a Run's outcome: a completed Run is
execution evidence, not a completed Goal (ontology invariants 5 and 6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: Provenance key recording the Goal a Run executes toward.
GOAL_ID_KEY = "goal_id"

#: Provenance key recording the exact Goal revision this Run consumes.
#:
#: Ontology contract: "The exact Goal revision consumed by a goal-driven Run
#: or artifact must remain recoverable. A later Goal revision must not rewrite
#: historical evidence." A goal-driven Run therefore carries the revision it
#: was admitted under; a projection may not invent or normalize it.
GOAL_REVISION_KEY = "goal_revision"

#: Provenance key naming the parent Goal when this Run executes a Subgoal.
#:
#: Subgoal lineage is Goal -> Goal (ontology relationship ``goal_subgoal``);
#: carrying the parent on the Run's Goal context keeps delegation recoverable
#: from execution evidence without a Goal store.
PARENT_GOAL_ID_KEY = "parent_goal_id"

#: Provenance key naming the Agent accountable for the Goal when admitted.
#:
#: Ontology relationship ``agent_goal_ownership``: accountability, not
#: authorization. Recorded as provenance of the admission decision; the live
#: owner is the Goal authority's fact, not this key's.
ACCOUNTABLE_AGENT_ID_KEY = "accountable_agent_id"

#: Provenance key recording the desired state the Goal describes.
DESIRED_STATE_KEY = "desired_state"

#: Provenance key recording the Goal's success condition.
SUCCESS_CONDITION_KEY = "success_condition"

#: Provenance key recording the Goal's stop condition.
STOP_CONDITION_KEY = "stop_condition"


@dataclass(frozen=True)
class GoalContext:
    """The Goal context one Run's provenance records, exactly as recorded.

    ``goal_id`` and ``goal_revision`` are the ontology's minimum for
    projecting a canonical Goal; the remaining fields are recorded-or-absent
    facts about the admission decision, never synthesized defaults.
    """

    goal_id: str
    goal_revision: str
    parent_goal_id: str | None = None
    accountable_agent_id: str | None = None
    desired_state: str | None = None
    success_condition: str | None = None
    stop_condition: str | None = None


def _clean(value: object) -> str | None:
    """A non-blank string, or None. Blank provenance is absence, not identity."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def goal_context_of(provenance: Mapping[str, object] | None) -> GoalContext | None:
    """The Goal context ``provenance`` records, or None when it names none.

    Fail-closed on the ontology's minimum: provenance that names a goal_id
    without a revision (or with blank identity on either) is *not* a Goal
    context. Guessing a revision there would let a later revision silently
    claim evidence admitted under an earlier one — the exact history rewrite
    the ``goal_revision`` contract exists to prevent. Such a Run simply is not
    projectable as goal-driven evidence yet, and a projection that wants to
    count it must say so itself rather than inherit an invented revision.
    """
    if not provenance:
        return None
    goal_id = _clean(provenance.get(GOAL_ID_KEY))
    if goal_id is None:
        return None
    revision = _clean(provenance.get(GOAL_REVISION_KEY))
    if revision is None:
        return None
    return GoalContext(
        goal_id=goal_id,
        goal_revision=revision,
        parent_goal_id=_clean(provenance.get(PARENT_GOAL_ID_KEY)),
        accountable_agent_id=_clean(provenance.get(ACCOUNTABLE_AGENT_ID_KEY)),
        desired_state=_clean(provenance.get(DESIRED_STATE_KEY)),
        success_condition=_clean(provenance.get(SUCCESS_CONDITION_KEY)),
        stop_condition=_clean(provenance.get(STOP_CONDITION_KEY)),
    )


__all__ = [
    "ACCOUNTABLE_AGENT_ID_KEY",
    "DESIRED_STATE_KEY",
    "GOAL_ID_KEY",
    "GOAL_REVISION_KEY",
    "PARENT_GOAL_ID_KEY",
    "STOP_CONDITION_KEY",
    "SUCCESS_CONDITION_KEY",
    "GoalContext",
    "goal_context_of",
]
