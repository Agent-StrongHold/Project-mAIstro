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

    def test_one_failed_run_makes_the_whole_candidate_unsuccessful(self, latency):
        cands = latency.candidates(
            [
                _run(496, "aaa", "15:00:00", "15:14:00"),
                _run(496, "aaa", "15:00:30", "15:05:00", conclusion="cancelled"),
            ],
            "develop",
        )
        assert cands[(496, "aaa")]["success"] is False


class TestBoundaryCohort:
    def _cands(self, latency):
        return latency.candidates(
            [
                _run(496, "aaa", "15:00:00", "15:14:00"),
                _run(628, "bbb", "15:30:00", "15:44:00"),
            ],
            "develop",
        )

    def test_a_truncated_listing_drops_candidates_at_the_old_edge(self, latency):
        """The API pages runs, not candidates: the oldest fetched runs can
        belong to a candidate whose remaining runs fell off the last page.
        Scoring that partial candidate would shorten its wall-clock and could
        hide an earlier attempt, so the boundary cohort goes."""
        kept = latency.drop_boundary_cohort(self._cands(latency), truncated=True)
        assert set(kept) == {(628, "bbb")}

    def test_the_whole_pr_leaves_with_its_boundary_candidate(self, latency):
        """Dropping only the boundary candidate would make its PR look
        *better*: one attempt fewer, and a residency clocked from the requeue
        instead of the real first entry. The PR's history starts before the
        window, so the PR cannot be scored from it."""
        cands = latency.candidates(
            [
                _run(496, "aaa", "15:00:00", "15:14:00", conclusion="failure"),
                _run(496, "bbb", "15:30:00", "15:44:00"),
                _run(628, "ccc", "15:31:00", "15:45:00"),
            ],
            "develop",
        )
        kept = latency.drop_boundary_cohort(cands, truncated=True)
        assert set(kept) == {(628, "ccc")}

    def test_an_untruncated_listing_keeps_every_candidate(self, latency):
        kept = latency.drop_boundary_cohort(self._cands(latency), truncated=False)
        assert set(kept) == {(496, "aaa"), (628, "bbb")}

    def test_an_empty_truncated_listing_stays_empty(self, latency):
        assert latency.drop_boundary_cohort({}, truncated=True) == {}


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

    def test_residency_prefers_the_admission_timestamp(self, latency):
        """`added_to_merge_queue` fires when the PR enters the queue — before
        Actions schedules anything and before a build slot frees up. Clocking
        from the first run start instead drops exactly the wait that grows
        when the queue is busiest."""
        merged = {496: latency._when("2026-08-29T15:50:00Z")}
        admitted = {496: latency._when("2026-08-29T14:50:00Z")}
        (pr496, _pr639) = latency.summarize(self._cands(latency), merged, admitted)
        assert pr496["residency_min"] == pytest.approx(60.0)
        assert pr496["residency_from_admission"] is True

    def test_an_admission_after_the_first_run_is_not_trusted(self, latency):
        """An admission timestamp later than the first observed run start can
        only mean the fetched timeline pages missed the admission that
        actually opened this window — using it would shrink residency below
        even the run-start lower bound. Fall back instead."""
        merged = {496: latency._when("2026-08-29T15:50:00Z")}
        admitted = {496: latency._when("2026-08-29T15:10:00Z")}
        (pr496, _pr639) = latency.summarize(self._cands(latency), merged, admitted)
        assert pr496["residency_min"] == pytest.approx(50.0)
        assert pr496["residency_from_admission"] is False

    def test_an_unmerged_pr_has_attempts_but_no_residency(self, latency):
        """Scoring an ejected-and-abandoned PR as zero residency would pull the
        median down — the queue looking faster the more PRs it fails."""
        (_, pr639) = latency.summarize(self._cands(latency), {})
        assert pr639["merged"] is False
        assert pr639["residency_min"] is None

    def test_only_completed_successful_candidates_contribute_wall_clock(self, latency):
        """An ejected candidate is cancelled mid-run, so its wall-clock is
        short for the wrong reason — including it would pull the 'clean pass'
        figure down exactly when the queue is at its least clean."""
        cands = latency.candidates(
            [
                _run(650, "fff", "19:30:00", "19:44:00"),
                _run(652, "ggg", "20:49:00", "20:55:00", conclusion=None),
                _run(639, "hhh", "16:00:00", "16:05:00", conclusion="cancelled"),
            ],
            "develop",
        )
        rows = {p["pr"]: p for p in latency.summarize(cands, {})}
        assert rows[650]["candidate_wall_min"] == [pytest.approx(14.0)]
        assert rows[652]["candidate_wall_min"] == []
        assert rows[639]["candidate_wall_min"] == []


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

    def test_dequeue_rate_counts_abandoned_prs_too(self, latency):
        """PR 639 here is ejected and never merged. The requeue rate cannot
        see it — it conditions on merging — so the dequeue rate exists: every
        candidate that landed no merge counts, and a queue that fails PRs
        outright gets a worse number, not a better one."""
        figs = latency.figures(self._prs(latency))
        assert figs["dequeued_candidates"] == 2
        assert figs["dequeue_rate"] == pytest.approx(0.5)

    def test_fallback_residencies_are_counted_for_the_report(self, latency):
        cands = latency.candidates([_run(495, "aaa", "19:13:00", "19:26:00")], "develop")
        merged = {495: latency._when("2026-08-29T19:27:00Z")}
        with_admission = latency.figures(
            latency.summarize(cands, merged, {495: latency._when("2026-08-29T19:00:00Z")})
        )
        without = latency.figures(latency.summarize(cands, merged))
        assert with_admission["residency_fallbacks"] == 0
        assert without["residency_fallbacks"] == 1
        assert without["residencies"] == 1

    def test_no_merged_prs_does_not_divide_by_zero(self, latency):
        figs = latency.figures([])
        assert figs["requeue_rate"] == 0.0
        assert figs["dequeue_rate"] == 0.0
        assert figs["median_residency"] == 0.0

    def test_percentiles_interpolate_between_ranks(self, latency):
        """`round(q * (n - 1))` on an even-sized sample is neither nearest-rank
        nor a conventional median, and ties-to-even picks a middle element by
        the parity of the sample size. Interpolation gives the median every
        statistics library would report."""
        assert latency.percentile([], 0.9) == 0.0
        assert latency.percentile([1.0, 2.0, 3.0], 0.5) == 2.0
        assert latency.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
        assert latency.percentile([0.0, 10.0], 0.9) == pytest.approx(9.0)
        assert latency.percentile([10.0], 0.9) == 10.0


