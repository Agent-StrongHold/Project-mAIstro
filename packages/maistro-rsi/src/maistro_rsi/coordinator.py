"""HTR coordinator — the long-lived loop that drives short-lived RSI executors.

Arbor (arXiv:2606.11926) splits autonomous research into a long-lived
*coordinator* that owns strategy and a fleet of short-lived *executors* that
each test one hypothesis in isolation. This module is the coordinator: it owns
a `maistro_rsi.htr.HypothesisTree`, and on each step it

  1. picks the next node to act on — an already-queued hypothesis if there is
     one, otherwise a fresh hypothesis refining the most promising explored
     branch (frontier refinement),
  2. hands the executor an `HtrContext` carrying that node *and the insights
     distilled from its lineage*, so the attempt builds on prior lessons,
  3. records the returned evidence back into the tree, which distills a new
     insight and prunes or keeps the branch.

The executor itself is injected (`ExecutorFn`). For a fake one, the coordinator
needs nothing but this module and `htr`; `report_from_cycle_result` bridges a
real `maistro_rsi.runner.RsiCycleResult` into the `ExecutionReport` the
coordinator records, importing the heavy runner lazily so this module — and its
tests — stay free of the sandbox/git import chain.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from maistro_rsi.htr import HypothesisEvidence, HypothesisNode, HypothesisTree
from maistro_rsi.intervention import Intervention, InterventionPolicy, ObjectiveParked

if TYPE_CHECKING:
    from maistro_rsi.runner import RsiCycleResult

logger = structlog.get_logger()


@dataclass
class HtrContext:
    """What an executor sees before it runs: the node it must test and the
    lessons distilled from that node's lineage so far."""

    node: HypothesisNode
    insights: list[str]
    tree: HypothesisTree


@dataclass
class ExecutionReport:
    """What an executor returns: the evidence to score the node by, plus the
    artifacts (diff, PR, run id) to retain and an optional pre-distilled
    insight (the tree distills one from the evidence if omitted)."""

    evidence: HypothesisEvidence
    diff: str | None = None
    pr_url: str | None = None
    run_id: str | None = None
    insight: str | None = None


# Injected: run one short-lived executor for the given context and return its
# report. Kept abstract so the coordinator's frontier logic is testable without
# a sandbox; the real implementation wraps `RsiCycle.run` (see the bridge below).
ExecutorFn = Callable[[HtrContext], Awaitable[ExecutionReport]]

# Injected: propose a fresh hypothesis refining the seed node, grounded in the
# insights distilled so far. Only called when no hypothesis is already queued.
HypothesisProposer = Callable[[HtrContext], str]


@dataclass
class CoordinatorResult:
    """The outcome of a coordinator run: the tree it grew, the best node found,
    the per-step node ids in execution order, and — when an intervention policy
    is wired in — the stall interventions performed, each preserving its
    lineage/evidence review, returned directions, cost, and subsequent gain."""

    tree: HypothesisTree
    steps: list[str] = field(default_factory=list)
    interventions: list[Intervention] = field(default_factory=list)

    @property
    def best(self) -> HypothesisNode | None:
        return self.tree.best_node()


class HtrCoordinator:
    """Drives ``num_cycles`` short-lived executors against a growing hypothesis
    tree, refining the frontier from each returned result.

    With a ``policy`` (M5-B), consecutive non-improving cycles trigger a stall
    intervention: a lineage review over the stalled branch's full evidence and
    the tree's archived promising candidates, reseeding the frontier from the
    returned materially-distinct directions. Without one, the coordinator
    behaves exactly as before (the policy is opt-in so existing callers and
    tests are untouched).
    """

    def __init__(
        self,
        tree: HypothesisTree,
        executor: ExecutorFn,
        *,
        policy: InterventionPolicy | None = None,
    ) -> None:
        self._tree = tree
        self._executor = executor
        self._policy = policy

    def _next_node(self, propose: HypothesisProposer) -> HypothesisNode:
        """The node to act on this step: drain queued hypotheses first, then
        grow a new one off the most promising explored branch."""
        pending = self._tree.pending()
        if pending:
            return pending[0]
        seed = self._tree.select_seed()
        seed_context = HtrContext(
            node=seed,
            insights=self._tree.distilled_insights(seed.id),
            tree=self._tree,
        )
        hypothesis = propose(seed_context)
        return self._tree.expand(seed.id, hypothesis)

    async def run(self, num_cycles: int, propose: HypothesisProposer) -> CoordinatorResult:
        result = CoordinatorResult(tree=self._tree)
        for _ in range(num_cycles):
            node = self._next_node(propose)
            context = HtrContext(
                node=node,
                insights=self._tree.distilled_insights(node.id),
                tree=self._tree,
            )
            report = await self._executor(context)
            self._tree.record(
                node.id,
                report.evidence,
                diff=report.diff,
                pr_url=report.pr_url,
                run_id=report.run_id,
                insight=report.insight,
            )
            result.steps.append(node.id)
            await logger.ainfo(
                "htr_step_complete",
                node_id=node.id,
                depth=node.depth,
                improved=report.evidence.improved,
                score=node.score,
                **self._tree.summary(),
            )
            if self._policy is None:
                continue
            # Measure first, detect second: the gain of the latest intervention
            # must include this cycle's outcome before a possible new stall
            # fires another intervention.
            self._policy.observe_post_intervention_cycle(self._tree, report.evidence.improved)
            if self._policy.observe(report.evidence.improved):
                await logger.ainfo(
                    "htr_stall_detected",
                    node_id=node.id,
                    stall_threshold=self._policy.config.stall_threshold,
                    consecutive_non_improving=(self._policy.tracker.consecutive_non_improving),
                    **self._tree.summary(),
                )
                try:
                    intervention = await self._policy.intervene(self._tree, node.id)
                except ObjectiveParked as exc:
                    # The park fires AFTER this cycle executed and recorded
                    # `node`, so the raised exception must carry the steps this
                    # run completed: the loop driver merges steps only from a
                    # returned CoordinatorResult, and dropping the executed
                    # cycle here would leave its node OPEN in the on-disk
                    # snapshot for a later resume to run again.
                    exc.steps = tuple(result.steps)
                    raise
                result.interventions.append(intervention)
        return result


def report_from_cycle_result(result: RsiCycleResult) -> ExecutionReport:
    """Bridge a real RSI cycle outcome into an `ExecutionReport`.

    Lives here (not in `runner`) and takes the result as a plain argument so
    importing the coordinator never pulls in the sandbox/git chain; the
    annotation resolves only under TYPE_CHECKING.
    """
    return ExecutionReport(
        evidence=HypothesisEvidence(
            tests_passed=result.branch_result.tests_passed,
            benchmarks_won=result.benchmarks_won,
            battles=len(result.battles),
            improved=result.improved,
        ),
        diff=result.branch_result.diff,
        pr_url=result.branch_result.pr_url,
        run_id=result.run_id,
    )
