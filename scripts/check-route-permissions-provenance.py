#!/usr/bin/env python3
"""Trusted-base enforcement for the route-permission gap ratchet (#542, #319).

`check-route-permissions.py` keeps its app walk, registry validation and
candidate-ledger bookkeeping; this adapter owns the trusted-base comparison so
a candidate cannot quiet a new undeclared-prefix gap by editing its own
baseline. The reviewed specification ledgers (``route-permissions.json``,
``public-routes.json``) stay candidate-authored: editing the declaration is the
substantive change under review.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-route-permissions.py"
# Keep the dynamically loaded checker visible to the tooling reachability graph.
CHECKER_TOOL = "check-route-permissions"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "route-permissions"
METRIC_DEFINITION_VERSION = "1"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {path}")
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _tolerated(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    tolerated = payload.get("tolerated")
    return {str(key) for key in tolerated} if isinstance(tolerated, dict) else set()


def main() -> int:
    checker = _load(CHECKER, CHECKER_TOOL)
    prov = _load(PROVENANCE, "_ratchet_provenance")

    gaps, import_error = checker.collect_gaps()
    if import_error is not None:
        print(f"FAIL: {import_error}", file=sys.stderr)
        return 1
    current = {item.key(): item.detail for item in gaps}
    candidate = checker._load_baseline()

    try:
        trusted_ref = prov.resolve_baseline(checker.BASELINE, root=ROOT)
        trusted = _tolerated(trusted_ref.loads(default={"tolerated": {}}))
        prov.require_measurement(
            checker._collect_prefixes()[0], ratchet=RATCHET, what="mounted route prefixes"
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(set(current) - trusted)
    unauthorized = [key for key in added if key not in authorized]
    candidate_new = sorted(set(current) - set(candidate))
    candidate_stale = sorted(set(candidate) - set(current))

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="mounted-prefix registry audit",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} reviewed tolerated gap(s)",
            new_value=f"{len(current)} current gap(s)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(f"{key}: {authorized[key]}" for key in added if key in authorized),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{key}: NEW route-permission gap absent from trusted base and not previously authorized"
        for key in unauthorized
    )
    failures.extend(f"{key}: current gap missing from candidate ledger" for key in candidate_new)
    failures.extend(
        f"{key}: stale candidate ledger entry must be pruned" for key in candidate_stale
    )

    if failures:
        print("FAIL: route-permissions ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {len(current)} gap(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
