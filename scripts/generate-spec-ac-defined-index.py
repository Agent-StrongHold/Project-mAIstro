#!/usr/bin/env python3
"""Regenerate the AC Defined section in docs/specs/README.md."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "docs" / "specs"
README = SPECS / "README.md"
START = "<!-- ac-defined-start -->"
END = "<!-- ac-defined-end -->"


def _ac_defined_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for path in sorted(SPECS.glob("SPEC-*.md")):
        text = path.read_text()
        if not re.search(r"^status:\s*AC Defined", text, re.M):
            continue
        spec_id = re.search(r"^id:\s*(SPEC-[^\n]+)", text, re.M)
        title = re.search(r"^title:\s*(.+)$", text, re.M)
        if spec_id is None or title is None:
            continue
        rows.append((spec_id.group(1).strip(), title.group(1).strip(), path.name))
    return rows


def _section(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        START,
        "",
        "## AC Defined specs (implementation backlog)",
        "",
        f"**{len(rows)} specs** with acceptance criteria defined but not yet fully implemented.",
        "Regenerate: `uv run python scripts/generate-spec-ac-defined-index.py`.",
        "",
        "| ID | Title | File |",
        "| --- | --- | --- |",
    ]
    for spec_id, title, fname in rows:
        safe_title = title.replace("|", "\\|")
        lines.append(f"| {spec_id} | {safe_title} | [{fname}]({fname}) |")
    lines.extend(["", END, ""])
    return "\n".join(lines)


def main() -> int:
    rows = _ac_defined_rows()
    text = README.read_text()
    section = _section(rows)
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        README.write_text(before + section + after.lstrip("\n"))
    else:
        README.write_text(text.rstrip() + "\n\n" + section)
    print(f"updated {README.relative_to(ROOT)} with {len(rows)} AC Defined spec(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
