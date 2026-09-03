#!/usr/bin/env python3
"""Freeze direct model-egress modules against a trusted base revision (#542, #319).

A candidate may not add a direct model caller and approve that escape by adding
the same module to quality/model-egress.json. Expansions are judged against the
merge-base inventory and require a separately landed authorization. Candidate
bookkeeping is checked independently so migrated callers must still be pruned.

A module move that carries already-reviewed egress verbatim to a new home is
not an expansion when the trusted base records the predecessor and the
candidate prunes it; CANDIDATE_MIGRATIONS is that operator-approved record,
scoped per move so it can never authorize a caller that did not exist before.
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

# An operator-approved record of a direct caller whose egress moved verbatim
# to a new module in a convergence PR, judged against the trusted base. This
#: An operator-approved record of a direct caller whose egress moved verbatim
#: to a new module in a convergence PR, judged against the trusted base. This
#: mirrors the CANDIDATE_AUTHORED design in check-ratchet-provenance.py: the
#: mapping is scoped to exactly one reviewed move and lands atomically with
#: the code that performs it. It is NOT an authorization to grow the set:
#: `_migration_predecessor` honors it only while the predecessor is recorded
#: in the trusted base AND has been pruned from the candidate inventory, so a
#: rename can relocate a caller but never add one (#835: graph_runner's
#: compatibility helpers moved into the legacy_dag_node adapter; #56:
#: llm_summarize's model HTTP moved into the approved llm_gateway Provider).
CANDIDATE_MIGRATIONS: dict[str, str] = {
    "services.legacy_dag_node": "services.graph_runner",
    "maistro.capabilities.providers.llm_gateway": "maistro.graph.nodes.llm_summarize",
}

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


def _migration_predecessor(module: str, *, trusted: set[str], candidate: set[str]) -> str | None:
    """The trusted-base module whose egress moved into `module`, or None.

    The exception fires only when both ratchet halves stay intact: the
    predecessor performed direct egress in the trusted base (it is recorded
    there), and the candidate pruned it (it is absent from the candidate
    inventory -- the same requirement `candidate_stale` enforces). Any other
    shape -- no recorded predecessor, an unpruned predecessor, a module with
    no mapping at all -- is not a migration and still requires an
    already-landed authorization.
    """
    predecessor = CANDIDATE_MIGRATIONS.get(module)
    if predecessor is None:
        return None
    if predecessor not in trusted:
        return None
    if predecessor in candidate:
        return None
    return predecessor


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
    migrated = {
        module: predecessor
        for module in added
        if (predecessor := _migration_predecessor(module, trusted=trusted, candidate=candidate))
    }
    unauthorized = [
        module for module in added if module not in authorized and module not in migrated
    ]
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
                [f"{module}: {authorized[module]}" for module in added if module in authorized]
                + [
                    f"{module}: operator-approved migration from {predecessor} "
                    "(predecessor pruned from the candidate inventory; not an expansion)"
                    for module, predecessor in migrated.items()
                ]
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
