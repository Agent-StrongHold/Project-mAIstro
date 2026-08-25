#!/usr/bin/env python3
"""Gate: collected pytest node IDs must match the recorded inventory.

C1 (#286) asks that "the expected inventory is generated with ``pytest
--collect-only -q`` per suite (node IDs — not static ``def test_`` counts, which
parametrization expands) and CI-collected node IDs match it (± documented
skips)". This script is the comparison half.

What it catches
---------------
A suite that silently stops collecting. That is the failure mode the inventory
exists for: a `conftest` import error, a renamed directory, a workflow that
quietly drops a path, or a `pytest.ini` `testpaths` edit turns a 400-test suite
into 0 collected and **every downstream job still goes green**, because "0 tests
ran" is not a pytest failure. Comparing against a recorded number makes that
loud.

Where the recorded number lives (ADR-082526-547c)
-------------------------------------------------
Not in one shared row. The expected count for a suite is::

    expected = baseline[suite] + Σ delta[suite] over every recorded change

- ``docs/testing/inventory/baseline.json`` holds the counts as of the last
  compaction. It moves only when ``--compact`` runs.
- Each change that moves a count records its own delta in the front matter of
  its own note under ``docs/testing/inventory-notes/``.

This is the whole point, so it is worth stating plainly. When the number was a
shared absolute in ``SUITE-INVENTORY.md``, two branches that both added tests
both rewrote it, and one merge to ``develop`` put 11 of 32 open PRs into
conflict on that single file (#208). Worse, table rows are adjacent lines, so
git had no unchanged context between them: a branch touching
``maistro-core/tests`` conflicted with one touching ``maistro-evolve/tests``,
two entirely unrelated changes. #209 moved the prose out; the number stayed.

Deltas fix both halves. Two changes never write the same path, so there is
nothing to reconcile even when they touch the same suite. And because deltas
are additive, a branch whose base moves needs no regeneration at all — its own
delta is still true, and the sum absorbs whatever else merged. That second
saving is the larger one in practice: re-recording an absolute meant collecting
thirteen suites on a branch that had not changed a test.

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
    python3 scripts/check-suite-inventory.py --show       # render expected counts
    python3 scripts/check-suite-inventory.py --update     # record this change's delta
    python3 scripts/check-suite-inventory.py --update --note 208-delta-ledger
    python3 scripts/check-suite-inventory.py --compact    # fold deltas into baseline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "docs" / "testing" / "SUITE-INVENTORY.md"
NOTES = REPO_ROOT / "docs" / "testing" / "inventory-notes"
BASELINE = REPO_ROOT / "docs" / "testing" / "inventory" / "baseline.json"

#: Env every collection runs under. Matches ci.yml's pytest steps — without it,
#: suites that build a settings object at import time raise on a missing secret.
BASE_ENV = {"REQUIRE_AUTH": "false", "MAISTRO_DRY_RUN": "1"}

#: The front-matter key a note uses to record what it moved.
DELTA_KEY = "inventory-delta"


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

#: Keyed by suite path. Every baseline entry and every delta must name one of
#: these — an unrecognized suite is an error, not a silent skip, otherwise
#: recording a count for it would appear to be gated when it is not.
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
    # workflow executes which part is documented in SUITE-INVENTORY.md.
    "tests/": Recipe(args=[]),
    "formal/": Recipe(args=[], pythonpath=["packages/maistro-core/src", *_EVOLVE_RSI]),
    # Trap 1 — bare python, never uv.
    "packages/hive-conductor/backend/tests": Recipe(args=[], bare_python=True),
    "packages/hive-conductor/tests/e2e": Recipe(args=[], bare_python=True),
}

COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected")
ERROR_RE = re.compile(r"(\d+)\s+errors?\b")

#: `  packages/maistro-core/tests: +12` — one delta line inside the front matter.
DELTA_LINE_RE = re.compile(r"^(\s+)([^:]+):\s*([+-]?\d+)\s*$")


class LedgerError(Exception):
    """A recorded number could not be read. Never silently skipped."""


# --------------------------------------------------------------------------
# the ledger: baseline + per-change deltas
# --------------------------------------------------------------------------


def load_baseline() -> tuple[dict[str, int], list[str]]:
    """Return ``(counts, folded_note_slugs)`` from ``baseline.json``."""
    if not BASELINE.is_file():
        raise LedgerError(f"{BASELINE.relative_to(REPO_ROOT)} is missing")
    try:
        doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"{BASELINE.relative_to(REPO_ROOT)} is not valid JSON: {exc}") from exc

    counts = doc.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise LedgerError(f"{BASELINE.relative_to(REPO_ROOT)} has no non-empty `counts` object")
    for suite, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise LedgerError(f"baseline count for `{suite}` is not an integer: {value!r}")

    folded = doc.get("folded", [])
    if not isinstance(folded, list) or any(not isinstance(s, str) for s in folded):
        raise LedgerError(f"{BASELINE.relative_to(REPO_ROOT)} `folded` must be a list of strings")
    return dict(counts), list(folded)


def split_front_matter(text: str) -> tuple[list[str], list[str]]:
    """Return ``(front_matter_lines, body_lines)``; front matter may be empty.

    Only a block delimited by ``---`` on the very first line counts, matching
    the ADR/spec convention used everywhere else in this repository.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1 :]
    raise LedgerError("front matter opens with `---` but is never closed")


