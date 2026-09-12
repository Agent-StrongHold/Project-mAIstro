"""Regression tests for the M1 shipped-surface truth matrix (#465)."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest
from scripts.shipped_surface_truth import (
    DYNAMIC_METHODS,
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


def test_fake_success_survives_logging_and_assignment_before_the_return(tmp_path: Path) -> None:
    """The exact #1144 fixture: a literal success-shaped return preceded by
    ordinary non-branching statements must still be caught."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/build")
def build():
    log("build requested")
    build_id = "fixture-123"
    return {"status": "completed", "id": build_id}
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.obvious_fake_success is True


def test_fake_success_detection_does_not_flag_a_handler_that_does_real_work(
    tmp_path: Path,
) -> None:
    """The regression this widening must not introduce: a handler that awaits
    a real effect and only *then* returns a status-shaped dict is not an
    obvious no-op, no matter how its return reads."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/cycle")
async def trigger_cycle():
    try:
        run_id = await svc.run_one_cycle()
        return {"status": "completed", "run_id": run_id}
    except RuntimeError:
        raise HTTPException(status_code=503)
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.obvious_fake_success is False


def test_fake_success_detection_stops_at_a_nested_helper_function(tmp_path: Path) -> None:
    """A `return` inside a closure defined *inside* the handler is not the
    handler's own return path and must not be attributed to it."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/build")
def build():
    def _inner():
        return {"status": "unrelated"}
    work = do_real_work()
    return {"status": "completed", "work": work}
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.obvious_fake_success is False


def test_discovers_add_api_route_registration_and_resolves_its_handler(tmp_path: Path) -> None:
    """The non-decorator FastAPI registration form (#1144): the route must be
    discovered, and an obvious fake-success handler registered this way must
    still be caught."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()

def build():
    log("build requested")
    return {"status": "completed"}

router.add_api_route("/build", build, methods=["POST"])
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert (surface.method, surface.route, surface.handler) == ("POST", "/build", "build")
    assert surface.obvious_fake_success is True


def test_add_api_route_with_an_unresolvable_endpoint_is_still_discovered(tmp_path: Path) -> None:
    """A handler the gate cannot statically resolve is never silently omitted
    from the inventory -- it still needs an explicit matrix disposition."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
router.add_api_route("/build", handlers.get("build"), methods=["POST"])
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert (surface.method, surface.route) == ("POST", "/build")
    assert surface.handler == "<unresolved endpoint>"
    assert surface.obvious_fake_success is False


def test_a_dynamically_built_route_path_is_never_silently_dropped(tmp_path: Path) -> None:
    """A non-literal route path (an f-string, a variable) is exactly the
    'non-literal routes' half of #1144's title: it must still surface as a
    discoverable, matrix-required entry rather than disappear."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
PREFIX = "/v2"
@router.post(f"{PREFIX}/build")
def build(): return work()
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.method == "POST"
    assert surface.route.startswith("<dynamic-route:")
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert any("unclassified backend surface" in error for error in errors)


def test_two_decorated_handlers_sharing_a_name_are_both_discovered(tmp_path: Path) -> None:
    """Python registers `@router.post("/a")` and then a redefinition of the
    same function name for `@router.post("/b")`; both routes are live at
    runtime, so both must be in the inventory (Codex, #1144)."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
@router.post("/a")
def handler(): return work()
@router.post("/b")
def handler(): return work()
""",
    )
    surfaces = discover_backend_surfaces(tmp_path, ["backend"])
    assert [(item.method, item.route, item.handler) for item in surfaces] == [
        ("POST", "/a", "handler"),
        ("POST", "/b", "handler"),
    ]


def test_add_api_route_with_a_keyword_path_is_discovered(tmp_path: Path) -> None:
    """`router.add_api_route(path="/build", endpoint=build, methods=["POST"])`
    has no positional arguments and is just as live as the positional form."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()

def build():
    log("build requested")
    return {"status": "completed"}

router.add_api_route(path="/build", endpoint=build, methods=["POST"])
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert (surface.method, surface.route, surface.handler) == ("POST", "/build", "build")
    assert surface.obvious_fake_success is True


def test_a_non_literal_methods_collection_is_never_silently_dropped(tmp_path: Path) -> None:
    """`methods=MUTATING_METHODS` cannot be read statically and may hold
    POST; like a dynamic path it becomes a matrix-required stand-in rather
    than an absent surface, on both registration forms."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()
MUTATING = ["POST"]
VERB = "POST"

def build(): return work()

router.add_api_route("/build", build, methods=MUTATING)

@router.api_route("/cancel", methods=[VERB])
def cancel(): return work()
""",
    )
    surfaces = discover_backend_surfaces(tmp_path, ["backend"])
    assert [(item.method, item.route) for item in surfaces] == [
        (DYNAMIC_METHODS, "/build"),
        (DYNAMIC_METHODS, "/cancel"),
    ]
    (tmp_path / "frontend").mkdir()
    errors = validate_matrix(tmp_path, _matrix())
    assert sum("unclassified backend surface" in error for error in errors) == 2


def test_a_qualified_endpoint_is_not_resolved_by_its_bare_name(tmp_path: Path) -> None:
    """`handlers.build` is an imported handler; a local function that merely
    shares the bare name `build` must not lend it a fake-success verdict."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
from . import handlers
router = APIRouter()

def build():
    return {"status": "completed"}

router.add_api_route("/build", handlers.build, methods=["POST"])
""",
    )
    [surface] = discover_backend_surfaces(tmp_path, ["backend"])
    assert surface.handler == "handlers.build"
    assert surface.obvious_fake_success is False


def test_state_mutation_is_real_work_not_a_fake_success(tmp_path: Path) -> None:
    """A synchronous handler that writes through an attribute or a subscript
    has a real effect that outlives it; only an inert local binding before
    the canned return keeps a handler an obvious no-op."""
    _write(
        tmp_path / "backend/routes.py",
        """
from fastapi import APIRouter
router = APIRouter()

@router.post("/enable")
def enable():
    state["enabled"] = True
    return {"status": "completed"}

@router.post("/finish")
def finish():
    record.status = "done"
    return {"status": "completed"}

@router.post("/forget")
def forget():
    del jobs["x"]
    return {"status": "completed"}

@router.post("/noop")
def noop():
    label = "noop"
    return {"status": "completed"}
""",
    )
    fake = {
        s.route: s.obvious_fake_success for s in discover_backend_surfaces(tmp_path, ["backend"])
    }
    assert fake == {"/enable": False, "/finish": False, "/forget": False, "/noop": True}


def test_a_dynamic_route_identity_follows_its_expression(tmp_path: Path) -> None:
    """Rewriting `f"{PREFIX}/safe"` to `f"{PREFIX}/admin"` on the same line is
    a different shipped route and must not inherit the old disposition."""
    source = """
from fastapi import APIRouter
router = APIRouter()
PREFIX = "/v2"
@router.post(f"{PREFIX}/%s")
def build(): return work()
"""
    _write(tmp_path / "backend/routes.py", source % "safe")
    [before] = discover_backend_surfaces(tmp_path, ["backend"])
    _write(tmp_path / "backend/routes.py", source % "admin")
    [after] = discover_backend_surfaces(tmp_path, ["backend"])
    assert before.route.startswith("<dynamic-route:") and after.route.startswith("<dynamic-route:")
    assert before.route != after.route


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
