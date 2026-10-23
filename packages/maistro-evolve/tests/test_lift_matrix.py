"""Matched same-model comparisons: the model x harness lift matrix (#104 M4-G).

The unit of measurement in M4-G is a *difference between configurations*, so
the matrix has to be structurally matched before any number derived from it
means anything. These tests pin the matching rules (which raise) and the
derived quantities (which are computed, never inferred).
"""

from __future__ import annotations

import pytest

from maistro_evolve.lift_matrix import (
    TRANSFER_EPSILON,
    BaselineVersionMismatchError,
    MatrixCell,
    UnmatchedCellsError,
    build_lift_report,
    combine_gap_closures,
    transfer_gate_failure,
)

BASELINE = "baseline-v1"


def _cell(
    role: str,
    kind: str,
    score: float,
    *,
    model: str = "weak-model",
    harness: str = "baseline-genome",
    version: str = BASELINE,
    benchmark: str = "proxy_ifeval",
    metadata: dict | None = None,
) -> MatrixCell:
    return MatrixCell(
        benchmark=benchmark,
        model_role=role,  # type: ignore[arg-type]
        model_id=model,
        harness_kind=kind,  # type: ignore[arg-type]
        harness_id=harness,
        score=score,
        baseline_version=version,
        metadata=metadata or {},
    )


def _matched(
    *,
    w_base: float = 0.20,
    w_evo: float = 0.50,
    f_base: float = 0.80,
    f_evo: float = 0.85,
    f_evo_metadata: dict | None = None,
) -> list[MatrixCell]:
    return [
        _cell("weak", "baseline", w_base),
        _cell("weak", "evolved", w_evo, harness="evolved-genome"),
        _cell("frontier", "baseline", f_base, model="frontier-model"),
        _cell(
            "frontier",
            "evolved",
            f_evo,
            model="frontier-model",
            harness="evolved-genome",
            metadata=f_evo_metadata,
        ),
    ]


class TestDerivedQuantities:
    def test_a_matched_matrix_derives_lift_gap_closure_and_transfer(self) -> None:
        report = build_lift_report(_matched())
        assert report.benchmark == "proxy_ifeval"
        assert report.baseline_version == BASELINE
        assert report.lift == pytest.approx(0.30)
        assert report.gap == pytest.approx(0.60)
        assert report.gap_closure == pytest.approx(0.5)
        assert report.transfer == pytest.approx(0.05)
        assert report.inversion is False

    def test_a_non_positive_gap_yields_no_gap_closure_at_all(self) -> None:
        """gap <= 0 invalidates; it does not become 0.0.

        0.0 would read as "the harness closed nothing" and 1.0 as "the harness
        closed everything". Neither is what a benchmark with no gap can say.
        """
        report = build_lift_report(_matched(w_base=0.80, w_evo=0.90, f_base=0.80))
        assert report.gap == pytest.approx(0.0)
        assert report.gap_closure is None

    def test_a_negative_gap_also_yields_no_gap_closure(self) -> None:
        report = build_lift_report(_matched(w_base=0.90, w_evo=0.95, f_base=0.80))
        assert report.gap < 0
        assert report.gap_closure is None

    def test_inversion_is_reported_when_the_frontier_model_loses(self) -> None:
        report = build_lift_report(_matched(f_evo=0.70))
        assert report.transfer == pytest.approx(-0.10)
        assert report.inversion is True

    def test_a_transfer_inside_the_epsilon_is_not_an_inversion(self) -> None:
        """The epsilon is noise tolerance, not a rounding step."""
        just_inside = -TRANSFER_EPSILON / 2
        report = build_lift_report(_matched(f_base=0.80, f_evo=0.80 + just_inside))
        assert report.transfer == pytest.approx(just_inside)
        assert report.inversion is False

    def test_a_stale_transfer_is_carried_forward_and_marked(self) -> None:
        report = build_lift_report(_matched(f_evo_metadata={"transfer_stale": True}))
        assert report.transfer_stale is True

    def test_cells_may_be_addressed_by_table_position(self) -> None:
        cells = _matched()
        by_position = {
            "w_base": cells[0],
            "w_evo": cells[1],
            "f_base": cells[2],
            "f_evo": cells[3],
        }
        assert build_lift_report(by_position) == build_lift_report(cells)


