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
different PRs. A new `branches:` filter under `pull_request:` or
`pull_request_target:` shows up here as a changed row rather than as a silent
hole in coverage.

For the active `develop` merge queue, it additionally requires every ordinary
required check producer to handle `merge_group: checks_requested`. A queue tests
a synthetic candidate SHA. A required check that only handles `pull_request`
can be green on the feature head and then remain `Expected` forever on the SHA
the queue is actually trying to land.

What it deliberately does not do
--------------------------------
Read the repository's actual live branch-protection settings. That needs an
admin-scoped token this workflow does not have and should not have, and a gate
that requires a privileged credential is one that gets disabled. It reads only
the checked-in `.github/branch-protection.json` declaration when deciding which
`develop` checks must also report on merge groups. #162 is where a human matches
the live settings to that reviewed declaration.

Usage
-----
    python3 scripts/check-required-checks.py            # check (what CI runs)
    python3 scripts/check-required-checks.py --update   # rewrite the table
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DOC = REPO_ROOT / "docs" / "ci" / "REQUIRED-CHECKS.md"
PROTECTION = REPO_ROOT / ".github" / "branch-protection.json"
BEGIN = "<!-- checks:table -->"
END = "<!-- /checks:table -->"


class ContractError(RuntimeError):
    """A workflow the contract cannot express, rather than one it misreads.

    Raised instead of recording a best guess. A gate whose failure mode is a
    plausible-looking wrong answer is worse than one that stops: the wrong
    answer gets banked into the table and read as the truth afterwards.
    """


def _trigger_block(doc: dict, events: tuple[str, ...]) -> dict | None:
    """The first requested Actions event block, normalized across YAML forms."""
    triggers = doc.get(True, doc.get("on"))
    if isinstance(triggers, list):
        return {} if any(event in triggers for event in events) else None
    if isinstance(triggers, str):
        return {} if triggers in events else None
    if not isinstance(triggers, dict):
        return None
    for event in events:
        if event in triggers:
            return triggers[event] or {}
    return None


def _pull_request_trigger(doc: dict) -> dict | None:
    """The PR trigger block, or None when the workflow has no PR trigger.

    Both `pull_request` and `pull_request_target` are merge-boundary checks.
    The latter matters for base-trusted judges such as autonomous-merge safety:
    excluding it from this contract would make a required check invisible to
    the branch-protection audit precisely because it is loaded from the base.

    Three spellings are valid for either trigger family:

        on: {pull_request: {branches: [main]}}   -> the filter dict
        on: {pull_request_target: null}          -> {} (unfiltered)
        on: [push, pull_request]                 -> {} (unfiltered)

    ``on:`` is YAML 1.1's boolean ``True`` after parsing — the classic GitHub
    Actions footgun. Both spellings are read so a `"on"`-quoted workflow is not
    silently treated as having no triggers at all.
    """
    return _trigger_block(doc, ("pull_request", "pull_request_target"))


def _merge_group_trigger(doc: dict) -> dict | None:
    """A usable merge-group trigger, or None when this workflow cannot queue-gate.

    `merge_group` currently emits `checks_requested`; accepting a trigger that
    explicitly omits that type would be the same as accepting no trigger at all.
    """
    block = _trigger_block(doc, ("merge_group",))
    if block is None:
        return None
    if not isinstance(block, dict):
        return None
    types = block.get("types")
    if types and "checks_requested" not in types:
        return None
    return block


#: Trigger filters that make a check's presence conditional, and how to say so.
_FILTER_LABELS = (
    ("branches", "base"),
    ("branches-ignore", "base-ignore"),
    ("paths", "paths"),
    ("paths-ignore", "paths"),
)


def _scope(pull_request: dict) -> str:
    if not isinstance(pull_request, dict):
        return "every PR"
    for key, label in _FILTER_LABELS:
        values = pull_request.get(key)
        if not values:
            continue
        if label.startswith("base"):
            return f"{label} `" + "`, `".join(values) + "`"
        return label
    return "every PR"


def _job_scope(job: dict, trigger_scope: str) -> str:
    """Narrow a trigger scope by the job's own `if:`.

    Only `base_ref` is looked for. A job condition can narrow on anything, and
    chasing the general case means evaluating GitHub's expression language;
    `base_ref` is the one that makes a check mean different things on different
    PRs, which is the property under contract here.
    """
    condition = str((job or {}).get("if", ""))
    if "base_ref" not in condition:
        return trigger_scope
    return f"{trigger_scope}, job `if:` on base_ref"


