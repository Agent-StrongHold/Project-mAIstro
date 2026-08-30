#!/usr/bin/env python3
"""Verify the specialized CI legs required by one integration candidate.

Pull requests and protected pushes preserve the existing contract: every
specialized leg must complete successfully. Merge-group candidates may use the
reviewed path classifier to omit legs that cannot be affected, but uncertainty
never widens the skip set: a missing or malformed scope requires every leg.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from ci_merge_group_scope import LEGS

JOB_IDS: dict[str, tuple[str, ...]] = {
    "postgres": ("postgres",),
    "object_storage": ("object-storage",),
    "durable_events": ("durable-events",),
    "strike_ladder": ("strike-ladder",),
    "hive_e2e": ("hive-conductor-e2e", "hive-conductor-e2e-ui"),
    "wheel_imports": ("wheel-imports",),
    "docker_build": ("docker-build",),
}


def _fail_closed_scope(raw: str | None) -> dict[str, bool]:
    if not raw:
        return dict.fromkeys(LEGS, True)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return dict.fromkeys(LEGS, True)
    if not isinstance(value, Mapping) or set(value) != set(LEGS):
        return dict.fromkeys(LEGS, True)
    if any(not isinstance(value[leg], bool) for leg in LEGS):
        return dict.fromkeys(LEGS, True)
    return {leg: value[leg] for leg in LEGS}


def required_jobs(event_name: str, scope_json: str | None) -> set[str]:
    """Return the job ids whose success this candidate must prove."""
    scope = (
        _fail_closed_scope(scope_json)
        if event_name == "merge_group"
        else dict.fromkeys(LEGS, True)
    )
    return {
        job_id
        for leg, job_ids in JOB_IDS.items()
        if scope[leg]
        for job_id in job_ids
    }


def evaluate(event_name: str, scope_json: str | None, results: Mapping[str, str]) -> list[str]:
    """Return findings for required jobs that did not complete successfully."""
    findings: list[str] = []
    for job_id in sorted(required_jobs(event_name, scope_json)):
        result = results.get(job_id)
        if result != "success":
            findings.append(f"{job_id}: required but result was {result or '<missing>'}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--scope-json")
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="JOB=RESULT",
        help="GitHub Actions job result, repeated once per specialized job id",
    )
    args = parser.parse_args(argv)

    results: dict[str, str] = {}
    for item in args.result:
        if "=" not in item:
            print(f"FAIL: malformed --result {item!r}; expected JOB=RESULT")
            return 1
        job_id, result = item.split("=", 1)
        if not job_id or job_id not in {job for jobs in JOB_IDS.values() for job in jobs}:
            print(f"FAIL: unknown specialized job id {job_id!r}")
            return 1
        results[job_id] = result

    findings = evaluate(args.event_name, args.scope_json, results)
    if findings:
        print("FAIL: integration-scope evidence is incomplete or unsuccessful:")
        for finding in findings:
            print(f"  {finding}")
        return 1

    print(f"ok: integration scope satisfied for {args.event_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