class TestMatchingRules:
    def test_two_models_in_one_row_is_not_a_harness_comparison(self) -> None:
        cells = _matched()
        cells[1] = cells[1].model_copy(update={"model_id": "other-model"})
        with pytest.raises(UnmatchedCellsError, match="weak row spans two models"):
            build_lift_report(cells)

    def test_two_models_in_the_frontier_row_is_refused(self) -> None:
        cells = _matched()
        cells[3] = cells[3].model_copy(update={"model_id": "third-model"})
        with pytest.raises(UnmatchedCellsError, match="frontier row spans two models"):
            build_lift_report(cells)

    def test_one_model_across_both_rows_is_a_degenerate_matrix(self) -> None:
        cells = _matched()
        cells[2] = cells[2].model_copy(update={"model_id": "weak-model"})
        cells[3] = cells[3].model_copy(update={"model_id": "weak-model"})
        with pytest.raises(UnmatchedCellsError, match="same model"):
            build_lift_report(cells)

    def test_two_baseline_versions_cannot_share_a_report(self) -> None:
        cells = _matched()
        cells[2] = cells[2].model_copy(update={"baseline_version": "baseline-v2"})
        with pytest.raises(BaselineVersionMismatchError, match="baseline versions"):
            build_lift_report(cells)

    def test_two_benchmarks_cannot_share_a_report(self) -> None:
        cells = _matched()
        cells[2] = cells[2].model_copy(update={"benchmark": "proxy_bfcl"})
        with pytest.raises(UnmatchedCellsError, match="benchmarks"):
            build_lift_report(cells)

    def test_two_baseline_harnesses_cannot_share_a_column(self) -> None:
        cells = _matched()
        cells[2] = cells[2].model_copy(update={"harness_id": "other-baseline"})
        with pytest.raises(UnmatchedCellsError, match="two harnesses"):
            build_lift_report(cells)

    def test_two_evolved_harnesses_cannot_share_a_column(self) -> None:
        cells = _matched()
        cells[3] = cells[3].model_copy(update={"harness_id": "other-evolved"})
        with pytest.raises(UnmatchedCellsError, match="two harnesses"):
            build_lift_report(cells)

    def test_a_cell_in_the_wrong_column_is_refused(self) -> None:
        cells = _matched()
        by_position = {
            "w_base": cells[0].model_copy(update={"harness_kind": "evolved"}),
            "w_evo": cells[1],
            "f_base": cells[2],
            "f_evo": cells[3],
        }
        with pytest.raises(UnmatchedCellsError, match="harness_kind"):
            build_lift_report(by_position)

    def test_an_evolved_cell_that_claims_the_baseline_column_is_refused(self) -> None:
        """The column check bites in both directions: an evolved position
        holding a baseline cell would measure the same harness twice."""
        cells = _matched()
        by_position = {
            "w_base": cells[0],
            "w_evo": cells[1].model_copy(update={"harness_kind": "baseline"}),
            "f_base": cells[2],
            "f_evo": cells[3],
        }
        with pytest.raises(UnmatchedCellsError, match="harness_kind"):
            build_lift_report(by_position)

    def test_the_wrong_number_of_cells_is_refused(self) -> None:
        with pytest.raises(UnmatchedCellsError, match="exactly 4 cells"):
            build_lift_report(_matched()[:3])

    def test_a_duplicate_cell_is_refused(self) -> None:
        cells = _matched()
        cells[1] = cells[1].model_copy(update={"harness_kind": "baseline"})
        with pytest.raises(UnmatchedCellsError, match="duplicate cell"):
            build_lift_report(cells)

    def test_a_missing_cell_is_refused(self) -> None:
        cells = [c for c in _matched() if c.model_role != "frontier" or c.harness_kind != "evolved"]
        with pytest.raises(UnmatchedCellsError, match="missing cell"):
            build_lift_report(cells)

    def test_a_position_mapping_missing_a_cell_is_refused(self) -> None:
        cells = _matched()
        by_position = {
            "w_base": cells[0],
            "w_evo": cells[1],
            "f_base": cells[2],
        }
        with pytest.raises(UnmatchedCellsError, match="missing cell"):
            build_lift_report(by_position)


class TestCombiningAndGating:
    def test_gap_closures_from_one_baseline_version_combine(self) -> None:
        reports = [build_lift_report(_matched()) for _ in range(2)]
        combined = combine_gap_closures(reports)
        assert combined == [pytest.approx(0.5), pytest.approx(0.5)]

    def test_gap_closures_across_baseline_versions_are_refused(self) -> None:
        first = build_lift_report(_matched())
        second = build_lift_report(_matched(f_base=0.70, f_evo=0.75))
        second = second.model_copy(update={"baseline_version": "baseline-v2"})
        with pytest.raises(BaselineVersionMismatchError, match="across baseline versions"):
            combine_gap_closures([first, second])

    def test_combining_nothing_yields_nothing(self) -> None:
        assert combine_gap_closures([]) == []

    def test_an_inverting_genome_is_gated_out(self) -> None:
        report = build_lift_report(_matched(f_evo=0.70))
        failure = transfer_gate_failure(report)
        assert failure is not None
        assert "inverts on the frontier model" in failure
        assert "disqualified" in failure

    def test_a_non_inverting_genome_produces_no_gate_failure(self) -> None:
        report = build_lift_report(_matched())
        assert transfer_gate_failure(report) is None

    def test_the_gate_uses_the_same_epsilon_as_the_report(self) -> None:
        report = build_lift_report(_matched(f_base=0.80, f_evo=0.80 - TRANSFER_EPSILON * 2))
        assert report.inversion is True
        assert transfer_gate_failure(report) is not None
