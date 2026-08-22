#!/usr/bin/env python3
"""Every unreachable module must have one disposition and one owner (#33).

`quality/reachability-baseline.json` records *that* a module is unreachable.
This gate records *what is to be done about it*: CONNECT, LIBRARY, or RETIRE,
grouped by coherent subsystem in `quality/reachability-dispositions.json`.

Without this pairing the baseline is a list of 207 unexplained facts, and the
reachability ratchet degrades into a number people learn to ignore. With it,
every entry carries a decision and the evidence for it, and the two files cannot
drift: a module added to the baseline with no disposition fails, and a
disposition for a module that has become reachable fails until it is pruned.

The per-disposition requirements are what stop a row from being a shrug:

- CONNECT must name the `root` that would reach the module. "Someone should wire
  this" is not a disposition; naming the entry point makes it checkable work.
- RETIRE must name what `replaced_by` it. A deletion with no successor is either
  a mistake or a capability being dropped, and both deserve to be said out loud.
  RETIRE is a decision, not permission to delete -- parity comes first (#35).
- LIBRARY must justify itself in prose, because "it's a library" is the excuse
  that would otherwise absorb every unreachable module in a published package.

`subsystem` must be a row in the convergence matrix, so the two M0 artifacts
cannot disagree about what a subsystem is.

Run: `python scripts/check-reachability-dispositions.py`
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "reachability-baseline.json"
LEDGER = ROOT / "quality" / "reachability-dispositions.json"
MATRIX_CHECKER = ROOT / "scripts" / "check-convergence-matrix.py"
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"

#: Required supporting field per disposition. LIBRARY needs only its rationale.
REQUIRED_FIELD = {"CONNECT": "root", "RETIRE": "replaced_by", "LIBRARY": None}


def matrix_subsystems() -> set[str]:
    """Subsystem names from the convergence matrix's ownership table."""
    spec = importlib.util.spec_from_file_location("_matrix", MATRIX_CHECKER)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {MATRIX_CHECKER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_matrix"] = module
    spec.loader.exec_module(module)
    rows = module.parse_table(MATRIX.read_text(), module.OWNERSHIP_MARKER)
    return {row[0] for row in rows[1:]}


def _shape_failures(group: dict[str, Any], gid: str, subsystems: set[str]) -> list[str]:
    """Whether the row itself is well formed, independent of the baseline."""
    failures: list[str] = []
    disposition = group.get("disposition")
    if disposition not in REQUIRED_FIELD:
        failures.append(
            f"{gid}: disposition {disposition!r} is not one of {', '.join(sorted(REQUIRED_FIELD))}"
        )
    else:
        required = REQUIRED_FIELD[disposition]
        if required and not str(group.get(required, "")).strip():
            failures.append(f"{gid}: {disposition} requires a non-empty '{required}'")
    if not str(group.get("rationale", "")).strip():
        failures.append(f"{gid}: needs a rationale")
    subsystem = group.get("subsystem")
    if subsystem not in subsystems:
        failures.append(f"{gid}: subsystem {subsystem!r} is not a row in CONVERGENCE-MATRIX.md")
    return failures


def _module_failures(
    group: dict[str, Any], gid: str, baseline: set[str], seen: dict[str, str]
) -> list[str]:
    """Whether the row's modules line up with the baseline. Mutates `seen`."""
    modules = group.get("modules")
    if not isinstance(modules, list) or not modules:
        return [f"{gid}: names no modules"]
    failures: list[str] = []
    for module in modules:
        if module in seen:
            failures.append(f"{module}: claimed by both {seen[module]} and {gid}")
        seen[module] = gid
        if module not in baseline:
            failures.append(
                f"{gid}: {module} is not in the reachability baseline — it became "
                f"reachable, or was never unreachable; prune the disposition"
            )
    return failures


def audit(ledger: dict[str, Any], baseline: set[str], subsystems: set[str]) -> list[str]:
    """Every way the ledger and the baseline disagree, named."""
    groups = ledger.get("groups")
    if not isinstance(groups, list) or not groups:
        return ["ledger has no 'groups' list"]

    failures: list[str] = []
    seen: dict[str, str] = {}
    ids: set[str] = set()
    for group in groups:
        gid = str(group.get("id", "<unnamed>"))
        if gid in ids:
            failures.append(f"{gid}: duplicate group id")
        ids.add(gid)
        failures.extend(_shape_failures(group, gid, subsystems))
        failures.extend(_module_failures(group, gid, baseline, seen))

    unclassified = sorted(baseline - set(seen))
    if unclassified:
        shown = ", ".join(unclassified[:10])
        more = f" (+{len(unclassified) - 10} more)" if len(unclassified) > 10 else ""
        failures.append(
            f"{len(unclassified)} unreachable module(s) have no disposition: {shown}{more}"
        )
    return failures


def main() -> int:
    for path in (BASELINE, LEDGER):
        if not path.exists():
            print(f"FAIL: {path} is missing", file=sys.stderr)
            return 1
    baseline = set(json.loads(BASELINE.read_text())["unreachable"])
    ledger = json.loads(LEDGER.read_text())
    failures = audit(ledger, baseline, matrix_subsystems())

    if failures:
        print(f"FAIL: {LEDGER.relative_to(ROOT)} does not account for the baseline\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nEvery unreachable module needs one disposition and one owner. Add the module to "
            "a group, or prune the group entry if the module is now reachable."
        )
        return 1

    counts: dict[str, int] = {}
    for group in ledger["groups"]:
        counts[group["disposition"]] = counts.get(group["disposition"], 0) + len(group["modules"])
    summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    print(
        f"OK: {len(ledger['groups'])} groups give all {len(baseline)} unreachable modules a "
        f"disposition ({summary})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
