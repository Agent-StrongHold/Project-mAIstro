#!/usr/bin/env python3
"""Gate: the lines a change touches must be covered — per file, arcs included.

Why not `diff-cover`
--------------------
It was the first implementation here, and review showed it cannot express two of
the four rules this gate exists for:

1. **It pools every changed line before applying the threshold.** Five uncovered
   lines in a new file plus ninety-five covered lines elsewhere is 95%, and
   passes — while the criterion is "a PR adding an uncovered file fails,
   *regardless* of the aggregate". Pooling is the same defect as the repository
   aggregate, one scope smaller.
2. **It scores line hits, not branch arcs.** A changed conditional executed
   along one outcome records a line hit and a missing branch, so `--branch`
   collected the arc data and nothing read it. "Line and branch" was documented
   and only the line half was true.

Both are per-file questions about `coverage.xml`, which is a small file with the
answers in it, so this reads it directly rather than wrapping a tool around it.

What it checks
--------------
For every file that the diff touches **and** that appears in the coverage
report, over the changed lines only:

- **line coverage** — executed at least once;
- **branch coverage** — every arc out of a changed conditional taken.

Each is compared per file. A file below either threshold fails and is named with
its uncovered lines.

What is in scope, and what is exempt
-----------------------------------
`MEASURED_ROOTS` below is the one reviewable place (#163 item 5). A changed
Python file under one of those trees **must** appear in `coverage.xml`; absent
means the measurement did not happen, and this fails rather than skipping. That
distinction is the point: a silent skip and a pass look identical in a green
tick, so a mistyped `--source`, a producer whose artefact uploaded empty, or a
namespace-package directory coverage declined to walk would all read as "this
change is exercised" while nothing had been measured.

`EXEMPT` holds the paths deliberately outside the gate, each with its reason,
and changed files matching one are listed in the output rather than passed over
in silence. Everything else — a package with no coverage producer at all — is
named as unmeasured scope so the hole is visible in the log.

`MEASURED_ROOTS` is checked against `quality.yml`'s own `--source=` flags by
`tests/test_check_diff_coverage.py`. A declaration nobody verifies drifts the
first time a producer is added, and drift here is silent by construction.

Note that `include_namespace_packages` must stay on in `[tool.coverage.report]`,
or a new module in a directory without `__init__.py` is absent from the report;
that used to defeat the gate silently and is now a failure.

Usage
-----
    python3 scripts/check-diff-coverage.py coverage.xml --base origin/develop
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Every tree whose Python files this gate measures, as `--source` paths.
#:
#: Kept in the same shape `quality.yml` passes to `coverage run --source=`, so
#: the two can be compared literally rather than through a normalisation nobody
#: reads. `tests/test_check_diff_coverage.py` asserts they are the same set.
#:
#: The publish set is the first five. The rest are outside it — they have no
#: aggregate floor — and are here because "the file you touched" is well defined
#: even where "the package's aggregate" is not yet governed (#163 item 6).
MEASURED_ROOTS = (
    "packages/maistro-core/src/maistro",
    "packages/maistro-canvas/src/maistro_canvas",
    "packages/maistro-evolve/src/maistro_evolve",
    "packages/maistro-rsi/src/maistro_rsi",
    "packages/maistro-bootstrap/src/maistro_bootstrap",
    "packages/maistro-server/src/maistro_server",
    "packages/maistro-turing/src/maistro_turing",
    "packages/maistro-turing/backend",
    "packages/maistro-design/src/maistro_design",
    "packages/hive-conductor/backend",
    # The gates themselves (#257). Every one of #160's five mandates is
    # enforced by a file in here, and until this entry they were the only
    # Python in the repository that no gate governed — 5632 statements at 55%,
    # with `ac_outcome_plugin.py` at 0% while every criterion's `passing` rung
    # depended on it. A bug in a gate does not fail CI; it makes CI wrong,
    # quietly, in whichever direction the bug points.
    "scripts",
)

#: Paths inside a measured root that the gate deliberately does not score, each
#: with the reason. An exemption list nobody can find becomes a place to hide,
#: so these are named in the output when a change touches one rather than being
#: dropped on the floor.
EXEMPT: tuple[tuple[str, str], ...] = (
    (
        "alembic/versions/",
        "a migration is exercised by running it against a real database, which "
        "the migration-chain suite does; line coverage of the module says "
        "nothing about whether the schema change is right",
    ),
    (
        "/tests/",
        "test code is the evidence, not the thing evidenced",
    ),
    (
        "/conftest.py",
        "fixtures are exercised by the tests that request them",
    ),
    # The four files under `scripts/` that are not tooling about this
    # repository's own truth. The boundary is that question, not "is it
    # covered": gates, generators and ratchets are all measured, including the
    # mutation family that is parked behind a disabled workflow, because a
    # parked gate is still a gate the repository will one day trust.
    (
        "/rlphd_",
        "a simulation supporting docs/reviews/2026-07-29-rsi-containment-review.md, "
        "not tooling — it models a policy rather than checking the repository, and "
        "testing it would pin the illustration rather than any claim CI makes",
    ),
    (
        "/openrouter_rpm_pacer.py",
        "an operational utility that paces LiteLLM against OpenRouter's daily budget; "
        "it asserts nothing about this repository and is exercised against a live "
        "account, which CI has none of",
    ),
)

#: `@@ -old,count +new,count @@` — only the new-side range matters, because a
#: line that no longer exists cannot be covered.
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

#: `<line ... condition-coverage="50% (1/2)">`
CONDITION_RE = re.compile(r"\((\d+)/(\d+)\)")


def changed_lines(base: str) -> dict[str, set[int]]:
    """Line numbers added or modified per file, against the merge base.

    `...` and not `..`: a PR is judged on what it changed, not on what the base
    branch has done since it forked. Using the two-dot form would blame a PR for
    every line anyone else merged in the meantime.
    """
    proc = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"FAIL: could not diff against {base!r}: {proc.stderr.strip()}")

    per_file: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = per_file.setdefault(line[6:], set())
        elif line.startswith("+++ /dev/null"):
            current = None
        elif current is not None and (hunk := HUNK_RE.match(line)):
            start = int(hunk.group(1))
            count = int(hunk.group(2) or 1)
            current.update(range(start, start + count))
    return per_file


def coverage_by_file(report: Path) -> dict[str, dict[int, tuple[int, int, int]]]:
    """filename -> {line: (hits, arcs_taken, arcs_total)}."""
    tree = ET.parse(report)
    measured: dict[str, dict[int, tuple[int, int, int]]] = {}
    for cls in tree.iter("class"):
        filename = cls.get("filename")
        if filename is None:
            continue
        lines = measured.setdefault(filename, {})
        for line in cls.iter("line"):
            number = int(line.get("number", 0))
            hits = int(line.get("hits", 0))
            taken = total = 0
            if line.get("branch") == "true":
                condition = CONDITION_RE.search(line.get("condition-coverage", ""))
                if condition:
                    taken, total = int(condition.group(1)), int(condition.group(2))
            lines[number] = (hits, taken, total)
    return measured


def classify(filename: str) -> tuple[str, str]:
    """Where a changed path sits relative to the gate: `(verdict, detail)`.

    Three verdicts, and the middle one is the reason this function exists.
    `measured` must be scored. `exempt` is deliberately not scored, and says
    why. `unmeasured` is a file no coverage producer covers — not a decision
    anyone made about that file, just a package the gate does not reach yet, and
    naming it keeps the hole visible instead of indistinguishable from a pass.
    """
    if not filename.endswith(".py"):
        return "ignored", "not Python"
    for marker, reason in EXEMPT:
        if marker in f"/{filename}":
            return "exempt", reason
    for root in MEASURED_ROOTS:
        if filename == root or filename.startswith(f"{root}/"):
            return "measured", root
    return "unmeasured", "no coverage producer measures this tree"


def audit(base: str, report: Path, line_floor: float, branch_floor: float) -> list[str]:
    """One message per file that falls short. Empty means the change is clean."""
    coverage = coverage_by_file(report)
    failures = []
    for filename, touched in sorted(changed_lines(base).items()):
        verdict, detail = classify(filename)
        if verdict != "measured":
            continue
        if filename not in coverage:
            # In scope and absent from the report: the measurement did not
            # happen. Skipping here is what let a mistyped `--source` or an
            # empty producer artefact read as a pass.
            failures.append(
                f"  {filename}: under a measured root ({detail}) but absent from "
                f"the coverage report — the measurement did not happen"
            )
            continue
        # Membership, not truthiness. Coverage emits a `<class>` with zero
        # `<line>` children for a file with no executable statements — an empty
        # `__init__.py`, a docstring-only module — and those are measured, with
        # nothing to score. Reading the empty dict as "absent" failed exactly
        # the files that are trivially correct.
        lines = coverage[filename]
        relevant = {n: lines[n] for n in sorted(touched) if n in lines}
        if not relevant:
            continue

        uncovered = [n for n, (hits, _t, _a) in relevant.items() if hits == 0]
        covered = len(relevant) - len(uncovered)
        line_pct = 100.0 * covered / len(relevant)

        arcs_taken = sum(taken for _h, taken, total in relevant.values() if total)
        arcs_total = sum(total for _h, _taken, total in relevant.values() if total)
        partial = [n for n, (_h, taken, total) in relevant.items() if total and taken < total]
        branch_pct = 100.0 * arcs_taken / arcs_total if arcs_total else 100.0

        if line_pct + 1e-9 < line_floor:
            failures.append(
                f"  {filename}: {line_pct:.1f}% of {len(relevant)} changed lines "
                f"(need {line_floor:g}%); uncovered {_ranges(uncovered)}"
            )
        elif branch_pct + 1e-9 < branch_floor:
            failures.append(
                f"  {filename}: {branch_pct:.1f}% of {arcs_total} changed branch arcs "
                f"(need {branch_floor:g}%); partial at {_ranges(partial)}"
            )
    return failures


def _ranges(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers) or "-"


def _report_scope(base: str) -> None:
    """Say what the gate did and did not score, before it says what failed.

    A gate that prints only failures cannot be read for what it covered, and
    "coverage passed" then means whatever the reader assumes. Both lists are
    short by construction — they are per change, not per repository.
    """
    by_verdict: dict[str, list[tuple[str, str]]] = {}
    for filename in sorted(changed_lines(base)):
        verdict, detail = classify(filename)
        by_verdict.setdefault(verdict, []).append((filename, detail))

    scored = len(by_verdict.get("measured", []))
    print(f"diff-coverage scope: {scored} changed file(s) measured")
    for verdict, heading in (
        ("exempt", "exempt, by declaration in scripts/check-diff-coverage.py"),
        ("unmeasured", "NOT measured — no coverage producer reaches these"),
    ):
        entries = by_verdict.get(verdict, [])
        if not entries:
            continue
        print(f"  {len(entries)} {heading}:")
        for filename, detail in entries:
            print(f"    {filename} — {detail}")
    print()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path, help="coverage.xml")
    ap.add_argument("--base", required=True, help="branch or rev the PR is based on")
    # Two floors, because the two distributions are different. Measured over
    # every PR merged into `develop` since 15abb9d, per file: worst line
    # coverage 94.9%, worst branch coverage 85.7%. Each floor sits under its own
    # measured worst with headroom — a floor pinned to its measurement fails the
    # first PR with one awkward case, and a single shared floor would have to be
    # the lower of the two, which would stop enforcing anything on lines.
    ap.add_argument("--fail-under", type=float, default=90.0, help="per-file line floor")
    ap.add_argument(
        "--branch-fail-under", type=float, default=80.0, help="per-file branch-arc floor"
    )
    args = ap.parse_args(argv)

    if not args.report.exists():
        print(f"FAIL: {args.report} does not exist; run `coverage xml` first")
        return 1

    _report_scope(args.base)
    failures = audit(args.base, args.report, args.fail_under, args.branch_fail_under)
    if not failures:
        print(
            f"ok: every measured file this change touches is at or above "
            f"{args.fail_under:g}% lines / {args.branch_fail_under:g}% branch arcs"
        )
        return 0

    print(f"FAIL: {len(failures)} file(s) below the diff-coverage floor\n")
    print("\n".join(failures))
    print(
        "\n  Per file, not pooled: covering other lines elsewhere in the same PR\n"
        "  does not make an uncovered file acceptable. Branch arcs count too — a\n"
        "  conditional executed along one outcome is half-tested.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
