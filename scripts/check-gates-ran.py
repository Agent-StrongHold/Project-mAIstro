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


def evaluate(
    required: list[str],
    check_runs: list[dict[str, Any]],
    *,
    require_complete: bool,
) -> Verdict:
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
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--base-branch")
    parser.add_argument("--event-name")
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
