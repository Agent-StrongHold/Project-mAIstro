#!/usr/bin/env python3
"""Trusted-base enforcement for the governing-citation ratchet (#542, #319)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-citation-status.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "citation-status"
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


def _identity(problem: object) -> str:
    return f"{problem.source}.{problem.field_name} -> {problem.target}"


def _known(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    values = payload.get("known")
    return {str(value) for value in values} if isinstance(values, list) else set()


def main() -> int:
    checker = _load(CHECKER, "_citation_status_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    corpus = checker._corpus()
    problems = checker.check_citations(corpus)
    current = {_identity(problem) for problem in problems}
    candidate = set(checker._load_baseline().entries)

    try:
        trusted_ref = prov.resolve_baseline(checker.LEDGER, root=ROOT)
        trusted = _known(trusted_ref.loads(default={"known": []}))
        prov.require_measurement(corpus, ratchet=RATCHET, what="governance documents")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(current - trusted)
    unauthorized = [identity for identity in added if identity not in authorized]
    candidate_new = sorted(current - candidate)
    candidate_stale = sorted(candidate - current)

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="registry governing-citation scan",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} reviewed citation exception(s)",
            new_value=f"{len(current)} current citation exception(s)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{identity}: {authorized[identity]}"
                for identity in added
                if identity in authorized
            ),
        ).render()
    )

    failures: list[str] = []
    failures.extend(
        f"{identity}: NEW governing-citation exception absent from trusted base and not previously authorized"
        for identity in unauthorized
    )
    failures.extend(
        f"{identity}: current exception missing from candidate ledger"
        for identity in candidate_new
    )
    failures.extend(
        f"{identity}: stale candidate ledger entry must be pruned"
        for identity in candidate_stale
    )

    if failures:
        print("FAIL: citation-status ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {len(current)} citation exception(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
