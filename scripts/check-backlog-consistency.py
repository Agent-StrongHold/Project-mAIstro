#!/usr/bin/env python3
"""Keep root BACKLOG.md internally consistent and honest about its references (#30).

`BACKLOG.md` is the hand-maintained work-source of record until the database
backlog is live (#50), and it is read by agents as well as people. That makes
two failure modes expensive: an item whose status is a word nobody defined, and
an item citing a decision that does not exist.

Both are checked here, and the vocabulary is read out of the file's own legend
tables rather than hard-coded. A legend and its usage therefore cannot drift
apart: adding a status to the table is what permits it on an item, and using one
that is not in the table fails. Hard-coding the list here would just move the
drift into this script.

What is deliberately *not* checked: whether an item's status matches the front
matter of the ADR it cites. The backlog records the work; the ADR records the
decision, and the two legitimately differ (an Accepted decision can have
Proposed follow-up work). ADR status has its own authority in registry CI.

Run: `python scripts/check-backlog-consistency.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "BACKLOG.md"
ADR_DIR = ROOT / "docs" / "adr"
SPEC_DIR = ROOT / "docs" / "specs"

#: `**[engine-001] Title — Status[; `gap-x`] — milestone**`, with the id allowing
#: the `[turing-030..034]` range form used for a batch of sibling items.
_ITEM = re.compile(
    r"^\*\*\[(?P<prefix>[a-z]+)-(?P<number>\d+(?:\.\.\d+)?)\]\s+"
    r"(?P<title>.+?)\s+—\s+(?P<state>[^—*]+?)\s*(?:—\s*(?P<milestone>[^*]+?))?\*\*"
)
_ITEM_LINE = re.compile(r"^\*\*\[[a-z]+-\d")
_TABLE_ROW = re.compile(r"^\|\s*`?([^`|]+?)`?\s*\|")
_PREFIX_BULLET = re.compile(r"^- `([a-z]+)-NNN`")

#: An item reference like `[engine-012]` — how one backlog item names another.
_ITEM_REF = re.compile(r"\[((?:[a-z]+)-\d+)\]")
_DECISION = re.compile(r"\b(?:ADR|SPEC)-\d[0-9A-Za-z]*(?:-[0-9a-f]{4})?")


def _section_terms(text: str, heading: str) -> set[str]:
    """First-column values of the markdown table under `heading`."""
    start = text.find(heading)
    if start < 0:
        raise SystemExit(f"BACKLOG.md: no '{heading}' section")
    terms: set[str] = set()
    for line in text[start + len(heading) :].splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and terms:
            break
        match = _TABLE_ROW.match(stripped)
        if not match:
            continue
        value = match.group(1).strip()
        if value and value != "Marker" and set(value) - {"-", ":"}:
            terms.add(value)
    return terms


def _prefixes(text: str) -> set[str]:
    return {m.group(1) for m in (_PREFIX_BULLET.match(line) for line in text.splitlines()) if m}


def _decision_exists(identifier: str) -> bool:
    directory = ADR_DIR if identifier.startswith("ADR-") else SPEC_DIR
    return (
        any(path.name.startswith(f"{identifier}-") for path in directory.glob("*.md"))
        or (directory / f"{identifier}.md").exists()
    )


def _state_failures(item_id: str, state: str, statuses: set[str], gaps: set[str]) -> list[str]:
    """Split `Status[; \\`gap-marker\\`]` and check each half against its legend."""
    status, _, gap = state.partition(";")
    failures: list[str] = []
    if status.strip() not in statuses:
        failures.append(
            f"{item_id}: status {status.strip()!r} is not in the status legend "
            f"({', '.join(sorted(statuses))})"
        )
    marker = gap.strip().strip("`")
    if marker and marker not in gaps:
        failures.append(f"{item_id}: gap marker {marker!r} is not in the gap legend")
    return failures


def audit(text: str) -> list[str]:
    statuses = _section_terms(text, "## Work status legend")
    gaps = _section_terms(text, "## Gap legend")
    prefixes = _prefixes(text)
    failures: list[str] = []
    if not statuses or not gaps or not prefixes:
        return ["BACKLOG.md: status legend, gap legend and id-prefix list must all be non-empty"]

    seen: set[str] = set()
    for line in text.splitlines():
        if not _ITEM_LINE.match(line):
            continue
        match = _ITEM.match(line)
        if match is None:
            failures.append(f"unparsable item header: {line[:80]}")
            continue
        item_id = f"{match.group('prefix')}-{match.group('number')}"
        if item_id in seen:
            failures.append(f"{item_id}: duplicate item id")
        seen.add(item_id)
        if match.group("prefix") not in prefixes:
            failures.append(
                f"{item_id}: prefix {match.group('prefix')!r} is not one of the documented "
                f"id prefixes ({', '.join(sorted(prefixes))})"
            )
        failures.extend(_state_failures(item_id, match.group("state"), statuses, gaps))

    for identifier in sorted(set(_DECISION.findall(text))):
        if not _decision_exists(identifier):
            failures.append(f"cites {identifier}, which is not in docs/adr or docs/specs")

    failures.extend(_dangling_item_references(text, seen))
    return failures


def _dangling_item_references(text: str, defined: set[str]) -> list[str]:
    """Item references that name an item this file never defines (#30).

    An item's dependencies are the part of it this repository can act on — the
    `sh-` header says exactly that. A reference to an id that does not exist
    reads as a recorded prerequisite while pointing at nothing, which is worse
    than recording none: the first says the dependency is known and tracked.

    The ids of range-form items (`[turing-030..034]`) are expanded, because a
    reference to any member of the range is legitimate.
    """
    expanded = set(defined)
    for base, upper in re.findall(r"(?m)^\*\*\[([a-z]+-\d+)\.\.(\d+)\]", text):
        prefix, low = base.rsplit("-", 1)
        for number in range(int(low), int(upper) + 1):
            expanded.add(f"{prefix}-{number:0{len(low)}d}")

    return [
        f"references [{reference}], which is not an item defined in this file"
        for reference in sorted(set(_ITEM_REF.findall(text)))
        if reference not in expanded
    ]


def main() -> int:
    if not BACKLOG.exists():
        print(f"FAIL: {BACKLOG} is missing", file=sys.stderr)
        return 1
    text = BACKLOG.read_text()
    failures = audit(text)
    if failures:
        print("FAIL: BACKLOG.md is inconsistent with its own legends\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nAdd the term to the legend if it is meant to exist, or fix the item. The legend "
            "is the vocabulary; an item cannot invent one."
        )
        return 1
    items = sum(1 for line in text.splitlines() if _ITEM_LINE.match(line))
    print(f"OK: {items} backlog items parse, and every status, gap marker and citation resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
