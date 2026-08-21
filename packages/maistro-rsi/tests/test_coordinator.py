"""Tests tied to SPEC.md §8 (HTR coordinator) acceptance criteria
coordinator-1..5."""

from __future__ import annotations

import pytest

from maistro_rsi.coordinator import (
    ExecutionReport,
    HtrContext,
    HtrCoordinator,
    report_from_cycle_result,
)
from maistro_rsi.htr import HypothesisEvidence, HypothesisTree, NodeStatus


def _report(*, tests_passed=True, won=2, battles=2, improved=True, insight=None) -> ExecutionReport:
    return ExecutionReport(
        evidence=HypothesisEvidence(
            tests_passed=tests_passed,
            benchmarks_won=won,
            battles=battles,
            improved=improved,
        ),
        diff="d",
        pr_url="http://pr",
        run_id="r",
        insight=insight,
    )


class RecordingExecutor:
    """Captures the context of every step and returns a queued/default report."""

    def __init__(self, reports=None) -> None:
        self.contexts: list[HtrContext] = []
        self._reports = list(reports or [])

    async def __call__(self, context: HtrContext) -> ExecutionReport:
        self.contexts.append(context)
        if self._reports:
            return self._reports.pop(0)
        return _report()


class TestCoordinatorRun:
    @pytest.mark.asyncio
    async def test_runs_exactly_n_steps_and_proposes_only_when_no_pending(self):
        """coordinator-1: n steps, one node recorded each; propose only when nothing is queued."""
        tree = HypothesisTree("root")
        executor = RecordingExecutor()
        proposals: list[str] = []

        def propose(ctx: HtrContext) -> str:
            name = f"hyp-{len(proposals)}"
            proposals.append(name)
            return name

        result = await HtrCoordinator(tree, executor).run(3, propose)

        assert len(result.steps) == 3
        # step 1 acts on the root (already OPEN, no proposal); steps 2-3 propose
        assert result.steps[0] == tree.root_id
        assert len(proposals) == 2
        # each acted-on node has recorded evidence
        assert all(tree.nodes[nid].evidence is not None for nid in result.steps)

    @pytest.mark.asyncio
    async def test_drains_queued_hypothesis_before_proposing(self):
        """coordinator-2: a pre-queued OPEN node is acted on first, not a freshly proposed one."""
        tree = HypothesisTree("root")
        queued = tree.expand(tree.root_id, "pre-queued hypothesis")
        executor = RecordingExecutor()
        proposals: list[str] = []

        def propose(ctx: HtrContext) -> str:
            proposals.append("new")
            return "new"

        result = await HtrCoordinator(tree, executor).run(1, propose)

        assert result.steps == [queued.id]  # acted on the queued node
        assert proposals == []  # no proposal needed this step

    @pytest.mark.asyncio
    async def test_context_carries_lineage_insights(self):
        """coordinator-3: the executor sees insights distilled from the acted-on node's lineage."""
        tree = HypothesisTree("root")
        # seed an explored ancestor with a known insight, then queue a child of it
        ancestor = tree.expand(tree.root_id, "ancestor")
        tree.record(
            ancestor.id,
            HypothesisEvidence(tests_passed=True, benchmarks_won=3, battles=4, improved=True),
            insight="ancestor-lesson",
        )
        child = tree.expand(ancestor.id, "child")

        executor = RecordingExecutor()
        result = await HtrCoordinator(tree, executor).run(1, lambda ctx: "unused")

        assert result.steps == [child.id]
        assert "ancestor-lesson" in executor.contexts[0].insights

    @pytest.mark.asyncio
    async def test_reports_recorded_and_best_reflects_run(self):
        """coordinator-4: every report is recorded; CoordinatorResult.best is the tree's best node."""
        tree = HypothesisTree("root")
        # first proposal wins big, second breaks tests
        reports = [
            _report(won=4, battles=4, improved=True, insight="winner"),
            _report(tests_passed=False, won=0, battles=4, improved=False, insight="broke it"),
        ]
        executor = RecordingExecutor(reports)
        result = await HtrCoordinator(tree, executor).run(2, lambda ctx: "hyp")

        statuses = {tree.nodes[nid].status for nid in result.steps}
        assert statuses == {NodeStatus.EXPLORED, NodeStatus.ABANDONED}
        # best node is the winning one (score 1.0), not the broken one (0.0)
        assert result.best is not None
        assert result.best.score == pytest.approx(1.0)
        assert result.best.artifacts.get("diff") == "d"


class TestCycleResultBridge:
    def test_maps_cycle_result_into_execution_report(self):
        """coordinator-5: report_from_cycle_result carries evidence + artifacts faithfully."""

        class _Branch:
            tests_passed = True
            diff = "the-diff"
            pr_url = "http://pr/9"

        class _Battle:
            pass

        class _CycleResult:
            run_id = "abc123"
            branch_result = _Branch()
            battles = (_Battle(), _Battle(), _Battle())
            benchmarks_won = 2
            improved = True

        report = report_from_cycle_result(_CycleResult())

        assert report.evidence.tests_passed is True
        assert report.evidence.benchmarks_won == 2
        assert report.evidence.battles == 3
        assert report.evidence.improved is True
        assert report.diff == "the-diff"
        assert report.pr_url == "http://pr/9"
        assert report.run_id == "abc123"

    def test_importing_coordinator_does_not_import_runner_chain(self):
        """coordinator-5: importing coordinator must not pull in the sandbox/git runner chain."""
        import importlib
        import sys

        mod_names = ("maistro_rsi.coordinator", "maistro_rsi.runner", "maistro_rsi.selfbranch")
        # Popping these from sys.modules (to force a fresh import below) mutates
        # *process-global* interpreter state. Restoring the originals in a
        # finally block is essential: leaving them popped corrupts every other
        # test in the session that resolves "maistro_rsi.runner"/".selfbranch"
        # by dotted string (e.g. monkeypatch.setattr("maistro_rsi.runner.x", ...)),
        # since Python re-imports (and, once the popped originals are garbage
        # collected, permanently replaces) those modules the next time anything
        # references them.
        saved = {name: sys.modules[name] for name in mod_names if name in sys.modules}
        try:
            for name in mod_names:
                sys.modules.pop(name, None)

            importlib.import_module("maistro_rsi.coordinator")
            assert "maistro_rsi.runner" not in sys.modules
            assert "maistro_rsi.selfbranch" not in sys.modules
        finally:
            sys.modules.update(saved)
