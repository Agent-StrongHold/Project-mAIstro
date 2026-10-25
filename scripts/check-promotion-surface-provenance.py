#!/usr/bin/env python3
"""Trusted-base enforcement for promotion-surface tolerances (#542, #319)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-promotion-surface.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "promotion-surface"
METRIC_DEFINITION_VERSION = "1"

#: Bounded analyzer implementation manifest (#319): this adapter plus the
#: delegated checker, which dynamically loads the sensitive-path classifier it
#: matches against (checker.CLASSIFIER). The classifier is a fixed sibling
#: file, deliberately part of the measurement implementation.
ANALYZER_MANIFEST = (
    "scripts/check-promotion-surface-provenance.py",
    "scripts/check-promotion-surface.py",
    "packages/maistro-rsi/src/maistro_rsi/sensitive_paths.py",
)


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


def _tool_version(prov: ModuleType) -> str:
    """Implementation identity of the analyzers that reached this verdict (#319)."""
    version: str = prov.bundled_implementation_fingerprint(
        Path(__file__).resolve().parents[1], ANALYZER_MANIFEST
    )
    return version


def _tolerated(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    values = payload.get("tolerated")
    return (
        {str(key): str(value) for key, value in values.items()} if isinstance(values, dict) else {}
    )


def main() -> int:
    checker = _load(CHECKER, "_promotion_surface_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    modules = checker.index_modules()
    candidate_findings, _candidate_tolerated = checker.audit()
    missing_roots = checker._missing_roots(modules)
    if missing_roots:
        print("FAIL: promotion roots are incomplete", file=sys.stderr)
        for finding in missing_roots:
            print(f"  {finding}", file=sys.stderr)
        return 1

    closure = checker.reachable(checker.PROMOTION_ROOTS, modules)
    matcher = checker._matcher()

    try:
        tool_version = _tool_version(prov)
        trusted_ref = prov.resolve_baseline(checker.BASELINE_PATH, root=ROOT)
        trusted = _tolerated(trusted_ref.loads(default={"tolerated": {}}))
        prov.require_measurement(modules, ratchet=RATCHET, what="first-party source modules")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    uncovered, _trusted_stale, trusted_tolerated = checker._coverage(
        closure, modules, trusted, matcher
    )
    symlinked = checker._symlinked_sources(closure, modules)
    unauthorized = [finding for finding in uncovered if finding.path not in authorized]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="promotion import-closure + sensitive-path classifier",
            tool_version=tool_version,
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} tolerated promotion-path module(s)",
            new_value=f"{len(trusted_tolerated) + len(uncovered)} unprotected module(s) in closure",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{finding.path}: {authorized[finding.path]}"
                for finding in uncovered
                if finding.path in authorized
            ),
        ).render()
    )

    failures = list(candidate_findings)
    failures.extend(symlinked)
    failures.extend(unauthorized)
    if failures:
        print("FAIL: promotion surface moved away from trusted state", file=sys.stderr)
        for finding in failures:
            print(f"  {finding}", file=sys.stderr)
        if unauthorized:
            print(
                "  New unprotected promotion-path modules require an already-landed authorization; candidate baseline edits cannot approve them.",
                file=sys.stderr,
            )
        return 1

    print(f"OK: {len(closure)} promotion-path module(s), no candidate-approved tolerance expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
