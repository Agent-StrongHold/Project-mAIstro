#!/usr/bin/env python3
"""Trusted-base enforcement for governed shell execution (#542, #319)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-shell-execution.py"
PROVENANCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "shell-execution"
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


def _declared(payload: object) -> set[tuple[str, str]]:
    if not isinstance(payload, dict):
        return set()
    entries = payload.get("calls")
    if not isinstance(entries, list):
        return set()
    return {
        (str(entry.get("file")), str(entry.get("symbol")))
        for entry in entries
        if isinstance(entry, dict) and entry.get("file") and entry.get("symbol")
    }


def _identity(item: tuple[str, str]) -> str:
    return f"{item[0]}::{item[1]}"


def _measured_files(checker: ModuleType) -> list[Path]:
    files: list[Path] = []
    for tree_root in checker.GOVERNED:
        base = ROOT / tree_root
        if not base.is_dir():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts and not checker._is_test(path.relative_to(ROOT))
        )
    return files


def main() -> int:
    checker = _load(CHECKER, "_shell_execution_under_provenance")
    prov = _load(PROVENANCE, "_ratchet_provenance")

    current = checker.discovered()
    try:
        candidate_payload = json.loads(checker.LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: candidate shell ledger could not be read: {exc}", file=sys.stderr)
        return 1
    candidate = _declared(candidate_payload)
    candidate_failures = checker.audit()

    try:
        trusted_ref = prov.resolve_baseline(checker.LEDGER, root=ROOT)
        trusted = _declared(trusted_ref.loads(default={"calls": []}))
        prov.require_measurement(
            _measured_files(checker), ratchet=RATCHET, what="governed Python source files"
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(current - trusted)
    unauthorized = [item for item in added if _identity(item) not in authorized]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python AST shell= scan",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} reviewed shell call(s)",
            new_value=f"{len(current)} current shell call(s)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{_identity(item)}: {authorized[_identity(item)]}"
                for item in added
                if _identity(item) in authorized
            ),
        ).render()
    )

    failures = list(candidate_failures)
    failures.extend(
        f"  {_identity(item)}: NEW shell execution absent from trusted base and not previously authorized"
        for item in unauthorized
    )
    for item in sorted(current - candidate):
        failures.append(
            f"  {_identity(item)}: current shell execution missing from candidate ledger"
        )
    for item in sorted(candidate - current):
        failures.append(f"  {_identity(item)}: stale candidate shell approval must be pruned")

    if failures:
        print("FAIL: shell-execution ratchet moved away from trusted state", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"OK: {len(current)} shell execution(s), no candidate-approved expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