def parse_delta(text: str, where: str) -> dict[str, int]:
    """Read a note's ``inventory-delta`` block.

    A note with no front matter, or front matter without the key, records no
    delta — that is the normal case for a change that moved no count, and for
    every note written before ADR-082526-547c. A block that is *present but
    unreadable* raises: a delta the gate cannot parse would otherwise silently
    become zero, which is exactly the kind of quiet wrong number this file
    exists to prevent.
    """
    try:
        front, _body = split_front_matter(text)
    except LedgerError as exc:
        raise LedgerError(f"{where}: {exc}") from exc
    if not front:
        return {}

    delta: dict[str, int] = {}
    inside = False
    for line in front:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            # A top-level key ends any block we were reading.
            inside = line.split(":", 1)[0].strip() == DELTA_KEY
            if inside and line.split(":", 1)[1].strip():
                raise LedgerError(
                    f"{where}: `{DELTA_KEY}:` must be followed by an indented "
                    f"`<suite>: <±count>` block, not a value on the same line"
                )
            continue
        if not inside:
            continue
        m = DELTA_LINE_RE.match(line)
        if not m:
            raise LedgerError(
                f"{where}: cannot read `{line.strip()}` as `<suite>: <±count>` under `{DELTA_KEY}:`"
            )
        suite, raw = m.group(2).strip(), m.group(3)
        if suite in delta:
            raise LedgerError(f"{where}: `{suite}` appears twice under `{DELTA_KEY}:`")
        delta[suite] = int(raw)
    return delta


def note_files() -> list[Path]:
    """Every note, sorted, excluding the directory's own README."""
    return sorted(p for p in NOTES.glob("*.md") if p.name != "README.md")


def load_deltas(folded: list[str]) -> dict[str, dict[str, int]]:
    """Return ``{note_slug: delta}`` for every note not already folded in."""
    already = set(folded)
    out: dict[str, dict[str, int]] = {}
    for path in note_files():
        slug = path.stem
        if slug in already:
            continue
        delta = parse_delta(
            path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix()
        )
        if delta:
            out[slug] = delta
    return out


