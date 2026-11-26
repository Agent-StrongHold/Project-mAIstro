#!/usr/bin/env python3
"""Gate: one reviewed disposition for every GitHub workflow, and no always-green rot (#400).

The failure this gate exists to close
-------------------------------------
`stream1-diagnostic.yml` sat in `.github/workflows/` pinned to
`feat/execution-runtime-spine-373` -- a branch deleted after #373 landed --
with a `git worktree add` baseline SHA the repository no longer contained, and
every step ended in `|| true`. It could never run, and had it run it could
never fail. Nothing rejected any of the three conditions, so the file kept
reading to every agent and reviewer as an active workflow pattern: the
definition of an always-green precedent.

The inventory
-------------
`quality/workflow-inventory.json` gives every workflow one reviewed
disposition, checked in both directions like `quality/image-inventory.json`:

- ACTIVE           event-triggered gate or automation. A trigger branch must
                   be a live remote ref (or a reviewed `retained_branches`
                   row -- the retired `integration` topology is retained on
                   purpose, and the row is what makes that visible).
- MANUAL_DIAGNOSTIC workflow_dispatch-only: an on-demand measurement an
                   operator or an agent invokes deliberately. It must declare
                   no other trigger, or it is an ACTIVE file dodging review.
- RETIRED          removed. Names `replaced_by`, `removal_owner` and
                   `removal_issue`. A retirement is a decision, not permission
                   to resurrect: a RETIRED entry whose file reappears fails,
                   so the only way back is a reviewed reclassification.

The three rots
--------------
1. **Dead branch references.** Every non-glob entry under `push.branches` /
   `pull_request.branches` / `pull_request_target.branches` must resolve as a
   remote-tracking ref (`refs/remotes/origin/<branch>`) or be covered by a
   reviewed `retained_branches` row. Globs are skipped: `feat/*` cannot rot.
2. **Dead SHA references.** A 40-hex token anywhere except a `uses:` line
   (other repositories' action pins are not this repository's objects) must
   resolve as a commit in this checkout. The all-zeros sentinel is exempt.
   This runs in the `quality-gate` job, which checks out full history -- a
   shallow checkout would report real references as missing, so a job that
   wants this gate wants `fetch-depth: 0`.
3. **Blanket error swallowing.** `|| true` and friends (`|| :`, `|| echo`,
   `|| exit 0`) in `run:` blocks, and `continue-on-error: true`, need a
   written reason: a comment on the same line or within six lines above. Even
   a cleanup step's swallow carries a reason, because "best-effort" is a claim
   a reviewer reads, not a vibe -- the difference between the apt install that
   documented itself against the 29-minute hang and stream1's four silent
   `|| true`s is exactly the difference between a decision and a shrug.

What it deliberately does not do
--------------------------------
Verify that a workflow's job graph still does what its rationale says.
Rationales are reviewed prose, not proofs; the gate holds the *set* closed and
the *references* live, which is the part that rots silently. It also does not
validate `workflow_run.workflows` names or `schedule.cron` values -- a renamed
upstream workflow or a broken cron fails visibly on its next run, unlike a
branch filter, which fails by never running at all.

Usage
-----
    python3 scripts/check-workflow-inventory.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "workflow-inventory.json"
WORKFLOWS = ROOT / ".github" / "workflows"

DISPOSITIONS = ("ACTIVE", "MANUAL_DIAGNOSTIC", "RETIRED")

#: A swallow: the command's exit code is discarded in favour of a constant.
#: (`:` has no word char to bound, so it is anchored to whitespace or EOL.)
SWALLOW_RE = re.compile(r"\|\|\s*(?:true\b|exit\s+0\b|echo\b|:(?:\s|$))")

#: A 40-hex token. `\b` keeps this from matching inside a longer hex run (a
#: sha256 checksum is 64 hex chars, whose interior positions are word chars).
HEX40_RE = re.compile(r"\b[0-9a-f]{40}\b")

NULL_SHA = "0" * 40

#: A step-level neutral-status declaration.
CONTINUE_ON_ERROR_RE = re.compile(r"^\s*continue-on-error:\s*true\b")

#: How many lines above a swallow a reason comment may sit. Six covers the
#: repository's own house pattern -- a multi-line rationale block ending one
#: to six lines above the line it justifies (ci.yml's bounded-apt comment) --
#: while still refusing a reason filed in a previous step.
REASON_WINDOW = 6

_EVENTS_WITH_BRANCHES = ("push", "pull_request", "pull_request_target")


class WorkflowError(Exception):
    """A workflow or the inventory could not be parsed. Never silently skipped."""


# --------------------------------------------------------------------------
# the tree
# --------------------------------------------------------------------------


def workflows_on_disk(root: Path) -> set[str]:
    """Every workflow file in the tree, repo-relative."""
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return set()
    return {
        str(path.relative_to(root))
        for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
        if path.is_file()
    }


def load_workflow(path: Path) -> dict[str, object]:
    """Parse one workflow, raising rather than skipping on a parse error."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise WorkflowError(f"{path.name} is not a YAML mapping")
    return doc


