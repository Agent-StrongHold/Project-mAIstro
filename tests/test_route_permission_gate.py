"""Shared route-declaration coverage for Conductor and Turing (#1140)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_both_apps_fail_when_a_new_route_has_no_declaration(gate, application: str) -> None:
    failures = gate._route_entry_failures(
        application,
        [("GET", "/v1/newly-registered")],
        [_permission()],
        gate.date(2026, 9, 8),
    )

    assert any("has no declaration" in failure for failure in failures)


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


def test_suffix_lookalike_is_not_a_public_route(gate, application: str) -> None:
    # A declaration for /invoke cannot authorize the unrelated sibling
    # /invoke-history; this is the regression against suffix-based bypasses.
    failures = gate._route_entry_failures(
        application,
        [("GET", "/v1/invoke-history")],
        [_public("/v1/invoke")],
        gate.date(2026, 9, 8),
    )

    assert any("has no declaration" in failure for failure in failures)
