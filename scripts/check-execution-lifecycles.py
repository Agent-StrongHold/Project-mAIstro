#!/usr/bin/env python3
"""Fail when a new work-state enum appears outside the trusted lifecycle ledger (#36, #542).

The convergence program's central claim is that Run/NodeRun/Attempt is the one
execution identity. A candidate may not introduce a second lifecycle and approve
it by adding a classification to quality/execution-lifecycles.json in the same
change. New identities are judged against the merge-base ledger and require a
separately landed authorization. The candidate ledger is still the source of
reviewed classification/rationale for identities already admitted, and stale
entries must be pruned immediately.

Discovery is deliberately syntax-independent within a small static vocabulary:
Enum subclasses and status-shaped Literal type aliases are treated alike. The
value/name heuristic keeps ordinary configuration Literals out of this ledger;
free-text and database-column audits remain separate gates.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "execution-lifecycles.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "execution-lifecycles"
METRIC_DEFINITION_VERSION = "2"

CLASSIFICATIONS = frozenset({"CANONICAL", "DOMAIN", "PROJECTION", "RECEIPT", "CONVERGE"})
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"})
_LITERAL_NAME = "Literal"
_ALIAS_HINTS = frozenset({"lifecycle", "phase", "state", "status"})
_WORK_STATES = frozenset(
    {
        "ABORTED",
        "ACTIVE",
        "ASSIGNED",
        "BLOCKED",
        "CANCELED",
        "CANCELLED",
        "CLAIMED",
        "COMPLETE",
        "COMPLETED",
        "DONE",
        "ERROR",
        "ERRORED",
        "FAILED",
        "IN_PROGRESS",
        "PAUSED",
        "PENDING",
        "QUEUED",
        "RETRYING",
        "RUNNING",
        "SKIPPED",
        "STOPPED",
        "SUCCEEDED",
        "TIMED_OUT",
        "TIMEOUT",
        "WAITING",
    }
)
_MIN_WORK_STATES = 3


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _load_reachability() -> object:
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


def _enum_members(node: ast.ClassDef) -> set[str]:
    return {
        target.id
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }


def _attribute_name(node: ast.expr) -> str:
    """Return the terminal name for ``typing.Literal``-style expressions."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _looks_like_status_alias(name: str) -> bool:
    normalized = name.replace("-", "_").lower()
    parts = {part for part in normalized.split("_") if part}
    return bool(parts & _ALIAS_HINTS or any(normalized.endswith(hint) for hint in _ALIAS_HINTS))


def _literal_names(tree: ast.AST) -> set[str]:
    names = {_LITERAL_NAME}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module not in {
            "typing",
            "typing_extensions",
        }:
            continue
        for imported in node.names:
            if imported.name == _LITERAL_NAME:
                names.add(imported.asname or imported.name)
    return names


