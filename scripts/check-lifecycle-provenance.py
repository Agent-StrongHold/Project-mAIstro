#!/usr/bin/env python3
"""Trusted-base adapter for the ADR/spec lifecycle ratchet (#542, #319)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "lint_lifecycle.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "lifecycle"
METRIC_DEFINITION_VERSION = "1"
_ROOTS = ["docs/adr", "docs/specs"]


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


def _violations(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("violations", {})
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    return set()


def main() -> int:
    checker = _load(CHECKER, "_lifecycle_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    documents = [
        path
        for root in _ROOTS
        for path in sorted((ROOT / root).glob("*.md"))
        if path.name.startswith(("ADR-", "SPEC-"))
    ]
    current_errors = checker.collect_errors(_ROOTS)
    current = set(current_errors)
    candidate = checker.load_baseline()

    try:
        prov.require_measurement(documents, ratchet=RATCHET, what="ADR/spec lifecycle corpus")
        trusted_ref = prov.resolve_baseline(checker.BASELINE, root=ROOT)
        trusted = _violations(trusted_ref.loads(default={"violations": {}}))
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    candidate_new, candidate_stale = checker.apply_baseline(current_errors, candidate)
    trusted_new = sorted(current - trusted)

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="tools/lint_lifecycle.py",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} accepted lifecycle violation(s)",
            new_value=f"{len(current)} current lifecycle violation(s)",
            candidate_sha=prov.head_sha(ROOT),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{item}: NEW lifecycle violation absent from trusted base" for item in trusted_new
    )
    failures.extend(
        f"{item}: current violation missing from candidate ledger" for item in candidate_new
    )
    failures.extend(
        f"{item}: stale candidate lifecycle entry must be pruned" for item in candidate_stale
    )
    if failures:
        print("FAIL: lifecycle ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"OK: {len(current)} lifecycle violation(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
