#!/usr/bin/env python3
"""Gate: no byte-identical test files across the gated suites (#396).

At the head this landed on, eleven test files existed twice — once under a
package's ``tests/`` tree and once under the root ``tests/`` tree — with
byte-identical content and no generator between them. Both roots are in
``testpaths``, so every one of those node IDs was collected twice, and
suite-level evidence (the inventory ledger, the AC outcome gate's pass
counts, coverage) double-credited each duplicate test for work done once.

The eleven were removed in favor of the package copies (see
``docs/testing/DUPLICATE-TEST-INVENTORY.md`` for the per-file inventory and
the authoritative-location decision). This gate keeps them from coming back,
and keeps the next copy of a suite from being checked in silently.

What it checks
--------------
Every ``test_*.py`` / ``*_test.py`` file under every suite root named in
``RECIPES`` in ``check-suite-inventory.py`` (the same universe the inventory
ledger gates) is hashed. Any content hash shared by more than one file fails,
unless the whole group is covered by an explicit entry in
``docs/testing/generated-test-contracts.json`` — the "generated-test
contract" escape hatch: a duplicate that a generator really does emit, named
file-for-file, with a justification. A contract covering *some* of a group
does not approve the rest; partial coverage fails like no contract at all.

The suite universe is imported from ``check-suite-inventory.py`` rather than
restated here. Two scripts each half-remembering which trees are gated is
how a new tree ends up gated by one and not the other.

What it deliberately does not check
-----------------------------------
Near-duplicates — files with the same basename and drifted bodies — are a
judgment call (consolidate vs. document distinct environments), not a
byte comparison. ``DUPLICATE-TEST-INVENTORY.md`` records that review; this
gate does not guess at it. Node-ID overlap across suites is reported by
``check-suite-inventory.py`` itself, which already collects everything.

Usage
-----
    python3 scripts/check-test-duplicates.py            # gate (what CI runs)
    python3 scripts/check-test-duplicates.py --list     # print dup groups, exit 0
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "docs" / "testing" / "generated-test-contracts.json"
INVENTORY_GATE = REPO_ROOT / "scripts" / "check-suite-inventory.py"

TEST_FILE_RE = ("test_*.py", "*_test.py")


def _suite_roots() -> list[str]:
    """The gated suite roots, imported from the inventory gate."""
    spec = importlib.util.spec_from_file_location("_check_suite_inventory", INVENTORY_GATE)
    if spec is None or spec.loader is None:  # pragma: no cover - path is relative to us
        raise RuntimeError(f"cannot load {INVENTORY_GATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return sorted(module.RECIPES)


def test_files(roots: list[str]) -> list[Path]:
    """Every test file under the gated roots, sorted for stable output."""
    files: list[Path] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            raise RuntimeError(f"suite root `{root}` does not exist — has it moved?")
        for pattern in TEST_FILE_RE:
            files.extend(p for p in base.rglob(pattern) if p.is_file())
    return sorted(set(files))


def duplicate_groups(files: list[Path]) -> dict[str, list[Path]]:
    """Group test files by content hash; return only the shared-hash groups."""
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash[digest].append(path)
    return {h: paths for h, paths in sorted(by_hash.items()) if len(paths) > 1}


def load_contracts() -> list[dict[str, object]]:
    """Read the generated-test contracts, or ``[]`` when there are none."""
    if not CONTRACTS.is_file():
        return []
    doc = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    contracts = doc.get("contracts")
    if not isinstance(contracts, list):
        raise RuntimeError(f"{CONTRACTS.relative_to(REPO_ROOT)} has no `contracts` list")
    for entry in contracts:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) and entry[k] for k in ("id", "justification")
        ):
            raise RuntimeError(
                f"{CONTRACTS.relative_to(REPO_ROOT)}: every contract needs a non-empty "
                "`id` and `justification`"
            )
        files = entry.get("files")
        if (
            not isinstance(files, list)
            or len(files) < 2
            or any(not isinstance(f, str) for f in files)
        ):
            raise RuntimeError(
                f"{CONTRACTS.relative_to(REPO_ROOT)}: contract `{entry.get('id')}` needs "
                "`files`: a list of at least two repo-relative paths"
            )
    return contracts


def approved_groups(
    groups: dict[str, list[Path]], contracts: list[dict[str, object]]
) -> tuple[set[str], dict[str, str]]:
    """Split duplicate groups into contract-approved and still-violating.

    A group is approved only when a contract names exactly its file set —
    a contract covering a strict subset approves nothing, because the
    remaining pair is exactly the unexplained duplicate the gate exists for.
    Returns ``(approved_hashes, {hash: partial-coverage hint})``.
    """
    by_fileset = {frozenset(entry["files"]): entry for entry in contracts}  # type: ignore[arg-type]
    approved: set[str] = set()
    hints: dict[str, str] = {}
    for digest, paths in groups.items():
        rel = frozenset(p.relative_to(REPO_ROOT).as_posix() for p in paths)
        if by_fileset.get(rel) is not None:
            approved.add(digest)
            continue
        covered = sorted(
            str(c["id"])
            for c in contracts
            if frozenset(c["files"]) & rel  # type: ignore[arg-type]
        )
        if covered:
            hints[digest] = f" (overlaps contract {', '.join(covered)})"
    return approved, hints


def format_group(paths: list[Path]) -> str:
    return "\n      ".join(p.relative_to(REPO_ROOT).as_posix() for p in paths)


def metrics(files: list[Path], groups: dict[str, list[Path]]) -> str:
    """Human-readable duplicate-content metrics over the test files."""
    redundant = sum(len(paths) - 1 for paths in groups.values())
    redundant_bytes = sum(
        len(max(paths, key=lambda p: p.stat().st_size).read_bytes()) * (len(paths) - 1)
        for paths in groups.values()
    )
    lines = [
        f"test files scanned: {len(files)}",
        f"unique content: {len(files) - redundant}",
        f"byte-identical groups: {len(groups)} (redundant files: {redundant}, "
        f"redundant bytes: {redundant_bytes})",
    ]
    return "\n  ".join(lines)


def fail_unapproved(
    groups: dict[str, list[Path]],
    approved: set[str],
    hints: dict[str, str],
) -> int:
    """Print the readable failure for unapproved duplicate groups; return 1."""
    print(
        f"\nFAIL: {len(groups) - len(approved)} byte-identical test-file group(s) with no "
        "generated-test contract.\n"
        "\n"
        "One test, one home. A byte-identical copy under another suite root\n"
        "is collected by both `testpaths` roots, so evidence (inventory\n"
        "counts, AC outcomes, coverage) is double-credited for work done\n"
        "once. Keep the copy that the owning package executes in CI; delete\n"
        "the other (see docs/testing/DUPLICATE-TEST-INVENTORY.md).\n"
        "\n"
        "If the duplication is genuinely produced by a generator, record it\n"
        f"in {CONTRACTS.relative_to(REPO_ROOT)}: one entry naming every file\n"
        "in the group, with the generator and the justification.",
        file=sys.stderr,
    )
    for digest, paths in groups.items():
        if digest in approved:
            continue
        print(f"\n  {digest[:12]}:\n      {format_group(paths)}", file=sys.stderr)
        if hint := hints.get(digest):
            print(f"      {hint}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--list",
        action="store_true",
        help="print duplicate groups and metrics without failing (audit mode)",
    )
    args = ap.parse_args()

    try:
        roots = _suite_roots()
        files = test_files(roots)
        groups = duplicate_groups(files)
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Duplicate-test-content metrics (gated suites):")
    print(f"  {metrics(files, groups)}")
    if not groups:
        print("ok: no byte-identical test files")
        return 0

    for digest, paths in groups.items():
        print(f"\n  duplicate group {digest[:12]}:")
        print(f"      {format_group(paths)}")

    if args.list:
        return 0

    try:
        contracts = load_contracts()
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    approved, hints = approved_groups(groups, contracts)

    if approved:
        print(f"\n  approved by generated-test contract: {len(approved)} group(s)")

    if len(approved) < len(groups):
        return fail_unapproved(groups, approved, hints)

    print("ok: all duplicate groups covered by generated-test contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
