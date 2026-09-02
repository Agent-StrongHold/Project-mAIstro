#!/usr/bin/env python3
"""Run Vulture and ratchet reviewed debt against a trusted base revision.

Rules in quality/vulture-baseline.json explain why a static-analysis category is
accepted. Each rule records the exact multiset of reviewed finding identities
(`path::message`, deliberately line-number-independent). New debt is judged
against the ledger as of the merge base, so a candidate cannot make its own
regression green by running ``--update`` and committing the rewritten ledger.

Candidate bookkeeping is still checked separately: stale rows must be removed,
blank/unrecorded debt fails, and ``--update`` remains a convenient way to rewrite
the candidate ledger from a real scan. A deliberate floor raise requires a
separately landed authorization in quality/ratchet-authorizations.json.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "vulture-baseline.json"
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"
_FINDING_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): (?P<message>.*?) \((?P<confidence>\d+)% confidence\)$"
)
_DETAIL_LIMIT = 20
RATCHET = "vulture"
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
class Finding:
    path: str
    line: int
    message: str
    confidence: int

    @classmethod
    def parse(cls, line: str) -> Finding | None:
        match = _FINDING_RE.match(line.strip())
        if not match:
            return None
        return cls(
            path=match.group("path"),
            line=int(match.group("line")),
            message=match.group("message"),
            confidence=int(match.group("confidence")),
        )

    @property
    def stable_key(self) -> str:
        return f"{self.path}::{self.message}"

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message} ({self.confidence}% confidence)"


@dataclass(frozen=True)
class Classification:
    by_rule: dict[str, list[Finding]]
    unclassified: list[Finding]
    never_allowlist: list[Finding]


@dataclass(frozen=True)
class RuleDelta:
    rule_id: str
    added: list[Finding]
    removed: list[str]
    unbanked: bool


def _load_baseline(path: Path = BASELINE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_for(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _matches_rule(finding: Finding, rule: dict[str, Any]) -> bool:
    path_regex = rule.get("path_regex")
    if path_regex and not re.search(str(path_regex), finding.path):
        return False
    message_regex = rule.get("message_regex")
    if message_regex and not re.search(str(message_regex), finding.message):
        return False
    source_needles = rule.get("source_contains_any") or []
    if source_needles:
        source = _source_for(finding.path)
        if not any(str(needle) in source for needle in source_needles):
            return False
    return True


def _run_vulture(args: list[str]) -> list[Finding]:
    cmd = [sys.executable, "-m", "vulture", *args]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    findings = [parsed for line in output.splitlines() if (parsed := Finding.parse(line))]
    if proc.returncode not in (0, 3):
        print(output, file=sys.stderr)
        raise SystemExit(proc.returncode)
    return findings


def _classify(findings: list[Finding], rules: list[dict[str, Any]]) -> Classification:
    by_rule: dict[str, list[Finding]] = {str(rule["id"]): [] for rule in rules}
    unclassified: list[Finding] = []
    never_allowlist: list[Finding] = []
    for finding in findings:
        if "unreachable code" in finding.message:
            never_allowlist.append(finding)
            continue
        matched = next((rule for rule in rules if _matches_rule(finding, rule)), None)
        if matched is None:
            unclassified.append(finding)
            continue
        by_rule[str(matched["id"])].append(finding)
    return Classification(by_rule, unclassified, never_allowlist)


def _rule_deltas(rules: list[dict[str, Any]], classification: Classification) -> list[RuleDelta]:
    deltas: list[RuleDelta] = []
    for rule in rules:
        rule_id = str(rule["id"])
        current_findings = classification.by_rule[rule_id]
        recorded_list = rule.get("findings")
        if not isinstance(recorded_list, list):
            deltas.append(RuleDelta(rule_id, list(current_findings), [], unbanked=True))
            continue
        current = Counter(finding.stable_key for finding in current_findings)
        recorded = Counter(str(entry) for entry in recorded_list)
        added_keys = current - recorded
        removed = sorted((recorded - current).elements())
        added: list[Finding] = []
        budget = dict(added_keys)
        for finding in current_findings:
            if budget.get(finding.stable_key, 0) > 0:
                budget[finding.stable_key] -= 1
                added.append(finding)
        if added or removed:
            deltas.append(RuleDelta(rule_id, added, removed, unbanked=False))
    return deltas


def _write_baseline(baseline: dict[str, Any], classification: Classification) -> None:
    for rule in baseline["rules"]:
        rule.pop("finding_count", None)
        rule.pop("finding_sha256", None)
        rule["findings"] = sorted(
            finding.stable_key for finding in classification.by_rule[str(rule["id"])]
        )
    BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")


def _print_summary(findings: list[Finding], classification: Classification) -> None:
    print("vulture baseline summary:")
    print(f"  total findings: {len(findings)}")
    for rule_id, accepted in sorted(classification.by_rule.items()):
        print(f"  {rule_id}: {len(accepted)}")
    print(f"  unclassified: {len(classification.unclassified)}")
    print(f"  never_allowlist: {len(classification.never_allowlist)}")


def _print_findings(title: str, findings: list[Finding]) -> None:
    if not findings:
        return
    print(f"\n{title}", file=sys.stderr)
    for finding in findings[:50]:
        print(f"  {finding.render()}", file=sys.stderr)


def _print_capped(lines: list[str]) -> None:
    for line in lines[:_DETAIL_LIMIT]:
        print(f"    {line}", file=sys.stderr)
    if len(lines) > _DETAIL_LIMIT:
        print(f"    … and {len(lines) - _DETAIL_LIMIT} more", file=sys.stderr)


def _print_deltas(
    deltas: list[RuleDelta], *, title: str = "Reviewed Vulture debt changed:"
) -> None:
    if not deltas:
        return
    print(f"\n{title}", file=sys.stderr)
    for delta in deltas:
        if delta.unbanked:
            print(
                f"  {delta.rule_id}: has no 'findings' ledger; "
                f"{len(delta.added)} current finding(s) are unrecorded",
                file=sys.stderr,
            )
            _print_capped([finding.render() for finding in delta.added])
            continue
        if delta.added:
            print(
                f"  {delta.rule_id}: {len(delta.added)} NEW identit(y/ies) not in the ledger:",
                file=sys.stderr,
            )
            _print_capped([finding.render() for finding in delta.added])
        if delta.removed:
            print(
                f"  {delta.rule_id}: {len(delta.removed)} recorded identit(y/ies) no longer "
                f"found — prune them:",
                file=sys.stderr,
            )
            _print_capped(delta.removed)


def _finding_count(rules: list[dict[str, Any]]) -> int:
    return sum(len(rule.get("findings") or []) for rule in rules)


def _candidate_has_unbankable_findings(classification: Classification, *, update: bool) -> bool:
    _print_findings("Unreachable-code findings must be fixed:", classification.never_allowlist)
    _print_findings(
        "Unclassified vulture findings need owner/category/rationale:", classification.unclassified
    )
    failed = bool(classification.never_allowlist or classification.unclassified)
    if failed and update:
        print(
            "\n--update refused: unreachable-code and unclassified findings are never "
            "banked — fix or classify them first.",
            file=sys.stderr,
        )
    return failed


def _trusted_state(
    findings: list[Finding], prov: ModuleType
) -> tuple[object, list[dict[str, Any]], dict[str, str]]:
    trusted_ref = prov.resolve_baseline(BASELINE, root=ROOT)
    trusted = trusted_ref.loads(default={"version": int(METRIC_DEFINITION_VERSION), "rules": []})
    if not isinstance(trusted, dict):
        raise prov.RatchetProvenanceError("vulture: trusted ledger is not a JSON object")
    trusted_rules = list(trusted.get("rules") or [])
    prov.require_measurement(findings, ratchet=RATCHET, what="Vulture findings")
    prov.require_metric_version(
        METRIC_DEFINITION_VERSION,
        recorded=str(trusted.get("version")) if trusted.get("version") is not None else None,
        ratchet=RATCHET,
        baseline=trusted_ref,
    )
    authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    return trusted_ref, trusted_rules, authorized


def _report_trusted_result(
    *,
    prov: ModuleType,
    trusted_ref: object,
    trusted_rules: list[dict[str, Any]],
    trusted_added: list[Finding],
    authorized: dict[str, str],
    findings: list[Finding],
    trusted_deltas: list[RuleDelta],
    candidate_deltas: list[RuleDelta],
) -> None:
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="vulture",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{_finding_count(trusted_rules)} reviewed identities",
            new_value=f"{len(findings)} findings",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{finding.stable_key}: {authorized[finding.stable_key]}"
                for finding in trusted_added
                if finding.stable_key in authorized
            ),
        ).render()
    )
    if trusted_added:
        _print_deltas(trusted_deltas, title="Vulture debt changed against the TRUSTED baseline:")
    if candidate_deltas:
        _print_deltas(candidate_deltas, title="Candidate ledger bookkeeping still needs attention:")


def _enforce_trusted(
    findings: list[Finding],
    candidate_rules: list[dict[str, Any]],
    candidate_classification: Classification,
) -> int:
    prov = _provenance()
    try:
        trusted_ref, trusted_rules, authorized = _trusted_state(findings, prov)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    trusted_classification = _classify(findings, trusted_rules)
    _print_findings(
        "Findings not classified by the TRUSTED baseline rules:",
        trusted_classification.unclassified,
    )
    _print_findings(
        "Unreachable-code findings are never authorizable:",
        trusted_classification.never_allowlist,
    )

    trusted_deltas = _rule_deltas(trusted_rules, trusted_classification)
    candidate_deltas = _rule_deltas(candidate_rules, candidate_classification)
    trusted_added = [finding for delta in trusted_deltas for finding in delta.added]
    unauthorized = [finding for finding in trusted_added if finding.stable_key not in authorized]
    candidate_added = [finding for delta in candidate_deltas for finding in delta.added]
    candidate_removed = [entry for delta in candidate_deltas for entry in delta.removed]
    candidate_unbanked_rules = [delta.rule_id for delta in candidate_deltas if delta.unbanked]

    _report_trusted_result(
        prov=prov,
        trusted_ref=trusted_ref,
        trusted_rules=trusted_rules,
        trusted_added=trusted_added,
        authorized=authorized,
        findings=findings,
        trusted_deltas=trusted_deltas,
        candidate_deltas=candidate_deltas,
    )

    if unauthorized:
        print(
            "\nNew Vulture debt is not authorized by the trusted base. Running --update "
            "in this branch cannot authorize it; land a reviewed grant first.",
            file=sys.stderr,
        )
    if candidate_added:
        print("\nAuthorized debt must also be banked in the candidate ledger.", file=sys.stderr)
    if candidate_removed:
        print("\nFixed debt must be pruned from the candidate ledger.", file=sys.stderr)
    if candidate_unbanked_rules:
        print(
            "\nEvery candidate classification rule must carry an explicit findings ledger.",
            file=sys.stderr,
        )

    return int(
        bool(
            trusted_classification.unclassified
            or trusted_classification.never_allowlist
            or unauthorized
            or candidate_added
            or candidate_removed
            or candidate_unbanked_rules
        )
    )


def main(argv: list[str]) -> int:
    update = "--update" in argv
    scan_args = [arg for arg in argv if arg != "--update"]
    scan_args = scan_args or ["packages", "tests", "--exclude", "*/.venv/*"]

    candidate = _load_baseline()
    candidate_rules = list(candidate["rules"])
    findings = _run_vulture(scan_args)
    candidate_classification = _classify(findings, candidate_rules)
    _print_summary(findings, candidate_classification)

    if _candidate_has_unbankable_findings(candidate_classification, update=update):
        return 1
    if update:
        _write_baseline(candidate, candidate_classification)
        print(f"\nwrote {BASELINE} — review the diff before committing")
        return 0
    return _enforce_trusted(findings, candidate_rules, candidate_classification)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
