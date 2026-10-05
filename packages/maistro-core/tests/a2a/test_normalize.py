"""Tests for `maistro.a2a.normalize` — remote Agent lifecycle normalization (M9-D3).

Each test names the acceptance criterion it pins (issue #960):

- remote protocol `completed` cannot override canonical Run terminal truth;
- cancellation remains truthful when remote acknowledgement is missing;
- ambiguous/lost responses do not trigger unsafe automatic side-effect replay;
- retries are governed by canonical Invocation/effect semantics;
- protocol-specific states are observable but remain projections.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.a2a.normalize import (
    PROGRESS_HISTORY_LIMIT,
    RemoteLifecycleState,
    RemoteRetryDecision,
    decide_cancellation,
    decide_retry,
    decide_settlement,
    normalize_remote_state,
    record_progress,
    settle_outcome,
)
from maistro.a2a.normalize import (
    CanonicalDelegationTruth as Truth,
)

_OPEN = Truth(status="waiting", terminal=False)
_TERMINAL = Truth(status="cancelled", terminal=True)


# --------------------------------------------------------------------------
# normalize_remote_state — the closed projection vocabulary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The A2A task states themselves.
        ("submitted", RemoteLifecycleState.SUBMITTED),
        ("working", RemoteLifecycleState.WORKING),
        ("input-required", RemoteLifecycleState.AWAITING_INPUT),
        ("completed", RemoteLifecycleState.COMPLETED),
        ("failed", RemoteLifecycleState.FAILED),
        ("canceled", RemoteLifecycleState.CANCELLED),
        ("rejected", RemoteLifecycleState.REJECTED),
        ("unknown", RemoteLifecycleState.UNKNOWN),
        # Common protocol synonyms.
        ("Completed", RemoteLifecycleState.COMPLETED),
        ("  completed  ", RemoteLifecycleState.COMPLETED),
        ("succeeded", RemoteLifecycleState.COMPLETED),
        ("in-progress", RemoteLifecycleState.WORKING),
        ("input_required", RemoteLifecycleState.AWAITING_INPUT),
        ("timed-out", RemoteLifecycleState.TIMED_OUT),
        ("cancelled", RemoteLifecycleState.CANCELLED),
        ("aborted", RemoteLifecycleState.CANCELLED),
        ("declined", RemoteLifecycleState.REJECTED),
    ],
)
def test_protocol_states_normalize_onto_the_closed_vocabulary(
    raw: str, expected: RemoteLifecycleState
) -> None:
    assert normalize_remote_state(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "banana",
        "COMPLETE!!",
        "almost done",
        "state: working",
        # Proximity to a real state is not a match: guessing "almost completed"
        # into a completion is the false-completion failure this module exists
        # to prevent.
        "completed-with-errors",
    ],
)
def test_unmapped_values_are_unknown_never_completed(raw: str) -> None:
    assert normalize_remote_state(raw) is RemoteLifecycleState.UNKNOWN


def test_the_vocabulary_is_projection_not_authority() -> None:
    """Protocol-specific states are observable (raw string retained by the
    caller) while every one of them normalizes onto the same closed set — no
    state smuggles a canonical authority of its own."""
    for raw in ("working", "WORKING", "In-Progress"):
        normalized = normalize_remote_state(raw)
        assert isinstance(normalized, RemoteLifecycleState)
        assert normalized.value in {member.value for member in RemoteLifecycleState}


# --------------------------------------------------------------------------
# settle_outcome / decide_settlement — terminal truth and progress
# --------------------------------------------------------------------------


def test_only_terminal_states_settle() -> None:
    assert settle_outcome(RemoteLifecycleState.COMPLETED) == "completed"
    assert settle_outcome(RemoteLifecycleState.FAILED) == "failed"
    assert settle_outcome(RemoteLifecycleState.CANCELLED) == "failed"
    assert settle_outcome(RemoteLifecycleState.REJECTED) == "rejected"
    assert settle_outcome(RemoteLifecycleState.TIMED_OUT) == "timed_out"
    assert settle_outcome(RemoteLifecycleState.SUBMITTED) is None
    assert settle_outcome(RemoteLifecycleState.WORKING) is None
    assert settle_outcome(RemoteLifecycleState.AWAITING_INPUT) is None
    assert settle_outcome(RemoteLifecycleState.UNKNOWN) is None


def test_remote_completed_settles_an_open_child() -> None:
    decision = decide_settlement("completed", _OPEN)
    assert decision.applies is True
    assert decision.progress is False
    assert decision.outcome_status == "completed"


def test_remote_completed_cannot_override_canonical_terminal_truth() -> None:
    """The core #960 acceptance rule: the child Run is already terminal
    (here: cancelled locally); a remote `completed` is an observation, never
    a settlement."""
    decision = decide_settlement("completed", _TERMINAL)
    assert decision.applies is False
    assert decision.outcome_status is None
    assert "already 'cancelled'" in decision.reason
    assert "cannot override canonical terminal truth" in decision.reason


def test_late_remote_completion_after_a_local_failure_is_also_refused() -> None:
    decision = decide_settlement("completed", Truth(status="failed", terminal=True))
    assert decision.applies is False


@pytest.mark.parametrize("raw", ["submitted", "working", "input-required"])
def test_recognized_progress_never_settles(raw: str) -> None:
    decision = decide_settlement(raw, _OPEN)
    assert decision.applies is False
    assert decision.progress is True
    assert decision.outcome_status is None
    assert "stays open" in decision.reason


def test_remote_cancellation_settles_failed_with_the_fact_named() -> None:
    decision = decide_settlement("canceled", _OPEN)
    assert decision.applies is True
    assert decision.outcome_status == "failed"
    assert "cancelled" in decision.reason


def test_remote_rejection_settles_rejected() -> None:
    decision = decide_settlement("rejected", _OPEN)
    assert decision.applies is True
    assert decision.outcome_status == "rejected"


def test_an_unmapped_status_fails_loudly_instead_of_staying_open() -> None:
    """A malformed value settles failed *with the raw value named* — never a
    completion, and never an open delegation a blind replay could sneak into."""
    decision = decide_settlement("banana", _OPEN)
    assert decision.applies is True
    assert decision.outcome_status == "failed"
    assert "banana" in decision.reason


def test_an_unmapped_status_for_a_terminal_child_is_refused_not_settled() -> None:
    decision = decide_settlement("banana", _TERMINAL)
    assert decision.applies is False
    assert decision.outcome_status is None


# --------------------------------------------------------------------------
# decide_retry — canonical Invocation/effect semantics govern retries
# --------------------------------------------------------------------------


def test_completed_is_forbidden() -> None:
    decision = decide_retry("completed", boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.FORBIDDEN


def test_cancelled_is_forbidden() -> None:
    decision = decide_retry("cancelled", boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.FORBIDDEN
    assert "owns the retry decision" in decision.reason


def test_rejected_is_forbidden() -> None:
    decision = decide_retry("rejected", boundary_crossed=False)
    assert decision.decision is RemoteRetryDecision.FORBIDDEN


@pytest.mark.parametrize("raw", ["failed", "timed-out"])
def test_explicit_post_acceptance_outcomes_are_effect_key_governed(raw: str) -> None:
    decision = decide_retry(raw, boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.EFFECT_KEY_GOVERNED
    assert "effect-key" in decision.reason


@pytest.mark.parametrize("raw", ["banana", "unknown"])
def test_ambiguous_responses_reconcile_and_never_replay(raw: str) -> None:
    for crossed in (True, False):
        decision = decide_retry(raw, boundary_crossed=crossed)
        assert decision.decision is RemoteRetryDecision.RECONCILE_ONLY
        assert "reconcile" in decision.reason


@pytest.mark.parametrize("raw", ["submitted", "working", "input-required"])
def test_in_flight_progress_reconciles_instead_of_re_submitting(raw: str) -> None:
    decision = decide_retry(raw, boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.RECONCILE_ONLY
    assert "crossed the transport boundary" in decision.reason


def test_ambiguity_reports_which_side_of_the_boundary_it_believes() -> None:
    crossed = decide_retry("banana", boundary_crossed=True)
    uncrossed = decide_retry("banana", boundary_crossed=False)
    assert "a submission crossed" in crossed.reason
    assert "no submission is known to have crossed" in uncrossed.reason


# --------------------------------------------------------------------------
# decide_cancellation — truthful without a remote acknowledgement
# --------------------------------------------------------------------------


def test_cancellation_is_canonical_with_an_ack() -> None:
    projection = decide_cancellation(remote_acknowledged=True)
    assert projection.canonical_status == "cancelled"
    assert projection.remote_acknowledged is True


def test_cancellation_remains_canonical_without_an_ack() -> None:
    """The #960 acceptance rule: the ack is projection metadata, never a
    condition of the truth."""
    projection = decide_cancellation(remote_acknowledged=False)
    assert projection.canonical_status == "cancelled"
    assert projection.remote_acknowledged is False
    assert "acknowledgement is missing" in projection.reason
    assert "cannot override" in projection.reason


def test_a_missing_ack_still_refuses_a_late_remote_completion() -> None:
    """The composition the acceptance criterion cares about: cancelled
    without an ack, remote later says `completed` — refused."""
    cancelled = decide_cancellation(remote_acknowledged=False)
    assert cancelled.canonical_status == "cancelled"
    decision = decide_settlement(
        "completed", Truth(status=cancelled.canonical_status, terminal=True)
    )
    assert decision.applies is False


# --------------------------------------------------------------------------
# record_progress — reconnect-safe observations, no identity minting
# --------------------------------------------------------------------------


def _observation_at(minutes: int) -> datetime:
    return datetime(2026, 10, 5, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def test_first_progress_record_has_sequence_one_and_is_not_a_duplicate() -> None:
    observation, history = record_progress(
        [],
        raw_state="working",
        receipt="task-1",
        detail="halfway",
        observed_at=_observation_at(0),
    )
    assert observation.sequence == 1
    assert observation.duplicate is False
    assert observation.normalized is RemoteLifecycleState.WORKING
    assert len(history) == 1
    assert history[0]["raw_state"] == "working"


def test_a_reconnect_re_report_of_the_same_state_is_flagged_not_new_progress() -> None:
    """Progress survives a network reconnect: the re-observed state is
    recorded honestly (duplicate=True) instead of reading as new progress."""
    _, history = record_progress(
        [],
        raw_state="working",
        receipt="task-1",
        detail="halfway",
        observed_at=_observation_at(0),
    )
    reconnected, history2 = record_progress(
        history,
        raw_state="working",
        receipt="task-1",
        detail="halfway",
        observed_at=_observation_at(5),
    )
    assert reconnected.sequence == 2
    assert reconnected.duplicate is True
    assert len(history2) == 2


def test_a_new_state_after_a_reconnect_is_not_a_duplicate() -> None:
    _, history = record_progress(
        [],
        raw_state="submitted",
        receipt="task-1",
        detail="",
        observed_at=_observation_at(0),
    )
    observation, _ = record_progress(
        history,
        raw_state="working",
        receipt="task-1",
        detail="",
        observed_at=_observation_at(1),
    )
    assert observation.duplicate is False


def test_progress_history_is_capped() -> None:
    history: tuple[dict[str, object], ...] = ()
    for minute in range(PROGRESS_HISTORY_LIMIT + 10):
        _, history = record_progress(
            history,
            raw_state="working",
            receipt="task-1",
            detail=f"tick {minute}",
            observed_at=_observation_at(minute),
        )
    assert len(history) == PROGRESS_HISTORY_LIMIT
    assert history[-1]["detail"] == f"tick {PROGRESS_HISTORY_LIMIT + 9}"
