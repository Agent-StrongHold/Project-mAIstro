"""Regression tests for the M1 shipped-surface truth matrix (#465)."""

from __future__ import annotations

from pathlib import Path

from scripts.shipped_surface_truth import (
    discover_backend_surfaces,
    discover_frontend_signals,
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
        "schema_version": 1,
        "backend_roots": ["backend"],
        "frontend_roots": ["frontend"],
        "backend_surfaces": [],
        "frontend_surfaces": [],
    }


def test_discovers_mutating_route_decorators_and_api_route_methods(
    tmp_path: Path,
) -> None:
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


def test_discovers_obvious_success_shaped_noop(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/build")
def build():
    return {"status": "completed", "id": "fake"}
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.obvious_fake_success is True


def test_discovers_frontend_timer_driven_execution_signal(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/Page.tsx",
        'setTimeout(() => setStatus("completed"), 500); // progress simulation\n',
    )
    assert [
        item.signal for item in discover_frontend_signals(tmp_path, ["frontend"])
    ] == ["timer-status-simulation"]


def test_missing_disposition_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/run")
def run():
    return create_run()
""",
    )
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unclassified backend surface" in error for error in errors)


def test_fake_success_cannot_be_labeled_local_only(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/build")
def build():
    return {"status": "completed"}
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
            "disposition": "local-only",
            "production_enabled": True,
            "reason": "planted fake success",
        }
    ]
    errors = validate_matrix(tmp_path, matrix)
    assert any("obvious success-shaped no-op" in error for error in errors)


def test_strict_gate_blocks_owned_but_unresolved_production_surface(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/run")
def run():
    return execute()
""",
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
    strict_errors = validate_matrix(tmp_path, matrix, strict=True)
    assert any("blocks Gate D" in error for error in strict_errors)


def test_manual_frontend_facade_must_reference_a_real_source(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    matrix = _matrix()
    matrix["frontend_surfaces"] = [
        {
            "source": "frontend/Missing.tsx",
            "signal": "manual-contract-gap",
            "disposition": "unresolved",
            "production_enabled": True,
            "owner_issue": 292,
            "reason": "tracked client-only facade",
        }
    ]
    errors = validate_matrix(tmp_path, matrix)
    assert any("frontend source does not exist" in error for error in errors)


def test_repository_surface_matrix_is_complete() -> None:
    matrix = load_matrix(MATRIX)
    errors = validate_matrix(ROOT, matrix, strict=False)
    assert not errors, "\n".join(errors)
