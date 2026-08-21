#!/usr/bin/env python3
"""Plan mutation work from per-source cost history.

This module deliberately separates mutation *safety* from repository mutation
*health*. PR safety is changed-file only. Repository-wide work is planned into
bounded, deterministic packets using historical per-source cost estimates.

Cost estimate priority:
1. EWMA mutation duration from validated historical samples.
2. mutant_count * baseline_test_duration for a source with bootstrap telemetry.
3. median known cost for the current inventory, else DEFAULT_UNKNOWN_SECONDS.

The planner uses deterministic longest-processing-time assignment: sort targets
by estimated cost descending (path tie-break), then place each target onto the
currently least-loaded packet. Packet count is derived from total estimated
work, target packet duration, and runner capacity. This balances cost rather
than source-row count and keeps the same inputs reproducible.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLANNER_VERSION = 1
DEFAULT_UNKNOWN_SECONDS = 15 * 60.0
DEFAULT_PACKET_SECONDS = 25 * 60.0
DEFAULT_RUNNER_CAPACITY = 8


@dataclass(frozen=True)
class Target:
    source: str
    tests: str
    estimated_seconds: float
    estimate_kind: str


@dataclass
class Packet:
    id: int
    targets: list[Target]
    estimated_seconds: float = 0.0

    def add(self, target: Target) -> None:
        self.targets.append(target)
        self.estimated_seconds += target.estimated_seconds


def load_history(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "planner_version": PLANNER_VERSION, "entries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mutation history must be a JSON object")
    entries = payload.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("mutation history entries must be an object")
    return payload


def read_targets(path: Path) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            source, tests = line.split("\t", 1)
        except ValueError as exc:
            raise ValueError(f"invalid target row: {line!r}") from exc
        targets.append((source, tests))
    return targets


def _historical_cost(entry: dict[str, Any]) -> tuple[float, str] | None:
    sample_count = int(entry.get("sample_count", 0) or 0)
    ewma = entry.get("ewma_mutation_seconds")
    if sample_count > 0 and isinstance(ewma, (int, float)) and ewma > 0:
        return float(ewma), "history-ewma"

    mutant_count = entry.get("mutant_count")
    baseline = entry.get("baseline_test_seconds")
    if (
        isinstance(mutant_count, int)
        and mutant_count > 0
        and isinstance(baseline, (int, float))
        and baseline > 0
    ):
        return float(mutant_count) * float(baseline), "bootstrap-mutants-x-baseline"
    return None


def estimate_targets(rows: list[tuple[str, str]], history: dict[str, Any]) -> list[Target]:
    entries = history.get("entries", {})
    known: dict[str, tuple[float, str]] = {}
    for source, _tests in rows:
        entry = entries.get(source, {})
        if isinstance(entry, dict):
            estimate = _historical_cost(entry)
            if estimate is not None:
                known[source] = estimate

    fallback = (
        statistics.median(cost for cost, _kind in known.values())
        if known
        else DEFAULT_UNKNOWN_SECONDS
    )

    estimated: list[Target] = []
    for source, tests in rows:
        if source in known:
            seconds, kind = known[source]
        else:
            seconds, kind = float(fallback), "inventory-median-fallback"
        estimated.append(Target(source, tests, max(1.0, seconds), kind))
    return estimated


def packet_count(targets: list[Target], target_seconds: float, runner_capacity: int) -> int:
    if not targets:
        return 0
    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")
    if runner_capacity <= 0:
        raise ValueError("runner_capacity must be positive")
    total = sum(target.estimated_seconds for target in targets)
    desired = max(1, math.ceil(total / target_seconds))
    # Never create more packets than targets. The capacity value describes the
    # intended concurrent worker budget, not a hard maximum packet count; extra
    # packets queue and keep workers occupied as packets finish.
    return min(len(targets), max(runner_capacity, desired))


def plan_packets(
    targets: list[Target], target_seconds: float, runner_capacity: int
) -> list[Packet]:
    count = packet_count(targets, target_seconds, runner_capacity)
    if count == 0:
        return []
    packets = [Packet(id=i, targets=[]) for i in range(count)]
    ordered = sorted(targets, key=lambda item: (-item.estimated_seconds, item.source))
    for target in ordered:
        packet = min(packets, key=lambda item: (item.estimated_seconds, item.id))
        packet.add(target)
    return [packet for packet in packets if packet.targets]


def plan_payload(packets: list[Packet]) -> dict[str, Any]:
    return {
        "planner_version": PLANNER_VERSION,
        "packets": [
            {
                "id": packet.id,
                "estimated_seconds": round(packet.estimated_seconds, 3),
                "targets": [
                    {
                        "source": target.source,
                        "tests": target.tests,
                        "estimated_seconds": round(target.estimated_seconds, 3),
                        "estimate_kind": target.estimate_kind,
                    }
                    for target in packet.targets
                ],
            }
            for packet in packets
        ],
    }


def simulation(packets: list[Packet]) -> dict[str, float]:
    if not packets:
        return {
            "max_seconds": 0.0,
            "median_seconds": 0.0,
            "p95_seconds": 0.0,
            "imbalance": 1.0,
        }
    loads = sorted(packet.estimated_seconds for packet in packets)
    median = statistics.median(loads)
    p95_index = max(0, math.ceil(len(loads) * 0.95) - 1)
    p95 = loads[p95_index]
    return {
        "max_seconds": max(loads),
        "median_seconds": median,
        "p95_seconds": p95,
        "imbalance": max(loads) / median if median else 1.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path, help="TSV from mutation_targets.py")
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--target-minutes", type=float, default=DEFAULT_PACKET_SECONDS / 60)
    parser.add_argument("--runner-capacity", type=int, default=DEFAULT_RUNNER_CAPACITY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    rows = read_targets(args.targets)
    history = load_history(args.history)
    estimates = estimate_targets(rows, history)
    packets = plan_packets(estimates, args.target_minutes * 60.0, args.runner_capacity)
    payload = plan_payload(packets)
    stats = simulation(packets)
    payload["simulation"] = {key: round(value, 3) for key, value in stats.items()}

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    print(
        "mutation plan: "
        f"packets={len(packets)} max={stats['max_seconds'] / 60:.1f}m "
        f"median={stats['median_seconds'] / 60:.1f}m "
        f"p95={stats['p95_seconds'] / 60:.1f}m "
        f"imbalance={stats['imbalance']:.2f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
