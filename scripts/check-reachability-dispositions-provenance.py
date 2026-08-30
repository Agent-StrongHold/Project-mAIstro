#!/usr/bin/env python3
"""Trusted-base enforcement for reachability dispositions (#542, #319).

A module newly admitted as unreachable needs one prior ``reachability``
authorization. That same authorization permits adding its required disposition
in the subsequent change; the baseline and disposition row should land together,
not require two independent permission merges for the same debt identity.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-reachability-dispositions.py"
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


def _disposition_modules(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return set()
    modules: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        values = group.get("modules")
        if isinstance(values, list):
            modules.update(str(item) for item in values)
    return modules


def main() -> int:
    checker = _load(CHECKER, "_reachability_dispositions_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    candidate_baseline = _unreachable(json.loads(checker.BASELINE.read_text(encoding="utf-8")))
    candidate_ledger_payload: dict[str, Any] = json.loads(
        checker.LEDGER.read_text(encoding="utf-8")
    )
    candidate_modules = _disposition_modules(candidate_ledger_payload)
    shape_failures = checker.audit(
        candidate_ledger_payload, candidate_baseline, checker.matrix_subsystems()
    )

    try:
        trusted_baseline_ref = prov.resolve_baseline(checker.BASELINE, root=ROOT)
        trusted_baseline = _unreachable(trusted_baseline_ref.loads(default={"unreachable": []}))
        trusted_ledger_ref = prov.resolve_baseline(checker.LEDGER, root=ROOT)
        trusted_modules = _disposition_modules(trusted_ledger_ref.loads(default={"groups": []}))
        prov.require_measurement(
            candidate_baseline,
            ratchet=RATCHET,
            what="unreachable module baseline",
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_baseline_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added_baseline = sorted(candidate_baseline - trusted_baseline)
    added_dispositions = sorted(candidate_modules - trusted_modules)
    unauthorized_dispositions = [
        module for module in added_dispositions if module not in authorized
    ]
    orphan_new_dispositions = [
        module for module in added_dispositions if module not in candidate_baseline
    ]

    print(
        prov.Provenance(
            ratchet="reachability-dispositions",
            baseline=trusted_ledger_ref,
            tool="disposition ledger",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted_modules)} dispositioned modules",
            new_value=f"{len(candidate_modules)} dispositioned modules",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{module}: {authorized[module]}"
                for module in added_dispositions
                if module in authorized
            ),
        ).render()
    )

    failures = list(shape_failures)
    failures.extend(
        f"{module}: NEW disposition absent from trusted ledger and not covered by an "
        "already-landed reachability authorization"
        for module in unauthorized_dispositions
    )
    failures.extend(
        f"{module}: disposition was added but module is not in candidate reachability baseline"
        for module in orphan_new_dispositions
    )
    failures.extend(
        f"{module}: authorized unreachable addition has no candidate disposition"
        for module in added_baseline
        if module in authorized and module not in candidate_modules
    )

    if failures:
        print("FAIL: reachability dispositions moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"OK: {len(candidate_modules)} unreachable module(s) have dispositions; "
        "new debt uses prior reachability authorization"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
