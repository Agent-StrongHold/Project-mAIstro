#!/usr/bin/env python3
"""Select one reproducible unbaselined mutation target."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.baseline.read_text(encoding="utf-8"))
    entries = payload.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("mutation baseline entries must be an object")

    candidates: list[str] = []
    for raw in args.targets.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        source, tests = raw.split("\t", 1)
        if source not in entries:
            candidates.append(f"{source}\t{tests}")

    if not candidates:
        args.output.write_text("", encoding="utf-8")
        print("mutation baseline selection: all resolvable sources already baselined")
        return 0

    candidates.sort()
    ranked = sorted(
        candidates,
        key=lambda row: hashlib.sha256(f"{args.seed}\0{row}".encode()).hexdigest(),
    )
    chosen = ranked[0]
    args.output.write_text(chosen + "\n", encoding="utf-8")
    print(f"mutation baseline selection: {chosen.split(chr(9), 1)[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