def trigger_keys(doc: dict[str, object]) -> list[str]:
    """The event keys under `on:`, sorted. (PyYAML reads bare `on` as True.)"""
    triggers = doc.get(True, doc.get("on"))
    if triggers is None:
        return []
    if isinstance(triggers, list):  # `on: [push, pull_request]`
        return sorted(str(item) for item in triggers)
    if isinstance(triggers, dict):
        return sorted(str(key) for key in triggers)
    if isinstance(triggers, str):  # scalar form: `on: push`
        return [triggers]
    raise WorkflowError(
        f"`on:` resolved to {triggers!r}; YAML 1.1 turns scalars like "
        "`on`/`off`/`true` into booleans, so this event name cannot be read "
        "from the parsed document"
    )


def branch_triggers(doc: dict[str, object]) -> list[tuple[str, str]]:
    """Every `(event, branch)` named under a branch-carrying trigger."""
    triggers = doc.get(True, doc.get("on"))
    found: list[tuple[str, str]] = []
    if not isinstance(triggers, dict):
        return found
    for event in _EVENTS_WITH_BRANCHES:
        spec = triggers.get(event)
        if not isinstance(spec, dict):
            continue
        branches = spec.get("branches")
        if not isinstance(branches, list):
            continue
        found.extend((event, str(branch)) for branch in branches)
    return found


# --------------------------------------------------------------------------
# git: are the references alive?
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkflowError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def live_remote_branch(root: Path, branch: str) -> bool:
    """Whether `origin/<branch>` resolves in this checkout.

    The quality-gate job checks out with `fetch-depth: 0`, which fetches every
    branch, so a deleted branch is absent here the same way it is absent on
    the remote. A shallow checkout cannot answer this question, and the gate
    fails closed below rather than pretending it can.
    """
    try:
        _git(root, "show-ref", "--verify", f"refs/remotes/origin/{branch}")
    except WorkflowError:
        return False
    return True


def commit_exists(root: Path, sha: str) -> bool:
    """Whether the checkout contains `sha` as a commit object."""
    try:
        _git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    except WorkflowError:
        return False
    return True


def git_available(root: Path) -> bool:
    try:
        _git(root, "rev-parse", "--git-dir")
    except WorkflowError:
        return False
    return True


# --------------------------------------------------------------------------
# error swallowing needs a written reason
# --------------------------------------------------------------------------


def has_reason(lines: list[str], index: int) -> bool:
    """Whether the swallow on `lines[index]` carries an adjacent reason comment.

    Accepted: a comment on the same line (after the swallow) or a comment line
    within `REASON_WINDOW` lines above. A reason seven lines up is a reason
    for something else -- the window is deliberately small.
    """
    line = lines[index]
    match = SWALLOW_RE.search(line)
    if match and "#" in line[match.end() :]:
        return True
    if CONTINUE_ON_ERROR_RE.match(line) and "#" in line:
        return True
    for offset in range(1, REASON_WINDOW + 1):
        if index - offset < 0:
            break
        if lines[index - offset].lstrip().startswith("#"):
            return True
    return False


def swallow_findings(lines: list[str], where: str) -> list[str]:
    """Findings for swallows in one file's lines, keyed by line number."""
    failures: list[str] = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue  # prose about swallowing is not swallowing
        flagged = bool(SWALLOW_RE.search(line)) or bool(CONTINUE_ON_ERROR_RE.match(line))
        if not flagged:
            continue
        if not has_reason(lines, index):
            failures.append(
                f"{where}:{index + 1}: error swallow with no written reason -- "
                "add a comment on the line or within "
                f"{REASON_WINDOW} lines above saying why this failure is "
                "tolerable; `|| true` that swallows silently is how a "
                "workflow stops being able to fail (#400)"
            )
    return failures


