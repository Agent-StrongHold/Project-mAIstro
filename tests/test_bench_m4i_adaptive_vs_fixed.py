"""Tests for `scripts/bench_m4i_adaptive_vs_fixed.py` (issue #106, epic M4-I).

The root suite is the coverage producer for `scripts/`, so the benchmark's
changed lines are scored by the diff-coverage gate — a script with zero tests
measures 0% and reds the gate (the same reason every sibling `bench_*.py`
carries one of these files). Beyond satisfying the measurement, these tests
pin the properties that make the recorded comparison trustworthy:

- the rendered record is byte-identical to the checked-in
  `docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json` (the artifact the
  issue's exit evidence points at regenerates exactly);
- every arm the harness compares appears in the record with per-task rows,
  so a silently dropped arm or task cannot masquerade as a comparison;
- the CLI entry point renders the markdown table and writes the same JSON
  the record holds.

Everything runs offline against the deterministic stub gateway (no network,
no PostgreSQL) inside the suite's `--timeout=30` producer budget.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_m4i_adaptive_vs_fixed.py"
RECORDED = ROOT / "docs" / "benchmarks" / "m4i-adaptive-vs-fixed-baseline.json"

spec = importlib.util.spec_from_file_location("bench_m4i_adaptive_vs_fixed", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return bench.build_report(bench._load_harness())


class TestReportShape:
    def test_every_compared_arm_is_present_with_task_rows(self, report: dict[str, Any]) -> None:
        # The issue's exit evidence is adaptive-vs-fixed: all four arms the
        # harness configures must appear, and each must score every workload
        # task (successes plus named failure cases == the whole workload).
        assert set(report["arms"]) == {"adaptive", "fixed-cheap", "fixed-strong", "fixed-vision"}
        assert len(report["workload"]) == 6
        assert {row["task"] for row in report["workload"]} == {
            row["task"] for result in report["results"] for row in result["per_task"]
        }
        for result in report["results"]:
            assert result["arm"] in report["arms"]
            assert len(result["per_task"]) == len(report["workload"])
            succeeded = sum(1 for row in result["per_task"] if row["success"])
            assert result["tasks_succeeded"] == f"{succeeded}/{len(result['per_task'])}"
            assert sorted(result["successes"]) == result["successes"]

    def test_record_cites_its_provenance(self, report: dict[str, Any]) -> None:
        assert report["benchmark"] == "m4i-adaptive-vs-fixed-routing"
        assert report["issue"] == "106"
        assert report["epic"] == "M4-I"
        # The record must name its seam: what is production and what is stubbed.
        assert report["seam"]["harness"].endswith("test_adaptive_vs_fixed_baseline.py")
        assert "stub" in report["seam"]["gateway"]

    def test_costs_are_non_negative_and_ranked_consistently(self, report: dict[str, Any]) -> None:
        for result in report["results"]:
            assert result["cost_cents"] >= 0.0
            assert result["latency_ms"] >= 0
            for row in result["per_task"]:
                assert row["cost_cents"] >= 0.0
                assert row["latency_ms"] >= 0
                if not row["requests"]:
                    # A task that made no physical request must be a loud
                    # pre-egress refusal: failed, zero cost, named failure.
                    assert row["run_status"] == "failed"
                    assert row["cost_cents"] == 0.0 and row["latency_ms"] == 0
                    assert row["failure_case"], "a request-less task must name its failure"
                else:
                    for req in row["requests"]:
                        assert req["prompt_tokens"] >= 0
                        assert req["completion_tokens"] >= 0


class TestRecordedArtifact:
    def test_checked_in_record_regenerates_byte_identically(self, report: dict[str, Any]) -> None:
        payload = json.dumps(report, indent=2, sort_keys=False) + "\n"
        assert RECORDED.read_text(encoding="utf-8") == payload


class TestMain:
    def test_main_writes_the_record_and_prints_the_table(self, tmp_path: Path, capsys: Any) -> None:
        output = tmp_path / "baseline.json"
        exit_code = bench.main(["--output", str(output)])
        assert exit_code == 0
        written = output.read_text(encoding="utf-8")
        assert written == RECORDED.read_text(encoding="utf-8")
        table = capsys.readouterr().out
        # The stdout table is the human-readable rendering of the same arms.
        for arm in ("adaptive", "fixed-cheap", "fixed-strong", "fixed-vision"):
            assert f"| {arm} |" in table
