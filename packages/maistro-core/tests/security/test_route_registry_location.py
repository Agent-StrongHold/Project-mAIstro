"""The route registry must be locatable from both runtime layouts (#1140).

The auth middlewares resolve ``quality/route-permissions.json`` by walking up
from their own file location. In the monorepo checkout that walk is several
levels; in a packaged image (e.g. ``/app/backend/middleware/auth.py`` with the
registry copied to ``/app/quality/``) only two parent levels exist. Indexed
``parents[n]`` access raised ``IndexError`` there and the production container
exited at import. These tests pin the boundary-safe locator instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro.security.http_routes import RoutePolicyError, locate_route_registry


def test_monorepo_checkout_layout_resolves_the_reviewed_registry() -> None:
    registry = locate_route_registry(Path(__file__))
    assert registry == Path(__file__).resolve().parents[4] / "quality" / "route-permissions.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert set(payload["routes"]) >= {"conductor", "turing"}


def test_packaged_image_layout_finds_the_registry_two_levels_up(tmp_path: Path) -> None:
    # The hive image layout: /app/backend/middleware/auth.py, registry at
    # /app/quality/route-permissions.json.
    app = tmp_path / "app"
    (app / "backend" / "middleware").mkdir(parents=True)
    (app / "quality").mkdir()
    registry = app / "quality" / "route-permissions.json"
    registry.write_text("{}", encoding="utf-8")
    middleware = app / "backend" / "middleware" / "auth.py"
    middleware.write_text("", encoding="utf-8")

    assert locate_route_registry(middleware) == registry


def test_shallow_layout_cannot_run_out_of_parents(tmp_path: Path) -> None:
    # parents[4] raised IndexError in containers where the app sits close to
    # the filesystem root; the walk must tolerate every depth.
    root = tmp_path / "srv"
    (root / "backend").mkdir(parents=True)
    (root / "quality").mkdir()
    (root / "quality" / "route-permissions.json").write_text("{}", encoding="utf-8")
    middleware = root / "backend" / "auth.py"
    middleware.write_text("", encoding="utf-8")

    assert locate_route_registry(middleware) == root / "quality" / "route-permissions.json"


def test_a_deployment_without_declarations_fails_closed(tmp_path: Path) -> None:
    middleware = tmp_path / "middleware" / "auth.py"
    middleware.parent.mkdir()
    middleware.write_text("", encoding="utf-8")

    with pytest.raises(RoutePolicyError, match="route authorization registry not found"):
        locate_route_registry(middleware)
