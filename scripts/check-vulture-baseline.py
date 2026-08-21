#!/usr/bin/env python3
"""Run Vulture and require an exact, monotonic reviewed debt ledger.

Rules in quality/vulture-baseline.json explain why a static-analysis category is
accepted. Each rule also records the count and SHA-256 digest of the sorted
stable finding-identity multiset. Count catches growth and unbanked improvement;
the digest catches same-count substitution. High-confidence unreachable code is
never allowlisted.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "vulture-baseline.json"
_FINDING_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): (?P<message>.*?) \((?P<confidence>\d+)% confidence\)$"
)


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
        """Identity that survives unrelated line movement while retaining symbol identity."""
        return f"{self.path}::{self.message}"

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message} ({self.confidence}% confidence)"


@dataclass(frozen=True)
class Classification:
    by_rule: dict[str, list[Finding]]
    unclassified: list[Finding]
    never_allowlist: list[Finding]


@dataclass(frozen=True)
class RuleLedger:
    rule_id: str
    finding_count: int
    finding_sha256: str


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


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


def _ledger(rule_id: str, findings: list[Finding]) -> RuleLedger:
    identities = sorted(finding.stable_key for finding in findings)
    payload = "\n".join(identities).encode("utf-8")
    return RuleLedger(rule_id, len(identities), hashlib.sha256(payload).hexdigest())


def _ledger_failures(
    rules: list[dict[str, Any]], classification: Classification
) -> tuple[list[RuleLedger], list[tuple[RuleLedger, int, str]]]:
    missing: list[RuleLedger] = []
    changed: list[tuple[RuleLedger, int, str]] = []
    for rule in rules:
        rule_id = str(rule["id"])
        current = _ledger(rule_id, classification.by_rule[rule_id])
        expected_count = rule.get("finding_count")
        expected_digest = rule.get("finding_sha256")
        if not isinstance(expected_count, int) or not isinstance(expected_digest, str):
            missing.append(current)
            continue
        if current.finding_count != expected_count or current.finding_sha256 != expected_digest:
            changed.append((current, expected_count, expected_digest))
    return missing, changed


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


def _print_ledger_failures(
    missing: list[RuleLedger], changed: list[tuple[RuleLedger, int, str]]
) -> None:
    if missing:
        print("\nRules missing exact count+digest ledger values:", file=sys.stderr)
        for item in missing:
            print(
                f'  {item.rule_id}: "finding_count": {item.finding_count}, '
                f'"finding_sha256": "{item.finding_sha256}"',
                file=sys.stderr,
            )
    if changed:
        print("\nReviewed Vulture debt changed:", file=sys.stderr)
        for current, expected_count, expected_digest in changed:
            direction = "grew" if current.finding_count > expected_count else "shrunk"
            if current.finding_count == expected_count:
                direction = "changed identity at constant count"
            print(
                f"  {current.rule_id}: {direction}; expected count={expected_count} "
                f"sha256={expected_digest}, current count={current.finding_count} "
                f"sha256={current.finding_sha256}",
                file=sys.stderr,
            )
        print(
            "\nAny improvement must be banked by lowering the count and updating the digest in "
            "the same PR. Same-count substitutions require explicit review.",
            file=sys.stderr,
        )


def main(argv: list[str]) -> int:
    scan_args = argv or ["packages", "tests", "--exclude", "*/.venv/*"]
    rules = _load_baseline()["rules"]
    findings = _run_vulture(scan_args)
    classification = _classify(findings, rules)
    missing, changed = _ledger_failures(rules, classification)

    _print_summary(findings, classification)
    _print_findings("Unreachable-code findings must be fixed:", classification.never_allowlist)
    _print_findings(
        "Unclassified vulture findings need owner/category/rationale:",
        classification.unclassified,
    )
    _print_ledger_failures(missing, changed)

    failed = bool(
        classification.never_allowlist or classification.unclassified or missing or changed
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
