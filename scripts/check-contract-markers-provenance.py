#!/usr/bin/env python3
"""Trusted-base enforcement for the contract-marker evidence ledger (#542, #319)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_contract_markers_impl.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "contract-markers"
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


def _categories(payload: object) -> dict[str, dict[str, object]]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("categories")
    if not isinstance(raw, dict):
        return {}
    return {str(name): entry for name, entry in raw.items() if isinstance(entry, dict)}


def _documents(checker: ModuleType) -> list[Path]:
    return [
        path
        for directory in checker.DOC_DIRS
        for path in (ROOT / directory).glob("*.md")
        if path.is_file()
    ]


def main() -> int:
    checker = _load(CHECKER, "_contract_markers_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    findings = checker.collect(ROOT)
    candidate = checker.load_baseline(checker.BASELINE)
    candidate_new, candidate_stale, candidate_unexplained = checker.compare(findings, candidate)

    try:
        trusted_ref = prov.resolve_baseline(checker.BASELINE, root=ROOT)
        trusted_payload = trusted_ref.loads(
            default={"metric_definition_version": METRIC_DEFINITION_VERSION, "categories": {}}
        )
        trusted = _categories(trusted_payload)
        recorded_version = (
            str(trusted_payload.get("metric_definition_version"))
            if isinstance(trusted_payload, dict)
            and trusted_payload.get("metric_definition_version") is not None
            else None
        )
        prov.require_measurement(_documents(checker), ratchet=RATCHET, what="contract documents")
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=recorded_version,
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    new_against_trusted, _trusted_stale, trusted_unexplained = checker.compare(findings, trusted)
    unauthorized = [
        finding for finding in new_against_trusted if finding.as_line() not in authorized
    ]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="contract front matter + pytest marker AST",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{sum(len(entry.get('entries', [])) for entry in trusted.values())} reviewed gap(s)",
            new_value=f"{len(findings)} current gap(s)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{finding.as_line()}: {authorized[finding.as_line()]}"
                for finding in new_against_trusted
                if finding.as_line() in authorized
            ),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{finding.as_line()}: NEW contract-marker gap absent from trusted base and not previously authorized"
        for finding in unauthorized
    )
    failures.extend(f"{finding.as_line()}: missing from candidate ledger" for finding in candidate_new)
    failures.extend(f"{entry}: stale candidate ledger entry must be pruned" for entry in candidate_stale)
    failures.extend(
        f"{category}: candidate category is banked without a disposition"
        for category in candidate_unexplained
    )
    failures.extend(
        f"{category}: trusted category is banked without a disposition"
        for category in trusted_unexplained
    )

    if failures:
        print("FAIL: contract-marker ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {len(findings)} contract-marker gap(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
