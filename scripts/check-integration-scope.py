#!/usr/bin/env python3
"""Verify the specialized CI checks required by one integration candidate.

Pull requests and protected pushes preserve the existing contract: every
specialized check must complete successfully. Merge-group candidates may use
the reviewed path classifier to omit checks that cannot be affected, but
uncertainty never widens the skip set: a missing or malformed scope requires
every check.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from ci_merge_group_scope import LEGS

CHECK_NAMES: dict[str, tuple[str, ...]] = {
    "postgres": ("postgres (pg17)", "postgres (pg18)"),
    "object_storage": ("object storage (MinIO)",),
    "durable_events": ("durable-events",),
    "strike_ladder": ("strike-ladder",),
    "hive_e2e": ("hive-conductor-e2e", "hive-conductor-e2e-ui"),
    "wheel_imports": ("wheel-imports",),
    "docker_build": ("docker-build",),
}
ALL_CHECK_NAMES: set[str] = set()
for _check_names in CHECK_NAMES.values():
    ALL_CHECK_NAMES.update(_check_names)


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


def required_checks(event_name: str, scope_json: str | None) -> set[str]:
    """Return the check names whose success this candidate must prove."""
    if event_name == "merge_group":
        scope = _fail_closed_scope(scope_json)
    else:
        scope = dict.fromkeys(LEGS, True)

    required: set[str] = set()
    for leg, check_names in CHECK_NAMES.items():
        if scope[leg]:
            required.update(check_names)
    return required


def evaluate(
    event_name: str,
    scope_json: str | None,
    results: Mapping[str, str],
) -> list[str]:
    """Return findings for specialized checks whose evidence is unacceptable."""
    required = required_checks(event_name, scope_json)
    findings: list[str] = []
    for check_name in sorted(required):
        result = results.get(check_name)
        if result != "success":
            finding = f"{check_name}: required but result was {result or '<missing>'}"
            findings.append(finding)

    # Out-of-scope jobs are allowed to be absent or explicitly skipped. If one
    # nevertheless executes, its verdict still matters: workflow/classifier
    # drift must not let a real failure disappear behind the scope decision.
    for check_name in sorted(set(results) - required):
        result = results[check_name]
        if result not in {"success", "skipped"}:
            findings.append(f"{check_name}: out of scope but result was {result}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--scope-json")
    parser.add_argument("--required-json", action="store_true")
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="CHECK=RESULT",
        help="GitHub check result, repeated once per specialized check name",
    )
    args = parser.parse_args(argv)

    required = required_checks(args.event_name, args.scope_json)
    if args.required_json:
        print(json.dumps(sorted(required)))
        return 0

    results: dict[str, str] = {}
    for item in args.result:
        if "=" not in item:
            print(f"FAIL: malformed --result {item!r}; expected CHECK=RESULT")
            return 1
        check_name, result = item.split("=", 1)
        if not check_name or check_name not in ALL_CHECK_NAMES:
            print(f"FAIL: unknown specialized check name {check_name!r}")
            return 1
        results[check_name] = result

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
