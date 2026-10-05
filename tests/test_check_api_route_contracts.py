"""In-process proof for the API route-contract gate (#389).

`packages/hive-conductor/backend/tests/test_noop_route_contracts.py` proves the
gate passes on the shipped tree by running it as a subprocess. That is the
shipped-behavior proof, but a subprocess records no coverage — the diff gate
scores `scripts/` files, so the gate's own logic must also be exercised in
process. This module does that: unit proofs for the canned-handler detector,
the temporary-disposition expiry rules, and the inventory-rot check, plus a
clean `main()` run against the real tree.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-api-route-contracts.py"

spec = importlib.util.spec_from_file_location("_check_api_route_contracts", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _func(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    node = tree.body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


# --------------------------------------------------------------------------- #
# _pure_constant: a literal built only from constants vs anything observable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1", True),
        ('"x"', True),
        ("[]", True),
        ("(1, 2)", True),
        ("{1, 2}", True),
        ('{"status": "ok", "items": []}', True),
        ("{'nested': {'a': [1, (2,)]}}", True),
        ("{None: 1}", True),
        ("status", False),
        ("build_dockerfile()", False),
        ('{"log": render_log()}', False),
    ],
)
def test_pure_constant_classification(expression: str, expected: bool) -> None:
    assert mod._pure_constant(ast.parse(expression, mode="eval").body) is expected


# --------------------------------------------------------------------------- #
# _performs_real_work: constants are canned only when nothing else is called
# --------------------------------------------------------------------------- #


def test_constants_with_no_calls_perform_no_work() -> None:
    assert mod._performs_real_work(_func("def h():\n    return []\n")) is False


def test_httpexception_only_body_is_not_real_work() -> None:
    source = "def h():\n    raise HTTPException(status_code=503)\n    return []\n"
    assert mod._performs_real_work(_func(source)) is False


def test_any_other_call_is_real_work() -> None:
    assert mod._performs_real_work(_func("def h():\n    return sorted([3, 1])\n")) is True


# --------------------------------------------------------------------------- #
# _router_decorator: (method, path) extraction
# --------------------------------------------------------------------------- #


def test_router_decorator_declares_method_and_path() -> None:
    assert mod._router_decorator(_func('@router.get("/things")\ndef h():\n    return []\n')) == (
        "get",
        "/things",
    )


def test_non_router_decorator_is_ignored() -> None:
    assert mod._router_decorator(_func('@app.get("/things")\ndef h():\n    return []\n')) is None


def test_decorator_without_path_constant_is_ignored() -> None:
    source = "@router.post(name=routes_name)\ndef h():\n    return []\n"
    assert mod._router_decorator(_func(source)) is None


# --------------------------------------------------------------------------- #
# _handlers + _canned_handlers on a synthetic routes tree
# --------------------------------------------------------------------------- #


CANNED = """
@router.get("/canned")
def canned_things():
    return {"items": [], "status": "clean"}
"""

REAL_WORK = """
@router.get("/real")
def real_things():
    entries = sorted([1])
    return {"items": entries}
"""

HTTP_ONLY = """
@router.post("/refuse")
def refuse():
    raise HTTPException(status_code=501, detail="unsupported")
"""

NO_RETURN = """
@router.get("/streams")
def streams():
    yield 1
