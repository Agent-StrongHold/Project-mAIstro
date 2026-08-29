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
6. Every module named as an owner in the Ownership table resolves to exactly one
   production module and is reached by a product path (#378). A future or
   unreached owner has to say so in the cell, and the annotation is checked in
   both directions so it cannot go stale either. This is the claim a planning
   surface most needs to get right -- the Ownership table's whole subject is
   who owns each subsystem *today* -- and it was the one thing nothing checked.

Run: `python scripts/check-convergence-matrix.py`
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
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


# --- ownership claims (#378) -------------------------------------------------
#
# Reachability proves a module *can* be reached. It says nothing about the
# prose beside it, and the matrix was free to name a current owner that no
# product path reaches -- which is the one claim a planning surface must not
# get wrong, because the whole point of the Ownership table is "who owns this
# today". Fifteen such claims were in the table when this was written.
#
# So each ownership cell now has a grammar. A code span shaped like a module
# path is a CLAIM about a production module; anything else in the cell is
# prose. A bare claim asserts a *current, reachable* owner. Annotations in the
# parenthesis that follows say otherwise, and each of them is checked in both
# directions so it cannot go stale the way the prose did.

#: A code span shaped like a module path. `TaskRecord`, `evaluate()`,
#: `postgresql://` and `quality/*.json` are prose about a non-module owner and
#: are deliberately not claims -- see `_is_claim`.
_MODULE_SPAN = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)+$")

#: `—`, `n/a`, `none` and `itself` are the declared absences. A cell that opens
#: with one of them is saying there is no module owner, so a claim in the same
#: cell contradicts it.
_ABSENCE = re.compile(r"^(—|n/a\b|none\b|itself\b)", re.IGNORECASE)

_OWNERSHIP_COLUMNS = ("Lifecycle owner", "Persistence owner", "Authorization owner")

#: What may follow a claim, and what each one licenses.
_ANNOTATIONS = frozenset({"canonical", "unreachable", "planned", "delegated"})

#: `<!-- matrix:ownership-census claims=53 declared=73 prose=30 -->`
_CENSUS = re.compile(
    r"<!--\s*matrix:ownership-census\s+claims=(\d+)\s+declared=(\d+)\s+prose=(\d+)\s*-->"
)


@dataclass(frozen=True)
class Claim:
    subsystem: str
    column: str
    span: str
    module: str
    annotations: frozenset[str]

    @property
    def current(self) -> bool:
        """A planned owner is a future owner, and is not a claim about today."""
        return "planned" not in self.annotations

    def where(self) -> str:
        return f"{self.subsystem}: {self.column} `{self.span}`"


def _is_claim(span: str, modules: frozenset[str]) -> bool:
    return bool(_MODULE_SPAN.match(span)) or span in modules


def _annotations_after(cell: str, end: int) -> frozenset[str]:
    """The first parenthesised group between this span and the next one.

    Scoped to the first group deliberately: `(canonical, #132)` annotates the
    span it follows, while a later `(ADR-018)` in the same cell annotates
    something else. Reading the whole tail would let one span's annotation
    silently license the next one's.
    """
    tail = cell[end:].split("`", 1)[0]
    group = re.search(r"\(([^)]*)\)", tail)
    if group is None:
        return frozenset()
    words = {word.strip(" .*_").lower() for word in re.split(r"[,;]", group.group(1))}
    return frozenset(words & _ANNOTATIONS)


def _resolve(span: str, prefixes: list[str], modules: frozenset[str]) -> list[str]:
    """The production module a span names, resolved in three tiers.

    Cells abbreviate: `runs.pg_store` for `maistro.runs.pg_store`,
    `design.engine` for `maistro_design.engine`, `canvas.runner` for
    `maistro_canvas.canvas.runner`. The row's own module prefixes are tried
    first and an exact match second -- that order matters, because the Turing
    row's `middleware.auth` means the Turing backend's, not the Conductor's,
    and both exist.
    """
    for tier in (_scoped(span, prefixes), {span}, {f"maistro.{span}"}):
        hits = sorted(tier & modules)
        if hits:
            return hits
    return []


def _scoped(span: str, prefixes: list[str]) -> set[str]:
    candidates: set[str] = set()
    head, _, rest = span.partition(".")
    for prefix in prefixes:
        for separator in (".", "::"):
            candidates.add(f"{prefix}{separator}{span}")
            # `design.engine` under prefix `maistro_design`: the writer used the
            # product's short name for its package, so the head is the prefix.
            if rest and (prefix.split(".")[-1] == head or prefix.endswith(f"_{head}")):
                candidates.add(f"{prefix}{separator}{rest}")
    return candidates


