"""The server must not seed a parallel PM catalog at startup (#129)."""

from __future__ import annotations

from pathlib import Path


_MAIN = Path(__file__).resolve().parents[1] / "src" / "maistro_server" / "main.py"


def test_server_startup_cannot_resurrect_pm_poc_catalog() -> None:
    source = _MAIN.read_text(encoding="utf-8")
    for retired in (
        "MAISTRO_POC_MODE",
        "register_pm_fleet",
        "pm_catalog",
        "pm_fleet_catalog_seeded",
    ):
        assert retired not in source


def test_server_task_execution_stays_on_canonical_executor() -> None:
    source = _MAIN.read_text(encoding="utf-8")
    assert "from maistro.agents.conductor import run_task" in source
    assert "executor=run_task" in source
