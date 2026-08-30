#!/usr/bin/env python3
"""Gate: the required checks must have *run* on the head being merged (#262 AC-2).

The gap this closes
-------------------
Every other gate in this repository asks whether the code is good. None asks
whether the gates ran at all on the artefact about to merge. Those are different
questions, and the second has a failure mode the first cannot see: a check that
never reports is not red, it is *absent*, and absence renders as an empty space
where a green tick would go.

That is not hypothetical. A workflow pushing with the default `GITHUB_TOKEN`
produces heads GitHub deliberately will not start workflows for, and on PR #242
every bot-actored run of `ci.yml` and `quality.yml` sat at `action_required`
while the PR displayed its own workflow's green job. 32 runs each, none
executed, newest actually-checked head two commits behind the tip.

This is the same class of gap as `check-ac-state.py`'s `passing` -> `reachable`
rung: a green result that nothing actually reached. There the fix was to ask
whether an entry point can get to the code; here it is to ask whether the gate
got to the commit.

What counts as red or pending
-----------------------------
- **Absent** — a required check with no run on this head at all. This is the
  "gates did not run" state AC-2 names. While sibling workflows may still be
  starting, absence is *pending evidence* rather than a terminal failure: exit
  code 2 keeps a merge-group waiting instead of ejecting it on the first
  producer completion. If the check never appears, the required `gates-ran`
  context remains pending and the merge fails closed at GitHub's queue timeout.
- **Non-executed** — a run record exists but its conclusion is
  `action_required`, `stale`, `skipped`, or `cancelled`. Presence alone is not
  evidence that the required enforcement executed. This is a hard finding and
  exits 1.
- **Unfinished** — present but not `completed`. Under `--require-complete` this
  is pending evidence (exit 2), not red. Without that flag an in-progress check
  is fine: it ran, which is what this gate is about.

Base-coupled checks
-------------------
CodeQL and the container scan are intentionally coupled to `main`. They are not
required execution evidence on a `develop` PR, but they *are* evidence on a
`main` promotion. Pass `--base-branch main` to include them. Any other base
keeps them excluded, matching the generated required-check contract.

A failure it must never produce
-------------------------------
Reporting green because it could not tell. An unreadable payload or a required
set that came back empty are *unmeasured* and exit 1. An empty or incomplete
check-run set is also never green; it exits 2 so a live merge queue waits for
more evidence instead of treating the transient state as a terminal rejection.

Usage
-----
    python3 scripts/check-gates-ran.py --check-runs runs.json
    python3 scripts/check-gates-ran.py --check-runs runs.json --require-complete
    python3 scripts/check-gates-ran.py --check-runs runs.json --require-complete --base-branch main

Exit codes are part of the publisher contract: 0 = complete execution evidence,
1 = hard/unmeasured failure, 2 = evidence is still pending.

`runs.json` is the body of `GET /repos/{owner}/{repo}/commits/{sha}/check-runs`.
The workflow fetches it; this script does no network I/O, so its logic is
testable without a token and it cannot be the reason a fork's build fails.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_CHECKS_SCRIPT = REPO_ROOT / "scripts" / "check-required-checks.py"

#: Conclusions that do not prove the required enforcement executed to a verdict.
NON_EXECUTED = frozenset({"action_required", "stale", "skipped", "cancelled"})
PENDING_EXIT = 2


def required_check_names(*, base_branch: str | None = None) -> list[str]:
    """Return the required execution-evidence set for one PR base.

    The source of truth is `check-required-checks.py`, not a second handwritten
    list. Base-coupled checks are included only for `main`, which is the branch
    whose contract actually requires CodeQL and the container scan.
    """
    spec = importlib.util.spec_from_file_location("check_required_checks", REQUIRED_CHECKS_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REQUIRED_CHECKS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rows = module.collect()

    names = {name for _workflow, name, _scope in rows}
    if base_branch != "main":
        names -= {name for _workflow, name in module.base_coupled(rows)}
    return sorted(names)


@dataclass
class Verdict:
    """What the head's check runs say about whether the gates reached it."""

    absent: list[str] = field(default_factory=list)
    not_executed: list[str] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.absent and not self.not_executed and not self.unfinished

    @property
    def pending(self) -> bool:
        """More executions can still turn this verdict green without a rerun."""
        return not self.not_executed and bool(self.absent or self.unfinished)


