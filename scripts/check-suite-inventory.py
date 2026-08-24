#!/usr/bin/env python3
"""Gate: collected pytest node IDs must match ``docs/testing/SUITE-INVENTORY.md``.

C1 (#286) asks that "the expected inventory is generated with ``pytest
--collect-only -q`` per suite (node IDs — not static ``def test_`` counts, which
parametrization expands) and CI-collected node IDs match it (± documented
skips)". ``SUITE-INVENTORY.md`` is the recorded half; this script is the
comparison half.

What it catches
---------------
A suite that silently stops collecting. That is the failure mode the inventory
exists for: a `conftest` import error, a renamed directory, a workflow that
quietly drops a path, or a `pytest.ini` `testpaths` edit turns a 400-test suite
into 0 collected and **every downstream job still goes green**, because "0 tests
ran" is not a pytest failure. Comparing against a recorded number makes that
loud.

Counts, not node-ID sets
------------------------
Deliberate. A set comparison catches renames (delete `test_a`, add `test_b`
— same count, different IDs) and a count comparison does not. It costs a
checked-in manifest of ~9,500 node IDs that churns on every `@parametrize`
tweak, turning a routine test edit into a 200-line diff and training everyone to
regenerate without reading. The rename case is also already covered: the suites
themselves *run* in `ci.yml`, so a renamed-but-broken test fails there on its
own merits. The gap this script closes is the one nothing else covers — a suite
vanishing from collection — and a count closes it. If node-level tracking is
ever wanted, add a second opt-in mode rather than making the default brittle.

Two invocation traps (both documented in SUITE-INVENTORY.md; honored here)
-------------------------------------------------------------------------
1. ``packages/hive-conductor/backend/tests`` runs under **bare python, never
   ``uv run``** — its conftest re-inserts the backend dir at ``sys.path[0]``
   because the monorepo root has a ``services/`` package that shadows its own.
2. ``formal/`` needs **evolve + rsi** on ``PYTHONPATH``, not just core. Omitting
   them is a collection ``ImportError``, which reads like a broken suite.

Usage
-----
    python3 scripts/check-suite-inventory.py              # check every suite
    python3 scripts/check-suite-inventory.py --suite formal/
    python3 scripts/check-suite-inventory.py --update     # rewrite the table
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "docs" / "testing" / "SUITE-INVENTORY.md"
NOTES = REPO_ROOT / "docs" / "testing" / "inventory-notes"

#: Env every collection runs under. Matches ci.yml's pytest steps — without it,
#: suites that build a settings object at import time raise on a missing secret.
BASE_ENV = {"REQUIRE_AUTH": "false", "MAISTRO_DRY_RUN": "1"}


@dataclass(frozen=True)
class Recipe:
    """How to collect one suite."""

    args: list[str]
    """Extra pytest args beyond the suite path (e.g. --ignore)."""

    pythonpath: list[str] = field(default_factory=list)
    """Repo-relative src trees to prepend to PYTHONPATH."""

    bare_python: bool = False
    """Run as ``<python> -m pytest`` instead of ``uv run pytest``."""


#: Workspace members that are NOT root dependencies, so `uv sync` does not
#: install them into the root env (ci.yml does the same for their test step).
_EVOLVE_RSI = ["packages/maistro-evolve/src", "packages/maistro-rsi/src"]

#: Keyed by the suite path recorded in the inventory table. Every table row must
#: have an entry here — an unrecognized row is an error, not a silent skip,
#: otherwise adding a row to the doc would appear to be gated when it is not.
RECIPES: dict[str, Recipe] = {
    "packages/maistro-core/tests": Recipe(args=[]),
    "packages/maistro-evolve/tests": Recipe(args=[], pythonpath=_EVOLVE_RSI),
    "packages/maistro-rsi/tests": Recipe(args=[], pythonpath=_EVOLVE_RSI),
    "packages/maistro-server/tests": Recipe(args=[]),
    "packages/maistro-turing/tests": Recipe(args=[]),
    "packages/maistro-design/tests": Recipe(args=[]),
    "packages/maistro-bootstrap/tests": Recipe(args=[]),
    "packages/maistro-canvas/tests": Recipe(args=[]),
    "packages/maistro-turing/backend/tests": Recipe(args=[]),
    # Whole root tree, including tests/tools/registry (which registry.yml owns
    # at run time). The inventory records what the tree *contains*; which
    # workflow executes which part is the table's third column.
    "tests/": Recipe(args=[]),
    "formal/": Recipe(args=[], pythonpath=["packages/maistro-core/src", *_EVOLVE_RSI]),
    # Trap 1 — bare python, never uv.
    "packages/hive-conductor/backend/tests": Recipe(args=[], bare_python=True),
    "packages/hive-conductor/tests/e2e": Recipe(args=[], bare_python=True),
}

#: `| `path` (note) | 1234 | where it runs |`
ROW_RE = re.compile(r"^\|\s*`([^`]+)`[^|]*\|\s*(\d+)\s*\|")
COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected")
ERROR_RE = re.compile(r"(\d+)\s+errors?\b")


def parse_inventory(text: str) -> list[tuple[int, str, int]]:
    """Return ``(line_index, suite_path, recorded_count)`` per table row."""
    rows: list[tuple[int, str, int]] = []
    for i, line in enumerate(text.splitlines()):
        m = ROW_RE.match(line)
        if m:
            rows.append((i, m.group(1), int(m.group(2))))
    return rows


def collect(suite: str, recipe: Recipe) -> tuple[int, str]:
    """Collect ``suite`` and return ``(node_id_count, human_readable_command)``."""
    if recipe.bare_python:
        argv = [sys.executable, "-m", "pytest"]
        shown = "python3 -m pytest"
    else:
        argv = ["uv", "run", "pytest"]
        shown = "uv run pytest"
    argv += [suite, *recipe.args, "--collect-only", "-q"]

    env = {**os.environ, **BASE_ENV}
    prefix = " ".join(f"{k}={v}" for k, v in BASE_ENV.items())
    if recipe.pythonpath:
        joined = ":".join(recipe.pythonpath)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{joined}:{existing}" if existing else joined
        prefix += f" PYTHONPATH={joined}"

    proc = subprocess.run(argv, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    cmd = f"{prefix} {shown} {' '.join([suite, *recipe.args])} --collect-only -q"

    matches = COLLECTED_RE.findall(out)
    if proc.returncode != 0 or not matches:
        errs = ERROR_RE.search(out)
        detail = f"{errs.group(0)} during collection" if errs else f"exit {proc.returncode}"
        tail = "\n".join(out.strip().splitlines()[-15:])
        raise RuntimeError(f"collection failed ({detail}) for `{suite}`\n  {cmd}\n{tail}")
    return int(matches[-1]), cmd


def select_rows(text: str, wanted: list[str] | None) -> list[tuple[int, str, int]]:
    """Parse and validate the inventory table, optionally narrowed to ``wanted``.

    Raises ``ValueError`` with an operator-readable message on any problem.
    """
    rows = parse_inventory(text)
    if not rows:
        raise ValueError(f"no suite rows parsed from {INVENTORY}")

    unknown = [s for _, s, _ in rows if s not in RECIPES]
    if unknown:
        raise ValueError(
            "inventory rows with no collection recipe in "
            f"{Path(__file__).name}: {', '.join(unknown)}\n"
            "       Add each to RECIPES so it is actually gated."
        )

    if wanted:
        rows = [r for r in rows if r[1] in set(wanted)]
        if not rows:
            raise ValueError(f"no inventory row matches {sorted(wanted)}")
    return rows


def _rewrite_count(line: str, actual: int) -> str:
    """Replace the recorded count in one table row with ``actual``."""
    m = ROW_RE.match(line)
    assert m is not None
    head, rest = m.group(0), line[m.end() :]
    return head[: m.start(2) - m.start(0)] + str(actual) + head[m.end(2) - m.start(0) :] + rest


def notes_problems() -> list[str]:
    """Check the notes directory the inventory points at is actually there.

    The prose explaining *why* a count moved lives in ``inventory-notes/``
    rather than in the inventory itself, because a shared prose block made
    every test-adding branch conflict with every other one (#208). That split
    only works while the pointer and the directory agree, so a rename or an
    accidental deletion should be loud rather than leaving a dead link.

    This deliberately does not require a note per change. Such a mandate would
    fail every PR already open when it landed, and the AC gate is where
    per-change requirements belong.
    """
    problems = []
    if not NOTES.is_dir():
        problems.append(f"{NOTES.relative_to(REPO_ROOT)}/ is missing")
        return problems
    if not (NOTES / "README.md").is_file():
        problems.append(f"{NOTES.relative_to(REPO_ROOT)}/README.md is missing")
    link = f"]({NOTES.name}/)"
    if link not in INVENTORY.read_text(encoding="utf-8"):
        problems.append(
            f"{INVENTORY.relative_to(REPO_ROOT)} no longer links to {NOTES.relative_to(REPO_ROOT)}/"
        )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", action="append", help="check only this suite path (repeatable)")
    ap.add_argument(
        "--update",
        action="store_true",
        help="rewrite SUITE-INVENTORY.md's counts from the current tree",
    )
    args = ap.parse_args()

    if problems := notes_problems():
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2

    text = INVENTORY.read_text(encoding="utf-8")
    try:
        rows = select_rows(text, args.suite)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    lines = text.splitlines()
    drift: list[tuple[str, int, int]] = []
    failures: list[str] = []

    for idx, suite, recorded in rows:
        try:
            actual, _cmd = collect(suite, RECIPES[suite])
        except RuntimeError as exc:
            failures.append(str(exc))
            print(f"ERROR  {suite}", file=sys.stderr)
            continue
        if actual == recorded:
            print(f"ok     {suite}: {actual}")
            continue
        drift.append((suite, recorded, actual))
        print(f"DRIFT  {suite}: inventory {recorded}, collected {actual}")
        lines[idx] = _rewrite_count(lines[idx], actual)

    if failures:
        print("\n".join(["", *failures]), file=sys.stderr)
        print(
            "\nOne or more suites failed to collect. That is a broken suite, not "
            "inventory drift — fix the collection error; do not update the inventory.",
            file=sys.stderr,
        )
        return 1

    if not drift:
        print(f"\nok: {len(rows)} suite(s) match {INVENTORY.relative_to(REPO_ROOT)}")
        return 0

    if args.update:
        INVENTORY.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nupdated {INVENTORY.relative_to(REPO_ROOT)} ({len(drift)} row(s))")
        return 0

    total = sum(a - r for _, r, a in drift)
    print(
        "\n"
        f"FAIL: {len(drift)} suite(s) drifted from "
        f"{INVENTORY.relative_to(REPO_ROOT)} (net {total:+d} node IDs).\n"
        "\n"
        "If you added or removed tests on purpose, this is expected — refresh the\n"
        "inventory and commit it with your change:\n"
        "\n"
        "    python3 scripts/check-suite-inventory.py --update\n"
        "\n"
        "If you did NOT change any test, a suite has silently stopped collecting\n"
        "(conftest import error, moved directory, changed testpaths). Investigate\n"
        "before touching the inventory — the number is the alarm, not the bug.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
