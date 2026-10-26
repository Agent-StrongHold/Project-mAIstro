#!/usr/bin/env python3
"""Load and validate the mutation-critical file list (#330).

The critical list (`quality/mutation-critical-files.json`) decides where the
PR gate must mutate changed lines and what the nightly sweep measures first.
It is a governance artifact: an unreadable, malformed, or silently emptied
list must fail loudly — a gate that cannot read its scope is a gate that
passes by doing nothing, which is exactly the placeholder #330 removes.

Modes
-----
    --validate             check schema, uniqueness, and file existence
    --sources              emit every critical source path (one per line)
    --changed-from PATH|-  intersect critical sources with the changed paths
                           read from PATH (or stdin) and emit `source<TAB>tests`
                           rows in the mutation_targets.py contract

`--changed-from` never invents a test scope: a critical source whose tests
cannot be resolved is an error ("zero selected tests is explicit"), not a
warning, because mutating against the whole suite is the failure mode
mutation_targets.py exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIST = ROOT / "quality" / "mutation-critical-files.json"

REQUIRED_ENTRY_FIELDS = ("source", "domain", "reason", "evidence")


class CriticalListError(Exception):
    """The critical list is unreadable, malformed, or otherwise unusable."""


def load(path: Path) -> dict:
    """Parse and structurally validate the critical list."""
    if not path.is_file():
        raise CriticalListError(f"critical-file list is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CriticalListError(f"critical-file list is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise CriticalListError("critical-file list must be a JSON object")

    domains = payload.get("domains")
    if not isinstance(domains, list) or not domains:
        raise CriticalListError("critical-file list needs a non-empty 'domains' array")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CriticalListError("critical-file list needs a non-empty 'entries' array")

    seen: set[str] = set()
    for entry in entries:
        _validate_entry(entry, domains, seen)
    return payload


def _validate_entry(entry: object, domains: list, seen: set[str]) -> None:
    """Validate one critical entry, updating the duplicate-detection set."""
    if not isinstance(entry, dict):
        raise CriticalListError("every critical entry must be an object")
    missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
    if missing:
        raise CriticalListError(f"critical entry missing field(s): {', '.join(missing)}: {entry}")
    if entry["domain"] not in domains:
        raise CriticalListError(
            f"critical entry domain {entry['domain']!r} is not declared in 'domains'"
        )
    source = entry["source"]
    if source in seen:
        raise CriticalListError(f"duplicate critical source: {source}")
    seen.add(source)
    if not (ROOT / source).is_file():
        raise CriticalListError(f"critical source does not exist in the repository: {source}")


def sources(payload: dict) -> list[str]:
    return [entry["source"] for entry in payload["entries"]]


def intersect(payload: dict, changed: list[str]) -> list[str]:
    """Critical sources named by the changed-path set."""
    wanted = set(changed)
    return [source for source in sources(payload) if source in wanted]


def _read_changed(path: str) -> list[str]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _emit_targets(critical_sources: list[str]) -> int:
    """Emit mutation_targets rows for critical sources, failing on unresolvable."""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import mutation_targets

    rows: list[str] = []
    unresolved: list[str] = []
    for source in critical_sources:
        tests = mutation_targets.resolve_script_tests(
            source
        ) or mutation_targets.resolve_package_tests(source)
        if tests is None:
            unresolved.append(source)
            continue
        rows.append(f"{source}\t{tests}")
    for source in unresolved:
        # Zero selected tests must be explicit, never a silent widening to the
        # whole suite and never a silent skip of a critical file.
        print(f"::error::critical source has no resolvable test scope: {source}", file=sys.stderr)
    for row in rows:
        print(row)
    return 1 if unresolved else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=Path, default=DEFAULT_LIST)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--sources", action="store_true")
    parser.add_argument("--changed-from", default=None, metavar="PATH_OR_-")
    args = parser.parse_args(argv)

    try:
        payload = load(args.list)
    except CriticalListError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    if args.validate:
        print(
            f"critical-file list OK: {len(payload['entries'])} source(s) "
            f"across {len(payload['domains'])} domain(s)"
        )
        return 0

    if args.changed_from is not None:
        changed = _read_changed(args.changed_from)
        selected = intersect(payload, changed)
        if not selected:
            print("no mutation-critical files in the changed set", file=sys.stderr)
            return 0
        return _emit_targets(selected)

    if args.sources:
        for source in sources(payload):
            print(source)
        return 0

    parser.error("choose a mode: --validate, --sources, or --changed-from")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
