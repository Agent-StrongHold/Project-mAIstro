#!/usr/bin/env python3
"""Trusted-base enforcement wrapper for check_enumerations.py (#542, #319).

The mature enumeration checker owns discovery and candidate-ledger tidiness. This
wrapper adds the missing monotonicity question without duplicating that large
measurement implementation: which gaps are new relative to the merge-base
ledger? A candidate may record a new gap for review, but it cannot authorize that
gap in the same change.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_enumerations.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "enumerations"
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


def main() -> int:
    checker = _load(CHECKER, "_enumerations_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    all_gaps: list[object] = []
    unavailable: list[tuple[str, str]] = []
    executed: list[str] = []
    for name, fn in checker.CHECKS.items():
        gaps, reason = fn()
        executed.append(name)
        if reason:
            unavailable.append((name, reason))
        all_gaps.extend(gaps)
    if unavailable:
        print("FAIL: enumeration checks could not run", file=sys.stderr)
        for name, reason in unavailable:
            print(f"  - {name}: {reason}", file=sys.stderr)
        return 1

    current = {gap.key(): gap for gap in all_gaps}
    candidate = checker.load_baseline()
    candidate_new = sorted(set(current) - set(candidate))
    candidate_stale = sorted(set(candidate) - set(current))

    try:
        trusted_ref = prov.resolve_baseline(checker.BASELINE_PATH, root=ROOT)
        trusted_payload = trusted_ref.loads(default={"tolerated": {}})
        trusted = (
            dict(trusted_payload.get("tolerated", {}))
            if isinstance(trusted_payload, dict)
            and isinstance(trusted_payload.get("tolerated", {}), dict)
            else {}
        )
        # A clean tree legitimately has zero gaps. Measurement completeness is
        # proven by the non-empty check registry plus the unavailable-result
        # guard above, not by requiring a violation to exist forever.
        prov.require_measurement(executed, ratchet=RATCHET, what="enumeration checks executed")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(set(current) - set(trusted))
    unauthorized = [key for key in added if key not in authorized]
    unbanked_authorized = [key for key in added if key in authorized and key not in candidate]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="enumeration property checks",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} tolerated gaps",
            new_value=f"{len(current)} current gaps",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(f"{key}: {authorized[key]}" for key in added if key in authorized),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{key}: NEW enumeration gap absent from trusted base and not previously authorized"
        for key in unauthorized
    )
    failures.extend(
        f"{key}: authorized new gap is not recorded in the candidate ledger"
        for key in unbanked_authorized
    )
    failures.extend(f"{key}: current gap missing from candidate ledger" for key in candidate_new)
    failures.extend(f"{key}: stale candidate ledger entry must be pruned" for key in candidate_stale)

    if failures:
        print("FAIL: enumeration ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {len(current)} enumeration gap(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
