"""Regression tests for #860 soak-evidence promotion gates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "soak" / "run_soak.py"


@pytest.fixture(scope="module")
def soak() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_soak_promotion_gates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_evidence() -> dict[str, object]:
    return {
        "thresholds": {
            "checks": {
                "exactly_once_task_admission": True,
                "exactly_once_schedule_occurrence": True,
                "rate_limit_enforced": True,
                "lb_failover_bounded": {"ok": True},
                "replica_2_rejoined": True,
                "nonterminal_runs_after_settle": {"ok": True},
                "task_admission_availability": {"ok": True},
                "sustain_duration": {"ok": True},
                "graceful_drain": {"required": True, "ok": True},
            }
        }
    }


def test_every_recorded_hard_gate_must_pass(soak: ModuleType) -> None:
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    checks["lb_failover_bounded"] = {"ok": False}  # type: ignore[index]
    checks["nonterminal_runs_after_settle"] = {"ok": False}  # type: ignore[index]
    checks["task_admission_availability"] = {"ok": False}  # type: ignore[index]
    checks["sustain_duration"] = {"ok": False}  # type: ignore[index]
    checks["graceful_drain"] = {"required": True, "ok": False}  # type: ignore[index]

    assert soak.failed_promotion_checks(evidence) == [
        "lb_failover_bounded",
        "nonterminal_runs_after_settle",
        "task_admission_availability",
        "sustain_duration",
        "graceful_drain",
    ]


def test_abrupt_kill_does_not_claim_a_graceful_drain(soak: ModuleType) -> None:
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    checks["graceful_drain"] = {"required": False, "ok": False}  # type: ignore[index]

    assert soak.failed_promotion_checks(evidence) == []