def _claims(
    header: list[str], rows: list[list[str]], modules: frozenset[str]
) -> tuple[list[Claim], list[str], dict[str, int]]:
    """Every claim in the ownership table, plus resolution failures and a census."""
    module_column = header.index("Modules")
    columns = [(name, header.index(name)) for name in _OWNERSHIP_COLUMNS if name in header]
    claims: list[Claim] = []
    failures: list[str] = []
    census = {"claims": 0, "declared": 0, "prose": 0}

    for row in rows:
        prefixes = _CODE_SPAN.findall(row[module_column])
        for name, index in columns:
            cell = row[index]
            if not cell:
                failures.append(f"{row[0]}: {name} is empty; say `—` if there is no owner")
                continue
            found = _cell_claims(row[0], name, cell, prefixes, modules, failures)
            claims.extend(found)
            _count(census, cell, modules)
            if found and _ABSENCE.match(cell):
                failures.append(
                    f"{row[0]}: {name} declares no owner but names "
                    f"{', '.join(sorted(c.span for c in found))}"
                )
    return claims, failures, census


def _count(census: dict[str, int], cell: str, modules: frozenset[str]) -> None:
    """Census by grammar, not by outcome.

    A cell counts as naming a module when it *contains* a module-shaped span,
    whether or not that span resolves. Counting resolution instead would quietly
    move a typo into the "prose we cannot check" bucket -- the one bucket that
    is supposed to hold only cells nobody could check.
    """
    if any(_is_claim(span, modules) for span in _CODE_SPAN.findall(cell)):
        census["claims"] += 1
    elif _ABSENCE.match(cell):
        census["declared"] += 1
    else:
        census["prose"] += 1


def _cell_claims(
    subsystem: str,
    column: str,
    cell: str,
    prefixes: list[str],
    modules: frozenset[str],
    failures: list[str],
) -> list[Claim]:
    found: list[Claim] = []
    for match in _CODE_SPAN.finditer(cell):
        span = match.group(1)
        if not _is_claim(span, modules):
            continue
        resolved = _resolve(span, prefixes, modules)
        if not resolved:
            failures.append(
                f"{subsystem}: {column} names `{span}`, which is not a production module"
            )
            continue
        if len(resolved) > 1:
            failures.append(
                f"{subsystem}: {column} `{span}` names {len(resolved)} production modules "
                f"({', '.join(resolved)}); write the one you mean in full"
            )
            continue
        found.append(
            Claim(subsystem, column, span, resolved[0], _annotations_after(cell, match.end()))
        )
    return found


def _claim_failures(
    claims: list[Claim], unreachable: set[str], verdicts: dict[str, str]
) -> list[str]:
    failures: list[str] = []
    failures.extend(_reachability_failures(claims, unreachable))
    failures.extend(_planned_failures(claims, verdicts))
    failures.extend(_keep_failures(claims, unreachable, verdicts))
    failures.extend(_single_lifecycle_owner_failures(claims))
    return failures


def _reachability_failures(claims: list[Claim], unreachable: set[str]) -> list[str]:
    """Both directions, so neither the claim nor its annotation can go stale."""
    failures: list[str] = []
    for claim in claims:
        missing = claim.module in unreachable
        annotated = "unreachable" in claim.annotations
        if missing and not annotated and claim.current:
            failures.append(
                f"{claim.where()} as a current owner, but no product path reaches "
                f"{claim.module}; mark it `(unreachable)` or `(planned)`, or wire it"
            )
        elif annotated and not missing:
            failures.append(
                f"{claim.where()} is marked `(unreachable)`, but {claim.module} is reached; "
                "drop the annotation"
            )
    return failures


def _planned_failures(claims: list[Claim], verdicts: dict[str, str]) -> list[str]:
    return [
        f"{claim.where()} is `(planned)` on a KEEP row; a subsystem still waiting for its "
        "owner is CONNECT or MIGRATE, not KEEP"
        for claim in claims
        if "planned" in claim.annotations and verdicts.get(claim.subsystem) == "KEEP"
    ]


