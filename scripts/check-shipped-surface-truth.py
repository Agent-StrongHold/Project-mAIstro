#!/usr/bin/env python3
"""Check or print the machine-reviewable shipped-surface truth matrix (#465)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shipped_surface_truth import discovered_inventory, format_errors, load_matrix, validate_matrix

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX = REPO_ROOT / "quality" / "shipped-surface-truth.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="also fail while a production-enabled unresolved facade remains",
    )
    parser.add_argument(
        "--discover-json",
        action="store_true",
        help="print the current machine-discovered shipped surface set",
    )
    args = parser.parse_args()
    matrix = load_matrix(MATRIX)
    if args.discover_json:
        print(json.dumps(discovered_inventory(REPO_ROOT, matrix), indent=2, sort_keys=True))
        return 0
    errors = validate_matrix(REPO_ROOT, matrix, strict=args.require_clean)
    print(format_errors(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
