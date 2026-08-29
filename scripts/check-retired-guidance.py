#!/usr/bin/env python3
"""Normative text that an accepted decision retired must not still direct anyone (#386).

`packages/maistro-core/CLAUDE.md` told agents "No `org_id` in core" long after
ADR-068 superseded that shorthand, while the code it governs carried 214
`org_id` references and the schema had shipped the column. It is the
highest-proximity instruction file for that package, so it outranked the root
`CLAUDE.md` decision that corrected it for anyone reading in-directory -- and
the retired phrasing had already propagated into an acceptance criterion in
SPEC-183.

That is the failure this gate exists for, and it is specific: not "these two
documents disagree", which no checker can decide, but "a statement a decision
has *declared* retired is still written as a directive".

The registry (`quality/retired-guidance.json`) is what makes it decidable. Each
entry names a retired pattern, the decision that retired it, and the
replacement. Adding an entry is a deliberate act performed when a decision
supersedes text that lives somewhere else.

## Recording is not directing

A line matching a retired pattern passes when it also carries one of the
entry's `citation_markers` -- the superseding ADR's id, or a word like
"supersedes" or "stale". ADR-019's own correction, root decision 7's
"(Supersedes the older ... shorthand)", and SPEC-227's note that the package
file is stale all say the retired words and all pass, because each names what
replaced it.

So the fix is never to delete the history. Cite the replacement and the line
passes, which is also what leaves a reader able to follow the change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "quality" / "retired-guidance.json"

#: Where normative text lives. Agent-instruction files first, because those are
#: the ones that direct implementation; then the decision and spec records that
#: acceptance criteria are drawn from.
SEARCH_GLOBS = (
    "CLAUDE.md",
    "*/CLAUDE.md",
    "packages/*/CLAUDE.md",
    "packages/*/*/CLAUDE.md",
    ".claude/**/*.md",
    "docs/adr/*.md",
    "docs/specs/*.md",
    "AGENTS.md",
    "packages/*/AGENTS.md",
)


@dataclass(frozen=True)
class Entry:
    id: str
    pattern: re.Pattern[str]
    retired_by: str
    replacement: str
    citation_markers: tuple[str, ...]
    issue: str

    def is_cited(self, line: str) -> bool:
        """True when the line names what replaced the retired statement.

        Case-insensitive and substring-based on purpose: "supersed" catches
        supersedes/superseded/superseding, and an ADR id is matched wherever it
        appears in the sentence.
        """
        lowered = line.lower()
        return any(marker.lower() in lowered for marker in self.citation_markers)


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    line: str
    entry: Entry


def load_entries(registry: Path = REGISTRY) -> list[Entry]:
    payload = json.loads(registry.read_text(encoding="utf-8"))
    entries = []
    for raw in payload["entries"]:
        entries.append(
            Entry(
                id=raw["id"],
                pattern=re.compile(raw["pattern"]),
                retired_by=raw["retired_by"],
                replacement=raw["replacement"],
                citation_markers=tuple(raw.get("citation_markers", ())),
                issue=str(raw.get("issue", "")),
            )
        )
    return entries


def governed_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    seen: set[Path] = set()
    for pattern in SEARCH_GLOBS:
        for path in repo_root.glob(pattern):
            if path.is_file():
                seen.add(path)
    return sorted(seen)


def scan_text(text: str, entries: list[Entry], *, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for entry in entries:
            if entry.pattern.search(line) and not entry.is_cited(line):
                findings.append(Finding(path=path, line_no=line_no, line=line.strip(), entry=entry))
    return findings


def scan(entries: list[Entry], *, repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in governed_files(repo_root):
        # The registry itself states every retired pattern by definition.
        if path.resolve() == REGISTRY.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(text, entries, path=str(path.relative_to(repo_root))))
    return findings


def render(findings: list[Finding], scanned: int, entries: int) -> str:
    if not findings:
        return (
            f"ok: {scanned} governed file(s) carry no retired guidance "
            f"({entries} retired statement(s) checked)"
        )
    lines = [f"FAIL: {len(findings)} line(s) still direct against a retired statement", ""]
    for finding in findings:
        entry = finding.entry
        lines.append(f"  {finding.path}:{finding.line_no}")
        lines.append(f"    {finding.line}")
        lines.append(f"    retired by {entry.retired_by}: {entry.replacement}")
        if entry.issue:
            lines.append(f"    tracked by #{entry.issue}")
        lines.append("")
    lines.append(
        "Rewrite the statement to match what replaced it. To keep the history, "
        "name the superseding decision on the same line — a line that cites its "
        "replacement is recording the change, not directing against it."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args(argv)

    entries = load_entries(args.registry)
    findings = scan(entries)
    print(render(findings, len(governed_files()), len(entries)))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