def _keep_failures(
    claims: list[Claim], unreachable: set[str], verdicts: dict[str, str]
) -> list[str]:
    """A KEEP column whose every owner is unreachable or future owns nothing today."""
    columns: dict[tuple[str, str], list[Claim]] = {}
    for claim in claims:
        columns.setdefault((claim.subsystem, claim.column), []).append(claim)
    return [
        f"{subsystem}: {column} is KEEP but every owner it names is unreachable or planned"
        for (subsystem, column), found in sorted(columns.items())
        if verdicts.get(subsystem) == "KEEP"
        and all(not c.current or c.module in unreachable for c in found)
    ]


def _single_lifecycle_owner_failures(claims: list[Claim]) -> list[str]:
    """Two subsystems cannot both own one module's work state.

    `(delegated)` is how a row says it reads another subsystem's owner rather
    than owning it -- maistro-server hands work to `maistro.tasks.queue`, it
    does not own the queue's lifecycle.
    """
    owners: dict[str, list[str]] = {}
    for claim in claims:
        if claim.column != "Lifecycle owner" or not claim.current:
            continue
        if "delegated" in claim.annotations:
            continue
        owners.setdefault(claim.module, []).append(claim.subsystem)
    return [
        f"{module} is the lifecycle owner of {len(rows)} subsystems ({', '.join(sorted(rows))}); "
        "one of them delegates -- mark it `(delegated)`"
        for module, rows in sorted(owners.items())
        if len(rows) > 1
    ]


def _census_failures(text: str, census: dict[str, int]) -> list[str]:
    """The stated limitation is checked, so it cannot drift like the prose did."""
    match = _CENSUS.search(text)
    if match is None:
        return [
            "the ownership census marker is missing; add "
            f"`<!-- matrix:ownership-census claims={census['claims']} "
            f"declared={census['declared']} prose={census['prose']} -->`"
        ]
    keys = ("claims", "declared", "prose")
    stated = dict(zip(keys, (int(group) for group in match.groups()), strict=True))
    if stated != census:
        return [
            "the ownership census is stale: it says "
            f"claims={stated['claims']} declared={stated['declared']} prose={stated['prose']}, "
            f"the table has claims={census['claims']} declared={census['declared']} "
            f"prose={census['prose']}"
        ]
    return []


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
    failures.extend(_key_failures(own_keys, dis_keys))

    if "Modules" not in own_header:
        return [*failures, "ownership table has no 'Modules' column"]
    missing = [name for name in _DISPOSITION_COLUMNS if name not in dis_header]
    if missing:
        return [*failures, f"disposition table is missing column(s): {', '.join(missing)}"]

    prefixes, prefix_failures = _prefixes(own_rows, own_header.index("Modules"))
    failures.extend(prefix_failures)
    owners = _assign(modules, prefixes)
    failures.extend(_partition_failures(modules, prefixes, own_keys, owners))
    verdicts = _verdicts(dis_header, dis_rows)
    failures.extend(_row_failures(dis_header, dis_rows, owners, unreachable, decision_exists))

    failures.extend(_ownership_failures(text, own_header, own_rows, modules, unreachable, verdicts))
    return failures


def _key_failures(own_keys: list[str], dis_keys: list[str]) -> list[str]:
    if own_keys == dis_keys:
        return []
    only_own = [key for key in own_keys if key not in set(dis_keys)]
    only_dis = [key for key in dis_keys if key not in set(own_keys)]
    failures = []
    if only_own:
        failures.append(f"rows in the ownership table only: {', '.join(only_own)}")
    if only_dis:
        failures.append(f"rows in the disposition table only: {', '.join(only_dis)}")
    if not failures:
        failures.append("both tables list the same subsystems in a different order")
    return failures


def _ownership_failures(
    text: str,
    header: list[str],
    rows: list[list[str]],
    modules: list[str],
    unreachable: set[str],
    verdicts: dict[str, str],
) -> list[str]:
    missing = [name for name in _OWNERSHIP_COLUMNS if name not in header]
    if missing:
        return [f"ownership table is missing column(s): {', '.join(missing)}"]
    claims, failures, census = _claims(header, rows, frozenset(modules))
    return [
        *failures,
        *_claim_failures(claims, unreachable, verdicts),
        *_census_failures(text, census),
    ]


def _verdicts(header: list[str], rows: list[list[str]]) -> dict[str, str]:
    column = header.index("Disposition")
    return {row[0]: (row[column].split() or [""])[0].strip("*_`") for row in rows}


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
