#!/usr/bin/env python3
"""Trusted-base enforcement for the ADR body-status-language ratchet (#387, #542, #319).

``check-adr-status-language.py`` measures legacy body ``**Status:**``
contradictions against ``quality/adr-status-language-baseline.json``. Reading
both the measurement and the ledger from the candidate tree would let one
commit widen its own tolerance, so this adapter resolves the ledger from the
trusted base exactly like the governing-citation ratchet.

One bootstrap rule is specific to this ratchet: the ledger is new in #387's
change, and "absent at the base" is a real answer — a genuinely new ratchet
whose trusted baseline is therefore empty. Treating that emptiness as the
reviewed tolerance would fail the introducing change for identities nothing at
the base ever constrained. Instead the introducing change is itself the review
of the initial ledger: it must bank the corpus exactly, with no hidden
contradictions and no stale entries. From the next change on the ledger exists
at the trusted base and the strict comparison applies — expansion requires a
landed grant (two-merge protocol, #534).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-adr-status-language.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "adr-status-language"
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


def _corpus(checker: ModuleType) -> list[Path]:
    """Every document the scan is pointed at, so an empty corpus is a failure."""
    return sorted(path for root in checker.DOC_ROOTS for path in sorted(root.glob("*.md")))


def _known(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    values = payload.get("known")
    return {str(value) for value in values} if isinstance(values, list) else set()


def main() -> int:
    checker = _load(CHECKER, "_adr_status_language_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    corpus = _corpus(checker)
    problems = checker.audit()
    current = {problem.identity for problem in problems}
    candidate = set(checker._load_baseline())

    try:
        trusted_ref = prov.resolve_baseline(checker.LEDGER, root=ROOT)
        trusted = _known(trusted_ref.loads(default={"known": []}))
        prov.require_measurement(corpus, ratchet=RATCHET, what="ADR and spec documents")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    first_introduction = trusted_ref.absent_at_base
    old_value = (
        "no ledger at the trusted base (ratchet introduced by this change)"
        if first_introduction
        else f"{len(trusted)} reviewed body-status contradiction(s)"
    )

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="ADR body-status language scan",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=old_value,
            new_value=f"{len(current)} current body-status contradiction(s)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{identity}: {authorized[identity]}"
                for identity in sorted(current - trusted)
                if identity in authorized
            ),
        ).render()
    )

    failures: list[str] = []
    if first_introduction:
        failures.extend(
            f"{identity}: contradiction hidden from the reviewed initial ledger"
            for identity in sorted(current - candidate)
        )
        failures.extend(
            f"{identity}: stale initial-ledger entry must be pruned"
            for identity in sorted(candidate - current)
        )
    else:
        added = sorted(current - trusted)
        unauthorized = [identity for identity in added if identity not in authorized]
        failures.extend(
            f"{identity}: NEW body-status contradiction absent from trusted base and not previously authorized"
            for identity in unauthorized
        )
        failures.extend(
            f"{identity}: current contradiction missing from candidate ledger"
            for identity in sorted(current - candidate)
        )
        failures.extend(
            f"{identity}: stale candidate ledger entry must be pruned"
            for identity in sorted(candidate - current)
        )

    if failures:
        print("FAIL: adr-status-language ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    if first_introduction:
        print(
            f"OK: {len(current)} contradiction(s) banked as the reviewed initial "
            "ledger (first introduction); expansion hereafter needs a landed grant"
        )
    else:
        print(f"OK: {len(current)} contradiction(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
