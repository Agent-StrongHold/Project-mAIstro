#!/usr/bin/env python3
"""Require complete successful leaf-job evidence for a stable required check."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence


def failures(expected: Sequence[str], raw: str) -> list[str]:
    """Refuse absent, malformed, unexpected, or non-success dependency evidence."""
    if not expected or len(set(expected)) != len(expected):
        return ["expected job IDs must be nonempty and unique"]
    try:
        evidence = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ["CHECK_RESULTS must contain a JSON object from toJSON(needs)"]
    if not isinstance(evidence, dict):
        return ["CHECK_RESULTS must contain a JSON object from toJSON(needs)"]
    if set(evidence) != set(expected):
        return ["dependency job IDs do not match the complete expected set"]
    return [
        f"{job}: dependency did not succeed"
        for job in expected
        if not isinstance(evidence[job], dict) or evidence[job].get("result") != "success"
    ]


def main() -> int:
    """Evaluate the workflow's complete dependency set without accepting skips."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", help="complete, literal dependency job IDs")
    args = parser.parse_args()
    problems = failures(args.jobs, os.environ.get("CHECK_RESULTS", ""))
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    print(f"All {len(args.jobs)} required dependency jobs succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