def expected_counts() -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Return ``(expected_per_suite, contributing_deltas)``.

    Raises ``LedgerError`` if any recorded suite has no collection recipe. An
    expected count for a suite nothing collects is a number that can never be
    checked, which reads as coverage and is not.
    """
    counts, folded = load_baseline()
    deltas = load_deltas(folded)

    recorded = set(counts) | {suite for delta in deltas.values() for suite in delta}
    if unknown := sorted(recorded - set(RECIPES)):
        raise LedgerError(
            "recorded suites with no collection recipe in "
            f"{Path(__file__).name}: {', '.join(unknown)}\n"
            "       Add each to RECIPES so it is actually gated."
        )

    expected = dict(counts)
    for delta in deltas.values():
        for suite, moved in delta.items():
            expected[suite] = expected.get(suite, 0) + moved
    return expected, deltas


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# writing this change's delta
# --------------------------------------------------------------------------


def default_note_slug() -> str | None:
    """Derive a note name from the current branch, or ``None`` if we cannot.

    The branch is the one identifier that is unique per change and available
    without asking, which is what keeps two PRs off the same path.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    branch = proc.stdout.strip()
    if proc.returncode != 0 or not branch or branch == "HEAD":
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")
    return slug or None


def render_delta_block(delta: dict[str, int]) -> list[str]:
    """The front-matter lines recording ``delta``."""
    return [f"{DELTA_KEY}:"] + [f"  {suite}: {moved:+d}" for suite, moved in sorted(delta.items())]


def write_note_delta(path: Path, delta: dict[str, int]) -> None:
    """Create or rewrite ``path``'s ``inventory-delta`` block, keeping its prose.

    Only the block is replaced. Any other front-matter key, and the whole body,
    survive untouched — a note is a person's explanation with a number attached,
    not a generated file.
    """
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        front, body = split_front_matter(text)
    else:
        front, body = (
            [],
            [
                f"# {path.stem}",
                "",
                "<!-- Say what moved and why, not just how much. The count alone hides",
                "     compensating changes; that is the case these notes exist for. -->",
                "",
            ],
        )

    kept: list[str] = []
    inside = False
    for line in front:
        if line and not line[0].isspace():
            inside = line.split(":", 1)[0].strip() == DELTA_KEY
        if not inside:
            kept.append(line)

    new_front = render_delta_block(delta) + kept if delta else kept
    out = (["---", *new_front, "---"] if new_front else []) + body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# other doc-shape checks this gate already owned
# --------------------------------------------------------------------------


def notes_problems() -> list[str]:
    """Check the notes directory the inventory points at is actually there.

    The prose explaining *why* a count moved lives in ``inventory-notes/``
    rather than in the inventory itself, because a shared prose block made
    every test-adding branch conflict with every other one (#208). Since
    ADR-082526-547c the same files also carry the numbers. That split only
    works while the pointer and the directory agree, so a rename or an
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


def render_table(expected: dict[str, int]) -> str:
    """A human-readable rendering of the current expected counts."""
    width = max(len(s) for s in expected)
    rows = [f"{'suite'.ljust(width)}  node IDs", f"{'-' * width}  --------"]
    rows += [
        f"{suite.ljust(width)}  {expected[suite]:>8}" for suite in RECIPES if suite in expected
    ]
    rows.append(f"{'total'.ljust(width)}  {sum(expected.values()):>8}")
    return "\n".join(rows)


def compact(expected: dict[str, int], deltas: dict[str, dict[str, int]]) -> int:
    """Fold every outstanding delta into the baseline; return how many."""
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    doc["counts"] = {suite: expected[suite] for suite in RECIPES if suite in expected}
    doc["folded"] = sorted(set(doc.get("folded", [])) | set(deltas))
    BASELINE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return len(deltas)


def run_checks(
    suites: list[str], expected: dict[str, int]
) -> tuple[list[tuple[str, int, int]], list[str]]:
    """Collect each suite and compare. Returns ``(drift, collection_failures)``.

    The two are kept apart deliberately. Drift is a number that moved and may
    well be intentional; a collection failure is a suite that did not run at
    all, and recording a delta for it would bank the breakage as the new truth.
    """
    drift: list[tuple[str, int, int]] = []
    failures: list[str] = []
    for suite in suites:
        try:
            actual, _cmd = collect(suite, RECIPES[suite])
        except RuntimeError as exc:
            failures.append(str(exc))
            print(f"ERROR  {suite}", file=sys.stderr)
            continue
        if actual == expected[suite]:
            print(f"ok     {suite}: {actual}")
            continue
        drift.append((suite, expected[suite], actual))
        print(f"DRIFT  {suite}: expected {expected[suite]}, collected {actual}")
    return drift, failures


def record_delta(
    note: str | None,
    drift: list[tuple[str, int, int]],
    deltas: dict[str, dict[str, int]],
) -> int:
    """Write this change's delta into its own note. Returns an exit code."""
    slug = note or default_note_slug()
    if not slug:
        print(
            "error: could not derive a note name from the current branch; pass --note <slug>",
            file=sys.stderr,
        )
        return 2
    path = NOTES / f"{slug}.md"
    # This note's delta is whatever makes the sum come out right, so re-running
    # --update after a base move is idempotent rather than cumulative.
    mine = dict(deltas.get(slug, {}))
    for suite, was, now in drift:
        mine[suite] = mine.get(suite, 0) + (now - was)
    write_note_delta(path, {s: v for s, v in mine.items() if v})
    print(
        f"\nrecorded {len(drift)} delta(s) in {path.relative_to(REPO_ROOT)}\n"
        "Write the prose too — the number alone hides compensating changes."
    )
    return 0


