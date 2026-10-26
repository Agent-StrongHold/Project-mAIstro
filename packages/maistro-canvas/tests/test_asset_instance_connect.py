"""CONNECT proof for ADR-044 AssetInstance modules (#2311)."""

from __future__ import annotations

from maistro_canvas.canvas.asset_compositor import plan_render
from maistro_canvas.canvas.asset_executor import AssetExecutor
from maistro_canvas.canvas.asset_routes import make_router
from maistro_canvas.canvas.asset_store import InMemoryAssetStore, PostgresAssetStore
from maistro_canvas.canvas.asset_tool import AssetTool
from maistro_canvas.canvas.composition import (
    _ASSET_INSTANCE_CONNECT,
    AssetInstanceSurface,
    build_asset_instance_surface,
)


def test_asset_instance_connect_tuple_roots_every_disposition_module() -> None:
    assert (
        PostgresAssetStore,
        InMemoryAssetStore,
        plan_render,
        AssetExecutor,
        make_router,
        AssetTool,
    ) == _ASSET_INSTANCE_CONNECT


def test_build_asset_instance_surface_binds_tool_and_router() -> None:
    surface = build_asset_instance_surface(org_id="acme")
    assert isinstance(surface, AssetInstanceSurface)
    assert isinstance(surface.store, InMemoryAssetStore)
    assert isinstance(surface.tool, AssetTool)
    assert surface.postgres_store_cls is PostgresAssetStore
    paths = {getattr(route, "path", "") for route in surface.router.routes}
    assert any("asset-definitions" in path for path in paths)
