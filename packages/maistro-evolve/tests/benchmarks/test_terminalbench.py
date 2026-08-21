from __future__ import annotations

import json
from typing import Any

import pytest

import maistro_evolve.benchmarks.terminalbench as terminalbench_module
from maistro_evolve.benchmarks.executable_terminal import HOLDOUT_TASKS, TRAINING_TASKS
from maistro_evolve.benchmarks.terminalbench import run_terminalbench

from .conftest import make_genome

# The underlying engine (initial_files/expected_files verification, action
# language parsing, untrusted-data handling) is exercised directly and
# thoroughly in tests/test_executable_terminal.py. These tests only cover
# run_terminalbench's wiring: prompt building, llm_call plumbing, and result
# aggregation into an EvalResult.

_GOOD_PLAN = json.dumps(
    [
        {"op": "copy", "src": "template.ini", "dst": "config/prod.ini"},
        {"op": "replace", "path": "config/prod.ini", "old": "PORT=8080", "new": "PORT=80"},
        {"op": "replace", "path": "config/prod.ini", "old": "MODE=dev", "new": "MODE=prod"},
    ]
)


class TestRunTerminalbench:
    async def test_llm_call_none_raises(self) -> None:
        genome = make_genome()
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_terminalbench(genome, None)

    async def test_scores_training_and_holdout_splits_separately(self) -> None:
        """The default task set is train+holdout, and each split is reported.

        The holdout is deliberately NOT withheld from the headline score (3
        training tasks is too thin a fitness signal), so what this asserts is
        observability: the two splits are averaged separately in metadata so
        train-up/holdout-flat divergence is visible instead of averaged away.
        """
        assert len(TRAINING_TASKS) == 3
        assert len(HOLDOUT_TASKS) == 3
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            # Solves TRAINING_TASKS[0] only; every other task fails. Which tasks
            # pass doesn't matter here — the point is that the per-split means
            # and the combined mean stay consistent with each other.
            return _GOOD_PLAN

        result = await run_terminalbench(genome, llm_call)
        assert result.metadata["total_samples"] == 6
        assert result.metadata["split"] == "combined"
        assert result.metadata["train_samples"] == 3
        assert result.metadata["holdout_samples"] == 3
        assert result.metadata["errors"] == 0
        train = result.metadata["train_score"]
        holdout = result.metadata["holdout_score"]
        assert train is not None and holdout is not None
        # The combined score is the sample-weighted mean of the two splits.
        assert result.score == pytest.approx((train * 3 + holdout * 3) / 6, abs=1e-4)
        assert result.metadata["generalization_gap"] == pytest.approx(train - holdout, abs=1e-4)
        # Every recorded failure is attributed to a split.
        for failure in result.metadata["failures"]:
            assert failure["split"] in {"train", "holdout"}

    async def test_single_split_subset_reports_the_other_split_as_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return _GOOD_PLAN

        result = await run_terminalbench(genome, llm_call)
        assert result.metadata["total_samples"] == 1
        assert result.metadata["train_samples"] == 1
        assert result.metadata["holdout_samples"] == 0
        assert result.metadata["train_score"] == result.score
        # No holdout ran, so there is no holdout score and no gap to report —
        # not a zero, which would read as "the holdout failed".
        assert result.metadata["holdout_score"] is None
        assert result.metadata["generalization_gap"] is None

    async def test_holdout_only_subset_is_attributed_to_the_holdout_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", HOLDOUT_TASKS[:1])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return _GOOD_PLAN

        result = await run_terminalbench(genome, llm_call)
        assert result.metadata["holdout_samples"] == 1
        assert result.metadata["train_samples"] == 0
        assert result.metadata["holdout_score"] == result.score
        assert result.metadata["train_score"] is None

    async def test_correct_plan_passes_and_is_scored_via_real_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return _GOOD_PLAN

        result = await run_terminalbench(genome, llm_call)
        assert result.benchmark == "proxy_terminalbench"
        assert result.samples_evaluated == 1
        assert result.score == 1.0
        assert result.cost_usd > 0.0
        assert result.metadata["fidelity"] == "proxy"
        assert result.metadata["check"] == "verified_filesystem_state"
        assert result.metadata["failures"] == []

    async def test_wrong_plan_fails_with_mismatch_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            # Does nothing — expected_files never get created.
            return json.dumps([])

        result = await run_terminalbench(genome, llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert len(result.metadata["failures"]) == 1
        assert result.metadata["failures"][0]["id"] == TRAINING_TASKS[0].id
        assert result.metadata["failures"][0]["mismatches"]

    async def test_prompt_includes_action_language_and_instruction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome()
        captured: dict[str, Any] = {}

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            captured["messages"] = messages
            return _GOOD_PLAN

        await run_terminalbench(genome, llm_call)
        user_content = captured["messages"][-1]["content"]
        assert "Return a JSON array of actions" in user_content
        assert TRAINING_TASKS[0].instruction in user_content

    async def test_llm_call_exception_increments_evaluated_without_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome()

        async def failing_llm_call(messages: Any, **kwargs: Any) -> str:
            raise RuntimeError("network down")

        result = await run_terminalbench(genome, failing_llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert result.cost_usd == 0.0
        # A gateway error scores 0.0 exactly like a genuine failure, so the only
        # way to tell "the model was wrong" from "the call never happened" is
        # this counter. Without it a degraded gateway reads as a regression.
        assert result.metadata["errors"] == 1
        assert result.metadata["failures"][0]["error"].startswith("error: ")

    async def test_llm_call_receives_model_config_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(terminalbench_module, "_TASKS", TRAINING_TASKS[:1])
        genome = make_genome(temperature=0.42, max_tokens=777)
        seen: dict[str, Any] = {}

        async def llm_call(messages: Any, temperature: float = 0.1, max_tokens: int = 1024) -> str:
            seen["temperature"] = temperature
            seen["max_tokens"] = max_tokens
            return _GOOD_PLAN

        await run_terminalbench(genome, llm_call)
        assert seen == {"temperature": 0.42, "max_tokens": 777}
