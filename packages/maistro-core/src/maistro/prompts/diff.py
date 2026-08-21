"""Prompt diff engine: compare versions side-by-side.

Uses difflib for unified diff output, structured as typed dataclasses
for the API and dashboard to consume.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass(frozen=True)
class DiffLine:
    """A single line in a unified diff."""

    op: str  # "add", "remove", "context", "header"
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


def compute_diff(
    old_content: str,
    new_content: str,
    *,
    old_label: str = "previous",
    new_label: str = "current",
    context_lines: int = 3,
) -> list[DiffLine]:
    """Compute a unified diff between two prompt versions."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_label,
        tofile=new_label,
        n=context_lines,
    )

    # difflib.unified_diff emits file headers as the first two lines, formatted
    # exactly as "--- <fromfile>" and "+++ <tofile>" (note the trailing space and
    # label). Content lines are "-"/"+" followed by arbitrary text — which may
    # itself be "--" or "++", e.g. a removed markdown "---" rule. We must not
    # confuse those content lines with file headers, or line numbers drift.
    file_headers = (
        f"--- {old_label}",
        f"+++ {new_label}",
    )

    result: list[DiffLine] = []
    old_lineno = 0
    new_lineno = 0

    for line in diff:
        stripped = line.rstrip("\n")

        if stripped.startswith(file_headers):
            result.append(DiffLine(op="header", content=stripped))
        elif line.startswith("@@"):
            result.append(DiffLine(op="header", content=stripped))
            parts = stripped.split()
            if len(parts) >= 3:
                try:
                    old_lineno = abs(int(parts[1].split(",")[0]))
                    new_lineno = int(parts[2].split(",")[0])
                except (ValueError, IndexError):
                    pass
        elif line.startswith("-"):
            result.append(DiffLine(op="remove", content=stripped[1:], old_lineno=old_lineno))
            old_lineno += 1
        elif line.startswith("+"):
            result.append(DiffLine(op="add", content=stripped[1:], new_lineno=new_lineno))
            new_lineno += 1
        else:
            result.append(
                DiffLine(
                    op="context",
                    content=stripped[1:] if stripped.startswith(" ") else stripped,
                    old_lineno=old_lineno,
                    new_lineno=new_lineno,
                )
            )
            old_lineno += 1
            new_lineno += 1

    return result
