"""Recover typed node outputs that an earlier serialization contract emptied (#566).

`NodeResult.output` was declared `dict[str, Any] | BaseModel | None`. Pydantic
serializes a union member typed as bare `BaseModel` through *that declared
schema*, which has no fields, so a node returning a typed model wrote its
Attempt as `output: {}`. The fix is in the contract -- the field is
`SerializeAsAny` now -- but rows already written stay as they were written.

**What is recoverable, and why exactly that.** The executor never lost the
output logically: it dumps the model explicitly before storing `NodeRun.result`.
So for the one Attempt the NodeRun accepted, the same bytes exist a row over,
and `AcceptedNodeOutcome.attempt_result.attempt_id` names that Attempt by id.
That is an exact key, not a heuristic: a NodeRun accepts one Attempt, so an
emptied output on the accepted Attempt is restored from evidence the same
record already holds.

**What is not, and why it is not guessed at.** An Attempt the NodeRun did not
accept -- a superseded retry, a failure, an in-flight try -- has no second copy
anywhere. Its output was written once, to the field this bug emptied. Nothing
in the record distinguishes such an Attempt from one that genuinely produced
`{}`, and inventing a value for a physical execution record is worse than an
honest gap. Those are reported as unrecoverable and left untouched.

Nothing here runs on its own. Rewriting stored execution history is an
operator's decision, so this is a function an operator or a migration calls,
and it returns what it changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .types import DurableRunRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping, Sequence

    from maistro.runs.model import Attempt, NodeRun

#: Why one emptied Attempt output could not be restored.
UNRECOVERABLE_NOT_ACCEPTED = "the NodeRun accepted a different Attempt, or accepted none"
UNRECOVERABLE_NO_EVIDENCE = "the NodeRun holds no output of its own to restore from"


@dataclass(frozen=True)
class EmptiedOutput:
    """One Attempt whose persisted node output is an empty mapping."""

    attempt_id: str
    node_run_id: str
    reason: str | None = None
    """Why it stayed emptied, or None when it was restored."""


@dataclass(frozen=True)
class OutputRecoveryReport:
    """What a recovery pass found and what it did about it."""

    recovered: tuple[EmptiedOutput, ...] = ()
    unrecoverable: tuple[EmptiedOutput, ...] = ()
    #: Set when a pass changed nothing, so a caller can skip the write.
    changed: bool = field(default=False)


def _emptied_output(attempt: Attempt) -> bool:
    """True when this Attempt's result carries an output that serialized away."""
    result = attempt.result
    if not isinstance(result, dict):
        return False
    return result.get("output") == {}


def _accepted_output(node_run: NodeRun, attempt: Attempt) -> Mapping[str, Any] | None:
    """The output this NodeRun recorded for this exact Attempt, if it has one."""
    accepted = node_run.accepted_outcome
    if accepted is None or accepted.attempt_result.attempt_id != attempt.attempt_id:
        return None
    result = node_run.result
    if not isinstance(result, dict) or not result:
        return None
    return result


def recover_typed_attempt_outputs(
    record: DurableRunRecord,
) -> tuple[DurableRunRecord, OutputRecoveryReport]:
    """Restore emptied Attempt outputs from the evidence the record already holds.

    Returns the repaired record and a report naming every emptied output --
    those restored, and those left alone with the reason. The record is
    returned unchanged when nothing was restored, so a caller that only wants
    the survey can read the report and discard the rest.
    """
    node_runs = {node_run.node_run_id: node_run for node_run in record.node_runs}
    recovered: list[EmptiedOutput] = []
    unrecoverable: list[EmptiedOutput] = []
    attempts: list[Attempt] = []

    for attempt in record.attempts:
        if not _emptied_output(attempt):
            attempts.append(attempt)
            continue
        node_run = node_runs.get(attempt.node_run_id)
        output = None if node_run is None else _accepted_output(node_run, attempt)
        if output is None:
            reason = _unrecoverable_reason(node_run, attempt)
            unrecoverable.append(
                EmptiedOutput(attempt.attempt_id, attempt.node_run_id, reason=reason)
            )
            attempts.append(attempt)
            continue
        assert isinstance(attempt.result, dict)
        attempts.append(
            attempt.model_copy(update={"result": {**attempt.result, "output": dict(output)}})
        )
        recovered.append(EmptiedOutput(attempt.attempt_id, attempt.node_run_id))

    report = OutputRecoveryReport(
        recovered=tuple(recovered),
        unrecoverable=tuple(unrecoverable),
        changed=bool(recovered),
    )
    if not recovered:
        return record, report
    return record.model_copy(update={"attempts": tuple(attempts)}), report


def _unrecoverable_reason(node_run: NodeRun | None, attempt: Attempt) -> str:
    accepted = None if node_run is None else node_run.accepted_outcome
    if accepted is None or accepted.attempt_result.attempt_id != attempt.attempt_id:
        return UNRECOVERABLE_NOT_ACCEPTED
    return UNRECOVERABLE_NO_EVIDENCE


def survey_emptied_outputs(records: Sequence[DurableRunRecord]) -> OutputRecoveryReport:
    """Report what a recovery pass over `records` would restore, changing nothing."""
    recovered: list[EmptiedOutput] = []
    unrecoverable: list[EmptiedOutput] = []
    for record in records:
        _repaired, report = recover_typed_attempt_outputs(record)
        recovered.extend(report.recovered)
        unrecoverable.extend(report.unrecoverable)
    return OutputRecoveryReport(
        recovered=tuple(recovered),
        unrecoverable=tuple(unrecoverable),
        changed=False,
    )


__all__ = [
    "UNRECOVERABLE_NOT_ACCEPTED",
    "UNRECOVERABLE_NO_EVIDENCE",
    "EmptiedOutput",
    "OutputRecoveryReport",
    "recover_typed_attempt_outputs",
    "survey_emptied_outputs",
]
