#!/usr/bin/env python3
"""Ratchet raw fetch and hand-typed frontend entities (Workspace cutover P0.3, #1048 AC-P3).

Phase 0 requires one generated client and backend entity types from ``types.gen.ts``
only. Until that lands, this gate records the debt and refuses growth:

  * ``raw_fetch`` -- a ``fetch(`` call site outside ``src/lib/``, where the
    shared HTTP helpers live.
  * ``hand_typed`` -- an ``interface`` or ``type`` declaration under
    ``src/pages/`` or ``src/components/``. These are local shapes that should
    eventually come from the OpenAPI document.

The tolerated set in ``quality/frontend-typed-client-baseline.json`` is read from
the trusted merge base (``docs/ci/RATCHET-PROVENANCE.md``). A new call site or
local type fails unless ``quality/ratchet-authorizations.json`` already granted it
at the base. The candidate ledger must match the tree exactly, so a fixed entry
must be deleted in the change that removes the debt.

Run:  uv run python scripts/check-frontend-typed-client.py
Bank: uv run python scripts/check-frontend-typed-client.py --write-baseline
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "packages" / "hive-conductor" / "frontend" / "src"
LIB = FRONTEND / "lib"
TYPES_GEN = FRONTEND / "api" / "types.gen.ts"
BASELINE = ROOT / "quality" / "frontend-typed-client-baseline.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "frontend-typed-client"
METRIC_DEFINITION_VERSION = "1"

_SKIP_PARTS = frozenset({"node_modules", "dist", "build", ".vite"})
_FETCH_RE = re.compile(r"\bfetch\s*\(")
_TYPE_RE = re.compile(r"^\s*(?:export\s+)?(?:interface|type)\s+(\w+)")
_WAIVER = re.compile(r"//\s*frontend-typed-client:\s*allow\s+(?P<reason>\S.*)")


@dataclass(frozen=True)
class Violation:
    kind: str
    path: str
    line_no: int
    subject: str
    detail: str

    def key(self) -> str:
        if self.subject:
            return f"{self.kind}::{self.path}:{self.line_no}:{self.subject}"
        return f"{self.kind}::{self.path}:{self.line_no}"

    def render(self) -> str:
        where = f"{self.path}:{self.line_no}"
        if self.subject:
            return f"  {where}  {self.subject} -- {self.detail}"
        return f"  {where} -- {self.detail}"


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _frontend_sources() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND.rglob(pattern):
            if _SKIP_PARTS.intersection(path.parts):
                continue
            if path.name.endswith(".gen.ts"):
                continue
            files.append(path)
    return sorted(files)


def _is_waived(lines: list[str], index: int) -> bool:
    candidates = [lines[index]]
    if index > 0:
        candidates.append(lines[index - 1])
    return any(_WAIVER.search(line) for line in candidates)


def _scan_raw_fetch(path: Path) -> list[Violation]:
    if path.is_relative_to(LIB):
        return []
    rel = _rel(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Violation] = []
    for index, line in enumerate(lines):
        if _is_waived(lines, index):
            continue
        code = line.split("//", 1)[0]
        if _FETCH_RE.search(code):
            found.append(
                Violation(
                    "raw_fetch",
                    rel,
                    index + 1,
                    "",
                    "bare fetch outside src/lib/",
                )
            )
    return found


def _scan_hand_typed(path: Path) -> list[Violation]:
    rel = _rel(path)
    if not (
        path.is_relative_to(FRONTEND / "pages") or path.is_relative_to(FRONTEND / "components")
    ):
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Violation] = []
    for index, line in enumerate(lines):
        if _is_waived(lines, index):
            continue
        match = _TYPE_RE.match(line)
        if match is None:
            continue
        name = match.group(1)
        found.append(
            Violation(
                "hand_typed",
                rel,
                index + 1,
                name,
                "local interface/type in pages/ or components/",
            )
        )
    return found


def collect_violations() -> tuple[list[Violation], int]:
    """Every violation in the tree, and how many frontend sources were scanned."""
    files = _frontend_sources()
    found: list[Violation] = []
    for path in files:
        found.extend(_scan_raw_fetch(path))
        found.extend(_scan_hand_typed(path))
    return sorted(found, key=lambda item: item.key()), len(files)


def _tolerated(payload: object) -> dict[str, str]:
    tolerated = payload.get("tolerated") if isinstance(payload, dict) else None
    return dict(tolerated) if isinstance(tolerated, dict) else {}


def compare(
    current: set[str], candidate: set[str], trusted: set[str], authorized: set[str]
) -> list[str]:
    added = current - trusted
    failures = [
        f"{key}: NEW frontend typed-client debt absent from the trusted base and not "
        "previously authorized"
        for key in sorted(added - authorized)
    ]
    failures.extend(
        f"{key}: authorized new entry is not recorded in the candidate ledger"
        for key in sorted((added & authorized) - candidate)
    )
    failures.extend(
        f"{key}: current violation missing from candidate ledger"
        for key in sorted(current - candidate)
    )
    failures.extend(
        f"{key}: fixed -- delete it from the candidate ledger"
        for key in sorted(candidate - current)
    )
    return failures


def write_baseline(violations: list[Violation]) -> None:
    raw = sum(1 for item in violations if item.kind == "raw_fetch")
    hand = sum(1 for item in violations if item.kind == "hand_typed")
    payload = {
        "_comment": (
            "Raw fetch and hand-typed frontend entity debt for Workspace cutover P0.3 "
            "(#1048). Judged against the trusted merge base; a fixed entry must be "
            "deleted here."
        ),
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "summary": {"raw_fetch": raw, "hand_typed": hand},
        "tolerated": {item.key(): item.detail for item in violations},
    }
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current violation set in the candidate ledger",
    )
    args = parser.parse_args()

    if not FRONTEND.is_dir():
        print(f"FAIL: frontend sources not found under {FRONTEND}", file=sys.stderr)
        return 1
    if not TYPES_GEN.is_file():
        print(f"FAIL: generated types not found at {TYPES_GEN}", file=sys.stderr)
        return 1

    violations, scanned = collect_violations()
    if args.write_baseline:
        write_baseline(violations)
        print(f"wrote {len(violations)} violation(s) to {BASELINE.relative_to(ROOT)}")
        return 0

    if scanned == 0:
        print("FAIL: no frontend sources scanned; nothing was measured", file=sys.stderr)
        return 1

    current = {item.key() for item in violations}
    candidate_payload = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    )
    candidate = set(_tolerated(candidate_payload))

    prov = _provenance()
    try:
        prov.require_measurement(scanned, ratchet=RATCHET, what="frontend source files")
        trusted_ref = prov.resolve_baseline(BASELINE, root=ROOT)
        trusted_payload = trusted_ref.loads(default={})
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=trusted_payload.get("metric_definition_version")
            if isinstance(trusted_payload, dict)
            else None,
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        trusted = set(_tolerated(trusted_payload))
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    raw_count = sum(1 for item in violations if item.kind == "raw_fetch")
    hand_count = sum(1 for item in violations if item.kind == "hand_typed")
    trusted_raw = sum(1 for key in trusted if key.startswith("raw_fetch::"))
    trusted_hand = sum(1 for key in trusted if key.startswith("hand_typed::"))
    first_introduction = trusted_ref.absent_at_base

    old_value = (
        "no ledger at the trusted base (ratchet introduced by this change)"
        if first_introduction
        else f"{trusted_raw} raw fetch, {trusted_hand} hand-typed (trusted)"
    )
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="static frontend scan",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=old_value,
            new_value=f"{raw_count} raw fetch, {hand_count} hand-typed (current)",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{key}: {authorized[key]}"
                for key in sorted(current - trusted)
                if key in authorized
            ),
        ).render()
    )
    for item in violations:
        print(f"  tolerated · {item.key()} -- {item.detail}")

    if first_introduction:
        failures = [
            f"{key}: current violation missing from candidate ledger"
            for key in sorted(current - candidate)
        ]
        failures.extend(
            f"{key}: fixed -- delete it from the candidate ledger"
            for key in sorted(candidate - current)
        )
    else:
        failures = compare(current, candidate, trusted, set(authorized))
    if failures:
        print(
            f"\nFAIL: {len(failures)} frontend typed-client ratchet problem(s):\n",
            file=sys.stderr,
        )
        print("\n".join(f"  - {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(
        f"ok: {raw_count} raw fetch and {hand_count} hand-typed declaration(s) tolerated, none new"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
