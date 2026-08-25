#!/usr/bin/env python3
"""Fail when a dependency-injection root carries a field production never reads.

`Container` is not a value object; it is the DI root, and its fields exist so
that the runtime can consume them. A field that is constructed, stored, and read
by nobody is wiring that does nothing — the defect found by hand in #133
(`archive_store`) and again in #225 (`a2a_broker`).

Neither existing gate sees it. `check-reachability.py` asks whether a *module* is
imported, and the container imports it. `check-vulture-baseline.py` asks whether
a *symbol* is used, and the assignment uses it. The question here is narrower
than either: does anything ever read the value back out.

Scope is deliberate. Flagging every uncalled public export would seed at 662
entries, which the vulture ledger's `core-public-api-surface` section already
concedes; flagging every unread public dataclass field would seed at 342 and
treat `RuntimeMetrics` — whose fields exist to be read by a consumer outside
this repo — the same as wiring. Restricted to declared DI roots it seeds at 17.
See ADR-082526-1899 for the measurement and for why transitive deadness, the
design proposed in #236, does not find the orphan it was proposed for.

Bank a reviewed state with `--update`, then write a disposition for each new
entry: an entry with an empty disposition fails, because "banked" and
"explained" have to be the same act.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "wiring-reads-baseline.json"


@dataclass(frozen=True)
class DIRoot:
    """A class whose fields are wiring rather than data."""

    name: str
    source: str
    cls: str


# Declared explicitly, the same discipline `FLAT_APPS` uses in
# check-reachability.py: a second DI root added without a declaration here is
# invisible to this gate, and that trade is recorded in ADR-082526-1899 rather
# than discovered later.
DI_ROOTS = (
    DIRoot(
        name="maistro.container.Container",
        source="packages/maistro-core/src/maistro/container.py",
        cls="Container",
    ),
)


def _production_python_files(root: Path) -> list[Path]:
    """Every production module, by the same rule check-reachability.py uses."""
    files: list[Path] = []
    for base in [*root.glob("packages/*/src"), *root.glob("packages/*/backend")]:
        for path in base.rglob("*.py"):
            rel = path.relative_to(base)
            if "tests" in rel.parts or path.name.startswith("test_"):
                continue
            files.append(path)
    return sorted(files)


def _public_fields(path: Path, class_name: str) -> list[str]:
    """Public annotated fields declared on `class_name`, in declaration order."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and not statement.target.id.startswith("_")
            ]
    raise RuntimeError(f"declared DI root {class_name} not found in {path}")


def _attribute_reads(files: list[Path]) -> set[str]:
    """Attribute names read anywhere in production code.

    Load context only: `self.archive_store = x` is the wiring under suspicion,
    not evidence against it. Matching by bare name over-approximates — a field
    sharing a name with an unrelated attribute elsewhere reads as consumed — and
    that is the safe direction for a blocking gate, the same direction vulture
    errs in.
    """
    reads: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                reads.add(node.attr)
    return reads


def unread_fields(
    root: Path = ROOT, di_roots: tuple[DIRoot, ...] = DI_ROOTS
) -> dict[str, list[str]]:
    """Declared DI root → its public fields that no production module reads."""
    files = _production_python_files(root)
    reads = _attribute_reads(files)
    return {
        di_root.name: [
            field
            for field in _public_fields(root / di_root.source, di_root.cls)
            if field not in reads
        ]
        for di_root in di_roots
    }


def _load_baseline(path: Path = BASELINE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return {name: dict(entry["unread"]) for name, entry in loaded["roots"].items()}


def _write_baseline(
    current: dict[str, list[str]],
    recorded: dict[str, dict[str, str]],
    di_roots: tuple[DIRoot, ...] = DI_ROOTS,
    path: Path = BASELINE,
) -> None:
    """Rewrite from an actual scan, carrying existing dispositions forward."""
    sources = {di_root.name: di_root.source for di_root in di_roots}
    payload = {
        "roots": {
            name: {
                "source": sources[name],
                "unread": {
                    field: recorded.get(name, {}).get(field, "") for field in sorted(fields)
                },
            }
            for name, fields in sorted(current.items())
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _display_path(path: Path, root: Path = ROOT) -> str:
    """Repo-relative when it is inside the repo, absolute when a test redirects it."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _report(
    current: dict[str, list[str]], recorded: dict[str, dict[str, str]]
) -> tuple[list[str], list[str], list[str]]:
    """New unread fields, stale ledger entries, and entries with no disposition."""
    added: list[str] = []
    stale: list[str] = []
    undocumented: list[str] = []
    for name, fields in sorted(current.items()):
        entries = recorded.get(name, {})
        added.extend(f"{name}.{field}" for field in sorted(set(fields) - set(entries)))
        stale.extend(f"{name}.{field}" for field in sorted(set(entries) - set(fields)))
        undocumented.extend(
            f"{name}.{field}"
            for field, why in sorted(entries.items())
            if field in set(fields) and not why.strip()
        )
    return added, stale, undocumented


def main(argv: list[str]) -> int:
    # Read the module globals at call time, not at def time: a default bound
    # in a signature cannot be substituted, and a gate whose ledger path is
    # unsubstitutable can only ever be tested against the real repo.
    current = unread_fields(ROOT, DI_ROOTS)
    recorded = _load_baseline(BASELINE)
    total = sum(len(fields) for fields in current.values())

    if "--update" in argv:
        _write_baseline(current, recorded, DI_ROOTS, BASELINE)
        print(f"wrote {_display_path(BASELINE)} — write a disposition for each new entry")
        return 0

    added, stale, undocumented = _report(current, recorded)
    print(f"{len(DI_ROOTS)} declared DI root(s), {total} field(s) no production module reads")

    if added:
        print(f"\n{len(added)} field(s) are wired and NEWLY UNREAD:\n", file=sys.stderr)
        for entry in added:
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nSomething builds these and nothing reads them back. If that is intended —\n"
            "a surface a downstream product consumes — bank it with --update and write\n"
            "why. If it is not, it is wiring that does nothing: give it a reader, or\n"
            "retire it and the code that populates it.",
            file=sys.stderr,
        )

    if stale:
        print(f"\n{len(stale)} recorded field(s) are now READ — prune them:\n", file=sys.stderr)
        for entry in stale:
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nThe ledger can only shrink. A stale entry would silently absorb the next\n"
            "field that goes unread under the same name.",
            file=sys.stderr,
        )

    if undocumented:
        print(f"\n{len(undocumented)} recorded field(s) carry no disposition:\n", file=sys.stderr)
        for entry in undocumented:
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nBanking without explaining is how a ledger becomes a place to put things.",
            file=sys.stderr,
        )

    if added or stale or undocumented:
        return 1

    print("\nWiring ledger matches the current unread set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
