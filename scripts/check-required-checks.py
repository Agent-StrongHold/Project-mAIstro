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

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DOC = REPO_ROOT / "docs" / "ci" / "REQUIRED-CHECKS.md"
BEGIN = "<!-- checks:table -->"
END = "<!-- /checks:table -->"


class ContractError(RuntimeError):
    """A workflow the contract cannot express, rather than one it misreads.

    Raised instead of recording a best guess. A gate whose failure mode is a
    plausible-looking wrong answer is worse than one that stops: the wrong
    answer gets banked into the table and read as the truth afterwards.
    """


def _pull_request_trigger(doc: dict) -> dict | None:
    """The `pull_request:` block, or None when the workflow has no PR trigger.

    Three spellings, all valid:

        on: {pull_request: {branches: [main]}}   -> the filter dict
        on: {pull_request: null}                 -> {} (unfiltered)
        on: [push, pull_request]                 -> {} (unfiltered)

    ``on:`` is YAML 1.1's boolean ``True`` after parsing — the classic GitHub
    Actions footgun. Both spellings are read so a `"on"`-quoted workflow is not
    silently treated as having no triggers at all.

    The sequence form matters for the same reason: rejecting every
    non-dictionary trigger dropped such a workflow out of the contract
    *entirely*, and `--update` then produced a table that passed CI while the
    checks it omitted were still gating merges.
    """
    triggers = doc.get(True, doc.get("on"))
    if isinstance(triggers, list):
        return {} if "pull_request" in triggers else None
    if isinstance(triggers, str):
        return {} if triggers == "pull_request" else None
    if not isinstance(triggers, dict) or "pull_request" not in triggers:
        return None
    return triggers["pull_request"] or {}


#: Trigger filters that make a check's presence conditional, and how to say so.
#: The `-ignore` forms are the same coupling stated in the negative — a
#: `branches-ignore` reintroduces exactly the base-dependence #161 removed, and
#: falling through to "every PR" would have left the table and `base_coupled()`
#: both green while it did.
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

    Reading only the trigger is not enough, and `security.yml` is the proof:

        Container scan + SBOM + cosign
          if: (github.event_name == 'pull_request' && github.base_ref == 'main') ...

    Its workflow triggers on every PR, so a trigger-only reading calls it
    "every PR" — while the job reports `skipped` on every PR not based on
    `main`. That is the same base-branch coupling #161 removed from the
    triggers, hiding one level down, and a contract that missed it would
    under-report exactly the thing it exists to surface.

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
    """Every matrix combination a job expands to, as name->value maps.

    GitHub evaluates `job.name` once per combination, so a matrix job does not
    emit the check name written in the YAML — CodeQL's
    `Analyze (${{ matrix.language }})` emits `Analyze (actions)`,
    `Analyze (javascript-typescript)` and `Analyze (python)`. Recording the
    unevaluated string gave branch protection a name no run ever produces, and
    changing the matrix would have altered three real check names without this
    gate noticing.
    """
    matrix = ((job.get("strategy") or {}).get("matrix")) or {}
    if not isinstance(matrix, dict):
        raise ContractError(f"matrix is not a mapping: {matrix!r}")
    if "exclude" in matrix:
        # Expressible, but only by reimplementing GitHub's exclude matching.
        # Refusing is honest; guessing would bank a wrong name.
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
    """Both extensions GitHub honours. Scanning only `.yml` meant a workflow
    renamed to `.yaml` left every one of its checks outside the contract, and
    `--update` produced a table that passed while those checks still gated."""
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
    """Branch protection keys checks by bare name, not by workflow.

    Two jobs resolving to one name give a rule an ambiguous status to wait on,
    which blocks merges in a way that reads as a stuck check rather than as a
    naming collision. Cheaper to refuse here, naming both producers.
    """
    seen: dict[str, str] = {}
    for workflow, name, _scope_value in rows:
        if name in seen and seen[name] != workflow:
            raise ContractError(
                f"two workflows emit the check name {name!r}: {seen[name]!r} and {workflow!r}. "
                "Branch protection cannot tell them apart; rename one."
            )
        seen.setdefault(name, workflow)


def base_coupled(rows: list[tuple[str, str, str]]) -> set[tuple[str, str]]:
    """The checks whose meaning depends on what a PR is based on.

    By trigger or by job condition — the two are the same defect wearing
    different clothes, so #161's acceptance is asserted against this rather than
    against the trigger alone.
    """
    return {(wf, check) for wf, check, scope in rows if "base" in scope}


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
