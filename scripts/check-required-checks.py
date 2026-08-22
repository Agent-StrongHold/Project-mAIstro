#!/usr/bin/env python3
"""Gate: ``docs/ci/REQUIRED-CHECKS.md`` must match the workflows it describes.

What it catches
---------------
A renamed or deleted CI job that branch protection still lists as required.

GitHub names required checks as **strings**. Nothing links that string back to
the job producing it, so renaming a job does not update the protection rule and
does not error — the rule simply waits for a check that will never report, or
(worse, under some configurations) stops being enforced while continuing to look
enforced. There is no signal at the moment of breakage. This script is that
signal: the contract lives in a file, and the file is compared to the workflows
on every PR.

It also records **how** each check is triggered, because #161's whole point is
that a check scoped to the PR's *base branch* means different things on
different PRs. A new `branches:` filter under `pull_request:` shows up here as a
changed row rather than as a silent hole in coverage.

What it deliberately does not do
--------------------------------
Read the repository's actual branch-protection settings. That needs an
admin-scoped token this workflow does not have and should not have, and a gate
that requires a privileged credential is one that gets disabled. The file is the
declared contract; #162 is where a human matches the settings to it. Keeping the
two separate means this check works on a fork with no secrets at all.

Usage
-----
    python3 scripts/check-required-checks.py            # check (what CI runs)
    python3 scripts/check-required-checks.py --update   # rewrite the table
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DOC = REPO_ROOT / "docs" / "ci" / "REQUIRED-CHECKS.md"
BEGIN = "<!-- checks:table -->"
END = "<!-- /checks:table -->"


def _pull_request_trigger(doc: dict) -> dict | None:
    """The `pull_request:` block, or None when the workflow has no PR trigger.

    ``on:`` is YAML 1.1's boolean ``True`` after parsing — the classic GitHub
    Actions footgun. Both spellings are read so a `"on"`-quoted workflow is not
    silently treated as having no triggers at all.
    """
    triggers = doc.get(True, doc.get("on"))
    if not isinstance(triggers, dict) or "pull_request" not in triggers:
        return None
    return triggers["pull_request"] or {}


def _scope(pull_request: dict) -> str:
    if not isinstance(pull_request, dict):
        return "every PR"
    if branches := pull_request.get("branches"):
        return "base `" + "`, `".join(branches) + "`"
    if pull_request.get("paths"):
        return "paths"
    return "every PR"


def collect() -> list[tuple[str, str, str]]:
    """(workflow, check name, scope) for every job reachable from a PR."""
    rows: list[tuple[str, str, str]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text()) or {}
        pull_request = _pull_request_trigger(doc)
        if pull_request is None:
            continue
        workflow = doc.get("name", path.name)
        scope = _scope(pull_request)
        for job_id, job in (doc.get("jobs") or {}).items():
            rows.append((workflow, (job or {}).get("name", job_id), scope))
    return sorted(rows)


def render(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Workflow | Check name | Runs on |", "|---|---|---|"]
    lines += [f"| {wf} | `{check}` | {scope} |" for wf, check, scope in rows]
    return "\n".join(lines)


def main() -> int:
    if not DOC.exists():
        print(f"FAIL: {DOC.relative_to(REPO_ROOT)} does not exist", file=sys.stderr)
        return 1

    text = DOC.read_text()
    if BEGIN not in text or END not in text:
        print(f"FAIL: {DOC.relative_to(REPO_ROOT)} has no checks:table markers", file=sys.stderr)
        return 1

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    table = render(collect())
    rebuilt = f"{head}{BEGIN}\n\n{table}\n\n{END}{tail}"

    if "--update" in sys.argv:
        DOC.write_text(rebuilt)
        print(f"updated {DOC.relative_to(REPO_ROOT)} ({len(collect())} checks)")
        return 0

    if rebuilt != text:
        print(
            f"FAIL: {DOC.relative_to(REPO_ROOT)} does not match .github/workflows/\n\n"
            "  A job was added, removed, renamed, or had its PR trigger changed.\n"
            "  Branch protection pins these names as strings, so a rename that is\n"
            "  not reflected here silently detaches a required check from the job\n"
            "  meant to produce it.\n\n"
            "  Refresh with: python3 scripts/check-required-checks.py --update\n"
            "  Then read the diff — a check moving off 'every PR' is a coverage\n"
            "  hole, not a formatting change.",
            file=sys.stderr,
        )
        return 1

    print(f"ok: {len(collect())} PR checks match docs/ci/REQUIRED-CHECKS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
