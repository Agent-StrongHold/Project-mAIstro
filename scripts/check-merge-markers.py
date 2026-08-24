#!/usr/bin/env python3
"""Gate: no conflict marker reaches a tracked file (#154).

Why this exists
---------------
It is not hypothetical. ``docs/testing/SUITE-INVENTORY.md`` was merged to
``develop`` carrying a literal ``<<<<<<< HEAD`` / ``=======`` /
``>>>>>>> origin/develop`` block, and every gate stayed green for the same
reason the marker survived review: nothing looked. ``check-suite-inventory.py``
compares the row counts it can *see*, and a marker line is not a row, so the
table still added up. Lint reads Python, and the file is Markdown.

A conflict marker is the one defect class with no false positives worth
arguing about — it is never intentional content, it is mechanically detectable,
and by the time it is in a merge commit the branch that could have caught it is
gone. So the check is cheap and absolute rather than clever.

What counts
-----------
Only the three markers git actually writes, anchored to the start of a line:
``<<<<<<< `` and ``>>>>>>> `` with their trailing space and label, and a bare
``=======`` line. The trailing space matters: a Markdown ``=======`` setext
underline is a real thing, and so is a ``>>>>>>>`` in a diff pasted into a
document — the separator is disambiguated by requiring the file to *also* carry
one of the labelled markers, which prose never does.

Scope is ``git ls-files``: tracked files only, so a vendored virtualenv or a
local scratch file cannot fail the build. Binary and unreadable files are
skipped rather than guessed at.

Usage
-----
    python3 scripts/check-merge-markers.py            # this repository
    python3 scripts/check-merge-markers.py <path>     # another checkout

The optional path exists so the gate can be pointed at a throwaway repository
under test. A gate whose scope is hard-wired to its own parent directory can
only be tested by dirtying the tree it is guarding.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The labelled markers. Both carry a trailing space before the ref name, which
#: is what separates them from prose that merely starts with the character.
_OURS = "<<<<<<< "
_THEIRS = ">>>>>>> "

#: The separator, which alone is ambiguous — ``=======`` under a line of text is
#: a setext heading in Markdown. It is only reported in a file that also holds a
#: labelled marker.
_SEPARATOR = "======="

#: This file quotes the markers it looks for, so it would fail itself.
_EXEMPT = frozenset({"scripts/check-merge-markers.py"})


def _tracked_files(root: Path = ROOT) -> list[str]:
    """Tracked paths, each once.

    ``git ls-files`` prints an *unmerged* path once per stage, so during the
    conflict this gate exists to catch, the offending file is listed three
    times and every finding in it is reported three times. Deduplicating here
    rather than in the caller keeps that an implementation detail of "what
    files are there".
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return list(dict.fromkeys(name for name in out.split("\0") if name))


def _markers_in(path: Path) -> list[tuple[int, str]]:
    """Marker lines in one file, as ``(line number, text)``.

    A file with no labelled marker reports nothing, so a bare ``=======`` in
    prose is not a finding on its own.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    labelled = [
        (n, line)
        for n, line in enumerate(lines, 1)
        if line.startswith(_OURS) or line.startswith(_THEIRS)
    ]
    if not labelled:
        return []

    separators = [(n, line) for n, line in enumerate(lines, 1) if line.rstrip() == _SEPARATOR]
    return sorted(labelled + separators)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else ROOT

    findings: list[str] = []
    for name in _tracked_files(root):
        if name in _EXEMPT:
            continue
        for line_no, line in _markers_in(root / name):
            findings.append(f"{name}:{line_no}: {line[:60]}")

    if findings:
        print("FAIL: conflict markers in tracked files", file=sys.stderr)
        print(file=sys.stderr)
        for finding in findings:
            print(f"    {finding}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "    Resolve the conflict and remove the markers. A marker that "
            "lands on a\n    branch is a merge nobody finished.",
            file=sys.stderr,
        )
        return 1

    print("ok: no conflict markers in any tracked file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
