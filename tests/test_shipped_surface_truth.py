"""Regression tests for the M1 shipped-surface truth matrix (#465)."""

from __future__ import annotations

from pathlib import Path

from scripts.shipped_surface_truth import (
    discover_backend_surfaces,
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
        "frontend_roots": ["frontend"],
        "backend_surfaces": [],
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


def test_repository_surface_matrix_is_complete() -> None:
    matrix = load_matrix(MATRIX)
    errors = validate_matrix(ROOT, matrix, strict=False)
    assert not errors, "\n".join(errors)
