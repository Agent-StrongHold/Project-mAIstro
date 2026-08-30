#!/usr/bin/env python3
"""Measure merge-queue latency and retry cost, per merged PR.

Why this exists
---------------
The build-efficiency program (#654) and its merge-group slice (#655) both
promise throughput, and #655's acceptance names the metric explicitly: track
ready-to-merge -> merge-group completion time and the queue's retry/dequeue
rate *before and after* the slice. The "before" side has to be captured while
the queue still runs every leg unconditionally — after the slice lands there is
nothing left to compare against. This script is that measurement, kept as a
sibling of `measure-ci-cost.py`: the same stdlib-only shape, the same rule that
a figure is read off the API rather than reasoned about (#161's lesson).

What it measures, and what it does not
--------------------------------------
Three figures over a window of recent merge-group activity on one base branch:

- **Queue residency** per merged PR: the PR's earliest `added_to_merge_queue`
  timeline event -> its `merged_at`. This is what a contributor whose PR is
  already approved and green actually waits, including every requeue and the
  wait for a queue build slot. Where the timeline is unreadable the figure
  falls back to the first merge-group run start (a lower bound) and the
  report discloses how many rows did.
- **Candidate wall-clock**: first run start -> last run's `updated_at` for one
  synthetic queue candidate whose runs all completed. The floor under residency.
- **Requeue rate**: merged PRs that needed more than one queue candidate. Each
  extra candidate is a full re-run of the gate set — the direct multiplier
  #654 exists to collapse.

Not measured here: job-minutes (that is `measure-ci-cost.py`'s figure, per
head), and *why* a candidate was ejected — the Actions API records the re-run,
not the reason. The requeue rate therefore bounds flake-plus-conflict cost
without attributing it.

The window is "the last N pages of merge-group runs", not a calendar interval:
the API pages newest-first, so the window is exact in runs and approximate in
days, and the report states the actual span it saw.

Usage
-----
    python3 scripts/measure-merge-latency.py                # public repo, no token
    GITHUB_TOKEN=... python3 scripts/measure-merge-latency.py --pages 5

The recorded baseline lives in docs/ci/MERGE-LATENCY.md; regenerate it by
re-running this and updating the table beside the new date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "Agent-StrongHold/Project-mAIstro")
API = "https://api.github.com"

_TS = "%Y-%m-%dT%H:%M:%SZ"

#: The branch GitHub's merge queue synthesizes for one candidate. The trailing
#: SHA is the candidate's identity: a PR that is ejected and requeued comes
#: back under the same `pr-N` with a different SHA, which is exactly the event
#: the requeue rate counts.
_QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/(?P<base>.+)/pr-(?P<pr>\d+)-(?P<sha>\w+)$")


def _when(stamp: str | None) -> dt.datetime | None:
    """Parse an Actions timestamp; absent stays absent rather than becoming now."""
    if not stamp:
        return None
    return dt.datetime.strptime(stamp, _TS)


def parse_queue_branch(branch: str | None, base: str) -> tuple[int, str] | None:
    """`(pr_number, candidate_sha)` for a queue branch on `base`, else None.

    Matching on the branch shape rather than trusting `event == merge_group`
    alone keeps a differently-based queue (main promotions) out of a develop
    measurement.
    """
    if not branch:
        return None
    match = _QUEUE_BRANCH.match(branch)
    if not match or match.group("base") != base:
        return None
    return int(match.group("pr")), match.group("sha")


def candidates(runs: list[dict[str, Any]], base: str) -> dict[tuple[int, str], dict[str, Any]]:
    """Group merge-group runs into queue candidates, keyed by `(pr, sha)`.

    One candidate runs the whole workflow set against one synthetic SHA;
    `started` is the earliest run start, `finished` the latest update among
    completed runs, and `done` only when every observed run has concluded — a
    candidate still executing must not contribute a foreshortened wall-clock.
    """
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for run in runs:
        if run.get("event") != "merge_group":
            continue
        key = parse_queue_branch(run.get("head_branch"), base)
        if key is None:
            continue
        started = _when(run.get("run_started_at"))
        finished = _when(run.get("updated_at"))
        row = out.setdefault(
            key, {"runs": 0, "started": None, "finished": None, "done": True, "success": True}
        )
        row["runs"] += 1
        if started and (row["started"] is None or started < row["started"]):
            row["started"] = started
        if finished and (row["finished"] is None or finished > row["finished"]):
            row["finished"] = finished
        if run.get("conclusion") is None:
            row["done"] = False
        if run.get("conclusion") != "success":
            row["success"] = False
    return out


#: How far a candidate's workflow runs can start apart. All of a candidate's
#: workflows trigger on the same merge_group event, so their run creations sit
#: within a couple of minutes of each other; five is comfortable slack.
_COHORT_MARGIN_S = 300.0


def drop_boundary_cohort(
    cands: dict[tuple[int, str], dict[str, Any]], truncated: bool
) -> dict[tuple[int, str], dict[str, Any]]:
    """Drop candidates the listing's page boundary may have cut through.

    The API pages individual workflow runs, not candidates, so the oldest
    fetched runs can belong to a candidate whose remaining runs fell off the
    last page — which would shorten its wall-clock and could hide an earlier
    attempt. When the listing was truncated, every candidate starting within
    `_COHORT_MARGIN_S` of the oldest fetched start is the boundary cohort and
    is excluded; a candidate starting later than that has all of its runs
    inside the window, because its runs were all created after the cut.

    The exclusion is per-PR, not per-candidate: dropping only the boundary
    candidate would leave its PR looking *better* — fewer attempts, and a
    residency clocked from a later requeue — when the truth is that its
    history starts before the window and cannot be scored from it.
    """
    if not truncated:
        return cands
    starts = [row["started"] for row in cands.values() if row["started"]]
    if not starts:
        return cands
    cutoff = min(starts) + dt.timedelta(seconds=_COHORT_MARGIN_S)
    boundary_prs = {
        pr for (pr, _sha), row in cands.items() if not row["started"] or row["started"] <= cutoff
    }
    return {key: row for key, row in cands.items() if key[0] not in boundary_prs}


def summarize(
    cands: dict[tuple[int, str], dict[str, Any]],
    merged_at: dict[int, dt.datetime],
    admitted_at: dict[int, dt.datetime] | None = None,
) -> list[dict[str, Any]]:
    """Fold candidates into one row per PR the queue worked on.

    `residency_min` exists only for PRs that actually merged; an
    ejected-and-abandoned PR has attempts but no residency, and counting it as
    zero would flatter the queue. It runs from the PR's earliest
    `added_to_merge_queue` timeline event when `admitted_at` carries one —
    true ready-to-merge latency, including the wait for a queue build slot.
    A PR without an admission timestamp (timeline unreadable, or event older
    than the pages fetched) falls back to the first observed workflow start,
    which trails admission and so understates; the row says which was used
    and the report discloses the fallback count.
    """
    admitted_at = admitted_at or {}
    per_pr: dict[int, list[dict[str, Any]]] = {}
    for (pr, _sha), row in cands.items():
        per_pr.setdefault(pr, []).append(row)
    out = []
    for pr, rows in sorted(per_pr.items()):
        starts = [row["started"] for row in rows if row["started"]]
        first = min(starts) if starts else None
        merged = merged_at.get(pr)
        admitted = admitted_at.get(pr)
        from_admission = bool(admitted and (first is None or admitted <= first))
        origin = admitted if from_admission else first
        residency = (merged - origin).total_seconds() / 60 if merged and origin else None
        walls = [
            (row["finished"] - row["started"]).total_seconds() / 60
            for row in rows
            if row["done"] and row["success"] and row["started"] and row["finished"]
        ]
        out.append(
            {
                "pr": pr,
                "attempts": len(rows),
                "merged": merged is not None,
                "residency_min": residency,
                "residency_from_admission": from_admission,
                "candidate_wall_min": walls,
            }
        )
    return out


def percentile(values: list[float], q: float) -> float:
    """Linearly interpolated percentile; empty input is 0 rather than a crash.

    Interpolation, not `round(q * (n - 1))`: for an even-sized sample that
    rounding is neither nearest-rank nor a conventional median, and Python's
    ties-to-even makes which middle element wins depend on the sample size's
    parity — a median that moves when one more PR merges is not a median.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


