"""Tests for the tool approval gate decision core (SPEC-253 / ADR-051)."""

from __future__ import annotations

from datetime import datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from maistro.tools.approval.gate import (
    PlanApprovalState,
    collapse_window,
    is_declared,
    needs_escalation,
    needs_plan_approval,
    thresholds_tripped,
)
from maistro.tools.approval.types import Impact, Threshold


def _state(*, approved_calls: frozenset[str] = frozenset()) -> PlanApprovalState:
    return PlanApprovalState(
        task_id="t1", approved_calls=approved_calls, approved_at=datetime(2026, 6, 20)
    )


class TestNeedsPlanApproval:
    def test_no_state_needs_approval(self) -> None:
        assert needs_plan_approval(None) is True

    def test_recorded_state_does_not_need_approval(self) -> None:
        assert needs_plan_approval(_state()) is False


class TestIsDeclared:
    def test_declared_call(self) -> None:
        state = _state(approved_calls=frozenset({"send_email"}))
        assert is_declared(state, "send_email") is True

    def test_undeclared_call(self) -> None:
        state = _state(approved_calls=frozenset({"send_email"}))
        assert is_declared(state, "delete_account") is False


class TestThresholdsTripped:
    def test_no_thresholds_never_trip(self) -> None:
        impacts = (Impact(dimension="dollars", value=1000),)
        assert thresholds_tripped(impacts, ()) == ()

    def test_below_threshold_does_not_trip(self) -> None:
        impacts = (Impact(dimension="dollars", value=50),)
        thresholds = (Threshold(dimension="dollars", gt=100),)
        assert thresholds_tripped(impacts, thresholds) == ()

    def test_above_threshold_trips(self) -> None:
        impacts = (Impact(dimension="dollars", value=150),)
        thresholds = (Threshold(dimension="dollars", gt=100),)
        assert thresholds_tripped(impacts, thresholds) == ("dollars",)

    def test_multiple_dimensions_trip_in_order(self) -> None:
        impacts = (
            Impact(dimension="dollars", value=150),
            Impact(dimension="recipients", value=60),
        )
        thresholds = (
            Threshold(dimension="dollars", gt=100),
            Threshold(dimension="recipients", gt=50),
        )
        assert thresholds_tripped(impacts, thresholds) == ("dollars", "recipients")


class TestNeedsEscalation:
    def test_undeclared_call_always_escalates(self) -> None:
        assert needs_escalation("delete_account", (), (), plan_state=_state()) is True

    def test_undeclared_call_with_no_plan_state_escalates(self) -> None:
        assert needs_escalation("delete_account", (), (), plan_state=None) is True

    def test_declared_call_under_threshold_does_not_escalate(self) -> None:
        state = _state(approved_calls=frozenset({"send_email"}))
        impacts = (Impact(dimension="dollars", value=10),)
        thresholds = (Threshold(dimension="dollars", gt=100),)
        assert needs_escalation("send_email", impacts, thresholds, plan_state=state) is False

    def test_declared_call_over_threshold_escalates(self) -> None:
        state = _state(approved_calls=frozenset({"send_email"}))
        impacts = (Impact(dimension="dollars", value=200),)
        thresholds = (Threshold(dimension="dollars", gt=100),)
        assert needs_escalation("send_email", impacts, thresholds, plan_state=state) is True


class TestCollapseWindow:
    def test_events_within_window_collapse(self) -> None:
        t0 = datetime(2026, 6, 20, 12, 0, 0)
        events = (
            (t0.isoformat(), ("dollars",)),
            ((t0 + timedelta(seconds=2)).isoformat(), ("recipients",)),
        )
        result = collapse_window(events, window_seconds=5.0)
        assert result == (("dollars", "recipients"),)

    def test_events_outside_window_stay_separate(self) -> None:
        t0 = datetime(2026, 6, 20, 12, 0, 0)
        events = (
            (t0.isoformat(), ("dollars",)),
            ((t0 + timedelta(seconds=10)).isoformat(), ("recipients",)),
        )
        result = collapse_window(events, window_seconds=5.0)
        assert result == (("dollars",), ("recipients",))


@given(
    impacts=st.lists(
        st.builds(
            Impact,
            dimension=st.sampled_from(["dollars", "recipients", "tokens"]),
            value=st.floats(min_value=0, max_value=1000, allow_nan=False),
        ),
        unique_by=lambda i: i.dimension,
    ),
    thresholds=st.lists(
        st.builds(
            Threshold,
            dimension=st.sampled_from(["dollars", "recipients", "tokens"]),
            gt=st.floats(min_value=0, max_value=1000, allow_nan=False),
        ),
        unique_by=lambda t: t.dimension,
    ),
)
def test_thresholds_tripped_only_names_configured_dimensions_strictly_exceeded(
    impacts, thresholds
) -> None:
    threshold_map = {t.dimension: t.gt for t in thresholds}
    tripped = thresholds_tripped(tuple(impacts), tuple(thresholds))
    for dim in tripped:
        assert dim in threshold_map
        impact_value = next(i.value for i in impacts if i.dimension == dim)
        assert impact_value > threshold_map[dim]
