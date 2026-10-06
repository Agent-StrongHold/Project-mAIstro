"""Remote Agent lifecycle normalization (M9-D3, epic #941).

Maps an external Agent protocol's task lifecycle onto canonical MAIstro
execution semantics, so protocol quirks cannot create false completion,
duplicate work, or irreconcilable cancellation state.

The one rule every function here serves: **canonical Run truth is written only
by the canonical settle path** (`maistro.runs`), never by a remote peer. A
remote protocol state is an *observation*. This module decides, from the raw
state string a peer reported and the canonical child Run's current facts:

- what the observation *means* (:func:`normalize_remote_state` — decomposed
  onto the delegation's own classified outcome ladder plus two orthogonal
  facts, with unknown values never guessed into completion);
- whether it may *settle* the delegation (:func:`decide_settlement` — a
  terminal answer for an already-terminal child is refused, so a remote
  ``completed`` can never override canonical Run terminal truth);
- whether any *retry* is allowed and in what shape (:func:`decide_retry` —
  ambiguous or lost responses reconcile, they never re-dispatch; explicit
  failures may only ever be retried through the canonical effect-key
  reservation);
- what a *cancellation* records when the peer never acknowledges
  (:func:`decide_cancellation` — cancellation is decided locally and remains
  truthful with or without a remote acknowledgement);
- how *progress* is recorded across reconnects (:func:`record_progress` —
  observations keyed to the delegation's existing identity, never minting a
  second NodeRun/Attempt).

Everything here is pure: no I/O, no store access, no state. The caller (the
``agent.delegate_remote`` graph node) owns persistence and the canonical
transitions; these helpers own the decisions so the transport, the node and
the conformance suite cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maistro.graph.nodes.agent_delegate_remote import DelegationStatus

__all__ = [
    "PROGRESS_HISTORY_KEY",
    "PROGRESS_HISTORY_LIMIT",
    "CancellationProjection",
    "CanonicalDelegationTruth",
    "RemoteProgressObservation",
    "RemoteRetryDecision",
    "RemoteState",
    "RetryDecision",
    "SettlementDecision",
    "decide_cancellation",
    "decide_retry",
    "decide_settlement",
    "normalize_remote_state",
    "record_progress",
    "settle_outcome",
]


@dataclass(frozen=True)
class RemoteState:
    """The projection of one raw remote protocol state, decomposed.

    Deliberately *not* a second state ladder: a remote observation is judged
    onto the delegation's own outcome vocabulary — the ``DelegationStatus``
    Literal of ``agent.delegate_remote``, already classified in
    ``quality/execution-lifecycles.json`` — plus two orthogonal facts:

    ``outcome``
        the recognized terminal outcome (``completed``, ``failed``,
        ``rejected``, ``timed_out``), or ``None`` when the raw state is not
        one. A remote cancellation projects onto ``failed`` (the work did
        not complete) with :attr:`cancelled` naming the difference;
    ``progress``
        the raw state is a recognized in-flight report (submitted, working,
        awaiting input) — the delegation stays open;
    ``cancelled``
        the remote work was cancelled or revoked: a different fact from a
        failure (declined-by-peer and cancelled-elsewhere own their retry
        decisions and their reasons).

    An unmapped raw value is unknown by construction: ``outcome`` is
    ``None`` and ``progress`` is ``False`` — never proximity-matched into a
    completion, because guessing a remote "almost completed" into a
    completion is exactly the false-completion failure this module exists to
    prevent. Protocol-specific states stay observable through the raw string
    that mapped here; they are projections of a remote lifecycle, never
    canonical authorities.
    """

    outcome: DelegationStatus | None = None
    progress: bool = False
    cancelled: bool = False

    @property
    def settles(self) -> bool:
        """Whether this observation is a terminal outcome the child Run may take."""
        return self.outcome is not None

    @property
    def is_progress(self) -> bool:
        """Whether this observation reports in-flight progress, not an outcome."""
        return self.progress

    @property
    def is_unknown(self) -> bool:
        """Whether the raw state was not recognized at all."""
        return self.outcome is None and not self.progress

    def describe(self) -> str:
        """A stable word for this projection, for reasons and durable metadata."""
        if self.cancelled:
            return "cancelled"
        if self.outcome is not None:
            return self.outcome
        return "progress" if self.progress else "unknown"


#: The shared projection values the protocol table maps onto.
_PROGRESS = RemoteState(progress=True)
_UNKNOWN = RemoteState()


#: The A2A task states (`submitted`, `working`, `input-required`, `completed`,
#: `failed`, `canceled`, `unknown`) plus the near-universal synonyms other
#: agent protocols use. Lowercase; :func:`normalize_remote_state` normalizes
#: before lookup. A state absent from this table is unknown by construction:
#: an unmapped value is never proximity-matched, because guessing a remote
#: "almost completed" into a completion is exactly the false-completion
#: failure this module exists to prevent.
_PROTOCOL_STATES: dict[str, RemoteState] = {
    # accepted / not yet running
    "submitted": _PROGRESS,
    "queued": _PROGRESS,
    "accepted": _PROGRESS,
    "scheduled": _PROGRESS,
    "pending": _PROGRESS,
    # in flight
    "working": _PROGRESS,
    "running": _PROGRESS,
    "in_progress": _PROGRESS,
    "in-progress": _PROGRESS,
    "progress": _PROGRESS,
    "started": _PROGRESS,
    # the peer needs something before it can continue
    "input-required": _PROGRESS,
    "input_required": _PROGRESS,
    "awaiting-input": _PROGRESS,
    "awaiting_input": _PROGRESS,
    "waiting-for-input": _PROGRESS,
    "waiting_for_input": _PROGRESS,
    # terminal success
    "completed": RemoteState(outcome="completed"),
    "complete": RemoteState(outcome="completed"),
    "success": RemoteState(outcome="completed"),
    "succeeded": RemoteState(outcome="completed"),
    "finished": RemoteState(outcome="completed"),
    "done": RemoteState(outcome="completed"),
    # terminal failure
    "failed": RemoteState(outcome="failed"),
    "failure": RemoteState(outcome="failed"),
    "error": RemoteState(outcome="failed"),
    "errored": RemoteState(outcome="failed"),
    # cancelled elsewhere: settles failed (the work did not complete), but
    # keeps its own fact so the reason and the retry decision can say so
    "canceled": RemoteState(outcome="failed", cancelled=True),
    "cancelled": RemoteState(outcome="failed", cancelled=True),
    "aborted": RemoteState(outcome="failed", cancelled=True),
    "revoked": RemoteState(outcome="failed", cancelled=True),
    # the peer declined the work (A2A `rejected`): declined work never ran
    "rejected": RemoteState(outcome="rejected"),
    "declined": RemoteState(outcome="rejected"),
    "refused": RemoteState(outcome="rejected"),
    # the peer gave up on its own deadline
    "timed_out": RemoteState(outcome="timed_out"),
    "timed-out": RemoteState(outcome="timed_out"),
    "timeout": RemoteState(outcome="timed_out"),
    "expired": RemoteState(outcome="timed_out"),
    # the protocol itself says it cannot say
    "unknown": _UNKNOWN,
    "indeterminate": _UNKNOWN,
    "unspecified": _UNKNOWN,
}


def normalize_remote_state(raw: str) -> RemoteState:
    """Map one raw protocol state string onto its canonical projection.

    Whitespace and case are normalized (peers report ``"Completed"``,
    ``" input-required "``); anything outside the table is unknown
    (``RemoteState().is_unknown``) — ambiguous by definition, never
    interpreted as a completion.
    """
    return _PROTOCOL_STATES.get(raw.strip().lower().replace(" ", "-"), _UNKNOWN)


def settle_outcome(state: RemoteState) -> str | None:
    """The delegation outcome a normalized projection settles the child Run with.

    Returns the shared settlement-contract value used by
    ``agent.delegate_remote``'s output schema (``completed``, ``failed``,
    ``rejected``, ``timed_out``), or ``None`` when the observation must not
    settle anything. A remote-reported cancellation settles *failed*, not
    completed: the delegated work did not produce a result, and the reason
    carried alongside says it was cancelled. A peer-reported rejection
    settles ``rejected``, which the canonical settle path records as a
    cancelled child — work the peer declined never ran, which is a different
    fact from work that started and went wrong.
    """
    return state.outcome


@dataclass(frozen=True)
class CanonicalDelegationTruth:
    """The canonical child Run's facts a remote answer is judged against.

    ``status`` is the child Run's persisted status value (empty when no child
    could be read — the store-less test construction), ``terminal`` whether it
    is past :data:`maistro.runs.model.TERMINAL_RUN_STATUSES`. This is the
    *only* authority :func:`decide_settlement` consults; a remote answer
    carries no vote about it.
    """

    status: str
    terminal: bool


@dataclass(frozen=True)
class SettlementDecision:
    """What one remote lifecycle report may do to the delegation.

    ``applies`` is True only when the report may settle an open child Run,
    with ``outcome_status`` naming the settlement-contract outcome. Every
    refusal carries its ``reason`` — a settlement that does not happen must
    say why in terms a parent Run's evidence can quote.
    """

    normalized: RemoteState
    outcome_status: str | None
    applies: bool
    reason: str
    #: True when the report is recognized in-flight progress: the delegation
    #: stays open and the caller re-parks instead of settling.
    progress: bool = False


def decide_settlement(raw_state: str, canonical: CanonicalDelegationTruth) -> SettlementDecision:
    """Decide whether one remote lifecycle report may settle the delegation.

    Three rules, in precedence order:

    1. **Canonical terminal truth wins.** When the child Run is already
       terminal, the report is an observation and nothing settles — a remote
       ``completed`` arriving after a local cancellation or failure cannot
       reopen, re-settle, or contradict it.
    2. **Only recognized terminal states settle.** A recognized progress
       state leaves the delegation open (``progress=True``); the caller
       re-parks on it.
    3. **Unrecognized states fail loudly.** An unmapped value is malformed
       input, not a completion; it settles the delegation failed with the
       raw value named, so a garbage answer can never read as success (and,
       being terminal, never leaves the delegation open to a blind replay).
    """
    normalized = normalize_remote_state(raw_state)
    if canonical.terminal:
        return SettlementDecision(
            normalized=normalized,
            outcome_status=None,
            applies=False,
            reason=(
                f"canonical child Run is already '{canonical.status}'; remote state "
                f"{raw_state!r} is an observation and cannot override canonical terminal truth"
            ),
        )
    outcome = settle_outcome(normalized)
    if outcome is not None:
        if normalized.cancelled:
            reason = (
                f"remote reports the delegated work was cancelled ({raw_state.strip().lower()!r}); "
                "settling failed — the work did not complete"
            )
        else:
            reason = f"remote reports the delegated work {normalized.describe()}"
        return SettlementDecision(
            normalized=normalized, outcome_status=outcome, applies=True, reason=reason
        )
    if normalized.is_progress:
        return SettlementDecision(
            normalized=normalized,
            outcome_status=None,
            applies=False,
            progress=True,
            reason=(
                f"remote reports progress ({raw_state.strip().lower()!r}), not a terminal "
                "outcome; the delegation stays open"
            ),
        )
    assert normalized.is_unknown, f"unrecognized projection: {normalized!r}"
    return SettlementDecision(
        normalized=normalized,
        outcome_status="failed",
        applies=True,
        reason=(
            f"delegate returned an unrecognised status {raw_state!r}; it is not a protocol "
            "state this instance can honour, so the delegation settles failed rather than "
            "being guessed into a completion"
        ),
    )


class RemoteRetryDecision(StrEnum):
    """Whether — and in what shape — a delegation may be attempted again.

    The three values encode canonical Invocation/effect semantics, not
    transport policy:

    ``FORBIDDEN``
        The delegation reached a terminal outcome that owns the decision
        (completed, or cancelled — a cancellation's retry decision is
        already made, and it was "don't"). Re-dispatching would duplicate
        completed work or resurrect cancelled work.
    ``RECONCILE_ONLY``
        The transport outcome is ambiguous (lost response, unknown state,
        in-flight progress). The only safe action is polling the existing
        reservation's receipt; a second submission could double side effects.
    ``EFFECT_KEY_GOVERNED``
        The remote explicitly failed or timed out after accepting work. More
        work may only ever be admitted through the canonical effect-key
        reservation (the same durable child Run identity), never as a fresh
        transport submission, and never automatically.
    """

    FORBIDDEN = "forbidden"
    RECONCILE_ONLY = "reconcile_only"
    EFFECT_KEY_GOVERNED = "effect_key_governed"


@dataclass(frozen=True)
class RetryDecision:
    """A :class:`RemoteRetryDecision` plus the reason it was reached."""

    decision: RemoteRetryDecision
    reason: str


def decide_retry(raw_state: str, *, boundary_crossed: bool) -> RetryDecision:
    """Decide the retry eligibility of a delegation from its remote state.

    ``boundary_crossed`` says whether a submission actually reached the peer
    (a transport acceptance, a claimed boundary). A response that was never
    sent anywhere cannot have side effects, but it is still reconciled first:
    the caller's belief that nothing crossed is exactly the belief a lost
    response mimics.
    """
    normalized = normalize_remote_state(raw_state)
    if normalized.settles:
        if normalized.outcome in ("failed", "timed_out") and not normalized.cancelled:
            return RetryDecision(
                decision=RemoteRetryDecision.EFFECT_KEY_GOVERNED,
                reason=(
                    f"remote state '{normalized.describe()}' is an explicit post-acceptance "
                    "outcome; any further work must be admitted through the canonical "
                    "effect-key reservation, never as a fresh transport submission"
                ),
            )
        return RetryDecision(
            decision=RemoteRetryDecision.FORBIDDEN,
            reason=(
                f"remote state '{normalized.describe()}' owns the retry decision "
                "(the work completed, was cancelled, or was declined); re-dispatching it "
                "would duplicate or resurrect work that already reached a terminal outcome"
            ),
        )
    boundary = (
        "a submission crossed the transport boundary"
        if boundary_crossed
        else ("no submission is known to have crossed the transport boundary")
    )
    if normalized.is_progress:
        return RetryDecision(
            decision=RemoteRetryDecision.RECONCILE_ONLY,
            reason=(
                f"remote state '{normalized.describe()}' reports work in flight ({boundary}); "
                "poll the existing reservation's receipt instead of submitting again"
            ),
        )
    return RetryDecision(
        decision=RemoteRetryDecision.RECONCILE_ONLY,
        reason=(
            f"remote state {raw_state!r} is ambiguous ({boundary}); reconcile the existing "
            "reservation — an automatic replay could double side effects the first "
            "submission may already have caused"
        ),
    )


@dataclass(frozen=True)
class CancellationProjection:
    """What a delegation cancellation records — with or without a remote ack.

    ``canonical_status`` is always ``cancelled``: cancellation is decided
    locally and takes effect immediately. ``remote_acknowledged`` is
    projection metadata about propagation, never a condition of the truth.
    """

    canonical_status: str
    remote_acknowledged: bool
    reason: str


def decide_cancellation(*, remote_acknowledged: bool) -> CancellationProjection:
    """The truthful record for a cancellation whose ack may never arrive.

    A missing acknowledgement does not block, soften, or delay the
    cancellation: the canonical child Run is cancelled regardless, and a
    remote ``completed`` that arrives afterwards is refused by
    :func:`decide_settlement` against the terminal canonical truth.
    """
    if remote_acknowledged:
        return CancellationProjection(
            canonical_status="cancelled",
            remote_acknowledged=True,
            reason="remote peer acknowledged the cancellation; canonical truth is cancelled",
        )
    return CancellationProjection(
        canonical_status="cancelled",
        remote_acknowledged=False,
        reason=(
            "remote acknowledgement is missing; cancellation is decided locally and remains "
            "canonical truth — a late remote completion cannot override it"
        ),
    )


#: Pause-metadata key under which a delegation's progress observations ride
#: the node's durable checkpoint. Progress history lives in the pause entry —
#: state this node already owns — rather than in a second store, and it is
#: keyed by the delegation's existing child Run identity, so a reconnecting
#: replica resumes the same history instead of forking a second one.
PROGRESS_HISTORY_KEY = "remote_progress"

#: Cap on the durable progress history. Observations are projections; an
#: unbounded list would let a chatty peer grow the checkpoint forever.
PROGRESS_HISTORY_LIMIT = 20


@dataclass(frozen=True)
class RemoteProgressObservation:
    """One recorded remote progress report, as a projection.

    ``sequence`` is this delegation's 1-based observation counter, and
    ``duplicate`` flags a reconnect re-report: the same state for the same
    receipt as the previous observation, recorded (so the timeline is honest)
    without reading as new progress.
    """

    raw_state: str
    normalized: RemoteState
    receipt: str
    detail: str
    observed_at: datetime
    sequence: int
    duplicate: bool

    def to_dict(self) -> dict[str, Any]:
        """The durable form stored in pause metadata (and only there)."""
        return {
            "raw_state": self.raw_state,
            "normalized": self.normalized.describe(),
            "receipt": self.receipt,
            "detail": self.detail,
            "observed_at": self.observed_at.isoformat(),
            "sequence": self.sequence,
            "duplicate": self.duplicate,
        }


def record_progress(
    history: Sequence[Mapping[str, Any]],
    *,
    raw_state: str,
    receipt: str,
    detail: str,
    observed_at: datetime,
    limit: int = PROGRESS_HISTORY_LIMIT,
) -> tuple[RemoteProgressObservation, tuple[dict[str, Any], ...]]:
    """Record one progress observation against the delegation's own history.

    ``history`` is the durable progress list carried in the pause metadata of
    this delegation's existing checkpoint. The updated history keeps the most
    recent ``limit`` entries; nothing here mints execution identity — the
    observation attaches to whatever NodeRun/Attempt identity the delegation
    already reserved, which is what lets progress survive a reconnect without
    duplicating either.
    """
    last = history[-1] if history else None
    duplicate = last is not None and (
        str(last.get("raw_state") or "") == raw_state
        and str(last.get("receipt") or "") == receipt
        and str(last.get("detail") or "") == detail
    )
    observation = RemoteProgressObservation(
        raw_state=raw_state,
        normalized=normalize_remote_state(raw_state),
        receipt=receipt,
        detail=detail,
        observed_at=observed_at,
        sequence=len(history) + 1,
        duplicate=duplicate,
    )
    updated = (*(dict(entry) for entry in history), observation.to_dict())
    return observation, tuple(updated[-limit:])
