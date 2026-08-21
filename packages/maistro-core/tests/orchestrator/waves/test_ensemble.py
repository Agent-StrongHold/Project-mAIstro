"""Tests for the SuperPlanner wave ensemble (SPEC-070226-b624 / ADR-071)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.graph.strategy import NodeStrategy
from maistro.graph.types import GraphBlackboard, GraphTask
from maistro.orchestrator.planner import SuperPlanner
from maistro.orchestrator.waves.ensemble import (
    EVENT_WAVE_COMPLETED,
    EVENT_WAVE_FAILED,
    EVENT_WAVE_STARTED,
    EVENT_WAVES_COMPARED,
    EVENT_WAVES_PLANNED,
    STATE_WAVES_COMPLETE,
    STATE_WAVES_PLANNED,
    InMemoryCheckpointStore,
    LLMJudgeComparator,
    MultiStrategyExpander,
    QualityComparator,
    SuperPlannerConfig,
    Wave,
    WaveEnsembleError,
    WaveEnsembleOutput,
    WaveEnsembleStrategy,
    WaveOrchestrator,
    WaveResult,
    WaveTask,
    task_to_wave_task,
)
from maistro.tasks.checkpoint import CheckpointKind


def make_task(task_id: str = "task-1") -> WaveTask:
    return WaveTask(id=task_id, description="solve it", context={"shared": {"k": "v"}})


def make_result(wave_id: str, score: float, task_id: str = "task-1") -> WaveResult:
    return WaveResult(
        wave_id=wave_id,
        task_id=task_id,
        output=f"output-{wave_id}",
        metadata={"quality_score": score},
    )


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


async def echo_runner(wave: Wave, task: WaveTask) -> WaveResult:
    return WaveResult(
        wave_id=wave.id,
        task_id=task.id,
        output=f"{wave.context.get('reasoning_strategy')}:{task.description}",
        metadata={"quality_score": 0.5},
    )


# ---------------------------------------------------------------------------
# MultiStrategyExpander
# ---------------------------------------------------------------------------


class TestMultiStrategyExpander:
    @pytest.mark.asyncio
    async def test_produces_n_waves_with_distinct_strategies(self) -> None:
        waves = await MultiStrategyExpander().expand(make_task(), max_waves=3)
        assert len(waves) == 3
        strategies = [w.context["reasoning_strategy"] for w in waves]
        assert strategies == ["chain_of_thought", "tree_of_thought", "self_critique"]
        assert len({w.id for w in waves}) == 3

    @pytest.mark.asyncio
    async def test_max_waves_caps_expansion(self) -> None:
        waves = await MultiStrategyExpander().expand(make_task(), max_waves=2)
        assert len(waves) == 2

    @pytest.mark.asyncio
    async def test_contexts_are_isolated_no_shared_mutable_state(self) -> None:
        task = make_task()
        waves = await MultiStrategyExpander().expand(task, max_waves=3)
        # Mutating one wave's context must not leak into siblings or the task.
        waves[0].context["shared"]["k"] = "mutated"
        waves[0].context["extra"] = True
        assert waves[1].context["shared"]["k"] == "v"
        assert waves[2].context["shared"]["k"] == "v"
        assert task.context["shared"]["k"] == "v"
        assert "extra" not in waves[1].context

    @pytest.mark.asyncio
    async def test_custom_strategies(self) -> None:
        expander = MultiStrategyExpander(("a", "b"), timeout_ms=123)
        waves = await expander.expand(make_task(), max_waves=5)
        assert [w.agent_ids for w in waves] == [["agent_a"], ["agent_b"]]
        assert all(w.timeout_ms == 123 for w in waves)


# ---------------------------------------------------------------------------
# QualityComparator
# ---------------------------------------------------------------------------


class TestQualityComparator:
    def test_picks_highest_quality(self) -> None:
        results = [make_result("w0", 0.2), make_result("w1", 0.9), make_result("w2", 0.5)]
        assert QualityComparator().compare(results).wave_id == "w1"

    def test_deterministic_on_ties_and_repeat_calls(self) -> None:
        results = [make_result("w0", 0.7), make_result("w1", 0.7)]
        comparator = QualityComparator()
        winners = {comparator.compare(results).wave_id for _ in range(10)}
        assert winners == {"w0"}

    def test_missing_quality_score_defaults_to_zero(self) -> None:
        no_score = WaveResult(wave_id="w0", task_id="t", output="x")
        scored = make_result("w1", 0.1)
        assert QualityComparator().compare([no_score, scored]).wave_id == "w1"

    def test_empty_results_raise(self) -> None:
        with pytest.raises(WaveEnsembleError):
            QualityComparator().compare([])

    @pytest.mark.asyncio
    async def test_llm_judge_is_a_stub(self) -> None:
        with pytest.raises(NotImplementedError):
            await LLMJudgeComparator().compare([make_result("w0", 0.1)])


# ---------------------------------------------------------------------------
# WaveOrchestrator execution
# ---------------------------------------------------------------------------


class TestWaveExecution:
    @pytest.mark.asyncio
    async def test_single_wave_baseline_equivalence(self) -> None:
        """One wave with one agent returns exactly what the agent alone returns."""
        task = make_task()
        wave = Wave(id="wave_0", agent_ids=["agent_chain_of_thought"], context=dict(task.context))
        wave.context["reasoning_strategy"] = "chain_of_thought"
        baseline = await echo_runner(wave, task)

        orchestrator = WaveOrchestrator(
            echo_runner,
            expander=MultiStrategyExpander(("chain_of_thought",)),
            config=SuperPlannerConfig(max_waves=1),
        )
        best = await orchestrator.execute(task)
        assert best.wave_id == "wave_0"
        assert best.output == baseline.output
        assert best.quality_score == baseline.quality_score

    @pytest.mark.asyncio
    async def test_returns_single_best_result(self) -> None:
        scores = {"wave_0": 0.1, "wave_1": 0.9, "wave_2": 0.4}

        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            return make_result(wave.id, scores[wave.id], task.id)

        best = await WaveOrchestrator(runner).execute(make_task())
        assert best.wave_id == "wave_1"

    @pytest.mark.asyncio
    async def test_waves_run_concurrently_with_isolated_contexts(self) -> None:
        seen: list[dict[str, Any]] = []

        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            wave.context["scribble"] = wave.id  # mutate own context only
            await asyncio.sleep(0)
            seen.append(wave.context)
            return make_result(wave.id, 0.5, task.id)

        await WaveOrchestrator(runner).execute(make_task())
        assert len(seen) == 3
        assert len({id(ctx["shared"]) for ctx in seen}) == 3  # distinct objects
        assert sorted(ctx["scribble"] for ctx in seen) == ["wave_0", "wave_1", "wave_2"]

    @pytest.mark.asyncio
    async def test_timeout_of_one_wave_does_not_kill_others(self) -> None:
        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            if wave.context["reasoning_strategy"] == "tree_of_thought":
                await asyncio.sleep(30)  # will hit the per-wave timeout
            return make_result(wave.id, 0.5, task.id)

        recorder = Recorder()
        orchestrator = WaveOrchestrator(
            runner,
            expander=MultiStrategyExpander(timeout_ms=50),
            emit=recorder,
        )
        best = await orchestrator.execute(make_task())
        assert best.wave_id in {"wave_0", "wave_2"}
        failed = [f for n, f in recorder.events if n == EVENT_WAVE_FAILED]
        assert len(failed) == 1 and failed[0]["error"] == "timeout"
        completed = [f for n, f in recorder.events if n == EVENT_WAVE_COMPLETED]
        assert len(completed) == 2

    @pytest.mark.asyncio
    async def test_exception_in_one_wave_does_not_kill_others(self) -> None:
        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            if wave.id == "wave_0":
                raise RuntimeError("boom")
            return make_result(wave.id, 0.5, task.id)

        best = await WaveOrchestrator(runner).execute(make_task())
        assert best.wave_id in {"wave_1", "wave_2"}

    @pytest.mark.asyncio
    async def test_all_waves_failed_raises(self) -> None:
        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            raise RuntimeError("boom")

        with pytest.raises(WaveEnsembleError, match="all waves failed"):
            await WaveOrchestrator(runner).execute(make_task())

    @pytest.mark.asyncio
    async def test_event_sequence(self) -> None:
        recorder = Recorder()
        await WaveOrchestrator(echo_runner, emit=recorder).execute(make_task())
        names = recorder.names()
        assert names[0] == EVENT_WAVES_PLANNED
        assert names[-1] == EVENT_WAVES_COMPARED
        assert names.count(EVENT_WAVE_STARTED) == 3
        assert names.count(EVENT_WAVE_COMPLETED) == 3
        planned = recorder.events[0][1]
        assert planned == {"task_id": "task-1", "wave_count": 3}
        compared = recorder.events[-1][1]
        assert compared["winner"] == "wave_0" and compared["task_id"] == "task-1"


# ---------------------------------------------------------------------------
# Checkpointing + crash recovery (ADR-056)
# ---------------------------------------------------------------------------


class TestCheckpointRecovery:
    @pytest.mark.asyncio
    async def test_checkpoints_written_before_and_after(self) -> None:
        store = InMemoryCheckpointStore()
        await WaveOrchestrator(echo_runner, checkpoint_store=store).execute(make_task())
        checkpoints = await store.load("task-1")
        assert [c.kind for c in checkpoints] == [
            CheckpointKind.WAVE_FAN_OUT,
            CheckpointKind.WAVE_COMPLETED,
        ]
        assert checkpoints[0].payload["state"] == STATE_WAVES_PLANNED
        assert checkpoints[0].payload["wave_ids"] == ["wave_0", "wave_1", "wave_2"]
        assert checkpoints[1].payload["state"] == STATE_WAVES_COMPLETE
        assert [c.sequence for c in checkpoints] == [0, 1]

    @pytest.mark.asyncio
    async def test_recovery_skips_rerun_when_waves_complete(self) -> None:
        store = InMemoryCheckpointStore()
        calls: list[str] = []

        async def counting_runner(wave: Wave, task: WaveTask) -> WaveResult:
            calls.append(wave.id)
            return make_result(wave.id, 0.5, task.id)

        orchestrator = WaveOrchestrator(counting_runner, checkpoint_store=store)
        first = await orchestrator.execute(make_task())
        assert len(calls) == 3

        # Simulate a crash + resume: a fresh orchestrator over the same store.
        resumed = WaveOrchestrator(counting_runner, checkpoint_store=store)
        second = await resumed.execute(make_task())
        assert len(calls) == 3  # waves were NOT re-run
        assert second.wave_id == first.wave_id
        assert second.output == first.output

    @pytest.mark.asyncio
    async def test_recovery_reruns_when_only_waves_planned(self) -> None:
        store = InMemoryCheckpointStore()

        async def crashing_runner(wave: Wave, task: WaveTask) -> WaveResult:
            raise asyncio.CancelledError  # crash mid-wave

        crashed = WaveOrchestrator(crashing_runner, checkpoint_store=store)
        with pytest.raises(asyncio.CancelledError):
            await crashed.execute(make_task())
        assert (await store.load("task-1"))[-1].payload["state"] == STATE_WAVES_PLANNED

        calls: list[str] = []

        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            calls.append(wave.id)
            return make_result(wave.id, 0.5, task.id)

        best = await WaveOrchestrator(runner, checkpoint_store=store).execute(make_task())
        assert len(calls) == 3  # re-ran from waves_planned
        assert best.wave_id == "wave_0"

    @pytest.mark.asyncio
    async def test_restart_strategy_ignores_saved_results(self) -> None:
        store = InMemoryCheckpointStore()
        calls: list[str] = []

        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            calls.append(wave.id)
            return make_result(wave.id, 0.5, task.id)

        await WaveOrchestrator(runner, checkpoint_store=store).execute(make_task())
        restart = WaveOrchestrator(
            runner,
            checkpoint_store=store,
            config=SuperPlannerConfig(recovery_strategy="restart"),
        )
        await restart.execute(make_task())
        assert len(calls) == 6

    @pytest.mark.asyncio
    async def test_recover_returns_none_without_checkpoint(self) -> None:
        orchestrator = WaveOrchestrator(echo_runner)
        assert await orchestrator.recover("unknown-task") is None


# ---------------------------------------------------------------------------
# SuperPlanner extension
# ---------------------------------------------------------------------------


class TestSuperPlannerEnsemble:
    @pytest.mark.asyncio
    async def test_execute_ensemble(self) -> None:
        recorder = Recorder()
        best = await SuperPlanner().execute_ensemble(make_task(), echo_runner, emit=recorder)
        assert best.wave_id == "wave_0"
        assert EVENT_WAVES_COMPARED in recorder.names()

    def test_build_wave_orchestrator(self) -> None:
        orchestrator = SuperPlanner().build_wave_orchestrator(echo_runner)
        assert isinstance(orchestrator, WaveOrchestrator)

    def test_existing_plan_api_unchanged(self) -> None:
        waves = SuperPlanner().plan()
        assert len(waves) > 1  # legacy template planning still works


# ---------------------------------------------------------------------------
# Graph integration (ADR-062)
# ---------------------------------------------------------------------------


class TestWaveEnsembleStrategy:
    def _strategy(self) -> WaveEnsembleStrategy:
        return WaveEnsembleStrategy(WaveOrchestrator(echo_runner))

    def test_satisfies_node_strategy_protocol(self) -> None:
        strategy = self._strategy()
        assert isinstance(strategy, NodeStrategy)
        assert strategy.output_type is WaveEnsembleOutput

    def test_build_user_prompt_and_scoring(self) -> None:
        strategy = self._strategy()
        task = GraphTask(description="do the thing", workspace="/ws", constraints=["c1"])
        prompt = strategy.build_user_prompt(
            task, GraphBlackboard(task_objective="obj", workspace="ws"), None, None, None
        )
        assert "do the thing" in prompt and "c1" in prompt
        output = WaveEnsembleOutput(winner_wave_id="wave_1", quality_score=0.75)
        assert strategy.score_output(output) == 0.75
        assert strategy.score_output(GraphBlackboard(task_objective="obj", workspace="ws")) == 0.0

    def test_update_blackboard_annotates_winner(self) -> None:
        strategy = self._strategy()
        output = WaveEnsembleOutput(winner_wave_id="wave_1", quality_score=0.75)
        board = strategy.update_blackboard(
            output, GraphBlackboard(task_objective="obj", workspace="ws")
        )
        assert "wave_1" in board.node_annotations["wave_ensemble"]

    @pytest.mark.asyncio
    async def test_run_ensemble_returns_typed_output(self) -> None:
        output = await self._strategy().run_ensemble(make_task())
        assert isinstance(output, WaveEnsembleOutput)
        assert output.winner_wave_id == "wave_0"
        assert output.task_id == "task-1"

    def test_task_to_wave_task(self) -> None:
        task = GraphTask(description="d", workspace="/ws", constraints=["c"])
        wave_task = task_to_wave_task(task)
        assert wave_task.description == "d"
        assert wave_task.context == {"workspace": "/ws", "constraints": ["c"]}


# ---------------------------------------------------------------------------
# Concurrency / load
# ---------------------------------------------------------------------------


class TestConcurrentInvocations:
    @pytest.mark.asyncio
    async def test_ten_concurrent_ensembles_no_context_crossing(self) -> None:
        async def runner(wave: Wave, task: WaveTask) -> WaveResult:
            await asyncio.sleep(0)
            assert wave.context["task_marker"] == task.id  # no cross-task leakage
            return make_result(wave.id, 0.5, task.id)

        async def run_one(i: int) -> WaveResult:
            task = WaveTask(id=f"task-{i}", description="d", context={"task_marker": f"task-{i}"})
            return await WaveOrchestrator(runner).execute(task)

        results = await asyncio.gather(*(run_one(i) for i in range(10)))
        assert [r.task_id for r in results] == [f"task-{i}" for i in range(10)]
