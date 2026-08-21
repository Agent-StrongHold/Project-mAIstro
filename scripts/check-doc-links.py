#!/usr/bin/env python3
"""Fail on a markdown link whose relative target does not exist.

The registry gate (`maistro-registry`) validates *front-matter* relationships —
`supersedes`, `depends_on`, and friends. It never resolves the ordinary prose
links in a document body, so a renamed ADR silently leaves dead `[ADR-071](...)`
links behind it in every spec that referenced the old filename. This closes that
gap.

Only *relative* targets are checked. External URLs are somebody else's uptime
problem, and anchors are not resolved — a `#section` fragment is stripped and
the file itself is what must exist.

Two things are deliberately skipped, because both produce false positives that
would train people to ignore this gate:

- **Inline code and fenced blocks.** A redaction regex such as
  `[?&](api_key\\|token)=\\S+` is not a link, but it parses as one. Code spans
  are blanked before scanning.
- **Paths in `ALLOWED_OUTSIDE_REPO`.** A few runbooks intentionally point at
  sibling checkouts that only exist on a deployed host.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that are not ours to police.
SKIP_DIRS = {".git", ".venv", "node_modules", "site-packages", "__pycache__"}

# Relative targets that intentionally resolve outside this repository — they
# point at sibling checkouts present only on a deployed host. Keyed by the
# document that may reference them, so an unrelated file cannot inherit the
# exemption.
ALLOWED_OUTSIDE_REPO: dict[str, set[str]] = {}

FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"`[^`]*`")
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(\s*<?([^)>\s]+?)>?\s*(?:\"[^\"]*\")?\s*\)")


def _strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, preserving line numbers."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else CODE_SPAN.sub("", line))
    return "\n".join(out)


def _markdown_files() -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob("*.md")
        if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)
    )


def _broken_links(path: Path) -> list[tuple[int, str]]:
    rel = path.relative_to(ROOT).as_posix()
    allowed = ALLOWED_OUTSIDE_REPO.get(rel, set())
    text = _strip_code(path.read_text(encoding="utf-8"))
    broken: list[tuple[int, str]] = []

    for match in LINK.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "tel:", "#")):
            continue
        if target in allowed:
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            line = text.count("\n", 0, match.start()) + 1
            broken.append((line, target))
    return broken


def main() -> int:
    findings: list[str] = []
    files = _markdown_files()

    for path in files:
        for line, target in _broken_links(path):
            findings.append(f"  {path.relative_to(ROOT).as_posix()}:{line} -> {target}")

    print("doc link summary:")
    print(f"  markdown files scanned: {len(files)}")
    print(f"  broken relative links: {len(findings)}")

    if not findings:
        print("\nEvery relative markdown link resolves.")
        return 0

    print("\nMarkdown links whose target does not exist:", file=sys.stderr)
    for finding in findings:
        print(finding, file=sys.stderr)
    print(
        "\nA renamed ADR or spec leaves dead links in every document that cited\n"
        "its old filename; the front-matter registry gate cannot see these.\n"
        "Point each link at the current file, or — for a path that is meant to\n"
        "resolve outside this checkout — add it to ALLOWED_OUTSIDE_REPO in\n"
        "scripts/check-doc-links.py, keyed by the referencing document.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
