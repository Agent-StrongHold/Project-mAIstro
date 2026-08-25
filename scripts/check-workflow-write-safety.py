#!/usr/bin/env python3
"""Gate: a workflow may not write in ways the gate set cannot see afterwards (#262).

What it catches
---------------
Three ways a workflow can change the artefact under review while leaving no
signal a reviewer or a gate would notice. All three were found together in
`m0-merge-candidate.yml`, which has since been removed — so this script starts
with nothing to report, and exists because the *pattern* is what recurs. A rule
written only after the second occurrence is a rule that cost two occurrences.

**1. `git push` (AC-1).** A push authenticated with the default `GITHUB_TOKEN`
does not trigger further workflow runs. That is documented GitHub behaviour and
deliberate — it stops recursive loops — but the consequence is structural rather
than flaky: *every head such a workflow produces is by construction a commit
`ci.yml` and `quality.yml` can never run on.* Observed on PR #242: 32 runs each
of both workflows, every bot-actored one stuck at `action_required`, and the
newest head that actually ran either was two commits behind the tip.

The PR then looks checked, because the pushing workflow's own job is green,
while the repository's real gate set has never seen the code.

**2. `-X ours` / `-X theirs` (AC-3).** A blanket merge strategy option resolves
*every* conflicting path in one side's favour and produces no conflict for
anyone to review. In `m0-merge-candidate.yml` the merge ran with `develop`
checked out, so "ours" was develop and the branch's side was discarded silently.
That happened to touch only regenerated files; the mechanism does not know that.
Resolving a named generated file is fine — `git checkout --ours -- <path>` says
which path, in the diff, where it can be read.

**3. `--bank` (AC-4).** `design_coverage` is the repository's only ratchet
*floor*, and `--bank` accepts a fall in it. `quality/ac-state-ceilings.json` says
in its own comment: "Bank a reviewed state with --ratchet --bank and read the
diff; never hand-edit a number to match a delta." A workflow cannot read a diff.
On PR #242 the fall was legitimate and exactly explainable as a denominator
change, but the step could not tell that from a regression and neither could a
reviewer reading only the result.

What it deliberately does not do
--------------------------------
Read repository settings, or ask GitHub anything. Like
`check-required-checks.py` beside it, this is static analysis over
`.github/workflows/` so it works on a fork with no secrets. Whether such a head
is *mergeable* is branch protection's job (#162); this makes the state visible,
which is the half that does not need an admin.

The escape hatch
----------------
A rule with no exception gets deleted the first time someone genuinely needs it.
Each finding can be waived by an `# workflow-write-safety: allow <reason>`
comment on the offending line or the line above it. The reason is mandatory and
lands in the diff, which is the whole point: the waiver is reviewable where the
silent behaviour was not.

Usage
-----
    python3 scripts/check-workflow-write-safety.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: Marker that waives one finding. The trailing text is the mandatory reason.
WAIVER = re.compile(r"#\s*workflow-write-safety:\s*allow\s+(?P<reason>\S.*)")


@dataclass(frozen=True)
class Rule:
    """One forbidden write, and why it is invisible rather than merely risky."""

    key: str
    pattern: re.Pattern[str]
    what: str
    why: str
    instead: str


RULES: tuple[Rule, ...] = (
    Rule(
        key="git-push",
        # `git push` with anything after it, but not `git push --dry-run`.
        pattern=re.compile(r"\bgit\s+push\b(?!\s+--dry-run\b)"),
        what="pushes commits from a workflow",
        why=(
            "a push authenticated with the default GITHUB_TOKEN does not trigger "
            "workflow runs, so every head it produces is one ci.yml and quality.yml "
            "can never run on -- the PR looks checked while the gate set has not "
            "seen the code (#262 AC-1)"
        ),
        instead=(
            "push with a credential whose pushes trigger workflows (a PAT or App "
            "token), and waive this rule naming that credential"
        ),
    ),
    Rule(
        key="blanket-merge-strategy",
        pattern=re.compile(r"-X\s*(ours|theirs)\b"),
        what="resolves merge conflicts with a blanket strategy option",
        why=(
            "it resolves every conflicting path in one side's favour and produces "
            "no conflict for anyone to review; with the base checked out, 'ours' is "
            "the base and the branch's side is discarded silently (#262 AC-3)"
        ),
        instead=(
            "resolve named generated files with `git checkout --ours -- <path>`, "
            "which says which path in the diff, and let anything else conflict"
        ),
    ),
    Rule(
        key="automated-bank",
        pattern=re.compile(r"--bank\b"),
        what="banks a ratchet baseline from a workflow",
        why=(
            "--bank accepts a fall in design_coverage, the repository's only floor, "
            "and a workflow cannot read the diff the ceilings file says to read "
            "before banking one (#262 AC-4)"
        ),
        instead=(
            "bank in a commit a human wrote, so the justification for a floor fall "
            "is in the diff beside the number"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    workflow: str
    line_no: int
    rule: Rule
    line: str

    def render(self) -> str:
        return (
            f"  {self.workflow}:{self.line_no} {self.rule.what}\n"
            f"    {self.line.strip()}\n"
            f"    why: {self.rule.why}\n"
            f"    instead: {self.rule.instead}\n"
            f"    or waive: # workflow-write-safety: allow <reason>"
        )


def _is_waived(lines: list[str], index: int) -> bool:
    """Whether this line, or the line above it, carries a waiver with a reason.

    Both placements, because YAML line length pushes comments up as often as it
    leaves room at the end, and a rule that only accepted one placement would be
    a rule people work around by reformatting.
    """
    candidates = [lines[index]]
    if index > 0:
        candidates.append(lines[index - 1])
    return any(WAIVER.search(candidate) for candidate in candidates)


def _rel(path: Path) -> str:
    """A repo-relative label, falling back to the full path.

    `relative_to` raises for anything outside the repository, and a reporting
    helper that throws turns a finding into a traceback — including for the
    tests, which necessarily scan files in a temporary directory.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def scan(path: Path) -> list[Finding]:
    """Every unwaived finding in one workflow file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Finding] = []
    for index, line in enumerate(lines):
        # A line that is only a waiver comment is not itself a finding, or the
        # waiver's own text would trip the rule it waives.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for rule in RULES:
            if rule.pattern.search(line) and not _is_waived(lines, index):
                found.append(
                    Finding(
                        workflow=_rel(path),
                        line_no=index + 1,
                        rule=rule,
                        line=line,
                    )
                )
    return found


def workflow_files() -> list[Path]:
    if not WORKFLOW_DIR.is_dir():
        return []
    return sorted(p for p in WORKFLOW_DIR.iterdir() if p.suffix in {".yml", ".yaml"})


def main() -> int:
    paths = workflow_files()
    if not paths:
        sys.stderr.write(f"no workflows found under {WORKFLOW_DIR}\n")
        return 1
    findings = [f for path in paths for f in scan(path)]
    if findings:
        print(f"FAIL: {len(findings)} workflow write(s) the gate set cannot see\n")
        for finding in findings:
            print(finding.render())
            print()
        print(
            "Each of these changes the artefact under review while leaving no signal\n"
            "a reviewer or a gate would notice. See #262."
        )
        return 1
    print(f"ok: {len(paths)} workflow(s) make no writes the gate set cannot see")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