"""


def _write_routes(tmp_path: Path, *bodies: str) -> Path:
    for index, body in enumerate(bodies):
        (tmp_path / f"routes_{index}.py").write_text(
            "from fastapi import APIRouter, HTTPException\nrouter = APIRouter()\n" + body
        )
    return tmp_path


def test_canned_handlers_flags_only_constant_noop_handlers(tmp_path, monkeypatch) -> None:
    routes = _write_routes(tmp_path, CANNED, REAL_WORK, HTTP_ONLY, NO_RETURN)
    monkeypatch.setattr(mod, "ROUTES_DIR", routes)
    handlers = mod._handlers()
    by_name = {func.name: (file, method, path) for file, func, method, path in handlers}
    # The generator-style handler is collected too, but its lack of a return
    # keeps it out of the canned findings below.
    assert set(by_name) == {"canned_things", "real_things", "refuse", "streams"}
    findings = mod._canned_handlers(handlers)
    assert len(findings) == 1
    assert "canned_things" in findings[0]
    assert "GET /canned" in findings[0]


# --------------------------------------------------------------------------- #
# _temporary_expired: the escape hatch must expire
# --------------------------------------------------------------------------- #


def test_future_expiry_is_accepted() -> None:
    entry: dict[str, Any] = {"expires": (date.today() + timedelta(days=7)).isoformat()}
    assert mod._temporary_expired(entry) is None


def test_past_expiry_is_reported() -> None:
    entry = {"expires": (date.today() - timedelta(days=1)).isoformat()}
    assert mod._temporary_expired(entry) == f"expired {entry['expires']}"


def test_unparseable_expiry_is_reported() -> None:
    assert "unparseable" in mod._temporary_expired({"expires": "soon"})


def test_datetime_expiry_branches() -> None:
    future: dict[str, Any] = {"expires": datetime.now() + timedelta(days=1)}
    past: dict[str, Any] = {"expires": datetime.now() - timedelta(days=1)}
    assert mod._temporary_expired(future) is None
    assert mod._temporary_expired(past) is not None


def test_missing_expiry_is_reported() -> None:
    assert "no parseable expires date" in mod._temporary_expired({})


# --------------------------------------------------------------------------- #
# _check_registry: the audited inventory must stay live and well-formed
# --------------------------------------------------------------------------- #


def _identity_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "route": "/v1/things",
        "method": "get",
        "path": "/things",
        "file": "synthetic.py",
        "handler": "things_handler",
        "disposition": "implemented",
        "contract": "Returns the things from the store.",
    }
    entry.update(overrides)
    return entry


def _registry_file(tmp_path: Path, entry: dict[str, Any]) -> Path:
    import json

    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"routes": [entry]}))
    return registry


def _live_identity() -> dict[tuple[str, str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    return {("synthetic.py", "get", "/things"): _func("def things_handler():\n    return []\n")}


def test_registry_happy_path_on_the_shipped_inventory() -> None:
    """Every real audited entry resolves to a live handler in this tree."""
    import json

    handlers = mod._handlers()
    by_identity = {(file, method, path): func for file, func, method, path in handlers}
    failures, count = mod._check_registry(by_identity)
    assert failures == []
    registered = len(json.loads(mod.REGISTRY.read_text())["routes"])
    assert count == registered


def test_registry_entry_missing_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, {"route": "/v1/x"}))
    failures, count = mod._check_registry({})
    assert count == 1
    assert any("missing" in failure for failure in failures)


def test_registry_unknown_disposition(tmp_path, monkeypatch) -> None:
    entry = _identity_entry(disposition="magic")
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    failures, _ = mod._check_registry(_live_identity())
    assert any("unknown disposition" in failure for failure in failures)


def test_registry_rot_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, _identity_entry()))
    failures, _ = mod._check_registry({})  # no live handler resolves the identity
    assert any("inventory rot" in failure for failure in failures)


# --------------------------------------------------------------------------- #
# #1860: the declared handler must be the discovered function's own name
# --------------------------------------------------------------------------- #


def test_registry_handler_drift_is_refused(tmp_path, monkeypatch) -> None:
    """A nonempty-but-wrong handler name is not validated away: the entry
    resolves by (file, method, path), so only the name comparison can catch
    that the declaration points at a function that is not there."""
    entry = _identity_entry(handler="different_handler")
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    failures, count = mod._check_registry(_live_identity())
    assert count == 1
    assert len(failures) == 1
    assert "handler identity drift" in failures[0]
    # Both names in the output: what the inventory declares, what is live.
    assert "'different_handler'" in failures[0]
    assert "'things_handler'" in failures[0]


def test_renamed_handler_fails_until_reconciled(tmp_path, monkeypatch) -> None:
    """The inverse rename: the live function was renamed, the inventory was
    not. Fails naming the stale declaration and the discovered name."""
    entry = _identity_entry()  # declares things_handler
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    renamed = {
        ("synthetic.py", "get", "/things"): _func("def renamed_things_handler():\n    return []\n")
    }
    failures, _ = mod._check_registry(renamed)
    assert len(failures) == 1
    assert "handler identity drift" in failures[0]
    assert "'things_handler'" in failures[0]
    assert "'renamed_things_handler'" in failures[0]


def test_correct_handler_identity_passes(tmp_path, monkeypatch) -> None:
    entry = _identity_entry()  # equals the live function's name
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    failures, count = mod._check_registry(_live_identity())
    assert failures == []
    assert count == 1


def test_unrelated_route_handler_cannot_satisfy_identity(tmp_path, monkeypatch) -> None:
    """A handler that exists on a *different* route cannot satisfy this
    entry: resolution is by (file, method, path) and the name is compared
    against that identity's function only."""
    entry = _identity_entry(handler="other_handler")
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    live = dict(_live_identity())
    live[("other.py", "get", "/others")] = _func("def other_handler():\n    return []\n")
    failures, _ = mod._check_registry(live)
    assert len(failures) == 1
    assert "handler identity drift" in failures[0]
    assert "'other_handler'" in failures[0]
    assert "'things_handler'" in failures[0]


