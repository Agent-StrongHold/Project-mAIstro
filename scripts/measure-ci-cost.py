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
**Job-minutes**, summed over every check on one head. Not billable minutes:
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

Regenerating the record:

    ... python3 scripts/measure-ci-cost.py --pr <n> --update
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


def collect(sha: str, token: str) -> list[dict[str, Any]]:
    """Every job of every workflow run on `sha`, with its workflow file path."""
    runs = _get(f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=100", token)
    jobs: list[dict[str, Any]] = []
    for run in runs.get("workflow_runs", []):
        workflow = Path(run["path"]).name
        listing = _get(f"/repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100", token)
        for job in listing.get("jobs", []):
            jobs.append(
                {
                    "workflow": workflow,
                    "name": job["name"],
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
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
        f"{'TOTAL':<26}{sum(r['jobs'] for r in totals.values()):>6}{figures['after_any']:>14.1f}"
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
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("FAIL: set GITHUB_TOKEN (or GH_TOKEN); the Actions API needs one")
        return 1

    try:
        sha = args.sha or _get(f"/repos/{REPO}/pulls/{args.pr}", token)["head"]["sha"]
        jobs = collect(sha, token)
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        print(f"FAIL: could not read the Actions API: {exc}")
        return 1

    if not jobs:
        print(f"FAIL: no workflow jobs found for {sha}; nothing to measure")
        return 1

    totals = aggregate(jobs)
    print(f"head {sha}\n")
    print(render(totals, split(totals)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
