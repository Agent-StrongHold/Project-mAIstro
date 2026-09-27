#!/usr/bin/env python3
"""Measure what one PR head costs in CI, split by what #161 changed.

Why this exists
---------------
#161 removed the `branches:` filter from `ci.yml`, `quality.yml`, `security.yml`
and `vulture-ratchet.yml`. Those filters matched on the PR's **base**, so a PR
stacked on a feature branch ran none of them — Registry CI and Formal
Conformance only. Its acceptance asks for one thing the implementing PR did not
supply: *runner cost measured before and after, with the deliberate exclusions
named.*

"Before and after" is measurable exactly, without a noisy time-window
comparison, because the change altered **which PRs trigger a workflow**, not
what any workflow does. The old trigger set is a strict subset of the new one,
so both costs can be read off a single PR head: the "before" cost of a stacked
PR is the subset that was already unfiltered, and the "after" cost is the whole
set. Comparing daily totals across the merge date would instead measure how busy
the repository happened to be that week.

What it measures, and what it does not
--------------------------------------
**Head-attributed job-minutes**, not the full cost caused by a candidate.
Default-branch workflow_run publishers (including Gates Ran) and other work
whose run metadata uses a different head are not included. Their attribution
remains separate work; this subtotal must not be presented as fleet cost.

Not billable minutes:
GitHub reports `total_ms: 0` for this repository, so a cost stated in money
would be zero and would say nothing about the constraint that is real —
contention for concurrent runners, and how long a contributor waits.

Wall-clock is reported separately, because the two answer different questions.
Job-minutes is what the fleet spends; the longest single job is the floor under
how fast a PR can possibly go green, and parallelism means the two are far
apart.

Not measured here: what `concurrency: cancel-in-progress` saves. Every one of
these workflows sets it for pull-request events, so a superseded push stops
paying — but that saving is a function of how often people push, not of one
head, and claiming a number for it from a single run would be exactly the kind
of reasoned-about-not-measured figure that reopened #161.

Usage
-----
    GITHUB_TOKEN=... python3 scripts/measure-ci-cost.py --pr 256
    GITHUB_TOKEN=... python3 scripts/measure-ci-cost.py --sha <head-sha>

Collection includes all pages and retry attempts. It refuses incomplete runs
and jobs instead of reporting their missing duration as zero. The returned run
set is an observation, not a guarantee that no future run will use the head.
The manual workflow explicitly excludes and discloses its own run, avoiding
self-wait when it measures its own head. Other in-flight runs remain incomplete.
The historical #161 comparison is not a before/after estimate for unrelated CI
optimizations; those need comparable candidate/profile measurements.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "docs" / "ci" / "RUNNER-COST.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "Agent-StrongHold/Project-mAIstro")
API = "https://api.github.com"

#: The workflows a stacked PR ran BEFORE #161 removed the base filters.
#:
#: Everything else in the repository was gated on the PR's base, so this pair is
#: the whole "before" cost for a PR not based on main/integration/develop. Named
#: rather than derived: deriving it would mean reading the workflows as they are
#: *now*, which no longer carry the filters, so the set would silently become
#: everything and the comparison would report a delta of zero.
UNFILTERED_BEFORE = frozenset({"registry.yml", "formal-conformance.yml"})

_TS = "%Y-%m-%dT%H:%M:%SZ"


def _seconds(started: str | None, completed: str | None) -> float:
    """Job duration, floored at zero.

    A skipped job can report `completed_at` a second *before* `started_at` —
    `Container scan + SBOM + cosign` does, because it never ran. A negative
    summand would quietly reduce the total, so the floor is not defensive
    padding; it is the difference between a right and a wrong number.
    """
    if not started or not completed:
        return 0.0
    delta = dt.datetime.strptime(completed, _TS) - dt.datetime.strptime(started, _TS)
    return max(0.0, delta.total_seconds())


def aggregate(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-workflow totals: `{workflow: {jobs, seconds, longest}}`.

    Keyed by the workflow's file path rather than its display name, because the
    display name is free text a rename can change while the file — which is what
    `UNFILTERED_BEFORE` names — stays put.
    """
    out: dict[str, dict[str, Any]] = {}
    for job in jobs:
        workflow = job["workflow"]
        seconds = _seconds(job.get("started_at"), job.get("completed_at"))
        row = out.setdefault(workflow, {"jobs": 0, "seconds": 0.0, "longest": ("", 0.0)})
        row["jobs"] += 1
        row["seconds"] += seconds
        if seconds > row["longest"][1]:
            row["longest"] = (job["name"], seconds)
    return out


