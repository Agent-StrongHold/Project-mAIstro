"""The process-local Home Assistant confirmation store is retired (#48).

`services.ha_tools` used to hold approvals in module-level dicts, answered via
`/v1/confirms/{id}/respond` -- a route any authenticated user could reach and
that wrote Home Assistant state. Nothing in production ever produced a confirm,
and the owner decision on #48 is one approval model: human-required work is a
waiting human NodeRun answered through `/v1/hitl`. These tests pin that the
parallel store, its routes and the tool that would feed it stay gone.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_HA_TOOLS = Path(__file__).resolve().parents[1] / "services" / "ha_tools.py"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    main = importlib.import_module("main")
    # No SPA catch-all: an unregistered path must answer 404, not the fallback.
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path / "no-dist")
    client = TestClient(main.create_app())
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200
    return client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/confirms"),
        ("GET", "/v1/confirms/pending"),
        ("POST", "/v1/confirms/x/respond"),
    ],
)
def test_confirm_routes_are_not_mounted(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"response": "approved"})

    assert response.status_code == 404


def test_ha_tool_definitions_offer_no_confirm_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    ha_tools = importlib.import_module("services.ha_tools")
    monkeypatch.setattr(ha_tools, "HA_URL", "http://ha.invalid")
    monkeypatch.setattr(ha_tools, "HA_TOKEN", "token")

    names = [tool["function"]["name"] for tool in ha_tools.get_tool_definitions()]

    assert "ha_control" in names
    assert "ha_confirm" not in names


def test_ha_tools_holds_no_module_level_approval_state() -> None:
    tree = ast.parse(_HA_TOOLS.read_text())
    approval_name = re.compile(r"confirm|approv|pending", re.IGNORECASE)

    module_names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            module_names += [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_names.append(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_names.append(node.name)

    assert not [name for name in module_names if approval_name.search(name)]
