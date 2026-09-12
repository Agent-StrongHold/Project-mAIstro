"""Regression tests for the M1 shipped-surface truth matrix (#465)."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest
from scripts.shipped_surface_truth import (
    discover_backend_surfaces,
    discover_cli_surfaces,
    discover_frontend_surfaces,
    load_matrix,
    validate_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "quality" / "shipped-surface-truth.json"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _matrix() -> dict:
    return {
        "schema_version": 2,
        "backend_roots": ["backend"],
        "cli_roots": [],
        "cli_project_roots": [],
        "lab_roots": [],
        "frontend_roots": ["frontend"],
        "backend_surfaces": [],
        "cli_surfaces": [],
        "frontend_surfaces": [],
    }


def test_discovers_mutating_route_decorators_and_api_route_methods(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/run")
def run(): return {"id": "r"}
@router.api_route("/cancel", methods=["GET", "POST", "DELETE"])
def cancel(): return None
@router.get("/status")
def status(): return {}
""",
    )
    surfaces = discover_backend_surfaces(tmp_path, ["backend"])
    assert [(item.method, item.route) for item in surfaces] == [
        ("DELETE", "/cancel"),
        ("POST", "/cancel"),
        ("POST", "/run"),
    ]


def test_discovers_websocket_routes_regardless_of_mutating_verb_status(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/ws.py",
        """
from fastapi import APIRouter, WebSocket
router = APIRouter()
@router.websocket("/tasks/{task_id}")
async def stream_task(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
@router.get("/status")
def status(): return {}
""",
    )
    surfaces = discover_backend_surfaces(tmp_path, ["backend"])
    assert [(item.method, item.route) for item in surfaces] == [
        ("WEBSOCKET", "/tasks/{task_id}"),
    ]


def test_missing_websocket_route_disposition_fails_closed(tmp_path: Path) -> None:
    """A discriminatory fixture: an undisposed `@router.websocket(...)` route
    must be just as unable to escape the inventory as an undisposed mutating
    HTTP route (#1122)."""
    _write(
        tmp_path / "backend/ws.py",
        """
from fastapi import APIRouter, WebSocket
router = APIRouter()
@router.websocket("/events/{run_id}")
async def stream_events(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
""",
    )
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unclassified backend surface" in error and "WEBSOCKET" in error for error in errors)


def test_discovers_cli_commands_and_argparse_subcommands(tmp_path: Path) -> None:
    _write(
        tmp_path / "cli/app.py",
        """
import argparse
import typer
app = typer.Typer()
@app.command("rotate")
def rotate_key(): pass
parser = argparse.ArgumentParser()
sub = parser.add_subparsers()
sub.add_parser("run")
""",
    )
    surfaces = discover_cli_surfaces(tmp_path, ["cli"])
    assert [(item.route, item.handler) for item in surfaces] == [
        ("rotate", "rotate_key"),
        ("run", "main"),
    ]


def test_published_cli_entrypoint_is_discovered_and_requires_disposition(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
[project]
name = "fixture"
version = "0.0.0"
[project.scripts]
fixture-autorun = "cli.autorun:main"
""",
    )
    _write(
        tmp_path / "cli/autorun.py",
        """
import argparse

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    return 0
""",
    )
    surfaces = discover_cli_surfaces(tmp_path, ["cli"], ["pyproject.toml"])
    assert [(item.route, item.handler) for item in surfaces] == [("fixture-autorun", "main")]

    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["cli_roots"] = ["cli"]
    matrix["cli_project_roots"] = ["pyproject.toml"]
    errors = validate_matrix(tmp_path, matrix)
    assert any(
        "unclassified CLI surface" in error and "fixture-autorun" in error for error in errors
    )


def test_workspace_project_script_resolves_member_source(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
[project]
name = "workspace"
version = "0.0.0"
[project.scripts]
workspace-cli = "member.cli:main"
""",
    )
    _write(
        tmp_path / "packages/member/src/member/cli.py",
        """
def main():
    return 0
""",
    )
    surfaces = discover_cli_surfaces(tmp_path, [], ["pyproject.toml"])
    assert [(item.source, item.route, item.handler) for item in surfaces] == [
        ("packages/member/src/member/cli.py", "workspace-cli", "main")
    ]