def split(totals: dict[str, dict[str, Any]]) -> dict[str, float]:
    """The before/after/marginal figures, in job-minutes.

    `before` is what a *stacked* PR cost. A PR based on `develop` already ran
    everything, so its cost is `after` on both sides of the change — which is
    the point: #161 did not make any PR more expensive than a develop-based PR
    already was. It made a class of PRs stop being cheap by being unmeasured.
    """
    after = sum(row["seconds"] for row in totals.values())
    before = sum(row["seconds"] for name, row in totals.items() if name in UNFILTERED_BEFORE)
    return {
        "before_stacked": before / 60,
        "after_any": after / 60,
        "marginal": (after - before) / 60,
        "longest_job": max((row["longest"][1] for row in totals.values()), default=0.0) / 60,
    }


def _get(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _page(data: dict[str, Any], key: str) -> tuple[list[dict[str, Any]], int]:
    """Validate list metadata instead of mistaking a missing page for no work."""
    rows, total = data.get(key), data.get("total_count")
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        raise ValueError(f"invalid {key} listing")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"invalid {key} row")
    return rows, total


def _list_all(path: str, key: str, token: str) -> list[dict[str, Any]]:
    """Read every stable page; refuse capped, moving or incomplete listings."""
    separator = "&" if "?" in path else "?"
    prefix = f"{path}{separator}per_page=100&page="
    rows, total = _page(_get(prefix + "1", token), key)
    # GitHub caps filtered workflow-run searches at 1,000 results. A capped
    # query is incomplete, not evidence that the remaining runs were free.
    if key == "workflow_runs" and total > 1000:
        raise ValueError("workflow-run search exceeds the API's 1,000-result limit")
    for page in range(2, (total + 99) // 100 + 1):
        batch, current_total = _page(_get(prefix + str(page), token), key)
        if current_total != total:
            raise ValueError(f"{key} listing changed during collection; repeat the measurement")
        rows.extend(batch)
    if len(rows) != total:
        raise ValueError(f"incomplete {key} listing: received {len(rows)} of {total}")
    ids = [row["id"] for row in rows]
    if any(type(identity) is not int or identity <= 0 for identity in ids):
        raise ValueError(f"invalid {key} identity")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate {key} identity across pages; repeat the measurement")
    return rows


def _completed_job(job: dict[str, Any]) -> None:
    """A running or unmeasurable job cannot contribute an invented zero cost."""
    if job.get("status") != "completed":
        raise ValueError(f"job {job['id']} is not completed; measurement is incomplete")
    start, end = job.get("started_at"), job.get("completed_at")
    if not start and job.get("conclusion") in ("skipped", "cancelled"):
        return  # No runner was allocated; this is not a running job with no end.
    if not start or not end:
        raise ValueError(f"job {job['id']} has incomplete timing evidence")
    started = dt.datetime.strptime(start, _TS)
    completed = dt.datetime.strptime(end, _TS)
    if completed < started and job.get("conclusion") != "skipped":
        raise ValueError(f"job {job['id']} has backwards timing evidence")


def _validate_measurement_run(run: dict[str, Any], sha: str) -> None:
    """Exclude only the current active manual reporter, never its history."""
    if (
        run.get("path") != ".github/workflows/runner-cost.yml"
        or run.get("head_sha") != sha
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "in_progress"
        or str(run["id"]) != os.environ.get("GITHUB_RUN_ID")
    ):
        raise ValueError("the excluded run is not this active Runner cost execution")


def collect(
    sha: str, token: str, *, exclude_measurement_run: int | None = None
) -> list[dict[str, Any]]:
    """Completed observed runs on `sha`, including every recorded retry attempt.

    This is an observation of the returned run set, not a promise that another
    workflow will never be scheduled on the same head. Missing/in-flight data
    refuses a definitive total rather than silently contributing zero.
    """
    runs = _list_all(f"/repos/{REPO}/actions/runs?head_sha={sha}", "workflow_runs", token)
    jobs: list[dict[str, Any]] = []
    for run in runs:
        if run["id"] == exclude_measurement_run:
            _validate_measurement_run(run, sha)
            continue
        if run.get("status") != "completed" or run.get("head_sha") != sha:
            raise ValueError(f"run {run['id']} is incomplete or belongs to another head")
        workflow = Path(run["path"]).name
        # The jobs endpoint defaults to filter=latest, omitting earlier
        # executions after a rerun. Those executions consumed runner time too.
        listing = _list_all(
            f"/repos/{REPO}/actions/runs/{run['id']}/jobs?filter=all", "jobs", token
        )
        if not listing and run.get("conclusion") not in ("skipped", "cancelled"):
            raise ValueError(f"completed run {run['id']} has no job evidence")
        for job in listing:
            _completed_job(job)
            jobs.append(
                {
                    "workflow": workflow,
                    "name": job["name"],
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "job_id": job["id"],
                    "run_id": run["id"],
                    "run_attempt": job.get("run_attempt"),
                    "event": run.get("event"),
                    "conclusion": job.get("conclusion"),
                }
            )
    return jobs


def render(totals: dict[str, dict[str, Any]], figures: dict[str, float]) -> str:
    lines = [
        f"{'workflow':<26}{'jobs':>6}{'job-minutes':>14}",
        "-" * 46,
    ]
    for workflow, row in sorted(totals.items(), key=lambda kv: -kv[1]["seconds"]):
        lines.append(f"{workflow:<26}{row['jobs']:>6}{row['seconds'] / 60:>14.1f}")
    lines.append("-" * 46)
    lines.append(
        f"{'HEAD-ATTRIBUTED SUBTOTAL':<26}"
        f"{sum(r['jobs'] for r in totals.values()):>6}{figures['after_any']:>14.1f}"
    )
    lines += [
        "",
        f"stacked PR, before #161 : {figures['before_stacked']:>6.1f} job-min",
        f"any PR, after #161      : {figures['after_any']:>6.1f} job-min",
        f"marginal, per PR head   : {figures['marginal']:>6.1f} job-min",
        f"longest single job      : {figures['longest_job']:>6.1f} min (the latency floor)",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=int, help="pull request number; its head is measured")
    group.add_argument("--sha", help="head sha to measure")
    ap.add_argument(
        "--exclude-measurement-run",
        type=int,
        help="exclude and disclose the Runner cost run itself",
    )
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("FAIL: set GITHUB_TOKEN (or GH_TOKEN); the Actions API needs one")
        return 1

    try:
        sha = args.sha or _get(f"/repos/{REPO}/pulls/{args.pr}", token)["head"]["sha"]
        jobs = collect(sha, token, exclude_measurement_run=args.exclude_measurement_run)
    except (urllib.error.URLError, KeyError, TimeoutError, ValueError) as exc:
        print(f"FAIL: could not obtain a complete CI measurement: {exc}")
        return 1

    if not jobs:
        print(f"FAIL: no workflow jobs found for {sha}; nothing to measure")
        return 1

    totals = aggregate(jobs)
    print(f"head {sha}: completed observed jobs, all recorded attempts\n")
    print("Scope: head-attributed workflow runs only; not total candidate or fleet cost.")
    print("Excluded: workflow_run publishers on another head (including Gates Ran).")
    print("Historical #161 figures below have the same limited scope.\n")
    if args.exclude_measurement_run is not None:
        print(f"Runner cost measurement run {args.exclude_measurement_run} excluded if present.")
    print(render(totals, split(totals)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
