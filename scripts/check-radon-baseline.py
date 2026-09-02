#!/usr/bin/env python3
"""Run Radon and ratchet reviewed complexity against a trusted base revision.

New or increased complexity is judged against quality/radon-baseline.json as of
the merge base. Candidate edits therefore cannot rewrite the oracle that judges
them. Candidate bookkeeping is checked separately so improvements still have to
shrink the ledger and an authorized increase must be recorded at its exact new
complexity before merge.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "radon-baseline.json"
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"
PASSING_RANKS = {"A", "B"}
RATCHET = "radon"
METRIC_DEFINITION_VERSION = "1"


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


@dataclass(frozen=True)
class Block:
    path: str
    line: int
    name: str
    classname: str | None
    rank: str
    complexity: int

    @property
    def key(self) -> str:
        qualified = f"{self.classname}.{self.name}" if self.classname else self.name
        return f"{self.path}::{qualified}"

    @property
    def authorization_key(self) -> str:
        # A grant for complexity 12 must not silently authorize 13 later.
        return f"{self.key}@{self.complexity}"

    def render(self) -> str:
        return f"{self.path}:{self.line} {self.name} -> {self.rank} ({self.complexity})"


@dataclass(frozen=True)
class Comparison:
    new_findings: list[Block]
    regressions: list[tuple[Block, int]]
    improvements: list[tuple[Block, int]]
    stale: list[str]

    @property
    def failed(self) -> bool:
        return bool(self.new_findings or self.regressions or self.improvements or self.stale)


def _load_baseline(path: Path = BASELINE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _entries(loaded: dict[str, Any]) -> dict[str, Any]:
    return {entry["key"]: entry for entry in loaded.get("entries", [])}


def _flatten(path: str, items: list[dict[str, Any]]) -> list[Block]:
    blocks: list[Block] = []
    for item in items:
        classname = item["classname"] if item["type"] == "method" else None
        blocks.append(
            Block(path, item["lineno"], item["name"], classname, item["rank"], item["complexity"])
        )
    return blocks


def _run_radon(args: list[str]) -> list[Block]:
    cmd = [sys.executable, "-m", "radon", "cc", "-j", *args]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    data = json.loads(proc.stdout)
    blocks: list[Block] = []
    for path, items in data.items():
        blocks.extend(_flatten(path, items))
    return blocks


def _compare(findings: list[Block], baseline: dict[str, Any]) -> Comparison:
    new_findings: list[Block] = []
    regressions: list[tuple[Block, int]] = []
    improvements: list[tuple[Block, int]] = []

    for block in findings:
        recorded = baseline.get(block.key)
        if recorded is None:
            new_findings.append(block)
            continue
        baseline_complexity = int(recorded["complexity"])
        if block.complexity > baseline_complexity:
            regressions.append((block, baseline_complexity))
        elif block.complexity < baseline_complexity:
            improvements.append((block, baseline_complexity))

    seen_keys = {block.key for block in findings}
    stale = [key for key in baseline if key not in seen_keys]
    return Comparison(new_findings, regressions, improvements, stale)


def _print_summary(findings: list[Block], baseline: dict[str, Any], result: Comparison) -> None:
    print("radon baseline summary:")
    print(f"  current C/D/E/F blocks: {len(findings)}")
    print(f"  baseline entries: {len(baseline)}")
    print(f"  new (unbaselined) findings: {len(result.new_findings)}")
    print(f"  regressed (more complex than baseline) findings: {len(result.regressions)}")
    print(f"  improved (baseline must shrink) findings: {len(result.improvements)}")
    print(f"  stale baseline entries (must be pruned): {len(result.stale)}")


def _print_block_group(title: str, blocks: list[Block]) -> None:
    if not blocks:
        return
    print(f"\n{title}", file=sys.stderr)
    for block in blocks[:50]:
        print(f"  {block.render()}", file=sys.stderr)


def _print_delta_group(title: str, deltas: list[tuple[Block, int]], improvement: bool) -> None:
    if not deltas:
        return
    print(f"\n{title}", file=sys.stderr)
    for block, baseline_complexity in deltas[:50]:
        suffix = (
            f"baseline: {baseline_complexity}; lower it to {block.complexity}"
            if improvement
            else f"baseline: {baseline_complexity}"
        )
        print(f"  {block.render()} ({suffix})", file=sys.stderr)


def _print_details(result: Comparison) -> None:
    _print_block_group("New complexity findings with no baseline entry:", result.new_findings)
    _print_delta_group(
        "Complexity regressions vs. recorded baseline:", result.regressions, improvement=False
    )
    _print_delta_group(
        "Complexity improvements not yet ratcheted into the baseline:",
        result.improvements,
        improvement=True,
    )
    if result.stale:
        print("\nStale baseline entries that must be removed:", file=sys.stderr)
        for key in result.stale[:50]:
            print(f"  {key}", file=sys.stderr)


def main(argv: list[str]) -> int:
    scan_args = argv or ["packages/maistro-core/src"]
    candidate_loaded = _load_baseline()
    candidate = _entries(candidate_loaded)
    findings = [block for block in _run_radon(scan_args) if block.rank not in PASSING_RANKS]

    prov = _provenance()
    try:
        trusted_ref = prov.resolve_baseline(BASELINE, root=ROOT)
        trusted_loaded = trusted_ref.loads(default={"entries": []})
        if not isinstance(trusted_loaded, dict):
            raise prov.RatchetProvenanceError("radon: trusted ledger is not a JSON object")
        trusted = _entries(trusted_loaded)
        prov.require_measurement(findings, ratchet=RATCHET, what="complexity blocks")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    trusted_result = _compare(findings, trusted)
    candidate_result = _compare(findings, candidate)
    raises = [
        *trusted_result.new_findings,
        *(block for block, _old in trusted_result.regressions),
    ]
    unauthorized = [block for block in raises if block.authorization_key not in authorized]

    _print_summary(findings, trusted, trusted_result)
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="radon cc -j",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} reviewed C-or-worse blocks",
            new_value=f"{len(findings)} C-or-worse blocks",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{block.authorization_key}: {authorized[block.authorization_key]}"
                for block in raises
                if block.authorization_key in authorized
            ),
        ).render()
    )

    # New debt/regressions are judged only against the trusted base. Candidate
    # improvements/stale rows are bookkeeping and still must tighten immediately.
    _print_block_group("New complexity vs. TRUSTED baseline:", trusted_result.new_findings)
    _print_delta_group(
        "Complexity regressions vs. TRUSTED baseline:",
        trusted_result.regressions,
        improvement=False,
    )
    _print_delta_group(
        "Complexity improvements not banked in candidate ledger:",
        candidate_result.improvements,
        improvement=True,
    )
    if candidate_result.stale:
        print("\nStale candidate baseline entries that must be removed:", file=sys.stderr)
        for key in candidate_result.stale[:50]:
            print(f"  {key}", file=sys.stderr)

    if unauthorized:
        print(
            "\nNew/increased complexity is not authorized by the trusted base. "
            "Land a grant keyed as '<qualified-block>@<new-complexity>' first.",
            file=sys.stderr,
        )

    # Even an authorized raise has to be recorded in the candidate ledger at
    # the exact measured value so the next merge inherits the new floor.
    unbanked_authorized = [
        block
        for block in raises
        if block.authorization_key in authorized
        and (
            block.key not in candidate
            or int(candidate[block.key].get("complexity", -1)) != block.complexity
        )
    ]
    if unbanked_authorized:
        print("\nAuthorized complexity raises must also be banked in this ledger.", file=sys.stderr)

    return int(
        bool(
            unauthorized
            or unbanked_authorized
            or candidate_result.new_findings
            or candidate_result.regressions
            or candidate_result.improvements
            or candidate_result.stale
        )
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
