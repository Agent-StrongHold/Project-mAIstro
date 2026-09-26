#!/usr/bin/env python3
"""Governing citations must resolve to active authority (#374).

`python -m maistro_registry.cli lint` asks whether a cited document exists.
This asks the stronger question: does an *active* document rest its authority
on something that is not itself active — a Superseded ADR, a Deprecated one, or
a decision still merely Proposed.

Run:  python scripts/check-citation-status.py
Bank: python scripts/check-citation-status.py --update

The baseline is per-identity, like every other ledger here. A new violation
fails; a fixed one must shrink the ledger in the same change, because an entry
left behind after its defect is gone silently absorbs the next regression at
that same citation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "maistro-registry" / "src"))

from maistro_registry.citations import (  # noqa: E402
    CitationBaseline,
    CitationProblem,
    check_citations,
    check_governing_references,
)
from maistro_registry.schema import FrontMatter  # noqa: E402
from maistro_registry.validator import validate_file  # noqa: E402

LEDGER = ROOT / "quality" / "citation-baseline.json"
DOC_ROOTS = (ROOT / "docs" / "adr", ROOT / "docs" / "specs")
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"
MATRIX_MARKER = "<!-- matrix:disposition -->"
_DECISION_ID = re.compile(r"\b(?:ADR|SPEC)-[0-9][0-9A-Za-z-]*")

#: A note that names its own relation. Only these are exempt from the status
#: gate: ``(supersedes ADR-046)`` is a statement about the past, and ``(proposed
#: in ADR-123)`` points at where a decision is being worked out rather than
#: claiming its authority. A bare ``(ADR-002)`` asserts nothing, so the ID it
#: holds is read as exactly what the governing column says it is -- governing.
_HISTORICAL_NOTE = re.compile(
    r"\b(?:supersed\w*|historical|formerly|previously|replac\w+|proposed\s+in)\b",
    re.IGNORECASE,
)


def _parenthetical_notes(text: str) -> list[str]:
    """The balanced top-level parenthetical notes in one cell."""
    notes: list[str] = []
    depth = 0
    start: int | None = None
    for index, character in enumerate(text):
        if character == "(":
            if depth == 0:
                start = index
            depth += 1
        elif character == ")" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                notes.append(text[start + 1 : index])
    return notes


def _governing_ids(cell: str) -> list[str]:
    """Decision IDs the cell puts forward as authority.

    Every ID counts unless a note around it explicitly names a historical,
    supersession or provenance relation. Silently dropping IDs from an
    unqualified parenthetical would let a Proposed decision govern shipped
    behaviour from behind punctuation the gate never looks past.
    """
    visible = cell
    for note in _parenthetical_notes(cell):
        if _HISTORICAL_NOTE.search(note):
            visible = visible.replace(f"({note})", " ")
    return _DECISION_ID.findall(visible)


def _corpus() -> list[FrontMatter]:
    front_matters: list[FrontMatter] = []
    for root in DOC_ROOTS:
        for path in sorted(root.glob("*.md")):
            result = validate_file(path)
            front_matter = getattr(result, "front_matter", None)
            if front_matter is not None:
                front_matters.append(front_matter)
    return front_matters


def _matrix_references(text: str) -> list[tuple[str, str, str]]:
    """Read direct authorities from the matrix disposition table.

    An ID counts as governing unless it sits inside a note that names its own
    relation -- ``(supersedes ADR-046)``, ``(proposed in ADR-123)``. Bare
    parentheticals are not a hiding place: ``(ADR-002)`` is checked like any
    other authority. The disposition gate owns table shape and existence; this
    gate owns the status of each authority the cell puts forward.
    """
    start = text.find(MATRIX_MARKER)
    if start < 0:
        return []

    rows: list[list[str]] = []
    in_table = False
    for line in text[start:].splitlines():
        if not line.lstrip().startswith("|"):
            if in_table:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        in_table = True
        rows.append(cells)

    if len(rows) < 3:
        return []
    try:
        subsystem_column = rows[0].index("Subsystem")
        governing_column = rows[0].index("Governing ADR/spec")
    except ValueError:
        return []

    references: list[tuple[str, str, str]] = []
    for row in rows[2:]:
        if len(row) <= max(subsystem_column, governing_column):
            continue
        source = f"matrix#{row[subsystem_column]}"
        references.extend(
            (source, "governing", f"maistro-engine#{identifier}")
            for identifier in _governing_ids(row[governing_column])
        )
    return references


def _matrix_problems(front_matters: list[FrontMatter]) -> list[CitationProblem]:
    if not MATRIX.exists():
        return []
    return check_governing_references(_matrix_references(MATRIX.read_text()), front_matters)


def _display(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise.

    `relative_to` raises for a path outside the root, which is exactly what a
    test pointing the ledger at a temp directory produces -- a crash in the
    reporting line of an otherwise-successful run.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_baseline() -> CitationBaseline:
    if not LEDGER.exists():
        return CitationBaseline(entries=frozenset())
    payload = json.loads(LEDGER.read_text())
    return CitationBaseline(entries=frozenset(payload.get("known", [])))


def _write_baseline(problems: list[CitationProblem]) -> None:
    payload = {
        "_comment": (
            "Governing citations (`substrate`, `implements`) from an active document to "
            "authority that is not active. Reviewed, per-identity, and expected to shrink: "
            "each entry is a governance judgement someone still has to make. See #374."
        ),
        "known": sorted(f"{p.source}.{p.field_name} -> {p.target}" for p in problems),
        "reasons": {
            f"{p.source}.{p.field_name} -> {p.target}": p.reason
            for p in sorted(problems, key=lambda item: (item.source, item.field_name, item.target))
        },
    }
    LEDGER.write_text(json.dumps(payload, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    # Explicit rather than reaching into `sys.argv`, so the gate's own tests
    # can drive it in-process. A subprocess run proves it works and measures
    # none of it, and `scripts/` is a coverage producer here.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="bank the current state")
    args = parser.parse_args(argv)

    corpus = _corpus()
    problems = [
        *check_citations(corpus),
        *_matrix_problems(corpus),
    ]

    if args.update:
        _write_baseline(problems)
        print(f"wrote {_display(LEDGER)} with {len(problems)} known citation(s)")
        print("review the diff before committing — each entry is a governance judgement")
        return 0

    new, stale = _load_baseline().partition(problems)

    if new:
        print(f"FAIL: {len(new)} governing citation(s) do not resolve to active authority\n")
        for problem in new:
            print(f"  {problem.render()}")
        print(
            "\nA governing citation (`substrate`, `implements`) from an active document "
            "must name an Accepted or Implemented decision. Cite the active replacement, "
            "accept the decision, or move the reference to `related` if it is historical."
        )
        return 1

    if stale:
        print(f"FAIL: {len(stale)} baseline entr(y/ies) no longer found — prune them\n")
        for entry in stale:
            print(f"  {entry}")
        print(
            "\nA fixed citation must shrink the ledger in the same change; a stale entry "
            "silently absorbs the next regression at that citation."
        )
        return 1

    print(
        f"OK: every governing citation resolves to active authority, "
        f"or is one of {len(_load_baseline().entries)} reviewed known exception(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
