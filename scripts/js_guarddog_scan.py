#!/usr/bin/env python3
"""Scan every direct JS dependency with GuardDog and merge the reports (#344).

The workflow's scanner half of the JS supply-chain gate: reads the scan list
from ``js_dependency_gate.py --direct-deps`` (single source of truth — the
lockfiles), runs GuardDog against each direct dependency at its LOCKED
version, and writes one merged JSON report per surface for the gate to read.

A package GuardDog could not scan is recorded as an ``errors`` entry, never
silently dropped: the gate treats it as an unavailable scanner (exit 3), so a
registry outage fails the job loudly instead of reading as a clean tree.

Usage:
    python scripts/js_guarddog_scan.py --output-dir <dir> [--guarddog <bin>]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "js_dependency_gate.py"


def scan_direct_dependencies(
    direct_deps: dict[str, dict[str, str]],
    *,
    output_dir: Path,
    guarddog: str,
    timeout: float = 300.0,
) -> dict[str, Path]:
    """Run GuardDog per (surface, package, locked version); merge per surface."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for surface, deps in direct_deps.items():
        slug = surface.replace("/", "_")
        merged: dict[str, dict[str, object]] = {}
        for name, version in sorted(deps.items()):
            try:
                completed = subprocess.run(
                    [
                        guarddog,
                        "npm",
                        "scan",
                        name,
                        "-v",
                        version,
                        "--no-sandbox",
                        "--output-format",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                merged[name] = {"errors": {"timeout": f"scan exceeded {timeout}s"}}
                continue
            if completed.returncode == 0 and completed.stdout.strip():
                try:
                    merged[name] = json.loads(completed.stdout)
                    continue
                except json.JSONDecodeError:
                    pass
            # GuardDog exits non-zero on findings (--exit-non-zero-on-finding
            # is NOT passed, but crashes happen too): a parseable report is a
            # result, anything else is an unavailable scanner, never a pass.
            stderr_tail = (completed.stderr or "").strip()[-300:]
            merged[name] = {"errors": {"scan": stderr_tail or f"exit {completed.returncode}"}}
        path = output_dir / f"{slug}.json"
        path.write_text(json.dumps(merged), encoding="utf-8")
        written[surface] = path
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--guarddog",
        default=shutil.which("guarddog") or "guarddog",
        help="guarddog executable (default: on PATH)",
    )
    args = parser.parse_args(argv)

    listed = subprocess.run(
        [sys.executable, str(GATE), "--direct-deps"],
        capture_output=True,
        text=True,
        check=True,
    )
    direct_deps: dict[str, dict[str, str]] = defaultdict(dict)
    for line in listed.stdout.splitlines():
        surface, name, version = line.split()
        direct_deps[surface][name] = version

    written = scan_direct_dependencies(
        dict(direct_deps), output_dir=args.output_dir, guarddog=args.guarddog
    )
    for surface, path in sorted(written.items()):
        print(f"{surface} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
