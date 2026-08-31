#!/usr/bin/env python3
"""Check the machine-reviewable shipped-surface truth matrix (#465)."""

from __future__ import annotations

import argparse
from pathlib import Path

from shipped_surface_truth import format_errors, load_matrix, validate_matrix

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX = REPO_ROOT / "quality" / "shipped-surface-truth.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="also fail while a production-enabled unresolved facade remains",
    )
    args = parser.parse_args()
    errors = validate_matrix(REPO_ROOT, load_matrix(MATRIX), strict=args.require_clean)
    print(format_errors(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
