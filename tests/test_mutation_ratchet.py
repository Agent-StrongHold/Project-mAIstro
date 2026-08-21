"""Regression coverage for viability-adjusted mutation ratchets."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_ratchet.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_ratchet", SCRIPT)
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


def telemetry(source: str = "a.py", *, killed: int = 95, viable: int = 100, seconds: float = 600):
    return {
        "source": source,
        "complete": True,
        "viable_mutants": viable,
        "killed_mutants": killed,
        "surviving_mutants": viable - killed,
        "survivor_ids": ["L10:4 core/ReplaceBinaryOperator_Add_Sub | x + y => x - y"],
        "mutation_seconds": seconds,
        "verified_commit": "abc123",
        "verified_at": "2026-08-15T20:00:00+00:00",
    }


def test_global_floor_applies_to_unreviewed_sources(module) -> None:
    report = module.evaluate([telemetry(killed=89)], {"entries": {}}, {"entries": {}})
    assert report["quality_passed"] is False
    assert "below required 90.0%" in report["quality_failures"][0]


def test_reviewed_source_specific_rate_is_stricter_than_floor(module) -> None:
    baseline = {"entries": {"a.py": {"kill_rate": 0.98, "survivor_ids": []}}}
    report = module.evaluate([telemetry(killed=95)], baseline, {"entries": {}})
    assert report["quality_passed"] is False
    assert report["sources"][0]["required_kill_rate"] == pytest.approx(0.98)


def test_candidate_never_weakens_reviewed_baseline(module) -> None:
    baseline = {
        "owner": "@owner",
        "entries": {"a.py": {"kill_rate": 0.98, "killed": 98, "viable": 100}},
    }
    candidate = module.baseline_candidate([telemetry(killed=95)], baseline)
    assert candidate["entries"]["a.py"]["kill_rate"] == pytest.approx(0.98)


def test_candidate_tightens_reviewed_baseline_on_improvement(module) -> None:
    baseline = {"entries": {"a.py": {"kill_rate": 0.93}}}
    candidate = module.baseline_candidate([telemetry(killed=98)], baseline)
    assert candidate["entries"]["a.py"]["kill_rate"] == pytest.approx(0.98)
    assert candidate["entries"]["a.py"]["survivor_ids"]


def test_new_survivor_identity_is_reported_for_reviewed_source(module) -> None:
    baseline = {"entries": {"a.py": {"kill_rate": 0.95, "survivor_ids": ["old"]}}}
    report = module.evaluate([telemetry()], baseline, {"entries": {}})
    assert report["newly_surviving"]["a.py"] == telemetry()["survivor_ids"]


def test_runtime_regression_requires_history_confidence(module) -> None:
    history = {"entries": {"a.py": {"sample_count": 4, "ewma_mutation_seconds": 600.0}}}
    report = module.evaluate([telemetry(seconds=1300)], {"entries": {}}, history)
    assert report["runtime_regressions"] == ["a.py"]
    assert report["sources"][0]["runtime_ratio"] == pytest.approx(1300 / 600)

    low_confidence = {"entries": {"a.py": {"sample_count": 2, "ewma_mutation_seconds": 600.0}}}
    report = module.evaluate([telemetry(seconds=1300)], {"entries": {}}, low_confidence)
    assert report["runtime_regressions"] == []


def test_incomplete_telemetry_is_rejected(module, tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    row = telemetry()
    row["complete"] = False
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        module.read_telemetry(path)
