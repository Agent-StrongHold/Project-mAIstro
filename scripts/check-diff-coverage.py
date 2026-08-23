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

What it cannot check
--------------------
A file outside every `--source` path of the coverage run. Coverage never records
it, so there is nothing to compare — the measured scope is the `--source` list
in `quality.yml`, and that list is the exemption list. Note that
`include_namespace_packages` must stay on in `[tool.coverage.report]`, or a new
module in a directory without `__init__.py` is silently absent from the report
and this gate sees nothing to check.

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


def audit(base: str, report: Path, line_floor: float, branch_floor: float) -> list[str]:
    """One message per file that falls short. Empty means the change is clean."""
    coverage = coverage_by_file(report)
    failures = []
    for filename, touched in sorted(changed_lines(base).items()):
        lines = coverage.get(filename)
        if not lines:
            continue  # outside the measured scope; see the module docstring
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

    failures = audit(args.base, args.report, args.fail_under, args.branch_fail_under)
    if not failures:
        print(
            f"ok: every file this change touches is at or above "
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