def evaluate(
    required: list[str],
    check_runs: list[dict[str, Any]],
    *,
    require_complete: bool,
) -> Verdict:
    """Classify each required check against the runs reported for one head.

    Latest-wins per name: GitHub keeps every attempt, and a re-run leaves the
    earlier one in the list. Taking the last occurrence matches what the UI
    shows and what branch protection evaluates.
    """
    latest: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = run.get("name")
        if isinstance(name, str):
            latest[name] = run

    verdict = Verdict()
    for name in required:
        run = latest.get(name)
        if run is None:
            verdict.absent.append(name)
            continue
        if run.get("conclusion") in NON_EXECUTED:
            verdict.not_executed.append(name)
            continue
        if run.get("status") != "completed":
            (verdict.unfinished if require_complete else verdict.ran).append(name)
            continue
        verdict.ran.append(name)
    return verdict


def _load(path: Path) -> list[dict[str, Any]]:
    """The `check_runs` array, or a loud failure.

    Every malformed shape raises rather than degrading to an empty list: an
    empty list would read as "no checks ran", which is a *finding*, and a
    parse error must not be able to masquerade as one.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        runs = payload
    elif isinstance(payload, dict):
        runs = payload.get("check_runs")
    else:
        raise ValueError(f"{path}: expected an object or a list, got {type(payload).__name__}")
    if not isinstance(runs, list):
        raise ValueError(f"{path}: no `check_runs` array")
    return [run for run in runs if isinstance(run, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-runs", type=Path, required=True)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="also require every present check to have finished",
    )
    parser.add_argument(
        "--base-branch",
        help="PR base branch; `main` includes base-coupled release checks",
    )
    args = parser.parse_args(argv)

    try:
        runs = _load(args.check_runs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"FAIL: the check-run payload is unreadable, so whether the gates ran is unmeasured.\n  {exc}"
        )
        return 1

    required = (
        required_check_names(base_branch=args.base_branch)
        if args.base_branch is not None
        else required_check_names()
    )
    if not required:
        print("FAIL: the required-check contract is empty; nothing to verify ran.")
        return 1

    verdict = evaluate(required, runs, require_complete=args.require_complete)
    if verdict.ok:
        print(f"ok: all {len(required)} required check(s) ran on this head")
        return 0

    heading = (
        "PENDING: execution evidence is still arriving"
        if verdict.pending
        else "FAIL: the gate set did not reach this commit"
    )
    print(f"{heading}\n")
    if verdict.absent:
        print(f"  not present yet ({len(verdict.absent)}):")
        for name in verdict.absent:
            print(f"    {name}")
        print(
            "\n  A required check with no run is not success. While sibling workflows may\n"
            "  still be starting, keep the aggregate pending. If it never appears,\n"
            "  GitHub's required context/queue timeout keeps the candidate blocked."
        )
    if verdict.not_executed:
        print(f"\n  present but did not execute to a verdict ({len(verdict.not_executed)}):")
        for name in verdict.not_executed:
            print(f"    {name}")
        print(
            "\n  A required check that is skipped, cancelled, stale, or awaiting approval\n"
            "  is not evidence that its enforcement ran on this commit."
        )
    if verdict.unfinished:
        print(f"\n  started but not finished ({len(verdict.unfinished)}):")
        for name in verdict.unfinished:
            print(f"    {name}")
    return PENDING_EXIT if verdict.pending else 1


if __name__ == "__main__":
    raise SystemExit(main())
