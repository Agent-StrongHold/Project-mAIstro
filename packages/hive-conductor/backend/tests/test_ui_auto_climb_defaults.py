"""Defaults for the autonomous UI climber stay on loopback."""

from __future__ import annotations

import asyncio
import runpy
import sys
import types
from pathlib import Path
from typing import Any

import pytest


def test_default_climb_url_is_loopback() -> None:
    from services import ui_auto_climb

    assert ui_auto_climb.DEFAULT_CLIMB_URL == "http://localhost:8101"
    # Binding the default at definition time is what coverage measures.
    assert ui_auto_climb.auto_climb.__defaults__[0] == ui_auto_climb.DEFAULT_CLIMB_URL


def test_cli_parser_defaults_to_the_module_loopback_url() -> None:
    from services import ui_auto_climb

    args = ui_auto_climb.build_cli_parser().parse_args([])
    assert args.url == ui_auto_climb.DEFAULT_CLIMB_URL


def test_main_parses_argv_and_runs_auto_climb(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` is the covered entry for ``python -m services.ui_auto_climb``."""
    from services import ui_auto_climb

    seen: dict[str, Any] = {}

    async def fake_climb(component: str, url: str, path: str, max_passes: int) -> dict[str, Any]:
        seen.update(component=component, url=url, path=path, max_passes=max_passes)
        return {"best_score": 1, "passes": max_passes, "history": []}

    monkeypatch.setattr(ui_auto_climb, "auto_climb", fake_climb)
    out = ui_auto_climb.main(["--component", "X.tsx", "--passes", "2", "--path", "/x"])
    assert out["best_score"] == 1
    assert seen == {
        "component": "X.tsx",
        "url": ui_auto_climb.DEFAULT_CLIMB_URL,
        "path": "/x",
        "max_passes": 2,
    }


def test_dunder_main_delegates_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m services.ui_auto_climb`` must hit the shared ``main()`` entry."""
    from services import ui_auto_climb

    runs: list[Any] = []

    def fake_run(coro: Any) -> Any:
        runs.append(coro)
        if hasattr(coro, "close"):
            coro.close()
        return {"best_score": 0, "passes": 0, "history": []}

    monkeypatch.setattr(sys, "argv", ["ui_auto_climb", "--passes", "1"])
    monkeypatch.setattr(asyncio, "run", fake_run)
    runpy.run_path(str(Path(ui_auto_climb.__file__)), run_name="__main__")
    assert runs, "dunder-main must call main() → asyncio.run(auto_climb(...))"


def test_loopback_service_defaults_import() -> None:
    """Module-level loopback defaults must execute under coverage (diff-coverage)."""
    from services import mcp_defaults, pipeline_orchestrator, ui_climb_vm

    assert "127.0.0.1" in mcp_defaults.FILESYSTEM_MCP_URL
    assert "127.0.0.1" in pipeline_orchestrator.FANTASIA_BASE
    assert "localhost" in ui_climb_vm.BROKER_URL


def test_trigger_deploy_lazy_imports_tork_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy import line must run under coverage (optional tork adapter)."""
    from services import pipeline_orchestrator

    stub = types.ModuleType("services.tork_client")

    def _yaml(**_: Any) -> str:
        return "job: yaml"

    async def _submit(_yaml_text: str) -> str:
        return "job-1"

    stub.build_job_yaml = _yaml  # type: ignore[attr-defined]
    stub.submit_job = _submit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "services.tork_client", stub)

    out = asyncio.run(pipeline_orchestrator.trigger_deploy("proj-1"))
    assert out == {"tork_job_id": "job-1", "status": "building"}
