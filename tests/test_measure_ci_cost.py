"""Tests for the CI runner-cost measurement (#161).

#161 was reopened because its cost criterion was reasoned about rather than
measured. A measurement tool that is itself unverified would reproduce that
defect one level down, so the arithmetic is pinned here — particularly the two
places where a plausible-looking implementation gives a wrong number: a skipped
job whose timestamps run backwards, and a `before` set derived from the current
workflows rather than named.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "measure-ci-cost.py"


@pytest.fixture(scope="module")
def cost():
    spec = importlib.util.spec_from_file_location("measure_ci_cost", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _job(workflow, name, start, end):
    return {
        "workflow": workflow,
        "name": name,
        "started_at": f"2026-08-25T05:{start}Z",
        "completed_at": f"2026-08-25T05:{end}Z",
    }


class TestDuration:
    def test_a_normal_job_is_its_elapsed_time(self, cost):
        assert cost._seconds("2026-08-25T05:19:18Z", "2026-08-25T05:26:10Z") == 412.0

    @pytest.mark.ac("ADR-082526-0d30/AC-2")
    def test_a_skipped_job_reporting_backwards_counts_as_zero(self, cost):
        """`Container scan + SBOM + cosign` really does report `completed_at`
        one second before `started_at`, because it never ran. Summed unfloored
        that is a negative summand, which silently *reduces* the total — a wrong
        number that looks like a plausible one."""
        assert cost._seconds("2026-08-25T05:19:15Z", "2026-08-25T05:19:14Z") == 0.0

    def test_a_job_with_no_timestamps_counts_as_zero(self, cost):
        assert cost._seconds(None, None) == 0.0
        assert cost._seconds("2026-08-25T05:19:15Z", None) == 0.0


class TestAggregate:
    def test_jobs_are_grouped_by_workflow_file(self, cost):
        totals = cost.aggregate(
            [
                _job("ci.yml", "test", "19:00", "26:00"),
                _job("ci.yml", "lint", "19:00", "20:00"),
                _job("quality.yml", "Quality gate", "19:00", "23:00"),
            ]
        )
        assert totals["ci.yml"]["jobs"] == 2
        assert totals["ci.yml"]["seconds"] == 480.0
        assert totals["quality.yml"]["jobs"] == 1

    def test_the_longest_job_in_each_workflow_is_kept(self, cost):
        """Job-minutes is what the fleet spends; the longest single job is the
        floor under how fast the PR can go green. Parallelism puts the two far
        apart, so reporting one as the other misstates the cost."""
        totals = cost.aggregate(
            [
                _job("ci.yml", "short", "19:00", "19:30"),
                _job("ci.yml", "test", "19:00", "26:00"),
            ]
        )
        assert totals["ci.yml"]["longest"] == ("test", 420.0)


class TestSplit:
    def _totals(self, cost):
        return cost.aggregate(
            [
                _job("ci.yml", "test", "19:00", "26:00"),
                _job("quality.yml", "Quality gate", "19:00", "23:00"),
                _job("registry.yml", "Validate ADR/spec front-matter", "19:00", "19:15"),
                _job("formal-conformance.yml", "formal-conformance", "19:00", "21:00"),
            ]
        )

    @pytest.mark.ac("ADR-082526-0d30/AC-1")
    def test_before_is_only_what_a_stacked_pr_already_ran(self, cost):
        figures = cost.split(self._totals(cost))
        assert figures["before_stacked"] == pytest.approx((15 + 120) / 60)

    @pytest.mark.ac("ADR-082526-0d30/AC-1")
    def test_after_is_the_whole_set_and_marginal_is_the_difference(self, cost):
        figures = cost.split(self._totals(cost))
        assert figures["after_any"] == pytest.approx((420 + 240 + 15 + 120) / 60)
        assert figures["marginal"] == pytest.approx(
            figures["after_any"] - figures["before_stacked"]
        )

    @pytest.mark.ac("ADR-082526-0d30/AC-3")
    def test_the_before_set_is_named_not_derived(self, cost):
        """Deriving it from the workflows as they are *now* would find no base
        filters at all — #161 removed them — so the `before` set would silently
        become everything and the measured delta would be zero. The bug would
        report the change as free."""
        expected = frozenset({"registry.yml", "formal-conformance.yml"})
        assert expected == cost.UNFILTERED_BEFORE

    def test_an_empty_measurement_does_not_divide_by_zero(self, cost):
        figures = cost.split({})
        assert figures["after_any"] == 0.0
        assert figures["longest_job"] == 0.0


class TestRender:
    def test_the_table_names_every_workflow_and_the_three_figures(self, cost):
        totals = cost.aggregate([_job("ci.yml", "test", "19:00", "26:00")])
        out = cost.render(totals, cost.split(totals))
        assert "ci.yml" in out
        assert "stacked PR, before #161" in out
        assert "marginal, per PR head" in out
        assert "longest single job" in out
