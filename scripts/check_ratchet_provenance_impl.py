"""Every script that reads a `quality/` ledger has a provenance decision (#542).

`scripts/ratchet_provenance.py` (#534/#536) exists because a ratchet that reads
its comparison ledger out of the tree being judged proves internal consistency
and not monotonicity: one commit can add the debt, bank it, and write the
disposition, and the gate goes red to green while the number it guards rises.

Converting the ratchets one at a time fixes the ones converted. It does not
stop the next one from being written the old way — and that is not
hypothetical. #542 enumerated **13** scripts reading a `quality/` ledger; by
the time this gate was written there were **20**. Seven arrived in between, all
candidate-authored, none noticed, because nothing was counting.

So this is an inventory with a ratchet on it. Every script that reads a ledger
is either converted, or carries a written decision saying why it is not. The
inventory may only shrink: a script recorded as unconverted that has since been
converted must be pruned, exactly as a reachability entry that became reachable
must be. A stale row is slack the next unconverted ratchet would slide into
under someone else's name.

Detection is AST-based, not textual. Half the `quality/` mentions in `scripts/`
are prose — the ledgers are discussed in docstrings far more often than they
are opened — and a grep-shaped gate would have to allowlist its way out of that,
which is how a gate ends up measuring its own allowlist.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INVENTORY = ROOT / "quality" / "ratchet-provenance-inventory.json"
PROVENANCE_MODULE = "ratchet_provenance.py"
RATCHET = "ratchet-provenance-inventory"
METRIC_DEFINITION_VERSION = "1"

#: Loaded by path, and registered in `sys.modules` before execution: this file
#: is itself loaded with `spec_from_file_location` by its tests, which puts
#: nothing on `sys.path` for a sibling import, and `@dataclass` resolves field
#: types through `sys.modules[cls.__module__]`.
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / PROVENANCE_MODULE


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Stands in for a ledger whose name is assembled at runtime. It is still a
#: ledger; the inventory row has to account for it in prose.
_COMPUTED = "<computed>"

#: The helper's entry points. A script that resolves a ledger through any of
#: these is reading it from the base revision.
_RESOLVERS = frozenset({"resolve_baseline", "resolve_baseline_dir"})

#: Decisions an unconverted script may record. `CONVERT_PENDING` is debt with a
#: name on it; the other two are answers, not deferrals.
DECISIONS = {
    # Should be base-resolved and is not yet. Names who owns doing it.
    "CONVERT_PENDING": "owner",
    # The ledger is the specification, not a tolerance: a candidate editing it
    # is the intended workflow (#542 group 3). Names what makes that safe.
    "CANDIDATE_AUTHORED": "safeguard",
    # Reads a `quality/` path but judges no floor — a reporter, a writer, or a
    # consumer of someone else's ledger.
    "NOT_A_RATCHET": None,
}


@dataclass(frozen=True)
class LedgerUse:
    """A script, and the `quality/` ledgers its code actually opens."""

    script: str
    ledgers: tuple[str, ...]
    base_resolved: bool


def _quality_paths(tree: ast.AST) -> set[str]:
    """Ledger names reached by a `... / "quality" / "<name>"` path expression.

    The repo's one idiom for naming a ledger, in every script that has one.
    Matching the expression rather than the string means a name that only ever
    appears in prose is not a use, and a name built from a variable is not
    silently reported as absent — it simply is not this shape, which the
    `NOT_A_RATCHET`/`CONVERT_PENDING` decision then has to account for.
    """
    divs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]
    # Only the outermost expression of each chain. `ast.walk` also yields the
    # inner `ROOT / "quality"` of `ROOT / "quality" / "x"`, whose tail is empty
    # -- so every named ledger would also have reported an unnamed one.
    nested = {id(part) for node in divs for part in (node.left, node.right)}
    found: set[str] = set()
    for node in divs:
        if id(node) in nested:
            continue
        parts = _flatten_div(node)
        if "quality" not in parts:
            continue
        tail = parts[parts.index("quality") + 1 :]
        # A use, named or not. `ROOT / "quality" / name` drops its tail here
        # because the segment is a variable, and an earlier version then
        # reported the script as touching no ledger at all -- the one spelling
        # that escaped the inventory entirely, and the only one a script
        # avoiding this gate would have to reach for.
        found.add("/".join(tail) if tail else _COMPUTED)
    return found


def _flatten_div(node: ast.expr) -> list[str]:
    """The constant string segments of a `/`-joined path expression, in order.

    A non-constant segment (a variable, a call) contributes nothing rather than
    aborting: `ROOT / "quality" / name` still tells us the script reads the
    directory, which is the fact this gate is about.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _flatten_div(node.left) + _flatten_div(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _is_base_resolved(name: str, source: str, tree: ast.AST) -> bool:
    """Whether the script resolves a ledger through `ratchet_provenance`.

    Both halves are required for a consumer. Naming the module without calling a
    resolver is what a script does when it loads the helper for
    `Provenance.render` alone — a provenance *report* over a candidate-read
    ledger, which reads as converted and is not.

    The helper itself is the one thing that cannot name itself: it defines the
    resolvers, and `load_authorizations` calls one. Requiring the filename there
    would have put `ratchet_provenance.py` on the unconverted list, which is
    both false and the sort of finding that gets an inventory row rather than a
    fix.
    """
    if name != PROVENANCE_MODULE and PROVENANCE_MODULE not in source:
        return False
    return any(
        isinstance(node, (ast.Attribute, ast.Name))
        and getattr(node, "attr", getattr(node, "id", None)) in _RESOLVERS
        for node in ast.walk(tree)
    )


def survey(scripts_dir: Path = SCRIPTS) -> list[LedgerUse]:
    """Every script under `scripts/` whose code opens a path under `quality/`."""
    uses: list[LedgerUse] = []
    for path in sorted(scripts_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - a broken script fails elsewhere
            raise SystemExit(f"FAIL: {path.name} does not parse: {exc}") from exc
        ledgers = _quality_paths(tree)
        if not ledgers:
            continue
        uses.append(
            LedgerUse(
                script=path.name,
                ledgers=tuple(sorted(ledgers)),
                base_resolved=_is_base_resolved(path.name, source, tree),
            )
        )
    return uses


def _scripts_of(payload: Any, *, where: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise SystemExit(f"FAIL: {where} is not an object")
    if payload.get("schema_version") != 1 or not isinstance(payload.get("scripts"), dict):
        raise SystemExit(f"FAIL: {where} must have schema_version=1 and a 'scripts' object")
    return payload["scripts"]


def load_inventory(path: Path = INVENTORY) -> dict[str, dict[str, Any]]:
    """The candidate's own inventory — what this change says the surface is."""
    if not path.is_file():
        raise SystemExit(f"FAIL: {path} is missing")
    return _scripts_of(json.loads(path.read_text(encoding="utf-8")), where=str(path))


def trusted_inventory(
    path: Path = INVENTORY, *, base: str | None = None, root: Path = ROOT
) -> tuple[dict[str, dict[str, Any]], Any]:
    """The inventory as of the base revision, and where that was.

    This gate obeys its own rule. Read from the candidate, a single commit
    could add an unconverted ratchet *and* the row excusing it, and the gate
    would pass -- the exact self-approval the helper it enforces exists to
    close, one level up. The base is the only tree in which "was this already
    excused?" has an answer the candidate did not write.
    """
    prov = _provenance()
    baseline = prov.resolve_baseline(path, base=base, root=root)
    loaded = baseline.loads(default=None)
    if loaded is None:
        return {}, baseline
    return _scripts_of(loaded, where=f"{baseline.base_sha}:{path.name}"), baseline


def _entry_failures(script: str, entry: dict[str, Any]) -> list[str]:
    """Whether the row is well formed, independent of the tree."""
    failures: list[str] = []
    decision = entry.get("decision")
    if decision not in DECISIONS:
        return [f"{script}: decision {decision!r} is not one of {', '.join(sorted(DECISIONS))}"]
    required = DECISIONS[decision]
    if required and not str(entry.get(required, "")).strip():
        failures.append(f"{script}: {decision} requires a non-empty '{required}'")
    # A reason under 40 characters is a category name restated, which is the
    # form a disposition takes when it is written to satisfy a gate rather than
    # to be read. The dispositions ledger uses the same floor for the same
    # reason.
    reason = str(entry.get("reason", "")).strip()
    if len(reason) < 40:
        failures.append(f"{script}: reason is missing or too vague ({len(reason)} chars)")
    return failures


def audit(
    uses: list[LedgerUse],
    recorded: dict[str, dict[str, Any]],
    trusted: dict[str, dict[str, Any]],
    authorized: dict[str, str],
    *,
    seeded: bool = False,
) -> list[str]:
    """Every way the tree and the inventory disagree, named.

    Two questions of two ledgers, the split `check-wiring-reads.py` established.
    *New* debt -- a script excused here that the base did not excuse -- is
    judged against `trusted`, so recording it on the branch cannot answer for
    it. Tidiness -- stale rows, vague reasons, a converted script still listed
    -- is the candidate's own bookkeeping and is judged against `recorded`,
    which is also what lets a genuine conversion pass with no authorization.
    """
    failures: list[str] = []
    by_script = {use.script: use for use in uses}

    for use in uses:
        entry = recorded.get(use.script)
        if use.base_resolved:
            if entry is not None:
                failures.append(
                    f"{use.script}: resolves its ledger from the base revision, but is still "
                    "recorded as unconverted — prune the inventory row so the list shrinks"
                )
            continue
        if entry is None:
            failures.append(
                f"{use.script}: reads {', '.join(use.ledgers)} from the candidate tree with no "
                "recorded decision. Convert it through scripts/ratchet_provenance.py, or record "
                "why it stays candidate-authored"
            )
            continue
        failures.extend(_entry_failures(use.script, entry))
        if not seeded and use.script not in trusted and use.script not in authorized:
            failures.append(
                f"{use.script}: newly excused from base-resolution. The base did not carry this "
                "row, so this change is raising the floor — record the grant in "
                "quality/ratchet-authorizations.json under "
                f"'{RATCHET}', which --update never writes"
            )

    for script, entry in sorted(recorded.items()):
        if script not in by_script:
            failures.append(
                f"{script}: inventory names a script that reads no quality/ ledger — "
                "it was removed or stopped reading one; prune the row"
            )
            continue
        failures.extend(_entry_failures(script, entry))

    return failures


def summarise(uses: list[LedgerUse], recorded: dict[str, dict[str, Any]]) -> str:
    converted = sum(1 for use in uses if use.base_resolved)
    counts: dict[str, int] = {}
    for entry in recorded.values():
        decision = str(entry.get("decision", "?"))
        counts[decision] = counts.get(decision, 0) + 1
    tail = ", ".join(f"{n} {d}" for d, n in sorted(counts.items())) or "none recorded"
    return (
        f"{len(uses)} script(s) read a quality/ ledger: "
        f"{converted} base-resolved, {len(uses) - converted} recorded ({tail})"
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python scripts/check-ratchet-provenance.py", file=sys.stderr)
        return 2

    uses = survey()
    recorded = load_inventory()

    prov = _provenance()
    try:
        trusted, baseline = trusted_inventory()
        # The same revision the inventory came from, named rather than resolved
        # a second time: two resolutions of "the base" can disagree, and a grant
        # read from one commit excusing a row measured against another is not
        # the check it looks like.
        authorized = prov.load_authorizations(RATCHET, base=baseline.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    # Absent at base is the seed, and the seed needs no grant. A grant
    # authorizes *raising* a floor, and `load_authorizations` reads grants at
    # the base too -- deliberately, so a grant cannot take effect in the change
    # that writes it. There is therefore no commit in which this gate could
    # ever have been introduced if seeding demanded one.
    #
    # The deeper reason it should not: these rows record scripts that were
    # already reading their ledgers from the candidate tree before this change
    # existed. Seeding writes the debt down; it does not create it, and calling
    # it a floor-raise would make "authorized" mean something different here
    # than everywhere else it is used.
    seeded = baseline.absent_at_base
    failures = audit(uses, recorded, trusted, authorized, seeded=seeded)

    print(summarise(uses, recorded))
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=baseline,
            tool="ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} unconverted",
            new_value=f"{sum(1 for u in uses if not u.base_resolved)} unconverted",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(f"{k}: {v}" for k, v in sorted(authorized.items())),
        ).render()
    )

    if failures:
        print(f"\nFAIL: {len(failures)} provenance inventory finding(s)\n", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nA ratchet reading its own tree's ledger proves the ledger agrees with the\n"
            "tree, which is what a candidate that banks its own regression also proves.\n"
            "See scripts/ratchet_provenance.py and check-wiring-reads.py for the pattern.",
            file=sys.stderr,
        )
        return 1

    return 0