# --------------------------------------------------------------------------
# the inventory
# --------------------------------------------------------------------------


def load_inventory(root: Path) -> tuple[dict[str, object], list[str]]:
    path = root / "quality" / "workflow-inventory.json"
    if not path.is_file():
        raise WorkflowError(f"{path.relative_to(root)} is missing")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{path.relative_to(root)} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise WorkflowError(f"{path.relative_to(root)} is not a JSON object")
    failures: list[str] = []
    if not str(doc.get("_comment", "")).strip():
        failures.append(
            "workflow-inventory.json: `_comment` is empty; say what the inventory is for"
        )
    workflows = doc.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        failures.append("workflow-inventory.json: `workflows` must be a non-empty list")
    return doc, failures


def check_retired(entry: dict[str, object], ident: str, failures: list[str]) -> None:
    """A RETIRED entry is a decision: successor, owner, issue, and no file."""
    for field in ("removal_owner", "replaced_by"):
        if not entry.get(field):
            failures.append(
                f"{ident}: RETIRED needs `{field}`. A retirement with no "
                "successor and no owner is a shrug, not a decision"
            )
    issue = entry.get("removal_issue")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0:
        failures.append(
            f"{ident}: RETIRED needs a positive integer `removal_issue` naming "
            "the issue that owns the removal"
        )


def check_entry_triggers(
    entry: dict[str, object],
    actual: list[str],
    ident: str,
    failures: list[str],
) -> None:
    """Declared triggers must match the file, and the class must fit them."""
    declared = entry.get("triggers")
    if not isinstance(declared, list) or not all(isinstance(t, str) for t in declared):
        failures.append(f"{ident}: `triggers` must be a list of event names")
        return
    if sorted(declared) != sorted(actual):
        failures.append(
            f"{ident}: declared triggers {sorted(declared)} do not match the "
            f"file's actual `on:` keys {sorted(actual)}; the inventory is the "
            "reviewed statement of what invokes this workflow"
        )
    disposition = str(entry.get("disposition", ""))
    non_manual = [t for t in actual if t != "workflow_dispatch"]
    if disposition == "MANUAL_DIAGNOSTIC" and non_manual:
        failures.append(
            f"{ident}: MANUAL_DIAGNOSTIC must be workflow_dispatch-only, but "
            f"the file also declares {sorted(non_manual)}; an event-triggered "
            "workflow is ACTIVE and needs review as one"
        )
    if disposition == "ACTIVE" and not non_manual:
        failures.append(
            f"{ident}: ACTIVE but the file declares no trigger beyond "
            "workflow_dispatch; a dispatch-only workflow is MANUAL_DIAGNOSTIC"
        )


def check_branch_references(
    root: Path,
    doc: dict[str, object],
    inventory: dict[str, object],
    where: str,
    failures: list[str],
) -> None:
    """Every non-glob trigger branch must be live or reviewed-retained."""
    retained = {
        str(row.get("branch", "")).strip(): row
        for row in inventory.get("retained_branches", [])  # type: ignore[union-attr]
        if isinstance(row, dict)
    }
    for _event, branch in branch_triggers(doc):
        if any(char in branch for char in "*?["):
            continue  # a glob cannot rot the way a literal branch can
        row = retained.get(branch)
        if row is not None:
            for field in ("owner", "reason"):
                if not str(row.get(field, "")).strip():
                    failures.append(
                        f"{where}: retained_branches row for `{branch}` needs "
                        f"`{field}`; retention without a stated why is silent rot"
                    )
            continue
        if not live_remote_branch(root, branch):
            failures.append(
                f"{where}: trigger branch `{branch}` does not exist as "
                "origin/<branch> in this checkout -- a workflow filtered to a "
                "dead branch can never run. Delete the trigger, or retain it "
                "with an owned `retained_branches` row in "
                "quality/workflow-inventory.json (#400)"
            )


