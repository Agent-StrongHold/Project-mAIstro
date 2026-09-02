#!/usr/bin/env python3
"""Fail when a new work-state enum appears outside the trusted lifecycle ledger (#36, #542).

The convergence program's central claim is that Run/NodeRun/Attempt is the one
execution identity. A candidate may not introduce a second lifecycle and approve
it by adding a classification to quality/execution-lifecycles.json in the same
change. New enum identities are judged against the merge-base ledger and require
a separately landed authorization. The candidate ledger is still the source of
reviewed classification/rationale for identities already admitted, and stale
entries must be pruned immediately.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "execution-lifecycles.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "execution-lifecycles"
METRIC_DEFINITION_VERSION = "1"

CLASSIFICATIONS = frozenset({"CANONICAL", "DOMAIN", "CONVERGE"})
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"})
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
        "FAILED",
        "IN_PROGRESS",
        "PAUSED",
        "PENDING",
        "QUEUED",
        "RETRYING",
        "RUNNING",
        "SKIPPED",
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


def _is_enum(node: ast.ClassDef) -> bool:
    bases = {
        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        for base in node.bases
    }
    return bool(bases & _ENUM_BASES)


def work_state_enums(source: str, module: str) -> dict[str, set[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum(node):
            continue
        states = _enum_members(node) & _WORK_STATES
        if len(states) >= _MIN_WORK_STATES:
            found[f"{module}::{node.name}"] = states
    return found


def discover() -> dict[str, set[str]]:
    reach = _load_reachability()
    found: dict[str, set[str]] = {}
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        found.update(work_state_enums(path.read_text(errors="replace"), module))
    return found


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
            f"{name}: an unclassified work-state enum ({', '.join(sorted(found[name]))}). "
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
        trusted_entries = _entries(trusted_ref.loads(default={"lifecycles": {}}))
        prov.require_measurement(found, ratchet=RATCHET, what="work-state enums")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(set(found) - set(trusted_entries))
    unauthorized = [name for name in added if name not in authorized]
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
        f"{name}: NEW work-state lifecycle is absent from the trusted base and has no "
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
    print(f"OK: {len(found)} work-state enums, all classified ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
