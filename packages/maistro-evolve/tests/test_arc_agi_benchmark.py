"""ARC-AGI as the M4-G second domain: grid induction with a host-owned verdict.

The adapter's job is to make a *second* task domain measurable without
overclaiming: the grader is exact structural match over the official grid
task format, the withheld answer never reaches the prompt, and the result is
never presented as comparable to a published leaderboard number.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from maistro_evolve.benchmarks import REAL_BENCHMARKS
from maistro_evolve.benchmarks import arc_agi as arc
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome() -> PipelineGenome:
    return PipelineGenome(
        id="g1",
        name="g1",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="direct",
                    model="test-model",
                    system_prompt="You solve grid tasks.",
                    temperature=0.0,
                    max_tokens=512,
                    max_tool_rounds=1,
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


def _task(output: list[list[int]] | None = None) -> dict[str, Any]:
    return {
        "train": [
            {"input": [[1, 2], [3, 4]], "output": [[2, 1], [4, 3]]},
            {"input": [[5, 6]], "output": [[6, 5]]},
        ],
        "test": [{"input": [[7, 8], [9, 0]], "output": output or [[8, 7], [0, 9]]}],
    }


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    directory = tmp_path / "tasks"
    directory.mkdir()
    (directory / "a_task.json").write_text(json.dumps(_task()), encoding="utf-8")
    (directory / "b_task.json").write_text(
        json.dumps(_task(output=[[1, 1], [2, 2]])), encoding="utf-8"
    )
    return directory


class TestCorpusLoading:
    def test_a_missing_corpus_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(arc.ArcAgiUnavailableError, match="corpus directory missing"):
            arc.load_arc_tasks(tmp_path / "nope")

    def test_an_empty_corpus_directory_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(arc.ArcAgiUnavailableError, match="no task files"):
            arc.load_arc_tasks(empty)

    def test_tasks_load_in_sorted_filename_order(self, corpus: Path) -> None:
        tasks = arc.load_arc_tasks(corpus)
        assert len(tasks) == 2

    def test_a_task_without_train_and_test_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        (directory / "x.json").write_text(json.dumps({"train": []}), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="not an ARC task"):
            arc.load_arc_tasks(directory)

    def test_a_train_pair_without_grids_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        payload = _task()
        payload["train"][0]["output"] = "not a grid"
        (directory / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="well-formed input/output grids"):
            arc.load_arc_tasks(directory)

    def test_a_test_entry_without_an_expected_output_raises(self, tmp_path: Path) -> None:
        """A task that cannot be graded must not be scored as a failure."""
        directory = tmp_path / "bad"
        directory.mkdir()
        payload = _task()
        payload["test"][0]["output"] = []
        (directory / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="cannot be graded"):
            arc.load_arc_tasks(directory)

    def test_a_task_with_an_empty_train_array_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        payload = _task()
        payload["train"] = []
        (directory / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="'train' must be a non-empty array"):
            arc.load_arc_tasks(directory)

    def test_a_task_with_an_empty_test_array_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        payload = _task()
        payload["test"] = []
        (directory / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="'test' must be a non-empty array"):
            arc.load_arc_tasks(directory)

    def test_a_test_entry_without_an_input_grid_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        payload = _task()
        payload["test"][0]["input"] = "not a grid"
        (directory / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="test entry without input grid"):
            arc.load_arc_tasks(directory)

    def test_an_unreadable_task_file_raises(self, tmp_path: Path) -> None:
        directory = tmp_path / "bad"
        directory.mkdir()
        (directory / "x.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(arc.ArcAgiUnavailableError, match="unreadable task file"):
            arc.load_arc_tasks(directory)


class TestPrompt:
    def test_the_withheld_answer_is_never_rendered(self) -> None:
        """The task file holds the answer; the prompt must not."""
        prompt = arc.render_task(_task())
        assert "8 7" not in prompt
        assert "0 9" not in prompt
        assert "Test input:" in prompt
        assert "7 8" in prompt

    def test_the_train_pairs_are_rendered(self) -> None:
        prompt = arc.render_task(_task())
        assert "Example 1 input:" in prompt
        assert "Example 2 output:" in prompt
        assert "6 5" in prompt

    def test_the_train_pair_count_can_be_capped(self) -> None:
        prompt = arc.render_task(_task(), max_train_pairs=1)
        assert "Example 1 input:" in prompt
        assert "Example 2 input:" not in prompt


class TestGrading:
    def test_an_exact_grid_match_passes(self) -> None:
        correct, spoofed = arc.grade_attempt("[[8, 7], [0, 9]]", [[8, 7], [0, 9]])
        assert correct is True
        assert spoofed is False

    def test_a_fenced_grid_match_passes(self) -> None:
        correct, _ = arc.grade_attempt(
            "```json\n[[8, 7], [0, 9]]\n```",
            [[8, 7], [0, 9]],
        )
        assert correct is True

    def test_a_wrong_grid_fails_without_a_gaming_signal(self) -> None:
        correct, spoofed = arc.grade_attempt("[[1, 2], [3, 4]]", [[8, 7], [0, 9]])
        assert correct is False
        assert spoofed is False

    def test_a_printed_pass_marker_never_passes_and_is_counted(self) -> None:
        """The #852 defect class: text that claims success."""
        correct, spoofed = arc.grade_attempt("PASS — I solved it", [[8, 7], [0, 9]])
        assert correct is False
        assert spoofed is True

    def test_prose_never_passes(self) -> None:
        correct, spoofed = arc.grade_attempt(
            "The transformation is a reflection, so the answer is 8 7 / 0 9.",
            [[8, 7], [0, 9]],
        )
        assert correct is False
        assert spoofed is False

    def test_an_empty_response_never_passes(self) -> None:
        assert arc.parse_output_grid("") is None
        assert arc.grade_attempt("", [[1]]) == (False, False)

    def test_a_json_object_is_not_a_grid(self) -> None:
        assert arc.parse_output_grid('{"answer": [[1]]}') is None

    def test_a_partial_grid_is_not_a_grid(self) -> None:
        assert arc.parse_output_grid("[[1, 2], [3]]") is None

    def test_a_grid_with_an_empty_row_is_not_a_grid(self) -> None:
        """An empty row is not a row: the format needs cells."""
        assert arc.parse_output_grid("[[]]") is None

    def test_booleans_are_not_grid_cells(self) -> None:
        assert arc.parse_output_grid("[[true, 1]]") is None


