#!/usr/bin/env python3
"""Fail when `@pytest.mark.contract` claims evidence that does not exist (#345).

See `check_contract_markers_impl` for what is measured and why it is a ledger
rather than a plain assertion. This is the entry point CI runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_contract_markers_impl import (  # noqa: E402
    BASELINE,
    ROOT,
    collect,
    compare,
    load_baseline,
    write_baseline,
)


def _report(label: str, lines: list[str]) -> None:
    """Print a bounded slice of one finding class, saying what it withheld."""
    if not lines:
        return
    print(f"\n{len(lines)} {label}:")
    for line in lines[:20]:
        print(f"  {line}")
    if len(lines) > 20:
        print(f"  ... and {len(lines) - 20} more")


def main(argv: list[str]) -> int:
    findings = collect(ROOT)
    if "--update" in argv:
        write_baseline(BASELINE, findings)
        print(f"wrote {BASELINE.relative_to(ROOT)} — review the diff before committing")
        return 0

    new, stale, unexplained = compare(findings, load_baseline(BASELINE))

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    print("contract-marker ledger:")
    for category in sorted(counts):
        print(f"  {category}: {counts[category]}")

    if not (new or stale or unexplained):
        print("\nOK: every contract claim is either evidenced or recorded with a reason.")
        return 0

    _report("NEW contract claim(s) with no evidence", [f.as_line() for f in new])
    _report("recorded entr(y/ies) no longer found — prune them", stale)
    _report("categor(y/ies) banked with no disposition", unexplained)
    if unexplained:
        print("'Banked' and 'explained' have to be the same act.")

    print(
        "\nADR-032 says a document claiming a contract kind has a test marked with "
        "that kind. Add the marker, correct the document, or bank a reviewed state "
        "with: scripts/check-contract-markers.py --update"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
