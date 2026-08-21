"""Tests for maistro.types.feedback — RLHF feedback loop dataclasses."""

from __future__ import annotations

from maistro.types.feedback import ViolationMetrics


class TestFindingsPerPr:
    def test_zero_prs_reviewed_returns_zero(self) -> None:
        metrics = ViolationMetrics(agent_id="a1")
        assert metrics.findings_per_pr == 0.0

    def test_computes_average(self) -> None:
        metrics = ViolationMetrics(agent_id="a1", total_prs_reviewed=4, total_findings=8)
        assert metrics.findings_per_pr == 2.0


class TestTrend:
    def test_insufficient_data_below_three_entries(self) -> None:
        metrics = ViolationMetrics(agent_id="a1", findings_per_pr_history=[1.0, 2.0])
        assert metrics.trend == "insufficient_data"

    def test_improving_when_recent_average_drops(self) -> None:
        metrics = ViolationMetrics(
            agent_id="a1", findings_per_pr_history=[5.0, 5.0, 5.0, 0.0, 0.0, 0.0]
        )
        assert metrics.trend == "improving"

    def test_regressing_when_recent_average_rises(self) -> None:
        metrics = ViolationMetrics(
            agent_id="a1", findings_per_pr_history=[0.0, 0.0, 0.0, 5.0, 5.0, 5.0]
        )
        assert metrics.trend == "regressing"

    def test_stable_when_delta_within_threshold(self) -> None:
        metrics = ViolationMetrics(
            agent_id="a1", findings_per_pr_history=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
        )
        assert metrics.trend == "stable"

    def test_uses_first_three_as_older_when_fewer_than_six_entries(self) -> None:
        metrics = ViolationMetrics(agent_id="a1", findings_per_pr_history=[5.0, 5.0, 5.0, 0.0])
        # len < 6 -> older = history[:3] = [5.0, 5.0, 5.0]; recent = last 3 = [5.0, 5.0, 0.0]
        assert metrics.trend == "improving"