def figures(prs: list[dict[str, Any]]) -> dict[str, float]:
    """The report's headline numbers, over one observation window.

    Two rates on purpose. The requeue rate conditions on merging — how often a
    PR that *did* land paid for the gate set more than once. The dequeue rate
    does not: every candidate that landed no merge counts, including those of
    PRs ejected and never requeued, so a queue that fails PRs outright gets a
    worse number, not a better one.
    """
    merged = [p for p in prs if p["merged"]]
    residencies = [p["residency_min"] for p in merged if p["residency_min"] is not None]
    walls = [w for p in prs for w in p["candidate_wall_min"]]
    requeued = [p for p in merged if p["attempts"] > 1]
    candidates_run = sum(p["attempts"] for p in prs)
    dequeued = candidates_run - len(merged)
    fallbacks = [
        p for p in merged if p["residency_min"] is not None and not p["residency_from_admission"]
    ]
    return {
        "residency_fallbacks": float(len(fallbacks)),
        "residencies": float(len(residencies)),
        "prs_seen": float(len(prs)),
        "prs_merged": float(len(merged)),
        "candidates": float(candidates_run),
        "requeued_prs": float(len(requeued)),
        "requeue_rate": len(requeued) / len(merged) if merged else 0.0,
        "dequeued_candidates": float(dequeued),
        "dequeue_rate": dequeued / candidates_run if candidates_run else 0.0,
        "median_residency": percentile(residencies, 0.5),
        "p90_residency": percentile(residencies, 0.9),
        "median_candidate_wall": percentile(walls, 0.5),
        "p90_candidate_wall": percentile(walls, 0.9),
    }


