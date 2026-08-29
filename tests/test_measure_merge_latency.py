"""Tests for the merge-queue latency measurement (#654/#655 baseline).

#655's acceptance names a metric — ready-to-merge -> merge-group completion
time, and the queue's retry/dequeue rate — that must be captured before the
merge-group slice lands, or there is no "before" to compare the slice against.
A measurement tool that is itself unverified would repeat the defect that
reopened #161, so the arithmetic is pinned here: candidate identity (a requeue
is a *new* SHA under the same PR), the refusal to time a candidate that is
still running, and the refusal to flatter the queue by scoring an abandoned
PR's residency as zero.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "measure-merge-latency.py"


@pytest.fixture(scope="module")
def latency():
    spec = importlib.util.spec_from_file_location("measure_merge_latency", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(pr, sha, start, end, conclusion="success", event="merge_group", base="develop"):
    return {
        "event": event,
        "head_branch": f"gh-readonly-queue/{base}/pr-{pr}-{sha}",
        "run_started_at": f"2026-08-29T{start}Z",
        "updated_at": f"2026-08-29T{end}Z",
        "conclusion": conclusion,
    }


class TestQueueBranch:
    def test_a_queue_branch_yields_pr_and_candidate_sha(self, latency):
        assert latency.parse_queue_branch("gh-readonly-queue/develop/pr-628-abc123", "develop") == (
            628,
            "abc123",
        )

    def test_a_queue_for_another_base_is_not_this_measurement(self, latency):
        """A `main` promotion queue run must not leak into a develop baseline —
        the two queues run different required sets and different traffic."""
        assert latency.parse_queue_branch("gh-readonly-queue/main/pr-1-abc", "develop") is None

    def test_an_ordinary_branch_or_absent_branch_is_none(self, latency):
        assert latency.parse_queue_branch("develop", "develop") is None
        assert latency.parse_queue_branch(None, "develop") is None


class TestWhen:
    def test_a_timestamp_parses_and_an_absent_one_stays_absent(self, latency):
        assert latency._when("2026-08-29T15:27:46Z").hour == 15
        assert latency._when(None) is None
        assert latency._when("") is None


class TestCandidates:
    def test_one_candidate_spans_its_earliest_start_to_latest_update(self, latency):
        cands = latency.candidates(
            [
                _run(628, "aaa", "15:00:00", "15:14:00"),
                _run(628, "aaa", "15:01:00", "15:16:00"),
            ],
            "develop",
        )
        row = cands[(628, "aaa")]
        assert row["runs"] == 2
        assert (row["finished"] - row["started"]).total_seconds() == 16 * 60

    def test_a_requeue_is_a_second_candidate_not_a_longer_first_one(self, latency):
        """The queue branch embeds the candidate SHA; an ejected PR comes back
        under the same `pr-N` with a new SHA. Folding both into one candidate
        would hide exactly the re-execution this measurement exists to count."""
        cands = latency.candidates(
            [
                _run(496, "aaa", "15:00:00", "15:14:00", conclusion="failure"),
                _run(496, "bbb", "15:30:00", "15:44:00"),
            ],
            "develop",
        )
        assert set(cands) == {(496, "aaa"), (496, "bbb")}

    def test_non_queue_events_and_foreign_bases_are_ignored(self, latency):
        cands = latency.candidates(
            [
                _run(628, "aaa", "15:00:00", "15:14:00", event="push"),
                _run(1, "ccc", "15:00:00", "15:14:00", base="main"),
            ],
            "develop",
        )
        assert cands == {}

    def test_a_candidate_with_an_unconcluded_run_is_not_done(self, latency):
        cands = latency.candidates(
            [_run(652, "ddd", "20:49:00", "20:55:00", conclusion=None)], "develop"
        )
        assert cands[(652, "ddd")]["done"] is False


class TestSummarize:
    def _cands(self, latency):
        return latency.candidates(
            [
                _run(496, "aaa", "15:00:00", "15:14:00", conclusion="failure"),
                _run(496, "bbb", "15:30:00", "15:44:00"),
                _run(639, "eee", "16:00:00", "16:12:00", conclusion="failure"),
            ],
            "develop",
        )

    def test_residency_runs_from_first_queue_entry_to_merge(self, latency):
        merged = {496: latency._when("2026-08-29T15:50:00Z")}
        (pr496, _pr639) = latency.summarize(self._cands(latency), merged)
        assert pr496["pr"] == 496
        assert pr496["attempts"] == 2
        assert pr496["residency_min"] == pytest.approx(50.0)

    def test_an_unmerged_pr_has_attempts_but_no_residency(self, latency):
        """Scoring an ejected-and-abandoned PR as zero residency would pull the
        median down — the queue looking faster the more PRs it fails."""
        (_, pr639) = latency.summarize(self._cands(latency), {})
        assert pr639["merged"] is False
        assert pr639["residency_min"] is None

    def test_only_completed_candidates_contribute_wall_clock(self, latency):
        cands = latency.candidates(
            [
                _run(650, "fff", "19:30:00", "19:44:00"),
                _run(652, "ggg", "20:49:00", "20:55:00", conclusion=None),
            ],
            "develop",
        )
        rows = {p["pr"]: p for p in latency.summarize(cands, {})}
        assert rows[650]["candidate_wall_min"] == [pytest.approx(14.0)]
        assert rows[652]["candidate_wall_min"] == []


class TestFigures:
    def _prs(self, latency):
        cands = latency.candidates(
            [
                _run(495, "aaa", "19:13:00", "19:26:00"),
                _run(496, "bbb", "15:00:00", "15:14:00", conclusion="failure"),
                _run(496, "ccc", "15:30:00", "15:44:00"),
                _run(639, "ddd", "16:00:00", "16:12:00", conclusion="failure"),
            ],
            "develop",
        )
        merged = {
            495: latency._when("2026-08-29T19:27:00Z"),
            496: latency._when("2026-08-29T15:50:00Z"),
        }
        return latency.summarize(cands, merged)

    def test_requeue_rate_is_over_merged_prs_only(self, latency):
        figs = latency.figures(self._prs(latency))
        assert figs["prs_seen"] == 3
        assert figs["prs_merged"] == 2
        assert figs["candidates"] == 4
        assert figs["requeue_rate"] == pytest.approx(0.5)

    def test_no_merged_prs_does_not_divide_by_zero(self, latency):
        figs = latency.figures([])
        assert figs["requeue_rate"] == 0.0
        assert figs["median_residency"] == 0.0

    def test_percentiles_are_nearest_rank(self, latency):
        assert latency.percentile([], 0.9) == 0.0
        assert latency.percentile([1.0, 2.0, 3.0], 0.5) == 2.0
        assert latency.percentile([10.0], 0.9) == 10.0


class TestRender:
    def test_the_report_names_the_rows_and_all_four_figures(self, latency):
        prs = [
            {
                "pr": 496,
                "attempts": 2,
                "merged": True,
                "residency_min": 58.1,
                "candidate_wall_min": [13.9, 14.1],
            },
            {
                "pr": 639,
                "attempts": 1,
                "merged": False,
                "residency_min": None,
                "candidate_wall_min": [12.0],
            },
        ]
        out = latency.render(prs, latency.figures(prs), "develop")
        assert "496" in out and "58.1" in out
        assert "requeue rate" in out
        assert "residency, median / p90" in out
        assert "candidate wall, med / p90" in out


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestGet:
    def test_the_token_is_sent_when_present_and_not_manufactured_when_absent(
        self, latency, monkeypatch
    ):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["auth"] = request.headers.get("Authorization")
            return _Response(json.dumps({"ok": True}).encode())

        monkeypatch.setattr(latency.urllib.request, "urlopen", fake_urlopen)
        assert latency._get("/x", "tok")["ok"] is True
        assert seen["auth"] == "Bearer tok"
        assert latency._get("/x", None)["ok"] is True
        assert seen["auth"] is None


class TestCollect:
    def test_runs_and_merged_prs_are_paged_until_a_page_is_empty(self, latency, monkeypatch):
        pages = {
            "event=merge_group&per_page=100&page=1": {"workflow_runs": [{"id": 1}]},
            "event=merge_group&per_page=100&page=2": {"workflow_runs": []},
            "state=closed&base=develop&sort=updated&direction=desc&per_page=100&page=1": [
                {"number": 496, "merged_at": "2026-08-29T15:50:00Z"},
                {"number": 639, "merged_at": None},
            ],
            "state=closed&base=develop&sort=updated&direction=desc&per_page=100&page=2": [],
        }

        def fake_get(path, token):
            for suffix, payload in pages.items():
                if path.endswith(suffix):
                    return payload
            raise AssertionError(path)

        monkeypatch.setattr(latency, "_get", fake_get)
        runs, merged_at = latency.collect("develop", 3, None)
        assert runs == [{"id": 1}]
        assert list(merged_at) == [496]


class TestMain:
    def test_a_measurement_prints_the_window_and_the_report(self, latency, monkeypatch, capsys):
        monkeypatch.setattr(
            latency,
            "collect",
            lambda base, pages, token: (
                [_run(628, "aaa", "15:00:00", "15:14:00")],
                {628: latency._when("2026-08-29T15:20:00Z")},
            ),
        )
        assert latency.main([]) == 0
        out = capsys.readouterr().out
        assert "window: 2026-08-29 15:00" in out
        assert "requeue rate" in out

    def test_an_unreachable_api_fails_rather_than_reporting_nothing(
        self, latency, monkeypatch, capsys
    ):
        def boom(base, pages, token):
            raise urllib.error.URLError("down")

        monkeypatch.setattr(latency, "collect", boom)
        assert latency.main(["--base", "develop"]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_an_empty_window_fails_loudly_not_with_empty_statistics(
        self, latency, monkeypatch, capsys
    ):
        """Zero merge-group runs means the queue is off or the base is wrong.
        Empty statistics would read as an implausibly fast queue."""
        monkeypatch.setattr(latency, "collect", lambda base, pages, token: ([], {}))
        assert latency.main(["--pages", "1"]) == 1
        assert "nothing to measure" in capsys.readouterr().out