def check_sha_references(
    root: Path,
    lines: list[str],
    where: str,
    failures: list[str],
) -> None:
    """40-hex references outside `uses:` must resolve as commits in the tree."""
    for index, line in enumerate(lines):
        # `uses:` pins (both `uses:` and inline `- uses:` styles) are other
        # repositories' objects, not this checkout's commits.
        if re.match(r"^\s*-?\s*uses:\s", line):
            continue
        for token in HEX40_RE.findall(line):
            if token == NULL_SHA:
                continue  # the git sentinel for "no previous revision"
            if not commit_exists(root, token):
                failures.append(
                    f"{where}:{index + 1}: commit {token} does not exist in "
                    "this checkout -- a pinned baseline that has been "
                    "garbage-collected away. Reference a maintained input "
                    "(a ledger, a tag, a reviewed inventory row) instead (#400)"
                )


def check_entry(
    root: Path,
    entry: object,
    inventory: dict[str, object],
    git_ok: bool,
) -> tuple[str | None, list[str]]:
    """One inventory entry's rules. Returns the file it claims, plus findings."""
    failures: list[str] = []
    if not isinstance(entry, dict):
        failures.append("workflow-inventory.json: every entry must be an object")
        return None, failures
    ident = str(entry.get("id", "")) or "<no id>"
    rel = str(entry.get("file", ""))
    disposition = str(entry.get("disposition", ""))
    if disposition not in DISPOSITIONS:
        failures.append(
            f"{ident}: disposition {disposition!r} is not one of {', '.join(DISPOSITIONS)}"
        )
        return None, failures
    if not entry.get("rationale"):
        failures.append(f"{ident}: `rationale` is empty; say what the workflow is for")
    if not rel.startswith(".github/workflows/"):
        failures.append(f"{ident}: `file` {rel!r} is not under .github/workflows/")
        return None, failures

    path = root / rel
    if disposition == "RETIRED":
        if path.exists():
            failures.append(
                f"{ident}: RETIRED but {rel} exists on disk -- a retirement "
                "is a decision, not permission to resurrect; reclassify "
                "ACTIVE/MANUAL_DIAGNOSTIC or delete the file"
            )
        check_retired(entry, ident, failures)
        return rel, failures

    if not path.exists():
        failures.append(
            f"{ident}: {rel} does not exist; an inventory entry naming no "
            "file is a list of things that used to exist"
        )
        return rel, failures
    try:
        doc = load_workflow(path)
        actual = trigger_keys(doc)
    except WorkflowError as exc:
        failures.append(str(exc))
        return rel, failures
    check_entry_triggers(entry, actual, ident, failures)
    lines = path.read_text(encoding="utf-8").splitlines()
    if git_ok:
        check_branch_references(root, doc, inventory, rel, failures)
        check_sha_references(root, lines, rel, failures)
    failures.extend(swallow_findings(lines, rel))
    return rel, failures


def check(root: Path) -> list[str]:
    """Run every rule. Returns failure strings; empty means clean."""
    try:
        inventory, failures = load_inventory(root)
    except WorkflowError as exc:
        return [str(exc)]

    entries: list[object] = inventory.get("workflows", [])
    if not isinstance(entries, list):
        return [*failures, "workflow-inventory.json: `workflows` must be a list"]

    git_ok = git_available(root)
    if not git_ok:
        failures.append(
            f"{root}: no git repository -- branch and SHA liveness cannot be "
            "verified, and this gate fails closed rather than pretending"
        )

    by_file: dict[str, str] = {}
    for entry in entries:
        rel, found = check_entry(root, entry, inventory, git_ok)
        failures.extend(found)
        if rel is not None:
            ident = str(entry.get("id", "")) if isinstance(entry, dict) else "<no id>"  # type: ignore[union-attr]
            if rel in by_file:
                failures.append(f"{ident}: {rel} is already dispositioned by {by_file[rel]}")
            else:
                by_file[rel] = ident

    orphaned = workflows_on_disk(root) - set(by_file)
    for rel in sorted(orphaned):
        failures.append(
            f"{rel}: no entry in quality/workflow-inventory.json -- every "
            "workflow carries a reviewed disposition (ACTIVE, "
            "MANUAL_DIAGNOSTIC or RETIRED); a workflow nobody dispositioned "
            "is how stream1-diagnostic.yml stayed always-green (#400)"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    try:
        failures = check(ROOT)
    except WorkflowError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"workflow inventory gate: {len(failures)} finding(s)\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    count = len(workflows_on_disk(ROOT))
    print(f"workflow inventory gate: clean ({count} workflow(s) dispositioned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
