#!/usr/bin/env python3
"""`ADR-INDEX.md` may not disagree with the ADR corpus (#379).

The index was excluded from registry validation, and 32 of its 82 rows carried
a status the ADR's own front matter contradicted — every one of them saying
`Proposed` about a decision that had since been Accepted, Deferred, Deprecated
or Superseded. That inverts the signal the index exists to carry: a reader
scanning it for what has been ratified was being told the opposite.

**Front matter is canonical.** #379 says so, and it is the defensible choice
independently: the front matter is what the lifecycle machine, the AC ladder
and the citation gate all read, so an index that disagreed would be the only
disagreeing copy. This regenerates the derived columns from it rather than
asking a human to keep two records in step by hand.

**Only the derived columns.** `Summary` is reviewed prose and `Ver` and
`Last Modified` come from git, not from front matter; none of them is touched.
That is the "preserves reviewed annotations outside generated regions"
requirement, and it is why this rewrites cells rather than regenerating the
file.

Run: python scripts/check-adr-index.py
Fix: python scripts/check-adr-index.py --fix
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "maistro-registry" / "src"))

from maistro_registry.validator import validate_file  # noqa: E402

INDEX = ROOT / "docs" / "adr" / "ADR-INDEX.md"
ADR_DIR = ROOT / "docs" / "adr"

#: `| ADR-020 | v2 | Proposed | 2026-05-30 | — | ... | summary |`
ROW = re.compile(
    r"^\|\s*(?P<id>ADR-[A-Za-z0-9-]+)\s*\|(?P<ver>[^|]*)\|(?P<status>[^|]*)\|"
    r"(?P<created>[^|]*)\|(?P<accepted>[^|]*)\|(?P<rest>.*)$"
)

#: The legend's marker for "no `accepted:` field, so the created date stands in".
PROXY = "†"

#: What an empty date cell looks like in this table.
ABSENT = "—"

#: Statuses that mean a decision has been ratified, and so should carry an
#: accepted date even if only by proxy.
RATIFIED = {"Accepted", "Implemented", "Superseded", "Deprecated"}


@dataclass(frozen=True)
class IndexProblem:
    adr_id: str
    field_name: str
    index_says: str
    front_matter_says: str

    def render(self) -> str:
        return (
            f"{self.adr_id}: index {self.field_name}={self.index_says!r} "
            f"but front matter says {self.front_matter_says!r}"
        )


def _front_matter() -> dict[str, object]:
    found: dict[str, object] = {}
    for path in sorted(ADR_DIR.glob("*.md")):
        if path.name == INDEX.name:
            continue
        result = validate_file(path)
        front_matter = getattr(result, "front_matter", None)
        if front_matter is not None:
            found[front_matter.id] = front_matter
    return found


def _expected_accepted(front_matter: object) -> str:
    """What the Accepted cell should read, honouring the legend's `†` proxy."""
    accepted = getattr(front_matter, "accepted", None)
    if accepted is not None:
        return str(accepted)
    if front_matter.status.value in RATIFIED:
        return f"{front_matter.created}{PROXY}"
    return ABSENT


def audit() -> tuple[list[IndexProblem], list[str]]:
    """Returns (disagreements, structural errors)."""
    corpus = _front_matter()
    problems: list[IndexProblem] = []
    structural: list[str] = []
    seen: set[str] = set()

    for line in INDEX.read_text().splitlines():
        match = ROW.match(line)
        if match is None:
            continue
        adr_id = match["id"]
        if adr_id in seen:
            structural.append(f"{adr_id}: appears in the index more than once")
            continue
        seen.add(adr_id)

        front_matter = corpus.get(adr_id)
        if front_matter is None:
            structural.append(f"{adr_id}: indexed but no ADR file carries that id")
            continue

        status = match["status"].strip()
        expected_status = front_matter.status.value
        if status != expected_status:
            problems.append(IndexProblem(adr_id, "status", status, expected_status))

        created = match["created"].strip()
        expected_created = str(front_matter.created)
        if created != expected_created:
            problems.append(IndexProblem(adr_id, "created", created, expected_created))

        accepted = match["accepted"].strip()
        expected_accepted = _expected_accepted(front_matter)
        if accepted != expected_accepted:
            problems.append(IndexProblem(adr_id, "accepted", accepted, expected_accepted))

    return problems, structural


def rewrite() -> int:
    """Rewrite only the derived cells, leaving Summary/Ver/Last Modified alone."""
    corpus = _front_matter()
    changed = 0
    out: list[str] = []

    for line in INDEX.read_text().splitlines():
        match = ROW.match(line)
        front_matter = corpus.get(match["id"]) if match else None
        if match is None or front_matter is None:
            out.append(line)
            continue

        status = front_matter.status.value
        created = str(front_matter.created)
        accepted = _expected_accepted(front_matter)
        rebuilt = (
            f"| {match['id']} |{match['ver']}| {status} | {created} | {accepted} |{match['rest']}"
        )
        changed += rebuilt != line
        out.append(rebuilt)

    INDEX.write_text("\n".join(out) + "\n")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true", help="rewrite derived cells from front matter"
    )
    args = parser.parse_args(argv)

    if args.fix:
        changed = rewrite()
        print(f"rewrote {changed} row(s) in {INDEX.relative_to(ROOT)} from ADR front matter")
        return 0

    problems, structural = audit()
    if structural:
        print(f"FAIL: {len(structural)} structural problem(s) in {INDEX.relative_to(ROOT)}\n")
        for item in structural:
            print(f"  {item}")
        return 1
    if problems:
        print(f"FAIL: {len(problems)} index row(s) disagree with ADR front matter\n")
        for problem in problems:
            print(f"  {problem.render()}")
        print(
            "\nFront matter is canonical (#379). Run "
            "`python scripts/check-adr-index.py --fix` to regenerate the derived columns, "
            "or correct the ADR's own front matter if the index was right."
        )
        return 1

    print("OK: every ADR-INDEX row agrees with its ADR's front matter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