def render(prs: list[dict[str, Any]], figs: dict[str, float], base: str) -> str:
    """The report. Per-PR rows first — the aggregate must stay auditable."""
    lines = [
        f"{'PR':>6}{'attempts':>10}{'merged':>8}{'residency-min':>15}",
        "-" * 39,
    ]
    for p in prs:
        residency = f"{p['residency_min']:.1f}" if p["residency_min"] is not None else "-"
        lines.append(
            f"{p['pr']:>6}{p['attempts']:>10}{'yes' if p['merged'] else 'no':>8}{residency:>15}"
        )
    lines += [
        "-" * 39,
        "",
        f"base branch               : {base}",
        f"PRs seen in queue         : {figs['prs_seen']:.0f} ({figs['prs_merged']:.0f} merged)",
        f"queue candidates run      : {figs['candidates']:.0f}",
        f"requeued merged PRs       : {figs['requeued_prs']:.0f} "
        f"({figs['requeue_rate']:.0%} requeue rate)",
        f"dequeued candidates       : {figs['dequeued_candidates']:.0f} of "
        f"{figs['candidates']:.0f} ({figs['dequeue_rate']:.0%} landed no merge)",
        f"residency, median / p90   : {figs['median_residency']:.1f} / "
        f"{figs['p90_residency']:.1f} min (queue admission -> merged; "
        f"{figs['residency_fallbacks']:.0f} of {figs['residencies']:.0f} "
        f"from run-start fallback, a lower bound)",
        f"clean candidate, med / p90: {figs['median_candidate_wall']:.1f} / "
        f"{figs['p90_candidate_wall']:.1f} min (all-success gate-set passes only)",
    ]
    return "\n".join(lines)


def _get(path: str, token: str | None) -> dict[str, Any]:
    """One API read. The repository is public, so the token is optional — but
    used when present, because the unauthenticated rate limit is 60/hour."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def collect(
    base: str, pages: int, token: str | None
) -> tuple[list[dict[str, Any]], dict[int, dt.datetime], bool]:
    """Recent merge-group runs, `merged_at` for recently closed PRs, and
    whether the runs listing was truncated.

    Both listings page newest-first; `pages` bounds the runs window and the
    closed-PR sweep is sized to comfortably cover the PRs those runs name.
    `truncated` is True when the last fetched page was full — older runs may
    exist, so the oldest candidates may be missing runs and the caller must
    drop the boundary cohort rather than score partial candidates.
    """
    runs: list[dict[str, Any]] = []
    truncated = False
    for page in range(1, pages + 1):
        listing = _get(
            f"/repos/{REPO}/actions/runs?event=merge_group&per_page=100&page={page}", token
        )
        batch = listing.get("workflow_runs", [])
        runs.extend(batch)
        truncated = len(batch) == 100
        if not batch:
            break
    merged_at: dict[int, dt.datetime] = {}
    for page in range(1, pages + 1):
        pulls = _get(
            f"/repos/{REPO}/pulls?state=closed&base={base}"
            f"&sort=updated&direction=desc&per_page=100&page={page}",
            token,
        )
        if not pulls:
            break
        for pull in pulls:
            merged = _when(pull.get("merged_at"))
            if merged:
                merged_at[pull["number"]] = merged
    return runs, merged_at, truncated


def collect_admissions(prs: list[int], pages: int, token: str | None) -> dict[int, dt.datetime]:
    """Earliest `added_to_merge_queue` timeline event per PR, where readable.

    This is what upgrades residency from a run-start lower bound to real
    ready-to-merge latency: admission happens when the PR enters the queue,
    before Actions schedules anything and before a build slot frees up. A PR
    whose timeline cannot be read, or whose admission event sits beyond the
    fetched pages, is simply absent — `summarize` falls back to run start for
    it and the report discloses the count, because a partial upgrade must not
    fail the whole measurement.
    """
    out: dict[int, dt.datetime] = {}
    for pr in prs:
        admissions: list[dt.datetime] = []
        try:
            for page in range(1, pages + 1):
                events = _get(f"/repos/{REPO}/issues/{pr}/timeline?per_page=100&page={page}", token)
                if not events:
                    break
                for event in events:
                    if event.get("event") != "added_to_merge_queue":
                        continue
                    when = _when(event.get("created_at"))
                    if when:
                        admissions.append(when)
        except (urllib.error.URLError, TimeoutError):
            continue
        if admissions:
            out[pr] = min(admissions)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="develop", help="queue base branch (default: develop)")
    ap.add_argument("--pages", type=int, default=3, help="API pages of runs to read (100/page)")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        runs, merged_at, truncated = collect(args.base, args.pages, token)
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        print(f"FAIL: could not read the GitHub API: {exc}")
        return 1

    cands = drop_boundary_cohort(candidates(runs, args.base), truncated)
    if not cands:
        print(f"FAIL: no merge-group runs found for base {args.base}; nothing to measure")
        return 1

    admitted_at = collect_admissions(sorted({pr for pr, _sha in cands}), args.pages, token)
    prs = summarize(cands, merged_at, admitted_at)

    spans = [_when(r.get("run_started_at")) for r in runs if r.get("run_started_at")]
    if spans:
        print(f"window: {min(spans):%Y-%m-%d %H:%M} -> {max(spans):%Y-%m-%d %H:%M} UTC\n")
    print(render(prs, figures(prs), args.base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
