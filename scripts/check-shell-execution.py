#!/usr/bin/env python3
"""Gate: every `shell=True` is declared, with a caller someone vouches for (#305).

Why a ledger rather than a ban
------------------------------
`shell=True` is not always wrong. `python -m maistro_rsi run --test-cmd "pytest -q
&& ruff check"` is an operator at a terminal typing a command, and a shell is the
thing they expect; taking it away would break the CLI to close a hole the CLI
never had.

What is wrong is a `shell=True` nobody decided about. `LocalRsiLoop._run_tests`
carried the comment "the test command is operator-supplied config, not agent
input" while `POST /v1/rsi/runs` accepted that command over HTTP. The comment was
true when it was written and false by the time it mattered, and nothing noticed,
because a comment is not checked against the callers.

So each call declares who reaches it and why that reach is safe. Adding one is
fine; adding one silently is not.

The ledger is exact in both directions
--------------------------------------
An undeclared call fails. So does a declared call that no longer exists — a stale
entry is a standing approval for whoever next writes `shell=True` in that file.

Usage
-----
    python3 scripts/check-shell-execution.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "quality" / "shell-execution.json"

#: Trees this gate governs. maistro-rsi executes candidate-influenced work, which
#: is what makes a shell there a different question than a shell in a build
#: script; the Conductor backend is here because it is the HTTP boundary.
GOVERNED: tuple[str, ...] = (
    "packages/maistro-rsi/src",
    "packages/hive-conductor/backend",
)

#: Required on every entry. `reachable_from` is the one that goes stale, and the
#: one whose staleness caused #305 — so it is named, not implied by `reason`.
REQUIRED_FIELDS: tuple[str, ...] = ("file", "symbol", "owner", "reachable_from", "reason")


def _enclosing_symbol(tree: ast.AST, lineno: int) -> str:
    """The dotted function (and class) a line sits inside, for a stable id.

    A line number alone would make every entry stale on the next edit above it,
    and a ledger that churns is a ledger people stop reading.
    """
    best: tuple[int, str] = (-1, "<module>")
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if node.lineno <= lineno <= end and node.lineno > best[0]:
            best = (node.lineno, node.name)
    if best[1] == "<module>":
        return best[1]
    # Qualify with the class when there is one, so `exec` is not ambiguous.
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            end = getattr(node, "end_lineno", None) or node.lineno
            if node.lineno <= lineno <= end:
                return f"{node.name}.{best[1]}"
    return best[1]


def shell_calls(source: str) -> list[str]:
    """Every enclosing symbol that passes a truthy `shell=` keyword."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "shell":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is True:
                found.append(_enclosing_symbol(tree, node.lineno))
    return found


def _is_test(relative: Path) -> bool:
    return "tests" in relative.parts or relative.name.startswith("test_")


def discovered() -> set[tuple[str, str]]:
    """`(path, symbol)` for every governed `shell=True` in the tree."""
    found: set[tuple[str, str]] = set()
    for tree_root in GOVERNED:
        base = ROOT / tree_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(ROOT)
            if _is_test(relative):
                continue
            for symbol in shell_calls(path.read_text(encoding="utf-8")):
                found.add((relative.as_posix(), symbol))
    return found


def audit() -> list[str]:
    """One message per undeclared call, stale entry, or malformed entry."""
    failures: list[str] = []
    try:
        entries = json.loads(LEDGER.read_text(encoding="utf-8"))["calls"]
    except (OSError, ValueError, KeyError) as exc:
        return [f"  {LEDGER.name} could not be read: {exc}"]

    declared: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append(f"  ledger entry is not an object: {entry!r}")
            continue
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            failures.append(f"  {entry.get('file', '?')}: entry is missing {', '.join(missing)}")
            continue
        declared.add((entry["file"], entry["symbol"]))

    live = discovered()
    for path, symbol in sorted(live - declared):
        failures.append(
            f"  {path}: {symbol} passes shell=True and is not in {LEDGER.name} — "
            f"declare who reaches it and why that reach is safe, or run an argv"
        )
    for path, symbol in sorted(declared - live):
        failures.append(
            f"  {path}: {symbol} is declared in {LEDGER.name} but no longer passes "
            f"shell=True — remove the entry, or it stands as approval for the next one"
        )
    return failures


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL: {LEDGER} does not exist", file=sys.stderr)
        return 1

    failures = audit()
    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the shell-execution ledger:\n")
        print("\n".join(failures))
        print(
            "\nA shell=True is not automatically wrong — an operator at a terminal "
            "\ntyped the command. What is wrong is one nobody decided about: #305's "
            "\ncomment said 'operator-supplied' while an HTTP route supplied it."
        )
        return 1

    count = len(discovered())
    print(f"ok: all {count} shell=True call(s) in the governed trees are declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
