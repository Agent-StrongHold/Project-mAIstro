#!/usr/bin/env python3
"""Keep the Architecture Convergence Matrix honest against the code it describes.

`docs/architecture/CONVERGENCE-MATRIX.md` is the M0 planning surface: one row per
subsystem, saying who owns its lifecycle, persistence and authorization today, and
whether it is KEEP / MIGRATE / RETIRE / CONNECT / LIBRARY. A planning surface that
drifts is worse than none — it launders stale assumptions as current architecture.
So the matrix is checked, not trusted:

1. The two tables describe the same subsystems, in the same order.
2. The module prefixes partition **every** production module. Longest prefix wins,
   so a new subsystem package cannot land unclassified and no module is counted
   twice. This is what makes "covers every significant subsystem" verifiable
   rather than asserted.
3. Each row's unreachable count is recomputed from the same import graph
   `check-reachability.py` ratchets, so the matrix cannot claim a subsystem is
   wired when the reachability gate says otherwise.
4. Every disposition comes from the fixed vocabulary.
5. Every ADR/SPEC id cited resolves to a file in `docs/adr` or `docs/specs`, so a
   row cannot point at a decision that does not exist.

Run: `python scripts/check-convergence-matrix.py`
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
ADR_DIR = ROOT / "docs" / "adr"
SPEC_DIR = ROOT / "docs" / "specs"

OWNERSHIP_MARKER = "<!-- matrix:ownership -->"
DISPOSITION_MARKER = "<!-- matrix:disposition -->"

DISPOSITIONS = frozenset({"KEEP", "MIGRATE", "RETIRE", "CONNECT", "LIBRARY"})
_DISPOSITION_COLUMNS = ("Unreachable", "Disposition", "Governing ADR/spec")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_DECISION_ID = re.compile(r"\b(ADR|SPEC)-[0-9][0-9A-Za-z-]*")
_UNREACHABLE_CELL = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def _load_reachability() -> object:
    """Import `check-reachability.py` by path — its filename is not an identifier."""
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


def production_modules() -> list[str]:
    """Every production module name, as the reachability gate reports it."""
    reach = _load_reachability()
    collected = reach._collect_modules()  # type: ignore[attr-defined]
    return sorted(
        reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        for key in collected
    )


def unreachable_modules() -> set[str]:
    baseline = json.loads((ROOT / "quality" / "reachability-baseline.json").read_text())
    return set(baseline["unreachable"])


def parse_table(text: str, marker: str) -> list[list[str]]:
    """Rows of the markdown table that follows `marker`, header and rule dropped."""
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"{MATRIX}: missing marker {marker}")
    rows: list[list[str]] = []
    for line in text[start + len(marker) :].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        raise SystemExit(f"{MATRIX}: no table body after {marker}")
    return rows


def _matches(module: str, prefix: str) -> bool:
    """Whether `prefix` owns `module`, across all three identity shapes.

    `.` for packages, `::` for a flat app's scoped modules, and `/` for repo
    tooling, whose identity is its path (`scripts/check-ac-state.py`) because
    the file name is not a legal dotted identifier (ADR-082526-aef8).
    """
    return (
        module == prefix
        or module.startswith(f"{prefix}.")
        or module.startswith(f"{prefix}::")
        or module.startswith(f"{prefix}/")
    )


def _assign(modules: list[str], prefixes: dict[str, str]) -> dict[str, str]:
    """Map each module to its owning row by longest matching prefix.

    Longest-prefix-wins is what lets a row own `maistro.graph` while another owns
    the whole-repo fallback: specificity decides, so adding a subsystem row never
    silently re-parents modules that a broader row already covers.
    """
    owners: dict[str, str] = {}
    for module in modules:
        hits = [(len(prefix), row) for prefix, row in prefixes.items() if _matches(module, prefix)]
        if not hits:
            continue
        best = max(length for length, _ in hits)
        winners = {row for length, row in hits if length == best}
        if len(winners) > 1:
            raise SystemExit(
                f"{MATRIX}: module {module} is claimed by {len(winners)} rows at the same "
                f"prefix length: {', '.join(sorted(winners))}"
            )
        owners[module] = winners.pop()
    return owners


def _decision_ids(cell: str) -> list[str]:
    return [match.group(0) for match in _DECISION_ID.finditer(cell)]


def _decision_exists(identifier: str) -> bool:
    directory = ADR_DIR if identifier.startswith("ADR-") else SPEC_DIR
    return (
        any(path.name.startswith(f"{identifier}-") for path in directory.glob("*.md"))
        or (directory / f"{identifier}.md").exists()
    )


def audit(
    text: str,
    modules: list[str],
    unreachable: set[str],
    *,
    decision_exists: Callable[[str], bool] = _decision_exists,
) -> list[str]:
    """Every way the matrix disagrees with the code, named. Empty means clean."""
    ownership = parse_table(text, OWNERSHIP_MARKER)
    disposition = parse_table(text, DISPOSITION_MARKER)
    failures: list[str] = []

    own_header, own_rows = ownership[0], ownership[1:]
    dis_header, dis_rows = disposition[0], disposition[1:]
    for header, label in ((own_header, "ownership"), (dis_header, "disposition")):
        if header[0] != "Subsystem":
            failures.append(f"{label} table: first column must be 'Subsystem', got {header[0]!r}")

    own_keys = [row[0] for row in own_rows]
    dis_keys = [row[0] for row in dis_rows]
    if own_keys != dis_keys:
        only_own = [key for key in own_keys if key not in set(dis_keys)]
        only_dis = [key for key in dis_keys if key not in set(own_keys)]
        if only_own:
            failures.append(f"rows in the ownership table only: {', '.join(only_own)}")
        if only_dis:
            failures.append(f"rows in the disposition table only: {', '.join(only_dis)}")
        if not only_own and not only_dis:
            failures.append("both tables list the same subsystems in a different order")

    if "Modules" not in own_header:
        return [*failures, "ownership table has no 'Modules' column"]
    missing = [name for name in _DISPOSITION_COLUMNS if name not in dis_header]
    if missing:
        return [*failures, f"disposition table is missing column(s): {', '.join(missing)}"]

    prefixes, prefix_failures = _prefixes(own_rows, own_header.index("Modules"))
    failures.extend(prefix_failures)
    owners = _assign(modules, prefixes)
    failures.extend(_partition_failures(modules, prefixes, own_keys, owners))
    failures.extend(_row_failures(dis_header, dis_rows, owners, unreachable, decision_exists))
    return failures


def _prefixes(rows: list[list[str]], column: int) -> tuple[dict[str, str], list[str]]:
    prefixes: dict[str, str] = {}
    failures: list[str] = []
    for row in rows:
        found = _CODE_SPAN.findall(row[column])
        if not found:
            failures.append(f"{row[0]}: Modules cell names no `module.prefix`")
        for prefix in found:
            if prefix in prefixes:
                failures.append(
                    f"prefix `{prefix}` is claimed by both {prefixes[prefix]} and {row[0]}"
                )
            prefixes[prefix] = row[0]
    return prefixes, failures


def _partition_failures(
    modules: list[str], prefixes: dict[str, str], keys: list[str], owners: dict[str, str]
) -> list[str]:
    failures: list[str] = []
    unclassified = [module for module in modules if module not in owners]
    if unclassified:
        shown = ", ".join(unclassified[:10])
        more = f" (+{len(unclassified) - 10} more)" if len(unclassified) > 10 else ""
        failures.append(
            f"{len(unclassified)} production module(s) match no matrix row: {shown}{more}"
        )
    for prefix, row in sorted(prefixes.items()):
        if not any(_matches(module, prefix) for module in modules):
            failures.append(f"{row}: prefix `{prefix}` matches no production module")
    claimed = set(owners.values())
    failures.extend(f"{key}: owns no production module" for key in keys if key not in claimed)
    return failures


def _row_failures(
    header: list[str],
    rows: list[list[str]],
    owners: dict[str, str],
    unreachable: set[str],
    decision_exists: Callable[[str], bool],
) -> list[str]:
    totals: dict[str, int] = {}
    misses: dict[str, int] = {}
    for module, subsystem in owners.items():
        totals[subsystem] = totals.get(subsystem, 0) + 1
        misses[subsystem] = misses.get(subsystem, 0) + (module in unreachable)

    unreachable_column = header.index("Unreachable")
    disposition_column = header.index("Disposition")
    governing_column = header.index("Governing ADR/spec")

    failures: list[str] = []
    for row in rows:
        key = row[0]
        spans = _CODE_SPAN.findall(row[unreachable_column])
        match = _UNREACHABLE_CELL.match(spans[0]) if spans else None
        if match is None:
            failures.append(f"{key}: Unreachable cell must be `<unreachable>/<total>`")
        elif key in totals:
            stated = (int(match.group(1)), int(match.group(2)))
            actual = (misses[key], totals[key])
            if stated != actual:
                failures.append(
                    f"{key}: Unreachable says {stated[0]}/{stated[1]}, code says "
                    f"{actual[0]}/{actual[1]}"
                )
        cell = row[disposition_column]
        verdict = cell.split()[0].strip("*_`") if cell.split() else ""
        if verdict not in DISPOSITIONS:
            failures.append(
                f"{key}: disposition {verdict!r} is not one of {', '.join(sorted(DISPOSITIONS))}"
            )
        for identifier in _decision_ids(row[governing_column]):
            if not decision_exists(identifier):
                failures.append(
                    f"{key}: cites {identifier}, which is not in docs/adr or docs/specs"
                )
    return failures


def main() -> int:
    if not MATRIX.exists():
        print(f"FAIL: {MATRIX} is missing", file=sys.stderr)
        return 1
    text = MATRIX.read_text()
    modules = production_modules()
    unreachable = unreachable_modules()
    failures = audit(text, modules, unreachable)
    if failures:
        print(f"FAIL: {MATRIX.relative_to(ROOT)} does not match the code it describes\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nUpdate the matrix row (or the code) so the two agree. The matrix is the "
            "M0 planning surface; a stale row is a wrong plan."
        )
        return 1
    subsystems = len(parse_table(text, OWNERSHIP_MARKER)) - 1
    print(
        f"OK: {subsystems} subsystems classify all {len(modules)} production modules; "
        f"{len(unreachable)} unreachable modules are attributed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