def _literal_values(
    node: ast.expr,
    aliases: dict[str, ast.expr],
    literal_names: set[str],
    resolving: frozenset[str] = frozenset(),
) -> set[str]:
    """Resolve the supported static Literal/type-alias shapes.

    ``Literal[...] | None`` is common in PEP 604 annotations. Resolving local
    aliases also catches a vocabulary split between a named type alias and a
    field alias without importing or executing production code.
    """
    if isinstance(node, ast.Subscript) and _attribute_name(node.value) in literal_names:
        return {
            value.value
            for value in ast.walk(node.slice)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
    if isinstance(node, ast.Name) and node.id in aliases and node.id not in resolving:
        return _literal_values(
            node=aliases[node.id],
            aliases=aliases,
            literal_names=literal_names,
            resolving=resolving | {node.id},
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _literal_values(node.left, aliases, literal_names, resolving) | _literal_values(
            node.right, aliases, literal_names, resolving
        )
    return set()


def _is_enum(node: ast.ClassDef) -> bool:
    bases = {
        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        for base in node.bases
    }
    return bool(bases & _ENUM_BASES)


def _normalized_work_states(values: set[str]) -> set[str]:
    return {
        value.upper().replace("-", "_").replace(" ", "_")
        for value in values
        if value.upper().replace("-", "_").replace(" ", "_") in _WORK_STATES
    }


def _enum_vocabularies(tree: ast.AST, module: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum(node):
            continue
        states = _enum_members(node) & _WORK_STATES
        if len(states) >= _MIN_WORK_STATES:
            found[f"{module}::{node.name}"] = states
    return found


def _literal_aliases(tree: ast.AST) -> dict[str, ast.expr]:
    aliases: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and _looks_like_status_alias(target.id):
                aliases[target.id] = node.value
    return aliases


def _literal_vocabularies(tree: ast.AST, module: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    aliases = _literal_aliases(tree)
    literal_names = _literal_names(tree)
    for name, value in aliases.items():
        states = _normalized_work_states(_literal_values(value, aliases, literal_names))
        if len(states) >= _MIN_WORK_STATES:
            found[f"{module}::{name}"] = states
    return found


def work_state_vocabularies(source: str, module: str) -> dict[str, set[str]]:
    """Find enum and status-shaped Literal vocabularies in one source file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {**_enum_vocabularies(tree, module), **_literal_vocabularies(tree, module)}


def work_state_enums(source: str, module: str) -> dict[str, set[str]]:
    """Compatibility name for the shared Enum and Literal lifecycle detector."""
    return work_state_vocabularies(source, module)


def work_state_literals(source: str, module: str) -> dict[str, set[str]]:
    """Return only Literal identities for focused gate and fixture tests."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    enum_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and _is_enum(node)
    }
    return {
        name: states
        for name, states in work_state_vocabularies(source, module).items()
        if name.rsplit("::", 1)[-1] not in enum_names
    }


def discover() -> dict[str, set[str]]:
    reach = _load_reachability()
    found: dict[str, set[str]] = {}
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        found.update(work_state_vocabularies(path.read_text(errors="replace"), module))
    return found


def _discover_at_revision(revision: str | None, current: dict[str, set[str]]) -> set[str]:
    """Find current identities whose source already existed at the trusted base."""
    if not revision:
        return set()
    modules = {name.split("::", 1)[0] for name in current}
    reach = _load_reachability()
    visible: set[str] = set()
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        if module not in modules:
            continue
        relative = path.relative_to(ROOT).as_posix()
        proc = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=ROOT,
        )
        if proc.returncode == 0:
            visible.update(work_state_vocabularies(proc.stdout, module))
    return visible


def _entries(ledger: object) -> dict[str, object]:
    if not isinstance(ledger, dict):
        return {}
    entries = ledger.get("lifecycles")
    return dict(entries) if isinstance(entries, dict) else {}


def audit(ledger: dict[str, object], found: dict[str, set[str]]) -> list[str]:
    """Every way the candidate ledger and code disagree, named."""
    entries = ledger.get("lifecycles")
    if not isinstance(entries, dict):
        return ["ledger has no 'lifecycles' object"]

    failures: list[str] = []
    for name in sorted(set(found) - set(entries)):
        failures.append(
            f"{name}: an unclassified work-state vocabulary ({', '.join(sorted(found[name]))}). "
            f"Classify it in {LEDGER.name} as one of {', '.join(sorted(CLASSIFICATIONS))}."
        )
    for name in sorted(set(entries) - set(found)):
        failures.append(f"{name}: classified here but no longer found in the code; prune it")

    for name in sorted(set(entries) & set(found)):
        entry = entries[name]
        if not isinstance(entry, dict):
            failures.append(f"{name}: entry must be an object")
            continue
        classification = entry.get("classification")
        if classification not in CLASSIFICATIONS:
            failures.append(
                f"{name}: classification {classification!r} is not one of "
                f"{', '.join(sorted(CLASSIFICATIONS))}"
            )
        if not str(entry.get("rationale", "")).strip():
            failures.append(f"{name}: needs a rationale")
        if classification == "CONVERGE" and not str(entry.get("converged_by", "")).strip():
            failures.append(
                f"{name}: CONVERGE requires 'converged_by' naming the issue that removes it"
            )
    return failures


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL: {LEDGER} is missing", file=sys.stderr)
        return 1
    candidate_ledger = json.loads(LEDGER.read_text())
    candidate_entries = _entries(candidate_ledger)
    found = discover()
    candidate_failures = audit(candidate_ledger, found)

    prov = _provenance()
    try:
        trusted_ref = prov.resolve_baseline(LEDGER, root=ROOT)
        trusted_payload = trusted_ref.loads(default={"lifecycles": {}})
        trusted_entries = _entries(trusted_payload)
        prov.require_measurement(found, ratchet=RATCHET, what="work-state vocabularies")
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=(
                str(trusted_payload.get("metric_definition_version"))
                if isinstance(trusted_payload, dict)
                and trusted_payload.get("metric_definition_version") is not None
                else None
            ),
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(set(found) - set(trusted_entries))
    # Scanner expansion must surface pre-existing debt without turning that debt
    # into a self-authorized new lifecycle. A current detector pass over the
    # trusted source distinguishes newly visible aliases from code introduced by
    # this change; the latter still needs a prior grant.
    visible_at_base = _discover_at_revision(trusted_ref.base_sha, found)
    unauthorized = [
        name for name in added if name not in authorized and name not in visible_at_base
    ]
    unbanked_authorized = [
        name for name in added if name in authorized and name not in candidate_entries
    ]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted_entries)} classified lifecycles",
            new_value=f"{len(found)} discovered lifecycles",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{name}: {authorized[name]}" for name in added if name in authorized
            ),
        ).render()
    )

    failures = list(candidate_failures)
    failures.extend(
        f"{name}: NEW work-state vocabulary is absent from the trusted base and has no "
        "already-landed authorization"
        for name in unauthorized
    )
    failures.extend(
        f"{name}: authorized lifecycle addition is not classified in the candidate ledger"
        for name in unbanked_authorized
    )
    if failures:
        print("FAIL: the execution-lifecycle ledger does not match trusted policy\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    counts: dict[str, int] = {}
    for entry in candidate_entries.values():
        if isinstance(entry, dict):
            key = str(entry["classification"])
            counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    print(f"OK: {len(found)} work-state vocabularies, all classified ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