def test_registry_temporary_needs_issue_and_unexpired_expiry(tmp_path, monkeypatch) -> None:
    entry = _identity_entry(
        disposition="temporary", expires=(date.today() - timedelta(days=1)).isoformat()
    )
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    failures, _ = mod._check_registry(_live_identity())
    assert any("needs an issue" in failure for failure in failures)
    assert any("expired" in failure for failure in failures)


def test_missing_registry_is_refused(tmp_path, monkeypatch) -> None:
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(mod, "REGISTRY", absent)
    failures, count = mod._check_registry({})
    assert count == 0
    assert failures == [f"missing registry: {absent}"]


# --------------------------------------------------------------------------- #
# main(): failure paths and the clean run on this tree
# --------------------------------------------------------------------------- #


def test_main_reports_findings_and_fails(tmp_path, monkeypatch, capsys) -> None:
    routes = _write_routes(tmp_path, CANNED)
    entry = _identity_entry(file="routes_9.py")  # rots: routes_9.py does not exist
    monkeypatch.setattr(mod, "ROUTES_DIR", routes)
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    monkeypatch.setattr(mod, "INVENTORY_DOC", tmp_path / "absent-doc.md")
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "canned route handler" in out
    assert "inventory rot" in out
    assert "missing inventory document" in out


def test_main_fails_on_handler_identity_drift_alone(tmp_path, monkeypatch, capsys) -> None:
    """#1860 end-to-end: a real-work route, a present inventory document, and
    a registry entry whose handler name is stale. The full gate must fail on
    the drift alone — naming both handlers — with no rot and no canned
    finding to confuse the repair."""
    routes = _write_routes(tmp_path, REAL_WORK)  # routes_0.py @router.get("/real")
    entry = _identity_entry(handler="different_handler", file="routes_0.py", path="/real")
    monkeypatch.setattr(mod, "ROUTES_DIR", routes)
    monkeypatch.setattr(mod, "REGISTRY", _registry_file(tmp_path, entry))
    inventory = tmp_path / "route-contract-inventory.md"
    inventory.write_text("# route contract inventory\n")
    monkeypatch.setattr(mod, "INVENTORY_DOC", inventory)
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "handler identity drift" in out
    assert "'different_handler'" in out
    assert "'real_things'" in out
    assert "inventory rot" not in out
    assert "canned route handler" not in out


def test_main_passes_on_this_tree(capsys) -> None:
    """The shipped tree has no canned handlers and a live inventory."""
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "0 canned" in out
    assert "audited routes registered" in out