class TestRender:
    def test_the_report_names_the_rows_and_all_four_figures(self, latency):
        prs = [
            {
                "pr": 496,
                "attempts": 2,
                "merged": True,
                "residency_min": 58.1,
                "residency_from_admission": True,
                "candidate_wall_min": [13.9, 14.1],
            },
            {
                "pr": 639,
                "attempts": 1,
                "merged": False,
                "residency_min": None,
                "residency_from_admission": False,
                "candidate_wall_min": [12.0],
            },
        ]
        out = latency.render(prs, latency.figures(prs), "develop")
        assert "496" in out and "58.1" in out
        assert "requeue rate" in out
        assert "dequeued candidates" in out
        assert "queue admission -> merged" in out
        assert "0 of 1 from run-start fallback" in out
        assert "clean candidate, med / p90" in out


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
        runs, merged_at, truncated = latency.collect("develop", 3, None)
        assert runs == [{"id": 1}]
        assert list(merged_at) == [496]
        assert truncated is False

    def test_a_full_final_page_reports_the_listing_as_truncated(self, latency, monkeypatch):
        """Older runs may exist beyond a full last page, so the oldest fetched
        candidates may be missing runs — the caller must know to drop them."""

        def fake_get(path, token):
            if "actions/runs" in path:
                return {"workflow_runs": [{"id": i} for i in range(100)]}
            return []

        monkeypatch.setattr(latency, "_get", fake_get)
        _runs, _merged_at, truncated = latency.collect("develop", 1, None)
        assert truncated is True


class TestCollectAdmissions:
    def test_the_earliest_admission_event_wins_and_other_events_are_ignored(
        self, latency, monkeypatch
    ):
        pages = {
            "/issues/496/timeline?per_page=100&page=1": [
                {"event": "labeled", "created_at": "2026-08-29T10:00:00Z"},
                {"event": "added_to_merge_queue", "created_at": "2026-08-29T15:30:00Z"},
                {"event": "added_to_merge_queue", "created_at": "2026-08-29T14:50:00Z"},
            ],
            "/issues/496/timeline?per_page=100&page=2": [],
            "/issues/639/timeline?per_page=100&page=1": [
                {"event": "review_requested", "created_at": "2026-08-29T09:00:00Z"}
            ],
            "/issues/639/timeline?per_page=100&page=2": [],
        }

        def fake_get(path, token):
            for suffix, payload in pages.items():
                if path.endswith(suffix):
                    return payload
            raise AssertionError(path)

        monkeypatch.setattr(latency, "_get", fake_get)
        admitted = latency.collect_admissions([496, 639], 3, None)
        assert admitted == {496: latency._when("2026-08-29T14:50:00Z")}

    def test_one_unreadable_timeline_does_not_fail_the_measurement(self, latency, monkeypatch):
        """A partial upgrade must not fail the whole measurement: the PR with
        the broken timeline falls back to run start, disclosed in the report,
        and every other PR keeps its admission timestamp."""

        def fake_get(path, token):
            if "/issues/496/" in path:
                raise urllib.error.URLError("boom")
            if path.endswith("page=1"):
                return [{"event": "added_to_merge_queue", "created_at": "2026-08-29T14:00:00Z"}]
            return []

        monkeypatch.setattr(latency, "_get", fake_get)
        admitted = latency.collect_admissions([496, 639], 2, None)
        assert admitted == {639: latency._when("2026-08-29T14:00:00Z")}


class TestMain:
    def test_a_measurement_prints_the_window_and_the_report(self, latency, monkeypatch, capsys):
        monkeypatch.setattr(
            latency,
            "collect",
            lambda base, pages, token: (
                [_run(628, "aaa", "15:00:00", "15:14:00")],
                {628: latency._when("2026-08-29T15:20:00Z")},
                False,
            ),
        )
        monkeypatch.setattr(
            latency,
            "collect_admissions",
            lambda prs, pages, token: {628: latency._when("2026-08-29T14:55:00Z")},
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
        monkeypatch.setattr(latency, "collect", lambda base, pages, token: ([], {}, False))
        assert latency.main(["--pages", "1"]) == 1
        assert "nothing to measure" in capsys.readouterr().out