def test_direct_python_module_entrypoint_is_discovered(tmp_path: Path) -> None:
    _write(
        tmp_path / "cli/free_router.py",
        """
def main():
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""",
    )
    surfaces = discover_cli_surfaces(tmp_path, ["cli"])
    assert [(item.route, item.handler) for item in surfaces] == [("free_router", "main")]

    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["cli_roots"] = ["cli"]
    errors = validate_matrix(tmp_path, matrix)
    assert any("unclassified CLI surface" in error and "free_router" in error for error in errors)


def test_unconfigured_lab_root_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path / "labs/demo.py",
        """
def main():
    return 0

if __name__ == "__main__":
    main()
""",
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unconfigured lab surface root: labs" in error for error in errors)


def test_declared_lab_root_is_scanned_for_cli_and_backend_surfaces(tmp_path: Path) -> None:
    _write(
        tmp_path / "labs/demo.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.websocket("/events")
async def events(websocket):
    pass

def main():
    return 0

if __name__ == "__main__":
    main()
""",
    )
    _write(tmp_path / "frontend/.keep", "")
    (tmp_path / "backend").mkdir()
    matrix = _matrix()
    matrix["lab_roots"] = ["labs"]
    errors = validate_matrix(tmp_path, matrix)
    assert any("unclassified backend surface" in error and "WEBSOCKET" in error for error in errors)
    assert any("unclassified CLI surface" in error and "demo" in error for error in errors)


def test_missing_cli_surface_disposition_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path / "cli/app.py",
        """
import typer
app = typer.Typer()
@app.command("rotate")
def rotate_key(): pass
""",
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["cli_roots"] = ["cli"]
    errors = validate_matrix(tmp_path, matrix)
    assert any("unclassified CLI surface" in error and "rotate" in error for error in errors)


def test_repo_wide_backend_discovery_excludes_tests_and_examples(tmp_path: Path) -> None:
    route = 'from fastapi import APIRouter\nrouter=APIRouter()\n@router.post("/run")\ndef run(): return execute()\n'
    _write(tmp_path / "backend/live.py", route)
    _write(tmp_path / "backend/tests/test_fake.py", route.replace("/run", "/test-run"))
    _write(tmp_path / "backend/examples/demo.py", route.replace("/run", "/demo-run"))
    assert [s.route for s in discover_backend_surfaces(tmp_path, ["backend"])] == ["/run"]


def test_deliberately_planted_production_fake_success_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/build")
def build():
    return {"status": "completed", "id": "fixture-123"}
""",
    )
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["backend_surfaces"] = [
        {
            "source": "backend/routes.py",
            "method": "POST",
            "route": "/build",
            "handler": "build",
            "disposition": "canonical",
            "production_enabled": True,
            "effect_owner": "fake.fixture",
            "reason": "deliberately planted fake-success fixture",
        }
    ]
    errors = validate_matrix(tmp_path, matrix)
    assert any("production success-shaped no-op" in error for error in errors)


def test_frontend_timer_detector_rejects_only_success_callback_not_request_timeout(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "frontend/Page.tsx",
        """
const timeout = setTimeout(() => controller.abort(), 120000);
const progressLabel = "progress";
setTimeout(() => setStatus("completed"), 500);
""",
    )
    surfaces = discover_frontend_surfaces(tmp_path, ["frontend"])
    assert [s.signal for s in surfaces] == ["timer-status-simulation"]


def test_request_abort_timeout_with_unrelated_progress_copy_is_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/Page.tsx",
        'const timeout = setTimeout(() => controller.abort(), 120000);\nconst label = "progress";\n',
    )
    assert discover_frontend_surfaces(tmp_path, ["frontend"]) == []


def test_discovers_literal_mutating_frontend_api_call(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/Page.tsx",
        'await fetch("/v1/runs", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(x) });\n',
    )
    [surface] = discover_frontend_surfaces(tmp_path, ["frontend"])
    assert (surface.signal, surface.method, surface.route) == (
        "mutating-api-call",
        "POST",
        "/v1/runs",
    )


def test_missing_new_route_disposition_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        'from fastapi import APIRouter\nrouter=APIRouter()\n@router.post("/run")\ndef run(): return create_run()\n',
    )
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unclassified backend surface" in error for error in errors)


def test_missing_new_frontend_mutation_disposition_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    _write(tmp_path / "frontend/Page.tsx", 'fetch("/v1/run", {method: "POST"});\n')
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unclassified frontend execution surface" in error for error in errors)


