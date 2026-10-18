#!/usr/bin/env python3
"""Reject self-approving changes to the formal security oracle (#341).

The behavioral fixture is intentionally separate from the implementation, but
that separation is not enough when one PR can rewrite both sides. This check
compares the candidate's changed paths with an immutable PR base and requires
oracle evolution and implementation evolution to land separately.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE_PATH = "formal/fixtures/security_oracle.json"
PROTECTED_WITH_ORACLE = (
    "packages/maistro-core/src/maistro/security/",
    "formal/models/",
    "formal/conftest.py",
    "formal/pyproject.toml",
    "formal/SECURITY-CONFORMANCE.md",
    ".github/workflows/formal-conformance.yml",
    "scripts/check-formal-oracle-independence.py",
)


class OracleIndependenceError(RuntimeError):
    """The trusted base or candidate diff could not be evaluated."""


def _verify_revision(base: str, *, root: Path) -> None:
    """Resolve the supplied base before asking git for candidate changes."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or "no matching commit"
        raise OracleIndependenceError(f"base revision {base!r} not found; {detail}")


def changed_paths(base: str, *, root: Path = ROOT) -> set[str]:
    """Return candidate paths changed from the resolved PR base."""
    _verify_revision(base, root=root)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", f"{base}...HEAD", "--"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or "git diff failed"
        raise OracleIndependenceError(detail)
    return {path for path in result.stdout.splitlines() if path}


def _implementation_changes(paths: Iterable[str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if any(
            path.startswith(prefix) or path == prefix.rstrip("/")
            for prefix in PROTECTED_WITH_ORACLE
        )
    )


def oracle_exists_at_base(base: str, *, root: Path = ROOT) -> bool:
    """Return whether the trusted base already carries the governed oracle."""
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{base}:{ORACLE_PATH}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def violations(paths: Iterable[str], *, oracle_at_base: bool = True) -> list[str]:
    """Describe any oracle/implementation co-change in a candidate diff.

    The absent-at-base exception is only for landing the oracle contract for the
    first time. Every later change is judged against the already governed file.
    """
    changed = set(paths)
    if ORACLE_PATH not in changed or not oracle_at_base:
        return []
    implementation = _implementation_changes(changed)
    if not implementation:
        return []
    return [
        f"{ORACLE_PATH} cannot change with security conformance implementation: "
        + ", ".join(implementation)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("FORMAL_ORACLE_BASE"),
        help="immutable PR base commit (also accepted as FORMAL_ORACLE_BASE)",
    )
    args = parser.parse_args(argv)
    if not args.base:
        parser.error("--base or FORMAL_ORACLE_BASE is required")

    try:
        paths = changed_paths(args.base)
        oracle_at_base = oracle_exists_at_base(args.base)
        errors = violations(paths, oracle_at_base=oracle_at_base)
    except OracleIndependenceError as exc:
        print(f"formal oracle independence: ERROR: {exc}", file=sys.stderr)
        return 2

    if not oracle_at_base and ORACLE_PATH in paths:
        print("formal oracle independence: OK (initial oracle contract is being established)")
        return 0

    if errors:
        for error in errors:
            print(f"formal oracle independence: ERROR: {error}", file=sys.stderr)
        return 1

    print("formal oracle independence: OK (oracle and implementation changes are separated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
