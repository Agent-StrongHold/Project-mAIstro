#!/usr/bin/env python3
"""Run Vulture and require the reviewed per-identity debt ledger to match exactly.

Rules in quality/vulture-baseline.json explain why a static-analysis category is
accepted. Each rule also records the exact multiset of reviewed finding
identities (`path::message`, deliberately line-number-independent so unrelated
code motion doesn't trip the gate). A finding with no recorded identity fails CI
by name; an identity that no longer occurs also fails CI by name until it is
pruned — the ledger can only shrink, and every change is legible in the PR diff
as the specific symbol that entered or left. High-confidence unreachable code is
never allowlisted.

Bank a reviewed change with `--update`, which rewrites each rule's `findings`
from an actual scan — never by editing entries by hand to match a delta.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "vulture-baseline.json"
_FINDING_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): (?P<message>.*?) \((?P<confidence>\d+)% confidence\)$"
)
_DETAIL_LIMIT = 20


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
class RuleDelta:
    rule_id: str
    added: list[Finding]
    removed: list[str]
    unbanked: bool  # rule has no "findings" ledger at all


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


def _rule_deltas(rules: list[dict[str, Any]], classification: Classification) -> list[RuleDelta]:
    """Compare each rule's current identity multiset against its recorded ledger."""
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
        # Report each new identity with its live line/confidence so it can be
        # located; a duplicate key surfaces once per unrecorded occurrence.
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


def _print_deltas(deltas: list[RuleDelta]) -> None:
    if not deltas:
        return
    print("\nReviewed Vulture debt changed:", file=sys.stderr)
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
    print(
        "\nEvery ledger change is per-identity: a new finding needs review, and a fixed one "
        "must shrink the ledger in the same PR (stale entries would silently absorb a later "
        "regression). Bank a reviewed state with: "
        "scripts/check-vulture-baseline.py --update <scan args>",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    update = "--update" in argv
    scan_args = [arg for arg in argv if arg != "--update"]
    scan_args = scan_args or ["packages", "tests", "--exclude", "*/.venv/*"]
    baseline = _load_baseline()
    rules = baseline["rules"]
    findings = _run_vulture(scan_args)
    classification = _classify(findings, rules)

    _print_summary(findings, classification)
    _print_findings("Unreachable-code findings must be fixed:", classification.never_allowlist)
    _print_findings(
        "Unclassified vulture findings need owner/category/rationale:",
        classification.unclassified,
    )

    if classification.never_allowlist or classification.unclassified:
        if update:
            print(
                "\n--update refused: unreachable-code and unclassified findings are never "
                "banked — fix or classify them first.",
                file=sys.stderr,
            )
        return 1

    if update:
        _write_baseline(baseline, classification)
        print(f"\nwrote {BASELINE} — review the diff before committing")
        return 0

    deltas = _rule_deltas(rules, classification)
    _print_deltas(deltas)
    return int(bool(deltas))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
