"""Retirement evidence for the maistro-server PM-Fleet POC surfaces (#129)."""

from pathlib import Path

from maistro_server.main import app

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


def test_retired_pm_agents_http_entrypoint_is_not_registered() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/maistro/agents" not in paths
    assert not any(path.startswith("/v1/maistro/agents/") for path in paths)


def test_server_main_does_not_mount_a_pm_specific_agents_router() -> None:
    source = _MAIN.read_text(encoding="utf-8")
    assert "agents.router" not in source
