"""Shared route-declaration coverage for Conductor and Turing (#1140)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from maistro.security.http_routes import route_policy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-public-routes.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_route_permissions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["conductor", "turing"])
def application(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _route(method: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(methods={method}, path=path)


def _permission(path: str = "/v1/protected") -> dict[str, object]:
    return {
        "methods": ["GET"],
        "path": path,
        "kind": "exact",
        "access": "permission",
        "permission": "example.read",
        "reason": "test protected route",
    }


def _public(path: str = "/health") -> dict[str, object]:
    return {
        "methods": ["GET"],
        "path": path,
        "kind": "exact",
        "access": "public",
        "owner": "@test",
        "risk": "low",
        "disposition": "permanent",
        "reason": "test liveness route",
    }


@pytest.mark.parametrize("entry_factory", [_permission, _public])
def test_conductor_and_turing_share_protected_and_public_classification(
    gate, application: str, entry_factory
) -> None:
    path = "/v1/protected" if entry_factory is _permission else "/health"
    failures = gate._route_entry_failures(
        application,
        [("GET", path)],
        [entry_factory(path)],
        gate.date(2026, 9, 8),
    )

    assert failures == []


def test_live_backend_route_trees_are_classified(gate, application: str) -> None:
    """Exercise the gate against each production FastAPI application, not tuples."""
    app = gate._load_application(application)
    discovered = gate.registered_routes(app)
    assert discovered
    registry = json.loads(gate.ROUTE_REGISTRY.read_text(encoding="utf-8"))
    entries = registry["routes"][application]

    assert gate._route_entry_failures(application, discovered, entries, gate.date(2026, 9, 8)) == []


@pytest.mark.parametrize("built_assets", [False, True])
def test_conductor_spa_registration_is_classified_with_or_without_assets(
    gate, monkeypatch, tmp_path, built_assets: bool
) -> None:
    import importlib

    gate._load_application("conductor")
    main = importlib.import_module("main")
    assets = tmp_path / "dist"
    if built_assets:
        assets.mkdir()
        (assets / "index.html").write_text("<title>fixture</title>")
    monkeypatch.setattr(main, "STATIC_DIR", assets)
    discovered = gate.registered_routes(main.create_app())
    assert ("GET", "/{full_path:path}") in discovered
    entries = json.loads(gate.ROUTE_REGISTRY.read_text())["routes"]["conductor"]
    assert gate._route_entry_failures("conductor", discovered, entries, gate.date(2026, 9, 8)) == []
    # Exact registered identity, never a wildcard approval for other handlers.
    assert route_policy(tuple(entries), "GET", "/unrelated/invoke") is None


def test_live_backend_route_trees_include_protected_and_public_examples(
    gate, application: str
) -> None:
    discovered = gate.registered_routes(gate._load_application(application))
    assert ("GET", "/docs") in discovered
    assert any(method == "GET" and path.startswith("/v1/") for method, path in discovered)
    expected = ("GET", "/v1/tasks") if application == "conductor" else ("GET", "/v1/feed")
    assert expected in discovered


def test_both_apps_fail_when_a_new_route_has_no_declaration(gate, application: str) -> None:
    app = gate._load_application(application)
    original_routes = list(app.router.routes)
    try:
        app.add_api_route("/v1/newly-registered", lambda: {}, methods=["GET"])
        entries = json.loads(gate.ROUTE_REGISTRY.read_text())["routes"][application]
        failures = gate._route_entry_failures(
            application, gate.registered_routes(app), entries, gate.date(2026, 9, 8)
        )
        assert any(
            "/v1/newly-registered: registered route has no declaration" in f for f in failures
        )
    finally:
        app.router.routes = original_routes


def test_application_import_failure_is_not_silently_skipped(gate, application, monkeypatch):
    original_import = gate.import_module
    target = "main" if application == "conductor" else "backend.main"

    def unavailable(name):
        if name == target:
            raise ImportError("fixture backend is unavailable")
        return original_import(name)

    monkeypatch.setattr(gate, "import_module", unavailable)
    with pytest.raises(RuntimeError, match=f"could not import {application} backend"):
        gate.audit_registered_routes()


def test_both_apps_reject_an_expired_exemption(gate, application: str) -> None:
    exemption = {
        "methods": ["GET"],
        "path": "/v1/temporary",
        "kind": "exact",
        "access": "exempt",
        "owner": "@test",
        "reason": "tracked migration",
        "expires": "2026-09-07",
    }

    failures = gate._route_entry_failures(
        application,
        [("GET", "/v1/temporary")],
        [exemption],
        gate.date(2026, 9, 8),
    )

    assert any("expired" in failure for failure in failures)


def test_exact_public_route_does_not_match_a_lookalike(gate, application: str) -> None:
    failures = gate._route_entry_failures(
        application,
        [("GET", "/openapi-anything")],
        [_public("/openapi.json")],
        gate.date(2026, 9, 8),
    )

    assert any("has no declaration" in failure for failure in failures)


def test_route_policy_ratchet_rejects_unreviewed_weakening(gate) -> None:
    key = ("turing", "GET", "/v1/state", "prefix")
    base = {key: ("permission", "turing.vault_read")}
    current = {key: ("public", "")}

    failures = gate._route_policy_failures(base, current, {})

    assert any("without trusted authorization" in failure for failure in failures)


@pytest.mark.parametrize("access", ["public", "exempt"])
def test_route_policy_ratchet_rejects_new_bypasses(gate, access) -> None:
    current = {("turing", "GET", "/v1/new-bypass", "exact"): (access, "")}
    assert any(
        "needs already-landed authorization" in failure
        for failure in gate._route_policy_failures({}, current, {})
    )


def test_route_policy_ratchet_allows_exemption_removal(gate) -> None:
    base = {("turing", "GET", "/v1/retired", "exact"): ("exempt", "")}
    assert gate._route_policy_failures(base, {}, {}) == []


def test_route_policy_ratchet_allows_an_already_landed_authorization(gate) -> None:
    key = ("turing", "GET", "/v1/state", "prefix")
    base = {key: ("permission", "turing.vault_read")}
    current = {key: ("public", "")}

    assert gate._route_policy_failures(base, current, {"turing:GET:/v1/state": "#1140"}) == []


def test_shared_runtime_matcher_applies_get_policy_to_fastapi_head(gate) -> None:
    assert route_policy((_public("/docs"),), "HEAD", "/docs") is not None


def test_shared_runtime_matcher_rejects_ambiguous_declarations(gate) -> None:
    entries = (
        _permission("/v1/items"),
        {**_permission("/v1/items"), "permission": "items.write"},
    )

    assert route_policy(entries, "GET", "/v1/items") is None


def test_shared_runtime_matcher_uses_exact_over_boundary_prefix(gate) -> None:
    entries = (
        {**_permission("/v1/items"), "kind": "prefix"},
        _public("/v1/items/current"),
    )

    assert route_policy(entries, "GET", "/v1/items/current")["access"] == "public"


@pytest.mark.parametrize(
    "path", ["/v1/invoke-history", "/v1/unrelated/invoke", "/v1/unrelated/feedback"]
)
def test_suffix_lookalike_is_not_a_public_route(gate, application: str, path: str) -> None:
    # Neither a similar name nor an ending /invoke or /feedback can borrow
    # another registered endpoint's explicit public declaration.
    from fastapi import FastAPI

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_api_route(path, lambda: {}, methods=["GET"])
    failures = gate._route_entry_failures(
        application,
        gate.registered_routes(app),
        [_public("/v1/invoke")],
        gate.date(2026, 9, 8),
    )

    assert any("has no declaration" in failure for failure in failures)
