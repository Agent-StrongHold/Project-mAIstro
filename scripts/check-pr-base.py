#!/usr/bin/env python3
"""The PR base must follow branch policy (#383).

The PR template told every author to target `main`, contradicting
CONTRIBUTING, ADR-095 and the actual branch flow — and it is the checklist
every authoring agent sees. A `main`-based PR is not a style problem: checks
that only report on main-based PRs (container scan, base-coupled gates) would
run, while the develop-merge contract would not, and branch protection then
waits on a different check set than the PR produces.

Policy (ADR-095, single-sourced with the topic prefixes in
`.github/branch-protection.json`):

* `develop` is the normal base.
* `main` is authorized only for a release/promotion PR, which carries the
  `release` label. Ordinary releases are a single `develop -> main` PR.
* A topic-branch base (`feat/*`, ... per the policy file) is a stacked PR:
  allowed, and it must be retargeted to `develop` before merge.
* Anything else — `integration` (retired), `feature/*` (not a documented
  prefix), bare names — is a policy violation and fails with the correction.

Usage (from the PR-triggered job):

    python scripts/check-pr-base.py \
        --base "$PR_BASE" --labels "$PR_LABELS"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_FILE = ROOT / ".github" / "branch-protection.json"

#: The label that authorizes a `develop -> main` promotion PR (ADR-095).
RELEASE_LABEL = "release"

#: The canonical integration base (ADR-095: `develop` is where work lands).
CANONICAL_BASE = "develop"

#: The promotion ledger (ADR-095: `main` receives `develop -> main` PRs).
PROMOTION_BASE = "main"

_GUIDE = (
    "Base the PR on 'develop' (ADR-095). A release/promotion PR may base on "
    f"'main' with the '{RELEASE_LABEL}' label; a stacked PR may base on a "
    "topic branch and must be retargeted to 'develop' before merge."
)


def topic_prefixes() -> set[str]:
    policy = json.loads(POLICY_FILE.read_text())
    return set(policy["topic_branch_policy"]["prefixes"])


def is_topic_branch(ref: str) -> bool:
    return any(ref.startswith(f"{prefix}/") for prefix in topic_prefixes())


def check(base: str, labels: list[str] | None = None) -> list[str]:
    """Problems with this PR base; empty means policy-compliant."""
    labels = labels or []
    if base == CANONICAL_BASE:
        return []
    if base == PROMOTION_BASE:
        if RELEASE_LABEL in labels:
            return []
        return [f"PR base is '{base}' without the '{RELEASE_LABEL}' label. {_GUIDE}"]
    if is_topic_branch(base):
        return []  # stacked; retargeting is review guidance, not a gate
    return [f"PR base '{base}' violates branch policy. {_GUIDE}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="github.event.pull_request.base.ref")
    parser.add_argument(
        "--labels",
        default="",
        help="comma-separated PR label names (may be empty)",
    )
    args = parser.parse_args(argv)
    labels = [label for label in args.labels.split(",") if label]
    problems = check(args.base, labels)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(f"\nFAIL: {len(problems)} branch-policy problem(s).")
        return 1
    print(f"ok: PR base '{args.base}' follows branch policy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