def _matrix_rows(job: dict) -> list[dict]:
    """Every matrix combination a job expands to, as name->value maps."""
    matrix = ((job.get("strategy") or {}).get("matrix")) or {}
    if not isinstance(matrix, dict):
        raise ContractError(f"matrix is not a mapping: {matrix!r}")
    if "exclude" in matrix:
        raise ContractError("matrix `exclude:` is not supported by the contract generator")
    include = matrix.get("include") or []
    axes = {k: v for k, v in matrix.items() if k != "include"}

    combos: list[dict] = [{}]
    for key, values in axes.items():
        if not isinstance(values, list):
            raise ContractError(f"matrix axis {key!r} is not a list")
        combos = [{**combo, key: value} for combo in combos for value in values]
    if include:
        extra = [dict(entry) for entry in include]
        combos = extra if combos == [{}] else combos + extra
    return combos


_EXPRESSION_RE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}")


def _check_names(job_id: str, job: dict) -> list[str]:
    """The check name(s) this job actually emits."""
    template = job.get("name", job_id)
    if "${{" not in str(template):
        return [template]

    def _substitute(combo: dict) -> str:
        return _EXPRESSION_RE.sub(
            lambda match: str(combo.get(match.group(1), match.group(0))), str(template)
        )

    names = []
    for combo in _matrix_rows(job):
        name = _substitute(combo)
        if "${{" in name:
            raise ContractError(
                f"job {job_id!r} has a name this generator cannot resolve: {template!r}. "
                "Branch protection needs a literal string, so either simplify the name or "
                "teach this script the expression."
            )
        names.append(name)
    return list(dict.fromkeys(names)) or [template]


def _workflow_files() -> list[Path]:
    """Both extensions GitHub honours."""
    return sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])


def collect() -> list[tuple[str, str, str]]:
    """(workflow, check name, scope) for every job reachable from a PR."""
    rows: list[tuple[str, str, str]] = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text()) or {}
        pull_request = _pull_request_trigger(doc)
        if pull_request is None:
            continue
        workflow = doc.get("name", path.name)
        trigger_scope = _scope(pull_request)
        for job_id, job in (doc.get("jobs") or {}).items():
            job = job or {}
            scope = _job_scope(job, trigger_scope)
            try:
                names = _check_names(job_id, job)
            except ContractError as exc:
                raise ContractError(f"{path.name}: {exc}") from exc
            rows.extend((workflow, name, scope) for name in names)
    _refuse_duplicates(rows)
    return sorted(rows)


def _refuse_duplicates(rows: list[tuple[str, str, str]]) -> None:
    """Branch protection keys checks by bare name, not by workflow."""
    seen: dict[str, str] = {}
    for workflow, name, _scope_value in rows:
        if name in seen and seen[name] != workflow:
            raise ContractError(
                f"two workflows emit the check name {name!r}: {seen[name]!r} and {workflow!r}. "
                "Branch protection cannot tell them apart; rename one."
            )
        seen.setdefault(name, workflow)


def base_coupled(rows: list[tuple[str, str, str]]) -> set[tuple[str, str]]:
    """The checks whose meaning depends on what a PR is based on."""
    return {(wf, check) for wf, check, scope in rows if "base" in scope}


def merge_group_gaps(rows: list[tuple[str, str, str]]) -> list[str]:
    """Required develop checks whose producing workflow cannot run in the queue.

    Synthetic contexts produced through the Checks API (currently `gates-ran`)
    are deliberately absent from `rows` and are validated by their own tests.
    This function governs ordinary Actions job contexts.
    """
    if not PROTECTION.exists():
        return [f"{PROTECTION.relative_to(REPO_ROOT)} does not exist"]
    protection = json.loads(PROTECTION.read_text(encoding="utf-8"))
    required = set(protection["branches"]["develop"]["required_status_checks"]["contexts"])
    producer = {check: workflow for workflow, check, _scope_value in rows}

    merge_capable: set[str] = set()
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if _merge_group_trigger(doc) is not None:
            merge_capable.add(doc.get("name", path.name))

    gaps: list[str] = []
    for check in sorted(required):
        workflow = producer.get(check)
        if workflow is not None and workflow not in merge_capable:
            gaps.append(f"{check!r} is required on develop but {workflow!r} has no merge_group gate")
    return gaps


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

    rows = collect()
    queue_gaps = merge_group_gaps(rows)
    if queue_gaps:
        print(
            "FAIL: develop merge queue has required checks that cannot report on merge_group:\n\n  "
            + "\n  ".join(queue_gaps),
            file=sys.stderr,
        )
        return 1

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    table = render(rows)
    rebuilt = f"{head}{BEGIN}\n\n{table}\n\n{END}{tail}"

    if "--update" in sys.argv:
        DOC.write_text(rebuilt)
        print(f"updated {DOC.relative_to(REPO_ROOT)} ({len(rows)} checks)")
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

    print(
        f"ok: {len(rows)} PR checks match docs/ci/REQUIRED-CHECKS.md; "
        "all ordinary required develop checks can report on merge_group"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
