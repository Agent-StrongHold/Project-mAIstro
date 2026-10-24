"""Defaults for the autonomous UI climber stay on loopback."""

from __future__ import annotations


def test_default_climb_url_is_loopback() -> None:
    from services import ui_auto_climb

    assert ui_auto_climb.DEFAULT_CLIMB_URL == "http://localhost:8101"
    # Binding the default at definition time is what coverage measures.
    assert ui_auto_climb.auto_climb.__defaults__[0] == ui_auto_climb.DEFAULT_CLIMB_URL


def test_cli_parser_defaults_to_the_module_loopback_url() -> None:
    from services import ui_auto_climb

    args = ui_auto_climb.build_cli_parser().parse_args([])
    assert args.url == ui_auto_climb.DEFAULT_CLIMB_URL


def test_loopback_service_defaults_import() -> None:
    """Module-level loopback defaults must execute under coverage (diff-coverage)."""
    from services import mcp_defaults, pipeline_orchestrator, ui_climb_vm

    assert "127.0.0.1" in mcp_defaults.FILESYSTEM_MCP_URL
    assert (
        "127.0.0.1" in pipeline_orchestrator.FANTASIA_BASE
        or pipeline_orchestrator.FANTASIA_BASE == ""
    )
    assert "localhost" in ui_climb_vm.BROKER_URL