class TestRun:
    async def test_a_missing_llm_call_raises(self, corpus: Path) -> None:
        """No fabricated scores: there is no stub fallback."""
        with pytest.raises(ValueError, match="requires an llm_call"):
            await arc.run_arc_agi(_genome(), None, corpus_dir=corpus)

    async def test_attempts_below_one_raise(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        with pytest.raises(ValueError, match="attempts must be >= 1"):
            await arc.run_arc_agi(_genome(), call, attempts=0, corpus_dir=corpus)

    async def test_a_fully_correct_run_scores_one(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        result = await arc.run_arc_agi(_genome(), call, corpus_dir=corpus)
        assert result.benchmark == "arc_agi"
        assert result.score == 0.5
        assert result.samples_evaluated == 2
        assert result.metadata["fidelity"] == "real"
        assert result.metadata["parse_failures"] == 0

    async def test_the_result_is_never_comparable_to_a_published_number(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        result = await arc.run_arc_agi(_genome(), call, corpus_dir=corpus)
        assert result.metadata["official_comparable"] is False
        assert "matched" in result.metadata["official_comparable_reason"]

    async def test_a_wrong_answer_is_a_failure_not_a_pass(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[0, 0], [0, 0]]"

        result = await arc.run_arc_agi(_genome(), call, corpus_dir=corpus)
        assert result.score == 0.0
        assert result.samples_evaluated == 2

    async def test_unparseable_answers_are_counted_as_parse_failures(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "I am not going to answer in the requested format."

        result = await arc.run_arc_agi(_genome(), call, attempts=1, corpus_dir=corpus)
        assert result.score == 0.0
        assert result.metadata["parse_failures"] == 2

    async def test_a_spoofed_pass_marker_is_counted_as_a_gaming_signal(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "PASS"

        result = await arc.run_arc_agi(_genome(), call, attempts=1, corpus_dir=corpus)
        assert result.score == 0.0
        assert result.metadata["gaming_signals"] == {"spoofed_pass_marker": 2}

    async def test_a_failed_call_is_counted_separately_from_a_parse_failure(
        self, corpus: Path
    ) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("provider exploded")

        result = await arc.run_arc_agi(_genome(), call, attempts=1, corpus_dir=corpus)
        assert result.score == 0.0
        assert result.metadata["call_errors"] == 2
        assert result.metadata["parse_failures"] == 0

    async def test_a_cap_of_zero_tasks_raises(self, corpus: Path) -> None:
        """A run over zero tasks would report a score with no denominator."""

        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        with pytest.raises(arc.ArcAgiUnavailableError, match="selected zero tasks"):
            await arc.run_arc_agi(_genome(), call, max_tasks=0, corpus_dir=corpus)

    async def test_a_capped_run_is_marked_sampled(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        result = await arc.run_arc_agi(_genome(), call, max_tasks=1, corpus_dir=corpus)
        assert result.samples_evaluated == 1
        assert result.metadata["sampled"] is True
        assert result.metadata["total_tasks"] == 2

    async def test_a_whole_corpus_run_is_not_marked_sampled(self, corpus: Path) -> None:
        async def call(*args: Any, **kwargs: Any) -> str:
            return "[[8, 7], [0, 9]]"

        result = await arc.run_arc_agi(_genome(), call, corpus_dir=corpus)
        assert result.metadata["sampled"] is False


class TestAvailability:
    def test_the_adapter_reports_its_absence_loudly(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(arc, "_CORPUS_DIR", tmp_path / "absent")
        ok, reason = arc.available()
        assert ok is False
        assert "not vendored" in reason

    def test_the_adapter_reports_an_empty_corpus_directory(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(arc, "_CORPUS_DIR", empty)
        ok, reason = arc.available()
        assert ok is False
        assert "holds no task files" in reason

    def test_the_adapter_reports_its_presence(self, monkeypatch, corpus: Path) -> None:
        monkeypatch.setattr(arc, "_CORPUS_DIR", corpus)
        ok, reason = arc.available()
        assert ok is True
        assert reason == "corpus present"

    def test_the_adapter_is_registered_as_a_real_benchmark(self) -> None:
        assert REAL_BENCHMARKS["arc_agi"] is arc.run_arc_agi
