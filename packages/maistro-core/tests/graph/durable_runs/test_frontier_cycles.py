"""Bounded-cycle parity coverage for durable Graph frontier execution.

ADR-081226-69ee retires the legacy ``GraphRun`` executor through parity tests,
so the durable path must prove the loop shapes ``GraphRun`` supports (#44).
Two claims, stated separately because their parity postures differ:

- A **condition-terminated** loop — a back edge whose guard flips on a later
  visit — reaches ``COMPLETED`` with distinct canonical NodeRuns and Attempts
  per visit, cycle-tagged edge decisions, and one parent-linked
  TraversalCommit chain spanning the repeated visits. Same outcome as
  ``GraphRun``, now with durable canonical identity.

- A loop whose guard **never** flips is refused fail-closed. ``GraphRun``
  exits its ``config.max_cycles`` loop and then marks the run ``COMPLETED``
  whenever every executed node succeeded — truncation reported as success.
  The durable path deliberately does not reproduce that: exhausting the step
  budget terminalizes the Run as ``FAILED`` even though no node failed,
  because claiming success over still-owed frontier work is exactly what the
  canonical spine refuses (#243, ADR-082526-237d). The divergence is pinned
  here on the Attempt-firewalled path, not silently inherited.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    RunStatus,
    SqliteDurableRunStore,
    attempt_executor,
)
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.runs.model import AttemptStatus
from maistro.runtime import PythonExecutionRuntime

from .._canonical_helpers import durable_record
from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag


class _EmptyIn(BaseModel):
    pass


class _StepOut(BaseModel):
    step: str


class _ReviewOut(BaseModel):
    approved: bool
    visit: int


class _NeverApproveNode(BaseNode[_EmptyIn, _ReviewOut]):
    """Rejects on every visit, so its back edge never stops selecting."""

    kind: ClassVar[str] = "test.cycle.never_approve"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _ReviewOut

    visits: ClassVar[int] = 0

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _ReviewOut:
        type(self).visits += 1
        return _ReviewOut(approved=False, visit=type(self).visits)


class _StepNode(BaseNode[_EmptyIn, _StepOut]):
    kind: ClassVar[str] = "test.cycle.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _StepOut:
        return _StepOut(step="ok")


class _FlipReviewNode(BaseNode[_EmptyIn, _ReviewOut]):
    """Rejects on the first visit and approves on the second."""

    kind: ClassVar[str] = "test.cycle.review"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _ReviewOut

    visits: ClassVar[int] = 0

    @classmethod
    def reset(cls) -> None:
        cls.visits = 0

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _ReviewOut:
        type(self).visits += 1
        return _ReviewOut(approved=type(self).visits >= 2, visit=type(self).visits)


for _cls in (_StepNode, _FlipReviewNode, _NeverApproveNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver(node_id: str, dag: dict[str, Any]) -> BaseNode[Any, Any]:
    for raw in dag["nodes"]:
        if raw["id"] == node_id:
            return get_node(raw["kind"])()
    raise KeyError(node_id)


def _review_loop_dag() -> dict[str, Any]:
    """planner -> coder -> reviewer, with a conditional retry edge back to coder."""
    return {
        "id": "cycle-review-loop",
        "name": "bounded review loop",
        "entry_node": "planner",
        "nodes": [
            {"id": "planner", "kind": _StepNode.kind},
            {"id": "coder", "kind": _StepNode.kind},
            {"id": "reviewer", "kind": _FlipReviewNode.kind},
            {"id": "done", "kind": _StepNode.kind},
        ],
        "edges": [
            {"id": "planner-coder", "from_node": "planner", "to_node": "coder"},
            {"id": "coder-reviewer", "from_node": "coder", "to_node": "reviewer"},
            {
                "id": "reviewer-coder",
                "from_node": "reviewer",
                "to_node": "coder",
                "condition": "approved == False",
            },
            {
                "id": "reviewer-done",
                "from_node": "reviewer",
                "to_node": "done",
                "condition": "approved == True",
            },
        ],
    }


def _fanout_loop_dag() -> dict[str, Any]:
    """A loop whose body fans out, so the fan-in join sits on the cycle itself."""
    return {
        "id": "cycle-fanout-loop",
        "name": "bounded loop with fan-out body",
        "entry_node": "start",
        "nodes": [
            {"id": "start", "kind": _StepNode.kind},
            {"id": "gate", "kind": _StepNode.kind},
            {"id": "work", "kind": _StepNode.kind},
            {"id": "collect", "kind": _FlipReviewNode.kind},
            {"id": "done", "kind": _StepNode.kind},
        ],
        "edges": [
            {"id": "start-gate", "from_node": "start", "to_node": "gate"},
            {"id": "gate-work", "from_node": "gate", "to_node": "work", "parallel": True},
            {
                "id": "gate-collect",
                "from_node": "gate",
                "to_node": "collect",
                "parallel": True,
            },
            {"id": "work-collect", "from_node": "work", "to_node": "collect"},
            {
                "id": "collect-gate",
                "from_node": "collect",
                "to_node": "gate",
                "condition": "approved == False",
            },
            {
                "id": "collect-done",
                "from_node": "collect",
                "to_node": "done",
                "condition": "approved == True",
            },
        ],
    }


async def test_bounded_cycle_completes_with_distinct_canonical_node_runs() -> None:
    _FlipReviewNode.reset()
    store = InMemoryDurableRunStore()

    result = await asyncio.wait_for(
        run_durable_dag(_review_loop_dag(), store=store, node_resolver=_resolver),
        timeout=5.0,
    )

    assert result.status is RunStatus.COMPLETED
    assert [(run.node_id, run.ordinal) for run in result.node_runs] == [
        ("planner", 1),
        ("coder", 2),
        ("reviewer", 3),
        ("coder", 4),
        ("reviewer", 5),
        ("done", 6),
    ]
    assert len({run.node_run_id for run in result.node_runs}) == 6
    assert all(run.status is RunStatus.COMPLETED for run in result.node_runs)
    assert result.graph_state.visit_counts == {
        "planner": 1,
        "coder": 2,
        "reviewer": 2,
        "done": 1,
    }


async def test_each_cycle_visit_gets_its_own_completed_attempt() -> None:
    _FlipReviewNode.reset()
    store = InMemoryDurableRunStore()

    result = await run_durable_dag(_review_loop_dag(), store=store, node_resolver=_resolver)

    completed = [
        attempt for attempt in result.attempts if attempt.status is AttemptStatus.COMPLETED
    ]
    assert len(completed) == len(result.node_runs) == 6
    assert {attempt.node_run_id for attempt in completed} == {
        run.node_run_id for run in result.node_runs
    }
    assert len({attempt.attempt_id for attempt in completed}) == 6


async def test_back_edge_decisions_carry_distinct_cycles_and_source_node_runs() -> None:
    _FlipReviewNode.reset()
    store = InMemoryDurableRunStore()

    result = await run_durable_dag(_review_loop_dag(), store=store, node_resolver=_resolver)

    reviewer_runs = [run for run in result.node_runs if run.node_id == "reviewer"]
    back_edge = [
        decision
        for decision in result.graph_state.edge_decisions
        if decision.edge_id == "reviewer-coder"
    ]
    assert [decision.selected for decision in back_edge] == [True, False]
    assert len({decision.cycle for decision in back_edge}) == 2
    assert [decision.source_node_run_id for decision in back_edge] == [
        reviewer_runs[0].node_run_id,
        reviewer_runs[1].node_run_id,
    ]

    exit_edge = [
        decision
        for decision in result.graph_state.edge_decisions
        if decision.edge_id == "reviewer-done" and decision.selected
    ]
    assert [decision.source_node_run_id for decision in exit_edge] == [reviewer_runs[1].node_run_id]


async def test_traversal_commits_link_across_cycle_visits() -> None:
    _FlipReviewNode.reset()
    store = InMemoryDurableRunStore()

    result = await run_durable_dag(_review_loop_dag(), store=store, node_resolver=_resolver)

    commits = result.traversal_commits
    assert [commit.commit_sequence for commit in commits] == list(range(1, len(commits) + 1))
    assert commits[0].prior_commit_id is None
    for prior, commit in itertools.pairwise(commits):
        assert commit.prior_commit_id == prior.traversal_commit_id

    advanced = [
        node_run_id for commit in commits for node_run_id in commit.ordered_source_node_run_ids
    ]
    coder_runs = [run.node_run_id for run in result.node_runs if run.node_id == "coder"]
    assert set(coder_runs) <= set(advanced)
    assert len(coder_runs) == 2


async def test_fanin_join_on_a_cycle_converges_each_visit() -> None:
    _FlipReviewNode.reset()
    store = InMemoryDurableRunStore()

    result = await asyncio.wait_for(
        run_durable_dag(_fanout_loop_dag(), store=store, node_resolver=_resolver),
        timeout=5.0,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.graph_state.visit_counts == {
        "start": 1,
        "gate": 2,
        "work": 2,
        "collect": 2,
        "done": 1,
    }
    assert result.graph_state.metadata.get("deferred_fanins") in (None, [])

    by_visit: dict[str, list[Any]] = {}
    runs_by_id = {run.node_run_id: run for run in result.node_runs}
    for decision in result.graph_state.edge_decisions:
        if decision.selected and decision.target_node_id == "collect":
            by_visit.setdefault(decision.source_node_id, []).append(decision)
    assert sorted(by_visit) == ["gate", "work"]
    for decisions in by_visit.values():
        assert len(decisions) == 2
        source_ids = {decision.source_node_run_id for decision in decisions}
        assert len(source_ids) == 2
        assert source_ids <= set(runs_by_id)


async def test_bounded_cycle_history_survives_sqlite_reopen(tmp_path: Any) -> None:
    _FlipReviewNode.reset()
    db = tmp_path / "cycles.db"
    store = SqliteDurableRunStore(db)

    result = await run_durable_dag(
        _review_loop_dag(),
        store=store,
        node_resolver=_resolver,
        run_id="r-cycle-sqlite-1",
    )
    assert result.status is RunStatus.COMPLETED

    reopened = SqliteDurableRunStore(db)
    persisted = await reopened.get("r-cycle-sqlite-1")
    assert persisted is not None
    assert persisted.status is RunStatus.COMPLETED
    assert persisted.graph_state.visit_counts["coder"] == 2
    assert persisted.graph_state.visit_counts["reviewer"] == 2
    assert [(run.node_id, run.ordinal) for run in persisted.node_runs] == [
        (run.node_id, run.ordinal) for run in result.node_runs
    ]
    assert len(persisted.traversal_commits) == len(result.traversal_commits)


def _endless_loop_dag() -> dict[str, Any]:
    """A back edge whose guard never flips: the loop is bounded only by budget."""
    return {
        "id": "cycle-endless-loop",
        "name": "unbounded review loop",
        "entry_node": "step",
        "nodes": [
            {"id": "step", "kind": _StepNode.kind},
            {"id": "review", "kind": _NeverApproveNode.kind},
            {"id": "done", "kind": _StepNode.kind},
        ],
        "edges": [
            {"id": "step-review", "from_node": "step", "to_node": "review"},
            {
                "id": "review-step",
                "from_node": "review",
                "to_node": "step",
                "condition": "approved == False",
            },
            {
                "id": "review-done",
                "from_node": "review",
                "to_node": "done",
                "condition": "approved == True",
            },
        ],
    }


async def test_unbounded_back_edge_fails_closed_instead_of_truncating() -> None:
    """The deliberate divergence from ``GraphRun.max_cycles`` semantics.

    ``GraphRun`` exits its cycle loop at the configured bound and reports
    ``COMPLETED`` when every executed node succeeded, silently truncating a
    graph that still owed work. The durable path must instead refuse: budget
    exhaustion is ``FAILED`` with the budget named, never a success claim over
    an owed frontier — even though not a single node failed.
    """
    store = InMemoryDurableRunStore()
    record = durable_record(
        _endless_loop_dag(),
        run_id="r-cycle-endless",
        active_node_id="step",
    )
    await store.create(record)

    result = await asyncio.wait_for(
        attempt_executor._walk(
            record,
            store=store,
            node_resolver=lambda node_id, graph: _resolver(node_id, _endless_loop_dag()),
            runtime=PythonExecutionRuntime(),
            max_steps=8,
        ),
        timeout=10.0,
    )

    assert result.status is RunStatus.FAILED
    assert result.run.error is not None
    assert result.run.error.startswith("StepBudgetExhausted:")
    assert "max_steps=8" in result.run.error

    executed = [run for run in result.node_runs if run.status is RunStatus.COMPLETED]
    assert executed, "the loop body must actually have run before the refusal"
    assert not any(run.status is RunStatus.FAILED for run in result.node_runs)
    completed_attempts = [
        attempt for attempt in result.attempts if attempt.status is AttemptStatus.COMPLETED
    ]
    assert {attempt.node_run_id for attempt in completed_attempts} >= {
        run.node_run_id for run in executed
    }
