#!/usr/bin/env python3
"""Gate: the required checks must have *run* on the head being merged (#262 AC-2).

The gap this closes
-------------------
Every other gate in this repository asks whether the code is good. None asks
whether the gates ran at all on the artefact about to merge. Those are different
questions, and the second has a failure mode the first cannot see: a check that
never reports is not red, it is *absent*, and absence renders as an empty space
where a green tick would go.

For merge-group candidates, specialized service checks may now be legitimately
out of scope. Their execution evidence is represented by one unconditional
``integration-scope`` aggregate, which itself verifies that every classifier-
selected specialized job completed successfully. Pull requests and protected
pushes retain the existing per-check execution-evidence contract.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_CHECKS_SCRIPT = REPO_ROOT / "scripts" / "check-required-checks.py"

NON_EXECUTED = frozenset({"action_required", "stale", "skipped", "cancelled"})
PENDING_EXIT = 2
INTEGRATION_SCOPE_CHECK = "integration-scope"
MERGE_GROUP_SPECIALIZED_CHECKS = frozenset(
    {
        "docker-build",
        "hive-conductor-e2e",
        "hive-conductor-e2e-ui",
        "wheel-imports",
        "strike-ladder",
        "durable-events",
        "object storage (MinIO)",
        "postgres (pg17)",
        "postgres (pg18)",
    }
)

# Every required check whose job may be path-scoped belongs here.  The values
# are the reviewed leg names from ci_merge_group_scope.py, rather than a
# second set of path globs.  Keeping the filtering generic means a future
# non-specialized required check gets the same skip handling without changing
# the evaluator's verdict rules.
PATH_SCOPED_CHECKS = {
    "postgres (pg17)": "postgres",
    "postgres (pg18)": "postgres",
    "object storage (MinIO)": "object_storage",
    "durable-events": "durable_events",
    "strike-ladder": "strike_ladder",
    "hive-conductor-e2e": "hive_e2e",
    "hive-conductor-e2e-ui": "hive_e2e",
    "wheel-imports": "wheel_imports",
    "docker-build": "docker_build",
}


def required_check_names(
    *,
    base_branch: str | None = None,
    event_name: str | None = None,
) -> list[str]:
    """Return the required execution-evidence set for one candidate."""
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
    if event_name == "merge_group":
        names -= MERGE_GROUP_SPECIALIZED_CHECKS
        names.add(INTEGRATION_SCOPE_CHECK)
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
        return not self.not_executed and bool(self.absent or self.unfinished)


def _supersedes(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    """Whether `candidate` should replace `incumbent` as a name's judged attempt.

    Multiple check runs can share one name for one commit: GitHub's own reruns,
    and -- since the quality.yml/security.yml concurrency fix (#1229) -- two
    independently triggered workflow runs (`push` and `pull_request`) landing
    in one concurrency group, where the loser is `cancelled` rather than
    simply absent. A `cancelled`/`skipped`/`stale`/`action_required` run never
    certifies that the enforcement it names ran to a verdict, so it must never
    shadow a sibling run for the same name that did -- regardless of which one
    the API happens to return later. Only when both runs agree on having
    executed (or both failed to) does list order -- the later entry being the
    newer attempt -- decide, preserving judging-by-latest-attempt for an
    ordinary rerun sequence.
    """
    candidate_executed = candidate.get("conclusion") not in NON_EXECUTED
    incumbent_executed = incumbent.get("conclusion") not in NON_EXECUTED
    if candidate_executed != incumbent_executed:
        return candidate_executed
    return True


def evaluate(
    required: list[str],
    check_runs: list[dict[str, Any]],
    *,
    require_complete: bool,
    scope: Mapping[str, bool] | None = None,
    scope_measured: bool = True,
) -> Verdict:
    latest: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = run.get("name")
        if not isinstance(name, str):
            continue
        incumbent = latest.get(name)
        if incumbent is None or _supersedes(run, incumbent):
            latest[name] = run

    # A measured out-of-scope check may be explicitly skipped.  Absence is
    # still pending (we cannot prove why it is absent), and any conclusion
    # other than skipped remains evidence that must be judged normally.
    if scope is not None:
        required = [
            name
            for name in required
            if not (
                name in PATH_SCOPED_CHECKS
                and not scope.get(PATH_SCOPED_CHECKS[name], True)
                and latest.get(name, {}).get("conclusion") == "skipped"
            )
        ]

    verdict = Verdict()
    for name in required:
        candidate = latest.get(name)
        if candidate is None:
            verdict.absent.append(name)
            continue
        if candidate.get("conclusion") in NON_EXECUTED:
            if (
                not scope_measured
                and name in PATH_SCOPED_CHECKS
                and candidate.get("conclusion") == "skipped"
            ):
                verdict.unfinished.append(name)
            else:
                verdict.not_executed.append(name)
            continue
        if candidate.get("status") != "completed":
            (verdict.unfinished if require_complete else verdict.ran).append(name)
            continue
        verdict.ran.append(name)
    return verdict


def _load(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs: Any
    if isinstance(payload, list):
        runs = payload
    elif isinstance(payload, dict):
        runs = payload.get("check_runs")
    else:
        raise ValueError(f"{path}: expected an object or a list, got {type(payload).__name__}")
    if not isinstance(runs, list):
        raise ValueError(f"{path}: no `check_runs` array")
    return [run for run in runs if isinstance(run, dict)]


def _load_scope_classifier() -> Any:
    path = REPO_ROOT / "scripts" / "ci_merge_group_scope.py"
    spec = importlib.util.spec_from_file_location("ci_merge_group_scope_for_gates_ran", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pull_request_scope(path: Path) -> tuple[dict[str, bool] | None, bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("measured") is not True:
        return None, False
    changed_files = payload.get("files")
    if not isinstance(changed_files, list) or not all(
        isinstance(item, str) for item in changed_files
    ):
        return None, False
    return _load_scope_classifier().classify(changed_files), True


def _scope_for_args(
    event_name: str | None, changed_files_path: Path | None
) -> tuple[dict[str, bool] | None, bool]:
    if event_name != "pull_request":
        return None, True
    if changed_files_path is None:
        print("PENDING: path-scoped execution scope is ambiguous (changed files were not measured)")
        return None, False
    try:
        scope, measured = _pull_request_scope(changed_files_path)
        if not measured:
            print(
                "PENDING: path-scoped execution scope is ambiguous (changed-file payload is invalid)"
            )
        return scope, measured
    except (OSError, TypeError, ValueError, json.JSONDecodeError, ImportError, RuntimeError) as exc:
        print(f"PENDING: path-scoped execution scope is ambiguous ({exc})")
        return None, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-runs", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--base-branch")
    parser.add_argument("--event-name")
    parser.add_argument(
        "--changed-files",
        type=Path,
        help="measured PR changed-file envelope used for path-scoped skip handling",
    )
    args = parser.parse_args(argv)

    try:
        runs = _load(args.check_runs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"FAIL: the check-run payload is unreadable, so whether the gates ran is unmeasured.\n  {exc}"
        )
        return 1

    required = required_check_names(
        base_branch=args.base_branch,
        event_name=args.event_name,
    )
    if not required:
        print("FAIL: the required-check contract is empty; nothing to verify ran.")
        return 1

    scope, scope_measured = _scope_for_args(args.event_name, args.changed_files)

    verdict = evaluate(
        required,
        runs,
        require_complete=args.require_complete,
        scope=scope,
        scope_measured=scope_measured,
    )
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
    if verdict.not_executed:
        print(f"\n  present but did not execute to a verdict ({len(verdict.not_executed)}):")
        for name in verdict.not_executed:
            print(f"    {name}")
    if verdict.unfinished:
        print(f"\n  started but not finished ({len(verdict.unfinished)}):")
        for name in verdict.unfinished:
            print(f"    {name}")
    return PENDING_EXIT if verdict.pending else 1


if __name__ == "__main__":
    raise SystemExit(main())
