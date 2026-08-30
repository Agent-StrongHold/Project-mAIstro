#!/usr/bin/env python3
"""Trusted-base enforcement wrapper for check-reachability.py (#542, #319)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-reachability.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "reachability"
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


def _unreachable(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    values = payload.get("unreachable")
    return {str(item) for item in values} if isinstance(values, list) else set()


def main() -> int:
    checker = _load(CHECKER, "_reachability_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    mods, seen = checker._reachability(
        checker.ROOT, checker.FLAT_APPS, checker.STATIC_ROOTS, checker.DYNAMIC_ROOTS
    )
    current = set(mods) - seen
    candidate_payload = json.loads(checker.BASELINE.read_text(encoding="utf-8"))
    candidate = _unreachable(candidate_payload)

    candidate_unknown = checker.unknown_baseline_entries(candidate, set(mods))
    candidate_added = sorted(current - candidate)
    candidate_removed = sorted(
        candidate - current - {entry for entry, _suggestion in candidate_unknown}
    )

    try:
        trusted_ref = prov.resolve_baseline(checker.BASELINE, root=ROOT)
        trusted = _unreachable(trusted_ref.loads(default={"unreachable": []}))
        prov.require_measurement(mods, ratchet=RATCHET, what="production module universe")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(current - trusted)
    unauthorized = [module for module in added if module not in authorized]
    unbanked_authorized = [
        module for module in added if module in authorized and module not in candidate
    ]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python import graph",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} unreachable modules",
            new_value=f"{len(current)} unreachable of {len(mods)} modules",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{module}: {authorized[module]}" for module in added if module in authorized
            ),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{module}: NEW unreachable module absent from trusted base and not previously authorized"
        for module in unauthorized
    )
    failures.extend(
        f"{module}: authorized unreachable addition is not banked in candidate baseline"
        for module in unbanked_authorized
    )
    failures.extend(
        f"{module}: current unreachable module missing from candidate baseline"
        for module in candidate_added
    )
    failures.extend(
        f"{module}: now reachable; prune from candidate baseline" for module in candidate_removed
    )
    failures.extend(
        f"{entry}: candidate baseline identity resolves to no module"
        + (f"; use {suggestion}" if suggestion else "")
        for entry, suggestion in candidate_unknown
    )

    if failures:
        print("FAIL: reachability ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {len(current)} unreachable module(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
