#!/usr/bin/env python3
"""Fail M1 changes that create a new architecture subsystem without an exception.

The convergence matrix is the checked inventory of production subsystems. During
M1 that inventory may converge, shrink, or change disposition, but it may not
grow a new architectural island silently. A genuinely necessary new subsystem
requires the explicit ``m1-convergence-exception`` label and review rationale.

Usage:
    python scripts/check-m1-convergence-freeze.py --base origin/develop
    python scripts/check-m1-convergence-freeze.py --base origin/develop --exception
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = "docs/architecture/CONVERGENCE-MATRIX.md"
OWNERSHIP_MARKER = "<!-- matrix:ownership -->"


def _subsystems(text: str) -> set[str]:
    marker = text.find(OWNERSHIP_MARKER)
    if marker < 0:
        raise ValueError(f"missing {OWNERSHIP_MARKER}")

    rows: list[str] = []
    for raw in text[marker + len(OWNERSHIP_MARKER) :].splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] == "Subsystem":
            continue
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue
        rows.append(cells[0])
    if not rows:
        raise ValueError("ownership table contains no subsystem rows")
    return set(rows)


def _git_show(base: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{base}:{path}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"cannot read {path} from {base}: {proc.stderr.strip()}")
    return proc.stdout


def new_subsystems(current: str, base: str) -> set[str]:
    return _subsystems(current) - _subsystems(base)


def check(current: str, base: str, *, exception: bool) -> list[str]:
    added = sorted(new_subsystems(current, base))
    if not added or exception:
        return []
    return [
        "M1 convergence freeze: new architecture subsystem(s) require the "
        "m1-convergence-exception label: " + ", ".join(added)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="git ref for the PR base")
    parser.add_argument("--exception", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    current = (ROOT / MATRIX_PATH).read_text(encoding="utf-8")
    base = _git_show(args.base, MATRIX_PATH)
    failures = check(current, base, exception=args.exception)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("M1 convergence freeze: no unapproved new architecture subsystem")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
