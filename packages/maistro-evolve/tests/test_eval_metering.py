"""Metered cost / security tax / RHAE for an evaluation run (#104 M4-G).

The meter reports what was *observed* during a run. Two properties matter and
are pinned here: absent observations read as zero events (a claim, not a
default), and an unknown event kind is an error rather than a silently
dropped reading.
"""

from __future__ import annotations

import pytest

from maistro_evolve.eval_metering import (
    GAMING_SIGNALS_KEY,
    SECURITY_EVENTS_KEY,
    RunMetering,
    attach_run_metering,
    meter_results,
    metering_gate_failures,
)
from maistro_evolve.types import EvalResult


def _result(
    *,
    benchmark: str = "proxy_ifeval",
    score: float = 1.0,
    cost_usd: float = 0.01,
    duration_seconds: float = 0.5,
    samples_evaluated: int = 1,
    metadata: dict | None = None,
) -> EvalResult:
    return EvalResult(
        benchmark=benchmark,
        score=score,
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        samples_evaluated=samples_evaluated,
        metadata=metadata or {},
    )


class TestAggregation:
    def test_cost_duration_and_samples_are_summed(self) -> None:
        metering = meter_results(
            [
                _result(cost_usd=0.01, duration_seconds=0.5, samples_evaluated=2),
                _result(cost_usd=0.02, duration_seconds=1.5, samples_evaluated=3),
            ]
        )
        assert metering.cost_usd == pytest.approx(0.03)
        assert metering.duration_seconds == pytest.approx(2.0)
        assert metering.samples_evaluated == 5

    def test_an_empty_run_measures_nothing(self) -> None:
        metering = meter_results([])
        assert metering.samples_evaluated == 0
        assert metering.security_tax == 0.0
        assert metering.rhae_estimate == 0.0
        assert metering.security_events == {}
        assert metering.gaming_signals == {}

    def test_the_block_carries_every_metered_field(self) -> None:
        block = RunMetering(
            cost_usd=1.5,
            duration_seconds=2.5,
            samples_evaluated=4,
            security_events={"policy_refusal": 2},
            security_tax=0.25,
            gaming_signals={"spoofed_pass_marker": 1},
            rhae_estimate=0.125,
            unresolved_security_violations=1,
        ).to_block()
        assert block == {
            "cost_usd": 1.5,
            "duration_seconds": 2.5,
            "samples_evaluated": 4,
            "security_events": {"policy_refusal": 2},
            "security_tax": 0.25,
            "gaming_signals": {"spoofed_pass_marker": 1},
            "rhae_estimate": 0.125,
            "unresolved_security_violations": 1,
        }


class TestSecurityTaxAndRhae:
    def test_the_tax_rises_with_events_and_falls_with_sample_size(self) -> None:
        small = meter_results(
            [_result(samples_evaluated=1, metadata={SECURITY_EVENTS_KEY: {"policy_refusal": 1}})]
        )
        large = meter_results(
            [_result(samples_evaluated=9, metadata={SECURITY_EVENTS_KEY: {"policy_refusal": 1}})]
        )
        assert small.security_tax == pytest.approx(0.5)
        assert large.security_tax == pytest.approx(0.1)

    def test_no_events_means_no_tax(self) -> None:
        metering = meter_results([_result(samples_evaluated=5)])
        assert metering.security_tax == 0.0
        assert metering.security_events == {}

    def test_rhae_counts_host_detected_gaming_attempts(self) -> None:
        metering = meter_results(
            [
                _result(
                    samples_evaluated=3,
                    metadata={GAMING_SIGNALS_KEY: {"spoofed_pass_marker": 3}},
                )
            ]
        )
        assert metering.gaming_signals == {"spoofed_pass_marker": 3}
        assert metering.rhae_estimate == pytest.approx(0.5)

    def test_a_run_with_no_samples_reports_no_rate(self) -> None:
        """Observed signals cannot be a rate without a denominator."""
        metering = meter_results(
            [_result(samples_evaluated=0, metadata={SECURITY_EVENTS_KEY: {"policy_refusal": 2}})]
        )
        assert metering.samples_evaluated == 0
        assert metering.security_tax == 0.0
        assert metering.rhae_estimate == 0.0
        # The counts survive: they were observed, they just do not make a rate.
        assert metering.security_events == {"policy_refusal": 2}

    def test_zero_counts_are_not_reported_as_events(self) -> None:
        metering = meter_results([_result(metadata={SECURITY_EVENTS_KEY: {"policy_refusal": 0}})])
        assert metering.security_events == {}


class TestFailClosedOnBadObservations:
    def test_an_unknown_event_kind_is_refused(self) -> None:
        """A misspelled kind must not read as "no events"."""
        with pytest.raises(ValueError, match="unknown security_events kind"):
            meter_results([_result(metadata={SECURITY_EVENTS_KEY: {"typo_kind": 1}})])

    def test_an_unknown_gaming_signal_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown gaming_signals kind"):
            meter_results([_result(metadata={GAMING_SIGNALS_KEY: {"typo_kind": 1}})])

    def test_a_non_mapping_observation_is_refused(self) -> None:
        with pytest.raises(TypeError, match="must be a mapping"):
            meter_results([_result(metadata={SECURITY_EVENTS_KEY: ["policy_refusal"]})])

    def test_a_negative_count_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-negative int"):
            meter_results([_result(metadata={SECURITY_EVENTS_KEY: {"policy_refusal": -1}})])

    def test_a_boolean_count_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-negative int"):
            meter_results([_result(metadata={SECURITY_EVENTS_KEY: {"policy_refusal": True}})])


class TestAttach:
    def test_every_result_carries_the_whole_run_block(self) -> None:
        results = [_result(), _result(benchmark="proxy_bfcl")]
        metering = attach_run_metering(results)
        for result in results:
            assert result.run_metering is not None
            assert result.run_metering["cost_usd"] == metering.cost_usd
            assert result.run_metering["samples_evaluated"] == 2

    def test_attaching_metering_does_not_touch_adapter_metadata(self) -> None:
        """``metadata`` is the adapter's contract; the meter has its own field."""
        results = [_result(metadata={"stub": False, "exit_code": 0})]
        attach_run_metering(results)
        assert results[0].metadata == {"stub": False, "exit_code": 0}
        assert results[0].run_metering is not None

    def test_reattaching_is_idempotent(self) -> None:
        results = [_result()]
        first = attach_run_metering(results)
        second = attach_run_metering(results)
        assert first.to_block() == second.to_block()
        assert results[0].run_metering == second.to_block()


class TestGate:
    def test_an_unresolved_violation_disqualifies_the_evidence(self) -> None:
        metering = meter_results([_result(metadata={"unresolved_security_violations": 2})])
        failures = metering_gate_failures(metering)
        assert failures
        assert "unresolved security violation" in failures[0]
        assert "not publishable" in failures[0]

    def test_a_detected_and_defeated_attempt_does_not_gate(self) -> None:
        """Double-punishing a defeated attempt would make the meter a score."""
        metering = meter_results(
            [
                _result(
                    samples_evaluated=1,
                    metadata={
                        SECURITY_EVENTS_KEY: {"policy_refusal": 1},
                        GAMING_SIGNALS_KEY: {"spoofed_pass_marker": 1},
                    },
                )
            ]
        )
        assert metering.security_tax > 0
        assert metering.rhae_estimate > 0
        assert metering_gate_failures(metering) == []
