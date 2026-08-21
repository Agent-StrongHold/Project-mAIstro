"""Tests for RsiCycleHarnessAdapter — dispatch/poll/cancel over a background task."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.graph.harness import HarnessAdapter, HarnessRequest
from maistro_evolve.tournament import GenomeBattle
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome
from maistro_rsi.harness_adapter import RsiCycleHarnessAdapter, RsiCycleRunner
from maistro_rsi.runner import RsiCycleResult
from maistro_rsi.selfbranch import SelfBranchAttempt, SelfBranchResult


def _genome(name: str = "test") -> PipelineGenome:
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _cycle_result(
    *, improved_battles: int = 2, total_battles: int = 2, tests_passed: bool = True
) -> RsiCycleResult:
    attempt = SelfBranchAttempt(
        branch_name="rsi/attempt-1",
        repo_url="https://example.com/repo.git",
        test_command="pytest",
        commit_message="rsi patch",
        pr_title="RSI patch",
    )
    branch_result = SelfBranchResult(
        attempt=attempt,
        test_exit_code=0 if tests_passed else 1,
        test_output="ok" if tests_passed else "failed",
        diff="diff --git a/x b/x",
    )
    battles = [
        GenomeBattle(
            benchmark=f"bench{i}",
            genome_a_id="baseline",
            genome_b_id="candidate",
            winner_id="candidate",
        )
        for i in range(improved_battles)
    ] + [
        GenomeBattle(
            benchmark=f"bench{i}",
            genome_a_id="baseline",
            genome_b_id="candidate",
            winner_id="baseline",
        )
        for i in range(total_battles - improved_battles)
    ]
    return RsiCycleResult(
        run_id="run-abc123",
        model_used="cerebras-qwen-3-235b",
        branch_result=branch_result,
        baseline_results=[],
        candidate_results=[],
        battles=battles,
    )


class _FakeRunner:
    """Satisfies RsiCycleRunner without any sandbox/git/tournament machinery."""

    def __init__(
        self,
        result: RsiCycleResult | None = None,
        *,
        delay: float = 0.0,
        exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._delay = delay
        self._exc = exc
        self.calls: list[tuple[PipelineGenome, PipelineGenome, list[str]]] = []

    async def run(
        self, baseline: PipelineGenome, candidate: PipelineGenome, available_models: list[str]
    ) -> RsiCycleResult:
        self.calls.append((baseline, candidate, available_models))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


def _request(*, timeout_seconds: int = 3600, **context: Any) -> HarnessRequest:
    return HarnessRequest(
        harness_type="rsi_cycle",
        task="run RSI cycle",
        context=context,
        timeout_seconds=timeout_seconds,
    )


def test_fake_runner_satisfies_protocol() -> None:
    assert isinstance(_FakeRunner(), RsiCycleRunner)


def test_adapter_satisfies_harness_adapter_protocol() -> None:
    assert isinstance(RsiCycleHarnessAdapter(_FakeRunner()), HarnessAdapter)


async def test_dispatch_requires_genome_context() -> None:
    adapter = RsiCycleHarnessAdapter(_FakeRunner())
    with pytest.raises(ValueError, match="baseline_genome"):
        await adapter.dispatch(_request())


async def test_dispatch_requires_available_models() -> None:
    adapter = RsiCycleHarnessAdapter(_FakeRunner())
    with pytest.raises(ValueError, match="available_models"):
        await adapter.dispatch(
            _request(baseline_genome=_genome("a"), candidate_genome=_genome("b"))
        )


async def test_dispatch_returns_handle_immediately() -> None:
    runner = _FakeRunner(_cycle_result(), delay=0.05)
    adapter = RsiCycleHarnessAdapter(runner)

    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["cerebras-qwen-3-235b"],
        )
    )

    assert handle.harness_type == "rsi_cycle"
    assert handle.handle_id
    # Dispatch returned before the (still-sleeping) cycle finished.
    result = await adapter.poll(handle)
    assert result is None


async def test_poll_returns_none_while_running_then_result_when_done() -> None:
    runner = _FakeRunner(_cycle_result(improved_battles=2, total_battles=2), delay=0.02)
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
        )
    )

    assert await adapter.poll(handle) is None
    await asyncio.sleep(0.05)
    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is True  # improved: tests passed + benchmark majority
    assert result.metadata["cycles_completed"] == 1
    assert result.metadata["cycles_improved"] == 1
    assert result.metadata["cycles"][0]["run_id"] == "run-abc123"
    assert result.metadata["cycles"][0]["benchmarks_won"] == 2
    assert result.metadata["cycles"][0]["battles_total"] == 2


async def test_poll_reports_not_improved_as_unsuccessful() -> None:
    runner = _FakeRunner(_cycle_result(improved_battles=0, total_battles=2, tests_passed=True))
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"), candidate_genome=_genome("b"), available_models=["m1"]
        )
    )
    await asyncio.sleep(0.01)

    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is False


async def test_poll_surfaces_exception_from_the_cycle() -> None:
    runner = _FakeRunner(exc=RuntimeError("sandbox blew up"))
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"), candidate_genome=_genome("b"), available_models=["m1"]
        )
    )
    await asyncio.sleep(0.01)

    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is False
    assert result.error == "sandbox blew up"


async def test_poll_unknown_handle_fails_without_crashing() -> None:
    from maistro.graph.harness import HarnessHandle

    adapter = RsiCycleHarnessAdapter(_FakeRunner())
    result = await adapter.poll(
        HarnessHandle(handle_id="never-dispatched", harness_type="rsi_cycle")
    )

    assert result is not None
    assert result.success is False
    assert result.error == "unknown handle"


async def test_poll_past_deadline_times_out_and_cancels() -> None:
    runner = _FakeRunner(_cycle_result(), delay=10.0)
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
            timeout_seconds=0,
        )
    )

    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is False
    assert result.error == "timed out"


async def test_cancel_stops_the_in_flight_task() -> None:
    runner = _FakeRunner(_cycle_result(), delay=10.0)
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"), candidate_genome=_genome("b"), available_models=["m1"]
        )
    )

    await adapter.cancel(handle)
    await asyncio.sleep(0.01)

    # Cancelled and forgotten -- polling again reports "unknown handle", not a hang.
    result = await adapter.poll(handle)
    assert result is not None
    assert result.error == "unknown handle"


async def test_cancel_unknown_handle_is_a_no_op() -> None:
    from maistro.graph.harness import HarnessHandle

    adapter = RsiCycleHarnessAdapter(_FakeRunner())
    await adapter.cancel(HarnessHandle(handle_id="never-dispatched", harness_type="rsi_cycle"))


async def test_runner_receives_the_genomes_and_models_from_context() -> None:
    runner = _FakeRunner(_cycle_result())
    adapter = RsiCycleHarnessAdapter(runner)
    baseline = _genome("baseline")
    candidate = _genome("candidate")

    handle = await adapter.dispatch(
        _request(
            baseline_genome=baseline, candidate_genome=candidate, available_models=["m1", "m2"]
        )
    )
    await asyncio.sleep(0.01)
    await adapter.poll(handle)

    assert runner.calls == [(baseline, candidate, ["m1", "m2"])]


# --- num_cycles: parallel multi-cycle dispatch ------------------------------


class _SequencedRunner:
    """Returns/raises a distinct outcome per call, in call order -- lets a
    test control exactly which of several parallel cycles fails."""

    def __init__(self, outcomes: list[RsiCycleResult | Exception]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def run(
        self, baseline: PipelineGenome, candidate: PipelineGenome, available_models: list[str]
    ) -> RsiCycleResult:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_dispatch_starts_num_cycles_concurrently() -> None:
    runner = _FakeRunner(_cycle_result(), delay=0.02)
    adapter = RsiCycleHarnessAdapter(runner)

    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
            num_cycles=3,
        )
    )
    await asyncio.sleep(0)  # let all 3 tasks reach their call-recording line
    assert len(runner.calls) == 3

    await asyncio.sleep(0.05)
    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is True
    assert result.metadata["cycles_completed"] == 3
    assert result.metadata["cycles_improved"] == 3
    assert len(result.metadata["cycles"]) == 3


async def test_dispatch_with_zero_num_cycles_starts_no_tasks() -> None:
    runner = _FakeRunner(_cycle_result())
    adapter = RsiCycleHarnessAdapter(runner)

    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
            num_cycles=0,
        )
    )
    assert not runner.calls  # no RsiCycle.run task was ever created

    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is True
    assert result.error is None
    assert result.metadata["cycles_completed"] == 0
    assert result.metadata["cycles_improved"] == 0
    assert result.metadata["cycles_failed"] == 0


async def test_multi_cycle_succeeds_if_any_cycle_improved_despite_a_failure() -> None:
    runner = _SequencedRunner(
        [
            _cycle_result(improved_battles=2, total_battles=2),
            RuntimeError("cycle 2 blew up"),
            _cycle_result(improved_battles=0, total_battles=2),
        ]
    )
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
            num_cycles=3,
        )
    )
    await asyncio.sleep(0.01)
    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is True  # one of the three improved
    assert result.metadata["cycles_completed"] == 2
    assert result.metadata["cycles_improved"] == 1
    assert result.metadata["cycles_failed"] == 1
    assert "cycle 2 blew up" in result.metadata["errors"]


async def test_multi_cycle_timeout_cancels_every_remaining_task() -> None:
    runner = _FakeRunner(_cycle_result(), delay=10.0)
    adapter = RsiCycleHarnessAdapter(runner)
    handle = await adapter.dispatch(
        _request(
            baseline_genome=_genome("a"),
            candidate_genome=_genome("b"),
            available_models=["m1"],
            num_cycles=3,
            timeout_seconds=0,
        )
    )

    result = await adapter.poll(handle)

    assert result is not None
    assert result.success is False
    assert result.error == "timed out"


# --- dict-serialized genomes -------------------------------------------------


async def test_dispatch_accepts_dict_form_genomes() -> None:
    """A persisted/JSON-deserialized durable DAG's HarnessRequest.context
    carries plain dicts, not live PipelineGenome instances."""
    runner = _FakeRunner(_cycle_result())
    adapter = RsiCycleHarnessAdapter(runner)
    baseline_dict = _genome("baseline").model_dump()
    candidate_dict = _genome("candidate").model_dump()

    handle = await adapter.dispatch(
        _request(
            baseline_genome=baseline_dict,
            candidate_genome=candidate_dict,
            available_models=["m1"],
        )
    )
    await asyncio.sleep(0.01)
    await adapter.poll(handle)

    assert len(runner.calls) == 1
    seen_baseline, seen_candidate, _ = runner.calls[0]
    assert isinstance(seen_baseline, PipelineGenome)
    assert isinstance(seen_candidate, PipelineGenome)
    assert seen_baseline.id == "g-baseline"
    assert seen_candidate.id == "g-candidate"


async def test_dispatch_rejects_a_genome_that_is_neither_dict_nor_pipeline_genome() -> None:
    adapter = RsiCycleHarnessAdapter(_FakeRunner())
    with pytest.raises(ValueError, match="baseline_genome"):
        await adapter.dispatch(
            _request(baseline_genome=123, candidate_genome=_genome("b"), available_models=["m1"])
        )
