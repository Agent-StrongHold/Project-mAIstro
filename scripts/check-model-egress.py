#!/usr/bin/env python3
"""Freeze direct model-egress modules against a trusted base revision (#542, #319).

A candidate may not add a direct model caller and approve that escape by adding
the same module to quality/model-egress.json. Expansions are judged against the
merge-base inventory and require a separately landed authorization. Candidate
bookkeeping is checked independently so migrated callers must still be pruned.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import check_direct_effects

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "model-egress.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "model-egress"
METRIC_DEFINITION_VERSION = "1"

_ENDPOINTS = ("chat/completions", "/completions", "/v1/responses")
_HTTP_CALLS = frozenset({"post", "stream", "send", "request"})


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


def performs_egress(source: str) -> bool:
    if not any(fragment in source for fragment in _ENDPOINTS):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _HTTP_CALLS
        for node in ast.walk(tree)
    )


def discover() -> set[str]:
    reach = _load_reachability()
    found: set[str] = set()
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        if performs_egress(path.read_text(errors="replace")):
            found.add(reach._display_name(key, reach.FLAT_APPS))  # type: ignore[attr-defined]
    return found


def audit(recorded: set[str], found: set[str]) -> list[str]:
    failures: list[str] = []
    for module in sorted(found - recorded):
        failures.append(
            f"{module}: calls a model endpoint directly and is not in the inventory. "
            "The set of direct callers may not grow while #56 builds the one egress."
        )
    for module in sorted(recorded - found):
        failures.append(
            f"{module}: recorded as calling a model endpoint but no longer does; prune it "
            "so the inventory shrinks with the migration"
        )
    return failures


def _modules(loaded: object) -> set[str]:
    if not isinstance(loaded, dict):
        return set()
    modules = loaded.get("modules")
    return {str(module) for module in modules} if isinstance(modules, list) else set()


def main() -> int:
    if not INVENTORY.exists():
        print(f"FAIL: {INVENTORY} is missing", file=sys.stderr)
        return 1
    candidate = _modules(json.loads(INVENTORY.read_text()))
    found = discover()

    prov = _provenance()
    try:
        trusted_ref = prov.resolve_baseline(INVENTORY, root=ROOT)
        trusted = _modules(trusted_ref.loads(default={"modules": []}))
        prov.require_measurement(found, ratchet=RATCHET, what="direct model-egress modules")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(found - trusted)
    unauthorized = [module for module in added if module not in authorized]
    unbanked_authorized = [
        module for module in added if module in authorized and module not in candidate
    ]
    candidate_new = sorted(found - candidate)
    candidate_stale = sorted(candidate - found)

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} direct callers",
            new_value=f"{len(found)} direct callers",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{module}: {authorized[module]}" for module in added if module in authorized
            ),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{module}: NEW direct model egress is absent from the trusted base and has no "
        "already-landed authorization"
        for module in unauthorized
    )
    failures.extend(
        f"{module}: authorized expansion is not recorded in the candidate inventory"
        for module in unbanked_authorized
    )
    failures.extend(
        f"{module}: current direct caller is missing from the candidate inventory"
        for module in candidate_new
    )
    failures.extend(
        f"{module}: candidate inventory is stale; this module no longer performs direct egress"
        for module in candidate_stale
    )

    if failures:
        print("FAIL: the direct-model-egress inventory does not match trusted policy\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK: {len(found)} direct model caller(s), no candidate-approved expansion")
    return check_direct_effects.main([])


if __name__ == "__main__":
    raise SystemExit(main())
