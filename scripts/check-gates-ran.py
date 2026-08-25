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

What counts as red
------------------
- **Absent** — a required check with no run on this head at all. This is the
  "gates did not run" state AC-2 names, and the one that renders as empty.
- **`action_required`** — a run that exists and will never execute without a
  human pressing a button. It is the exact symptom a `GITHUB_TOKEN` push
  produces, and it is worth naming separately because it looks like a run.
- **Unfinished** — present but not `completed`. Red only under
  `--require-complete`, which is how the `workflow_run`-triggered job asks the
  question once the other workflows have finished. Without that flag an
  in-progress check is fine: it ran, which is what this gate is about.

A failure it must never produce
-------------------------------
Reporting green because it could not tell. An unreadable payload, an empty
check-run list, or a required set that came back empty are all *unmeasured*, and
this script exits non-zero for every one of them rather than passing by default.
The distinction is the same one `passing_ac_ids` draws between `set()` and
`None`: "nothing passed" and "we do not know" are different answers, and only
one of them is safe to treat as success.

Usage
-----
    python3 scripts/check-gates-ran.py --check-runs runs.json
    python3 scripts/check-gates-ran.py --check-runs runs.json --require-complete

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

#: Conclusions that mean the run exists but will not execute on its own.
STALLED = frozenset({"action_required", "stale"})


def required_check_names() -> list[str]:
    """The contract `check-required-checks.py` already keeps honest.

    Read from that script rather than restated here, for the reason its own
    docstring gives: a name that lives in two places drifts in one of them, and
    the drift is invisible because both sides keep reporting.
    """
    spec = importlib.util.spec_from_file_location("check_required_checks", REQUIRED_CHECKS_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REQUIRED_CHECKS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rows = module.collect()
    # Base-coupled checks are excluded, and the exclusion is the difference
    # between a gate people keep and one they switch off. CodeQL runs only on
    # PRs based on `main`, so on a `develop` PR its three checks legitimately
    # produce no run at all -- requiring them would paint every PR in the
    # repository red for a reason that is correct behaviour. #161 named this
    # class of check and `base_coupled` already identifies it, so this reads
    # the same answer rather than inventing a second one.
    #
    # The cost is stated rather than hidden: on a `main`-based PR nothing here
    # verifies CodeQL ran. That needs the base branch, which this script
    # deliberately does not take (see the module docstring on network I/O), and
    # it is the narrower gap.
    excluded = {name for _workflow, name in module.base_coupled(rows)}
    return sorted({name for _workflow, name, _scope in rows} - excluded)


@dataclass
class Verdict:
    """What the head's check runs say about whether the gates reached it."""

    absent: list[str] = field(default_factory=list)
    stalled: list[str] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.absent and not self.stalled and not self.unfinished


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
        if run.get("conclusion") in STALLED:
            verdict.stalled.append(name)
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
        help="also fail when a required check is present but has not finished",
    )
    args = parser.parse_args(argv)

    try:
        runs = _load(args.check_runs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"FAIL: the check-run payload is unreadable, so whether the gates ran is unmeasured.\n  {exc}"
        )
        return 1

    required = required_check_names()
    if not required:
        print("FAIL: the required-check contract is empty; nothing to verify ran.")
        return 1

    verdict = evaluate(required, runs, require_complete=args.require_complete)
    if verdict.ok:
        print(f"ok: all {len(required)} required check(s) ran on this head")
        return 0

    print("FAIL: the gate set did not reach this commit\n")
    if verdict.absent:
        print(f"  never ran ({len(verdict.absent)}):")
        for name in verdict.absent:
            print(f"    {name}")
        print(
            "\n  A required check with no run is absent, not red -- it renders as an\n"
            "  empty space where a tick would go. If a workflow pushed this head with\n"
            "  the default GITHUB_TOKEN, GitHub will not start workflows for it (#262)."
        )
    if verdict.stalled:
        print(f"\n  awaiting approval, will never run on their own ({len(verdict.stalled)}):")
        for name in verdict.stalled:
            print(f"    {name}")
    if verdict.unfinished:
        print(f"\n  started but not finished ({len(verdict.unfinished)}):")
        for name in verdict.unfinished:
            print(f"    {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
