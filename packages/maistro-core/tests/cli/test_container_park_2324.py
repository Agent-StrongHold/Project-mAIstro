"""#2324 — keep ``maistro.cli._container`` CONNECT / unwired from the Typer surface.

Decision A on #2280 keeps the CLI at operator-lifecycle only for v1.0. The
Docker/Podman runtime package stays a CONNECT leaf until a named operator
subcommand (or ADR-093 sandbox consumer) reaches it — never product CRUD.
"""

from __future__ import annotations

import json
from pathlib import Path

from maistro.cli import app

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DISPOSITIONS = _REPO_ROOT / "quality" / "reachability-dispositions.json"

_CONTAINER_MODULES = (
    "maistro.cli._container",
    "maistro.cli._container.docker_runtime",
    "maistro.cli._container.lifecycle",
    "maistro.cli._container.podman_runtime",
    "maistro.cli._container.runtime",
)


def _registered_group_names() -> set[str]:
    return {str(group.name) for group in app.registered_groups if group.name}


def test_typer_app_has_no_container_subcommand() -> None:
    """Product CLI must not expose a ``container`` group or leaf command."""
    names = _registered_group_names()
    assert "container" not in names
    assert "_container" not in names
    leaf = {command.name for command in app.registered_commands if command.name}
    assert "container" not in leaf


def test_cli_container_runtimes_remain_connect_disposition() -> None:
    """Reachability ledger keeps the package CONNECT (parked), not RETIRE/INTERNAL."""
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    groups = payload["groups"]
    match = next(g for g in groups if g["id"] == "cli-container-runtimes")
    assert match["disposition"] == "CONNECT"
    assert set(match["modules"]) == set(_CONTAINER_MODULES)
    rationale = str(match["rationale"]).lower()
    assert "2324" in rationale or "#2324" in str(match["rationale"])
    assert "2280" in rationale or "#2280" in str(match["rationale"])
