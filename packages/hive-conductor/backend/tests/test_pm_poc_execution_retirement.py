"""Reachability tests for the retired PM-Fleet POC execution switch (#129)."""

from __future__ import annotations

from pathlib import Path


_BACKEND = Path(__file__).resolve().parents[1]
_ENGINE = _BACKEND / "services" / "engine.py"


def test_demo_engine_has_one_executor_regardless_of_retired_poc_env() -> None:
    """Demo mode must not regain a second executor through an environment flag."""
    source = _ENGINE.read_text(encoding="utf-8")
    for retired in (
        "MAISTRO_POC_MODE",
        "HIVE_POC_MODE",
        "run_pm_task",
        "register_pm_fleet",
        "_pm_catalog",
    ):
        assert retired not in source


def test_engine_keeps_canonical_demo_executor() -> None:
    source = _ENGINE.read_text(encoding="utf-8")
    assert "from maistro.agents.conductor import run_task" in source
    assert "executor=run_task" in source
