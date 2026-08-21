"""Repo-history corpus: contamination discipline and corpus integrity.

The tests that matter here are the *refusals*. This corpus's only value over
IFEval/BFCL is the chronological contamination defence, and that defence is
worth exactly nothing if the loader will guess a cutoff, accept a tampered
corpus, or return an empty list that scores 0.0 and looks like a bad genome.

Corpus-dependent tests skip when the corpus has not been generated; the
refusal-behaviour tests never skip, because they are the guarantee.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from maistro_evolve.benchmarks import repo_history
from maistro_evolve.benchmarks.repo_history import (
    ContaminationError,
    RepoHistoryUnavailableError,
    RepoTask,
    corpus_metadata,
    load_repo_tasks,
    resolve_cutoff,
)


def _task(task_id: str = "abc123", commit_date: str = "2026-07-15T12:00:00+00:00") -> RepoTask:
    return RepoTask(
        task_id=task_id,
        repo_state="parent0",
        commit_date=commit_date,
        issue_text="fix(core): something was broken",
        failing_tests=("packages/x/tests/test_y.py",),
        test_patch="--- a\n+++ b\n",
        gold_patch="--- a\n+++ b\n",
    )


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Write a corpus and pin its digest, so the loader sees a valid tree."""

    def build(tasks: list[RepoTask]) -> None:
        body = {
            "schema": "maistro.repo_history_tasks/1",
            "generated_from": "deadbeef",
            "benchmark": "repo_history",
            "filters": {"max_patch_lines": 300, "max_src_files": 5},
            "tasks": [
                {
                    "task_id": t.task_id,
                    "repo_state": t.repo_state,
                    "commit_date": t.commit_date,
                    "issue_text": t.issue_text,
                    "failing_tests": list(t.failing_tests),
                    "test_patch": t.test_patch,
                    "gold_patch": t.gold_patch,
                }
                for t in tasks
            ],
            "counts": {"admitted": len(tasks), "rejected": 0, "candidates": len(tasks)},
        }
        serialized = json.dumps(body, indent=2, sort_keys=True) + "\n"
        path = tmp_path / "repo_history_tasks.json"
        path.write_text(serialized, encoding="utf-8")
        monkeypatch.setattr(repo_history, "_CORPUS", path)
        monkeypatch.setattr(
            repo_history,
            "_CORPUS_SHA256",
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        )

    return build


class TestContaminationDiscipline:
    """The refusals. These are the whole point of the module."""

    def test_no_model_and_no_cutoff_raises(self) -> None:
        with pytest.raises(ContaminationError, match="requires a model or an explicit cutoff"):
            resolve_cutoff()

    def test_unknown_model_raises_rather_than_guessing(self) -> None:
        """Guessing fails silently: you would score against tasks the model may
        have trained on and read the result as contamination-free evidence."""
        with pytest.raises(ContaminationError, match="no training cutoff recorded"):
            resolve_cutoff("some-model-nobody-registered")

    def test_explicit_cutoff_overrides_the_table(self) -> None:
        assert resolve_cutoff(cutoff=date(2026, 1, 1)) == date(2026, 1, 1)

    def test_known_model_resolves_from_the_table(self, monkeypatch) -> None:
        monkeypatch.setitem(repo_history.MODEL_CUTOFFS, "test-model", date(2026, 3, 1))
        assert resolve_cutoff("test-model") == date(2026, 3, 1)

    def test_cutoff_comparison_is_strict(self) -> None:
        """A task committed ON the cutoff is not provably after it. Ties go to
        caution, because the corpus's only claim is that its tasks are unseen."""
        task = _task(commit_date="2026-07-15T12:00:00+00:00")
        assert task.is_post_cutoff(date(2026, 7, 14)) is True
        assert task.is_post_cutoff(date(2026, 7, 15)) is False
        assert task.is_post_cutoff(date(2026, 7, 16)) is False

    def test_tasks_at_or_before_cutoff_are_filtered_out(self, corpus) -> None:
        corpus(
            [_task("old", "2026-01-01T00:00:00+00:00"), _task("new", "2026-07-20T00:00:00+00:00")]
        )
        kept = load_repo_tasks(cutoff=date(2026, 6, 1))
        assert [t.task_id for t in kept] == ["new"]

    def test_everything_filtered_raises_instead_of_returning_empty(self, corpus) -> None:
        """An empty corpus scoring 0.0 is indistinguishable from a genome that
        failed every task. That ambiguity has to be an error, not a result."""
        corpus([_task("old", "2026-01-01T00:00:00+00:00")])
        with pytest.raises(ContaminationError, match="none is provably unseen"):
            load_repo_tasks(cutoff=date(2026, 6, 1))

    def test_caller_may_opt_out_of_the_nonempty_guard(self, corpus) -> None:
        corpus([_task("old", "2026-01-01T00:00:00+00:00")])
        assert load_repo_tasks(cutoff=date(2026, 6, 1), require_nonempty=False) == []


class TestCorpusIntegrity:
    def test_tampered_corpus_is_refused(self, corpus, tmp_path) -> None:
        corpus([_task("a", "2026-07-20T00:00:00+00:00")])
        path = tmp_path / "repo_history_tasks.json"
        body = json.loads(path.read_text())
        # Add a free task the pin never saw.
        body["tasks"].append(
            {
                "task_id": "injected",
                "repo_state": "x",
                "commit_date": "2026-07-25T00:00:00+00:00",
                "issue_text": "free point",
                "failing_tests": [],
                "test_patch": "",
                "gold_patch": "",
            }
        )
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(RepoHistoryUnavailableError, match="does not match its pinned checksum"):
            load_repo_tasks(cutoff=date(2026, 6, 1))

    def test_missing_corpus_probes_unavailable_with_a_hint(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(repo_history, "_CORPUS", tmp_path / "absent.json")
        ok, reason = repo_history.available()
        assert ok is False
        assert "generate_repo_tasks.py" in reason

    def test_unpinned_digest_probes_unavailable(self, tmp_path, monkeypatch) -> None:
        """A generated-but-unpinned corpus must not be loadable. Otherwise the
        first run after generation silently scores against an unverified exam."""
        path = tmp_path / "repo_history_tasks.json"
        path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(repo_history, "_CORPUS", path)
        monkeypatch.setattr(repo_history, "_CORPUS_SHA256", "PENDING_FIRST_GENERATION")
        ok, reason = repo_history.available()
        assert ok is False
        assert "not yet pinned" in reason


class TestMetadata:
    def test_official_comparable_is_always_false(self, corpus) -> None:
        """There is no published number to compare against, under any
        configuration. Asserted because every other adapter can set it True."""
        corpus([_task("a", "2026-07-20T00:00:00+00:00")])
        meta = corpus_metadata()
        assert meta["official_comparable"] is False
        assert meta["contamination_defence"] == "chronological (post-cutoff commits)"

    def test_metadata_carries_generation_provenance(self, corpus) -> None:
        corpus([_task("a", "2026-07-20T00:00:00+00:00")])
        meta = corpus_metadata()
        assert meta["generated_from"] == "deadbeef"
        assert meta["filters"]["max_src_files"] == 5
        assert meta["counts"]["admitted"] == 1