def ledger_only_mode(
    args: argparse.Namespace,
    expected: dict[str, int],
    deltas: dict[str, dict[str, int]],
) -> int | None:
    """Handle the modes that read or fold the ledger without collecting anything.

    Returns an exit code if one of them ran, ``None`` to carry on to the check.
    """
    if args.show:
        print(render_table(expected))
        if deltas:
            print(f"\n{len(deltas)} unfolded delta note(s): {', '.join(sorted(deltas))}")
        return 0
    if args.compact:
        print(
            f"folded {compact(expected, deltas)} delta note(s) into "
            f"{BASELINE.relative_to(REPO_ROOT)}"
        )
        return 0
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", action="append", help="check only this suite path (repeatable)")
    ap.add_argument(
        "--update",
        action="store_true",
        help="record this change's delta in its own note, so no shared line is written",
    )
    ap.add_argument(
        "--note",
        help="note slug to record the delta under (default: derived from the git branch)",
    )
    ap.add_argument("--show", action="store_true", help="print the expected counts and exit")
    ap.add_argument(
        "--compact",
        action="store_true",
        help="fold outstanding deltas into baseline.json (deliberate maintenance)",
    )
    args = ap.parse_args()

    if problems := notes_problems():
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2

    try:
        expected, deltas = expected_counts()
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if (code := ledger_only_mode(args, expected, deltas)) is not None:
        return code

    wanted = set(args.suite) if args.suite else None
    if wanted and (missing := sorted(wanted - set(RECIPES))):
        print(f"error: no collection recipe for {missing}", file=sys.stderr)
        return 2
    suites = [s for s in RECIPES if s in expected and (wanted is None or s in wanted)]

    drift, failures = run_checks(suites, expected)

    if failures:
        print("\n".join(["", *failures]), file=sys.stderr)
        print(
            "\nOne or more suites failed to collect. That is a broken suite, not "
            "inventory drift — fix the collection error; do not update the inventory.",
            file=sys.stderr,
        )
        return 1

    if not drift:
        print(f"\nok: {len(suites)} suite(s) match the recorded inventory")
        return 0

    if args.update:
        return record_delta(args.note, drift, deltas)

    total = sum(a - r for _, r, a in drift)
    print(
        "\n"
        f"FAIL: {len(drift)} suite(s) drifted from the recorded inventory "
        f"(net {total:+d} node IDs).\n"
        "\n"
        "If you added or removed tests on purpose, this is expected — record the\n"
        "delta in your own note and commit it with your change:\n"
        "\n"
        "    python3 scripts/check-suite-inventory.py --update\n"
        "\n"
        "That writes docs/testing/inventory-notes/<your-branch>.md and touches no\n"
        "shared line, so it cannot conflict with another branch doing the same.\n"
        "\n"
        "If you did NOT change any test, a suite has silently stopped collecting\n"
        "(conftest import error, moved directory, changed testpaths). Investigate\n"
        "before recording anything — the number is the alarm, not the bug.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
