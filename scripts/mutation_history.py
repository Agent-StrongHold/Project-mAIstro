#!/usr/bin/env python3
"""Merge complete mutation-session telemetry into per-source history.

Only complete validated source sessions should be passed here. Infrastructure
failures and partial Cosmic Ray sessions must never update historical quality or
cost data. The output is a candidate history file suitable for artifact review
and later commit.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

EWMA_ALPHA = 0.35
HISTORY_VERSION = 1
PLANNER_VERSION = 1


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "version": HISTORY_VERSION,
            "planner_version": PLANNER_VERSION,
            "entries": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("entries", {})
    return payload


def _ewma(previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return EWMA_ALPHA * current + (1.0 - EWMA_ALPHA) * previous


def merge_entry(previous: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    required = {
        "source",
        "source_hash",
        "test_scope_hash",
        "baseline_test_seconds",
        "mutation_seconds",
        "mutant_count",
        "viable_mutants",
        "killed_mutants",
        "surviving_mutants",
        "non_viable_mutants",
        "invalid_mutants",
        "undetermined_mutants",
        "kill_rate",
        "runner",
        "python_version",
        "cosmic_ray_version",
        "pytest_version",
        "tool_fingerprint",
        "verified_commit",
    }
    missing = sorted(required - sample.keys())
    if missing:
        raise ValueError(f"telemetry sample missing required fields: {', '.join(missing)}")
    if sample.get("complete") is not True:
        raise ValueError("refusing to persist incomplete mutation telemetry")

    count = int(previous.get("sample_count", 0)) + 1
    mutation_seconds = float(sample["mutation_seconds"])
    baseline_seconds = float(sample["baseline_test_seconds"])
    prior_mutation = previous.get("ewma_mutation_seconds")
    prior_baseline = previous.get("ewma_baseline_test_seconds")

    return {
        "source_hash": sample["source_hash"],
        "test_scope_hash": sample["test_scope_hash"],
        "mutant_count": int(sample["mutant_count"]),
        "viable_mutants": int(sample["viable_mutants"]),
        "killed_mutants": int(sample["killed_mutants"]),
        "surviving_mutants": int(sample["surviving_mutants"]),
        "non_viable_mutants": int(sample["non_viable_mutants"]),
        "invalid_mutants": int(sample["invalid_mutants"]),
        "undetermined_mutants": int(sample["undetermined_mutants"]),
        "kill_rate": round(float(sample["kill_rate"]), 6),
        "baseline_test_seconds": round(baseline_seconds, 6),
        "mutation_seconds": round(mutation_seconds, 6),
        "ewma_baseline_test_seconds": round(
            _ewma(
                float(prior_baseline) if prior_baseline is not None else None,
                baseline_seconds,
            ),
            6,
        ),
        "ewma_mutation_seconds": round(
            _ewma(
                float(prior_mutation) if prior_mutation is not None else None,
                mutation_seconds,
            ),
            6,
        ),
        "sample_count": count,
        "runner": sample["runner"],
        "python_version": sample["python_version"],
        "cosmic_ray_version": sample["cosmic_ray_version"],
        "pytest_version": sample["pytest_version"],
        "tool_fingerprint": sample["tool_fingerprint"],
        "last_verified_commit": sample["verified_commit"],
        "last_verified_at": sample.get("verified_at"),
        "planner_version": PLANNER_VERSION,
    }


def merge(history: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    entries = dict(history.get("entries", {}))
    for sample in samples:
        source = sample.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("telemetry sample has no source")
        previous = entries.get(source, {})
        if not isinstance(previous, dict):
            previous = {}
        entries[source] = merge_entry(previous, sample)
    return {
        "version": HISTORY_VERSION,
        "planner_version": PLANNER_VERSION,
        "generated_with_python": platform.python_version(),
        "entries": dict(sorted(entries.items())),
    }


def read_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("telemetry JSONL rows must be objects")
        samples.append(payload)
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = merge(load(args.history), read_samples(args.telemetry))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote mutation history candidate for {len(result['entries'])} source file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
