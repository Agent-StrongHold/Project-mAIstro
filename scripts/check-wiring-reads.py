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
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "wiring-reads-baseline.json"

#: Resolved from this file rather than from `ROOT`, which the tests redirect at
#: a synthetic tree. Loaded by path rather than imported by name because
#: `tests/test_check_wiring_reads.py` loads *this* script with
#: `spec_from_file_location`, which puts nothing on `sys.path` for a sibling to
#: be found on.
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    # Registered before execution, not after: `@dataclass` resolves a field's
    # type through `sys.modules[cls.__module__]`, so a module executed while
    # absent from that table raises on its first dataclass.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


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
        # Persisted so a later scan can tell whether the floor it is comparing
        # against measures the same question. Declared and never recorded, the
        # constant could be bumped and the gate would still compare a v2
        # measurement with a v1 ledger and pass (Codex, #534).
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "roots": {
            name: {
                "source": sources[name],
                "unread": {
                    field: recorded.get(name, {}).get(field, "") for field in sorted(fields)
                },
            }
            for name, fields in sorted(current.items())
        },
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


#: Names this ratchet in `quality/ratchet-authorizations.json`.
RATCHET = "wiring-reads"

#: Bumped when the question changes -- when "unread" starts meaning something
#: other than what `unread_fields` measures today. A floor recorded under an
#: older definition is not comparable and is refused rather than reinterpreted.
METRIC_DEFINITION_VERSION = "1"


def _entries_from(loaded: object) -> dict[str, dict[str, str]]:
    """The `{root: {field: disposition}}` shape, from a parsed ledger."""
    if not isinstance(loaded, dict):
        return {}
    roots = loaded.get("roots")
    if not isinstance(roots, dict):
        return {}
    return {name: dict(entry["unread"]) for name, entry in roots.items()}


def _print_failures(unauthorized: list[str], stale: list[str], undocumented: list[str]) -> None:
    """Everything the run has to say about why it is failing.

    Split out of `main` so the verdict stays legible next to the measurement;
    the three categories answer three different questions and share nothing.
    """
    if unauthorized:
        print(
            f"\n{len(unauthorized)} field(s) are NEWLY UNREAD against the trusted baseline:\n",
            file=sys.stderr,
        )
        for entry in unauthorized:
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nThese are not in the ledger as of the base revision, so banking them\n"
            "here cannot answer for them — that is the point: a change may not be\n"
            "its own oracle. Give the field a reader, or retire it. If the wiring is\n"
            "genuinely consumed by a downstream product, raise the floor deliberately\n"
            f"in quality/ratchet-authorizations.json under {RATCHET!r}, with an owner,\n"
            "an issue, and a reason — a separate edit from the one that regressed it.",
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


def _integration_target_base(prov: ModuleType) -> str | None:
    """Current PR target when CI supplied a historical pull-request base snapshot.

    GitHub's pull-request `base.sha` is the target snapshot from the PR object,
    not necessarily the target tip used to build today's synthetic merge. Using
    that old SHA serializes long-lived PRs behind unrelated target-side ratchet
    changes. The current remote target is still outside candidate control, and
    `resolve_baseline` takes its merge-base with HEAD, so the trusted ledger is
    bound to the exact integration target represented by the synthetic merge.

    Only override a PR run that already opted into an explicit CI ratchet base.
    This preserves local/shallow test jobs that intentionally have no base, and
    leaves push and merge-group revisions supplied by their workflows untouched.
    """
    if os.environ.get("GITHUB_EVENT_NAME", "").strip() != "pull_request":
        return None
    if not os.environ.get(prov.BASE_REV_ENV, "").strip():
        return None
    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if not base_ref:
        raise prov.RatchetProvenanceError(
            "pull-request wiring ratchet has an explicit base SHA but GITHUB_BASE_REF is empty; "
            "cannot resolve the current integration target fail-closed"
        )
    return f"origin/{base_ref}"


def _trusted_baseline() -> tuple[dict[str, dict[str, str]], object, object]:
    """The ledger as of the base revision, where that was, and its metric version.

    Its own function so a test can substitute the trusted state without
    standing up a git history -- the same reason the ledger path is a module
    global rather than a default argument.
    """
    prov = _provenance()
    baseline = prov.resolve_baseline(BASELINE, base=_integration_target_base(prov), root=ROOT)
    loaded = baseline.loads(default={})
    version = loaded.get("metric_definition_version") if isinstance(loaded, dict) else None
    return _entries_from(loaded), baseline, version


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

    prov = _provenance()
    try:
        trusted, baseline, recorded_version = _trusted_baseline()
        prov.require_measurement(current, ratchet=RATCHET, what="DI roots")
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=recorded_version,
            ratchet=RATCHET,
            baseline=baseline,
        )
        # The SAME revision the ledger came from, named explicitly rather than
        # resolved a second time. Two independent resolutions of "the base" can
        # disagree -- and a grant read from one commit authorizing a floor
        # measured against another is not the check anyone thinks it is.
        authorized = prov.load_authorizations(RATCHET, base=baseline.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    # Two different questions, deliberately asked of two different ledgers.
    # New debt is judged against the *base*, so banking on the branch cannot
    # answer it (#534). Tidiness -- stale rows, blank dispositions -- is the
    # candidate's own bookkeeping and is judged against its own ledger, which
    # is also what lets a genuine cleanup pass without an authorization.
    added, _, _ = _report(current, trusted)
    _, stale, undocumented = _report(current, recorded)
    unauthorized = [entry for entry in added if entry not in authorized]
    # An authorization permits the increase; it does not stand in for recording
    # it. Banked nowhere, the field is absent from the candidate's ledger too,
    # so after the merge the trusted floor still lacks it and every later run
    # keeps leaning on the grant (Codex, #534).
    unbanked = [
        entry
        for entry in added
        if entry in authorized and entry not in {f"{r}.{f}" for r, e in recorded.items() for f in e}
    ]

    print(f"{len(DI_ROOTS)} declared DI root(s), {total} field(s) no production module reads")
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=baseline,
            tool="ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{sum(len(e) for e in trusted.values())} unread",
            new_value=f"{total} unread",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{entry}: {authorized[entry]}" for entry in added if entry in authorized
            ),
        ).render()
    )

    if added and not unauthorized and not unbanked:
        print(f"\n{len(added)} authorized floor-raise(s) — see the record above.")

    if unbanked:
        print(
            f"\n{len(unbanked)} authorized field(s) are NOT in this change's ledger:\n",
            file=sys.stderr,
        )
        for entry in unbanked:
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nAn authorization permits the increase; it does not record it. Run\n"
            "--update and write the disposition, or the trusted floor never learns\n"
            "about the field and every later run depends on the grant.",
            file=sys.stderr,
        )

    _print_failures(unauthorized, stale, undocumented)

    if unauthorized or unbanked or stale or undocumented:
        return 1

    print("\nWiring ledger matches the current unread set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