def test_production_timer_success_cannot_be_classified_truthful(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    _write(tmp_path / "frontend/Page.tsx", 'setTimeout(() => setStatus("completed"), 500);\n')
    matrix = _matrix()
    matrix["frontend_surfaces"] = [
        {
            "source": "frontend/Page.tsx",
            "signal": "timer-status-simulation",
            "disposition": "local-only",
            "production_enabled": True,
            "truth_contract": "client animation",
            "reason": "planted client-timer success",
        }
    ]
    errors = validate_matrix(tmp_path, matrix)
    assert any("production timer-driven execution state" in error for error in errors)


def test_strict_gate_blocks_owned_unresolved_production_surface(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        'from fastapi import APIRouter\nrouter=APIRouter()\n@router.post("/run")\ndef run(): return execute()\n',
    )
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["backend_surfaces"] = [
        {
            "source": "backend/routes.py",
            "method": "POST",
            "route": "/run",
            "handler": "run",
            "disposition": "unresolved",
            "production_enabled": True,
            "owner_issue": 999,
            "reason": "owned convergence gap",
        }
    ]
    assert validate_matrix(tmp_path, matrix, strict=False) == []
    assert any("blocks Gate D" in error for error in validate_matrix(tmp_path, matrix, strict=True))


def test_disabled_surface_requires_owner_and_is_not_production_enabled(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        'from fastapi import APIRouter\nrouter=APIRouter()\n@router.post("/x")\ndef x(): return work()\n',
    )
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["backend_surfaces"] = [
        {
            "source": "backend/routes.py",
            "method": "POST",
            "route": "/x",
            "handler": "x",
            "disposition": "disabled",
            "production_enabled": True,
            "reason": "contained",
        }
    ]
    errors = validate_matrix(tmp_path, matrix)
    assert any("must name owner_issue" in error for error in errors)
    assert any("cannot be production_enabled" in error for error in errors)


def test_server_container_entrypoint_is_in_the_cli_discovery_roots() -> None:
    matrix = load_matrix(MATRIX)
    surfaces = discover_cli_surfaces(
        ROOT,
        matrix["cli_roots"],
        matrix["cli_project_roots"],
    )
    assert any(
        surface.source == "packages/maistro-server/src/maistro_server/entrypoint.py"
        and surface.route == "entrypoint"
        and surface.handler == "main"
        for surface in surfaces
    )


def test_repository_surface_matrix_is_complete() -> None:
    matrix = load_matrix(MATRIX)
    errors = validate_matrix(ROOT, matrix, strict=False)
    assert not errors, "\n".join(errors)


# --------------------------------------------------------------------------
# the checker CLI (scripts/check-shipped-surface-truth.py)
# --------------------------------------------------------------------------


def _load_cli(monkeypatch: pytest.MonkeyPatch):
    """Import the checker CLI the way `python scripts/<name>.py` would.

    The CLI does a bare ``from shipped_surface_truth import ...``, so the
    scripts directory has to be importable for the module to load at all.
    """
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "check_shipped_surface_truth", ROOT / "scripts" / "check-shipped-surface-truth.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_cli_reports_the_clean_matrix(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    cli = _load_cli(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check-shipped-surface-truth.py"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "Shipped-surface truth matrix is complete." in out


def test_checker_cli_discover_json_prints_the_machine_surface_set(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    cli = _load_cli(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check-shipped-surface-truth.py", "--discover-json"])
    assert cli.main() == 0
    discovered = json.loads(capsys.readouterr().out)
    assert isinstance(discovered["backend_surfaces"], list)
    assert discovered["backend_surfaces"]


def test_checker_cli_exit_code_reflects_reported_errors(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Exit 1 exactly when the report says the matrix failed.

    Non-strict always passes today; the strict Gate D closeout form fails while
    the six disclosed unresolved facades remain. Asserting the invariant, not
    the facade count, keeps the test truthful as owners land their fixes.
    """
    cli = _load_cli(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check-shipped-surface-truth.py", "--require-clean"])
    code = cli.main()
    out = capsys.readouterr().out
    assert (code == 1) == ("Shipped-surface truth matrix failed:" in out)


def test_checker_cli_main_guard_exits_from_script_execution(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    cli_path = str(ROOT / "scripts" / "check-shipped-surface-truth.py")
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setattr(sys, "argv", ["check-shipped-surface-truth.py", "--discover-json"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(cli_path, run_name="__main__")
    assert excinfo.value.code == 0
    assert json.loads(capsys.readouterr().out)["backend_surfaces"]
