"""Behavioral tests for GraphPipelineExecutor: waves, skips, gates, budgets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import (
    DispatchResult,
    GraphPipelineExecutor,
    _build_prompt,
)
from maistro.graph.node import IterationBudget


def test_build_prompt_falls_back_to_raw_template_on_malformed_format_spec() -> None:
    assert _build_prompt("{0!Z}", {}) == "{0!Z}"


@dataclass
class FakeRun:
    id: str = "run-1"
    status: str = "pending"
    context: RunContext = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)
    failed_stage_error: str = ""
    revisions: dict[str, int] = field(default_factory=dict)
    gate_exhausted: list[str] = field(default_factory=list)


class FakeDispatcher:
    """Scripted dispatcher: outputs per node, optional failures and delays."""

    def __init__(
        self,
        outputs: dict[str, str | list[str]] | None = None,
        *,
        fail: set[str] | None = None,
        unsupported: set[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._outputs = outputs or {}
        self._fail = fail or set()
        self._unsupported = unsupported or set()
        self._delay = delay
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name not in self._unsupported

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        self.calls.append(node_name)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if node_name in self._fail:
                return DispatchResult(ok=False, error=f"{node_name} broke")
            scripted = self._outputs.get(node_name, f"{node_name} output")
            if isinstance(scripted, list):
                output = scripted[min(self.calls.count(node_name) - 1, len(scripted) - 1)]
            else:
                output = scripted
            return DispatchResult(ok=True, output=output)
        finally:
            self.in_flight -= 1


def _node(name: str, deps: tuple[str, ...] = (), **kwargs: Any) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name=f"agent-{name}",
        prompt_template="do {title} after: {" + (deps[0] if deps else "title") + "}",
        depends_on=deps,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_happy_path_runs_all_nodes_in_dependency_order() -> None:
    dispatcher = FakeDispatcher()
    graph = PipelineGraph([_node("a"), _node("b", ("a",)), _node("c", ("b",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert dispatcher.calls == ["a", "b", "c"]
    # INV-04: each node's output is recorded under its name.
    assert run.context["a"] == "a output"
    assert run.context["c"] == "c output"


@pytest.mark.asyncio
async def test_invalid_graph_never_executes() -> None:
    # INV-05: a cyclic graph fails validation before any execution.
    dispatcher = FakeDispatcher()
    graph = PipelineGraph([_node("a", ("b",)), _node("b", ("a",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status.startswith("invalid graph")
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_independent_nodes_run_concurrently() -> None:
    dispatcher = FakeDispatcher(delay=0.02)
    graph = PipelineGraph([_node("a"), _node("b"), _node("c", ("a", "b"))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert dispatcher.max_in_flight == 2


@pytest.mark.asyncio
async def test_skip_if_skips_node_and_unblocks_dependents() -> None:
    # INV-03
    dispatcher = FakeDispatcher()
    graph = PipelineGraph([_node("a", skip_if=lambda ctx: True), _node("b", ("a",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert run.skipped_stages == ["a"]
    assert dispatcher.calls == ["b"]


@pytest.mark.asyncio
async def test_unsupported_agent_is_skipped() -> None:
    dispatcher = FakeDispatcher(unsupported={"a"})
    graph = PipelineGraph([_node("a"), _node("b", ("a",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert run.skipped_stages == ["a"]
    assert dispatcher.calls == ["b"]


@pytest.mark.asyncio
async def test_failure_halts_downstream() -> None:
    # INV-02 / INV-07: no downstream node runs after a failure.
    dispatcher = FakeDispatcher(fail={"a"})
    graph = PipelineGraph([_node("a"), _node("b", ("a",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "failed at a"
    assert run.failed_stage_error == "a broke"
    assert dispatcher.calls == ["a"]
    assert "a" not in run.context


@pytest.mark.asyncio
async def test_timeout_fails_node_without_on_complete() -> None:
    # INV-09: timeout marks the stage failed and skips on_complete.
    hook_ran: list[str] = []

    async def hook(run: Any, output: str) -> None:
        hook_ran.append(output)

    dispatcher = FakeDispatcher(delay=0.2)
    graph = PipelineGraph([_node("a", timeout_seconds=0.01, on_complete=hook)])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "failed at a"
    assert "timed out" in run.failed_stage_error
    assert hook_ran == []


@pytest.mark.asyncio
async def test_on_complete_receives_run_and_output() -> None:
    # INV-08
    seen: list[tuple[Any, str]] = []

    async def hook(run: Any, output: str) -> None:
        seen.append((run, output))

    dispatcher = FakeDispatcher()
    graph = PipelineGraph([_node("a", on_complete=hook)])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert seen == [(run, "a output")]
    assert run.context["a"] == "a output"


@pytest.mark.asyncio
async def test_on_complete_can_fail_the_run() -> None:
    async def hook(run: Any, output: str) -> None:
        run.status = "failed at a"
        run.failed_stage_error = "verification failed"

    dispatcher = FakeDispatcher()
    graph = PipelineGraph([_node("a", on_complete=hook), _node("b", ("a",))])
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "failed at a"
    assert dispatcher.calls == ["a"]


@pytest.mark.asyncio
async def test_gate_failure_revises_target_with_feedback() -> None:
    # First review fails the gate; implement re-runs with feedback and the
    # second review passes.
    dispatcher = FakeDispatcher(
        outputs={"review": ["VIOLATION: missing tests", "APPROVED — clean"]}
    )
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: "approved" in str(ctx.get("review", "")).lower(),
                revise_target="implement",
                max_revisions=2,
            ),
        ]
    )
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert dispatcher.calls == ["implement", "review", "implement", "review"]
    assert run.revisions == {"review": 1}
    assert run.context["review_feedback"] == "VIOLATION: missing tests"
    assert "approved" in run.context["review"].lower()


@pytest.mark.asyncio
async def test_gate_exhausted_fail_policy_halts_run() -> None:
    dispatcher = FakeDispatcher(outputs={"review": "VIOLATION: still broken"})
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=1,
                gate_exhausted="fail",
            ),
            _node("after", ("review",)),
        ]
    )
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "failed at review"
    assert "Gate failed after 1 revisions" in run.failed_stage_error
    assert "after" not in dispatcher.calls
    # implement ran twice (original + one revision), review twice.
    assert dispatcher.calls.count("implement") == 2
    assert dispatcher.calls.count("review") == 2


@pytest.mark.asyncio
async def test_gate_exhausted_continue_policy_proceeds_downstream() -> None:
    dispatcher = FakeDispatcher(outputs={"review": "VIOLATION: still broken"})
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=1,
                gate_exhausted="continue",
            ),
            _node("cleanup", ("review",)),
        ]
    )
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert run.gate_exhausted == ["review"]
    assert "cleanup" in dispatcher.calls


@pytest.mark.asyncio
async def test_budget_exhaustion_halts_gracefully() -> None:
    dispatcher = FakeDispatcher(outputs={"review": "VIOLATION"})
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=50,
            ),
        ]
    )
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher, budget=IterationBudget(max_iterations=5)).execute(
        graph, run
    )

    assert "iteration budget exhausted" in run.status
    assert len(dispatcher.calls) == 5


@pytest.mark.asyncio
async def test_revision_clears_descendants_of_target() -> None:
    # docs depends on implement only; a review gate failure must also
    # invalidate docs so it re-runs against the revised implementation.
    dispatcher = FakeDispatcher(outputs={"review": ["VIOLATION", "APPROVED"]})
    graph = PipelineGraph(
        [
            _node("implement"),
            _node("docs", ("implement",)),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: "approved" in str(ctx.get("review", "")).lower(),
                revise_target="implement",
                max_revisions=2,
            ),
        ]
    )
    run = FakeRun()

    await GraphPipelineExecutor(dispatcher).execute(graph, run)

    assert run.status == "completed"
    assert dispatcher.calls.count("docs") == 2
    assert run.context["docs"] == "docs output"
