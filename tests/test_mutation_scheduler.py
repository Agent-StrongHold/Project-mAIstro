"""Regression coverage for deterministic mutation scheduling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_scheduler.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_scheduler", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules[spec.name]


def test_history_ewma_beats_bootstrap_estimate(module) -> None:
    rows = [("a.py", "tests/a"), ("b.py", "tests/b")]
    history = {
        "entries": {
            "a.py": {
                "sample_count": 3,
                "ewma_mutation_seconds": 120,
                "mutant_count": 100,
                "baseline_test_seconds": 9,
            },
            "b.py": {
                "sample_count": 0,
                "mutant_count": 20,
                "baseline_test_seconds": 3,
            },
        }
    }

    estimates = {target.source: target for target in module.estimate_targets(rows, history)}
    assert estimates["a.py"].estimated_seconds == 120
    assert estimates["a.py"].estimate_kind == "history-ewma"
    assert estimates["b.py"].estimated_seconds == 60
    assert estimates["b.py"].estimate_kind == "bootstrap-mutants-x-baseline"


def test_unknown_cost_uses_inventory_median(module) -> None:
    rows = [("a.py", "tests/a"), ("b.py", "tests/b"), ("new.py", "tests/new")]
    history = {
        "entries": {
            "a.py": {"sample_count": 2, "ewma_mutation_seconds": 100},
            "b.py": {"sample_count": 2, "ewma_mutation_seconds": 300},
        }
    }

    estimates = {target.source: target for target in module.estimate_targets(rows, history)}
    assert estimates["new.py"].estimated_seconds == 200
    assert estimates["new.py"].estimate_kind == "inventory-median-fallback"


def test_cost_aware_packets_balance_pathological_inventory(module) -> None:
    targets = [
        module.Target("huge.py", "tests/huge", 1200, "history-ewma"),
        *[
            module.Target(f"tiny-{index:03}.py", "tests/tiny", 60, "history-ewma")
            for index in range(20)
        ],
    ]

    packets = module.plan_packets(targets, target_seconds=900, runner_capacity=4)
    loads = sorted(packet.estimated_seconds for packet in packets)

    assert len(packets) == 4
    assert max(loads) <= 1200
    assert min(loads) >= 360
    assert sum(loads) == 2400


def test_planner_is_deterministic(module) -> None:
    targets = [
        module.Target("c.py", "tests/c", 300, "history-ewma"),
        module.Target("a.py", "tests/a", 300, "history-ewma"),
        module.Target("b.py", "tests/b", 300, "history-ewma"),
        module.Target("d.py", "tests/d", 300, "history-ewma"),
    ]

    first = module.plan_payload(module.plan_packets(targets, 600, 2))
    second = module.plan_payload(module.plan_packets(list(reversed(targets)), 600, 2))
    assert first == second


def test_packet_count_expands_beyond_runner_capacity(module) -> None:
    targets = [
        module.Target(f"source-{index}.py", "tests/x", 900, "history-ewma") for index in range(10)
    ]

    assert module.packet_count(targets, target_seconds=900, runner_capacity=4) == 10


def test_simulation_reports_imbalance(module) -> None:
    packets = [
        module.Packet(0, [], 600),
        module.Packet(1, [], 900),
        module.Packet(2, [], 600),
    ]

    stats = module.simulation(packets)
    assert stats["median_seconds"] == 600
    assert stats["max_seconds"] == 900
    assert stats["imbalance"] == pytest.approx(1.5)
