"""Tests for the private organizational extension catalog API (#979).

The routes are the operator's HTTP surface over the catalog service: list
with search/filter, per-extension version history, and per-version detail.
The suite pins the acceptance criteria at the API boundary — discovery works
from a fresh instance, manifest metadata is inspectable before any download,
digests travel with every view, unauthenticated callers are rejected, and
every route handler is declared in the module's ``__all__`` (the
fastapi-route-handler ledger contract).
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.resolution import CatalogEntry, ExtensionDependency
from maistro.extensions.types import (
    ExtensionEntryPoint,
    ExtensionManifest,
    PackageIdentity,
)
from maistro_server.api import catalog as catalog_api
from maistro_server.api.auth import AuthenticatedPrincipal, verify_api_key


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


def _make_manifest(
    extension_id: str,
    name: str,
    version: str,
    publisher: str,
    api_version: str,
    permissions: tuple[str, ...],
    entry_points: tuple[ExtensionEntryPoint, ...],
    dependencies: tuple[ExtensionDependency, ...],
    artifact_sha256: str,
    artifact_size: int,
    source_sha256: str,
) -> ExtensionManifest:
    manifest_dict = {
        "manifest_version": 1,
        "id": extension_id,
        "name": name,
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "permissions": list(permissions),
        "entry_points": [
            {"name": ep.name, "module": ep.module, "attribute": ep.attribute} for ep in entry_points
        ],
        "dependencies": [{"target": dep.target, "range": dep.range_text} for dep in dependencies],
        "artifact": {"sha256": artifact_sha256, "size": artifact_size},
    }
    raw = json.dumps(manifest_dict, sort_keys=True).encode("utf-8")
    return ExtensionManifest(
        manifest_version=1,
        extension_id=extension_id,
        name=name,
        version=version,
        publisher=publisher,
        api_version=api_version,
        permissions=permissions,
        entry_points=entry_points,
        dependencies=dependencies,
        artifact_sha256=artifact_sha256,
        artifact_size=artifact_size,
        source_sha256=source_sha256,
        raw=raw,
    )


@pytest.fixture
def catalog_store() -> InMemoryCatalogStore:
    return InMemoryCatalogStore()


@pytest.fixture
def catalog_service(catalog_store: InMemoryCatalogStore) -> CatalogService:
    return CatalogService(catalog_store)


@pytest.fixture
def sample_catalog() -> list[tuple[CatalogEntry, ExtensionManifest]]:
    """Three entries across two extensions and two publishers, with manifests."""
    manifest1 = _make_manifest(
        extension_id="tool-a",
        name="Tool A",
        version="1.0.0",
        publisher="pub-1",
        api_version="1.0",
        permissions=("network.http", "storage.workspace"),
        entry_points=(ExtensionEntryPoint(name="main", module="tool_a.main", attribute="run"),),
        dependencies=(),
        artifact_sha256="a" * 64,
        artifact_size=1024,
        source_sha256="m" * 64,
    )
    entry1 = CatalogEntry(
        identity=PackageIdentity(
            extension_name="tool-a",
            semantic_version="1.0.0",
            package_sha256="a" * 64,
            manifest_sha256="m" * 64,
        ),
        source="https://example.com/catalog/v1",
        catalog_snapshot_sha256="s" * 64,
        publisher_id="pub-1",
        signature="sig1",
        dependencies=(),
    )
    manifest2 = _make_manifest(
        extension_id="tool-a",
        name="Tool A",
        version="2.0.0",
        publisher="pub-2",
        api_version="1.1",
        permissions=("network.http", "storage.workspace", "system.filesystem"),
        entry_points=(ExtensionEntryPoint(name="main", module="tool_a.main", attribute="run"),),
        dependencies=(),
        artifact_sha256="b" * 64,
        artifact_size=2048,
        source_sha256="n" * 64,
    )
    entry2 = CatalogEntry(
        identity=PackageIdentity(
            extension_name="tool-a",
            semantic_version="2.0.0",
            package_sha256="b" * 64,
            manifest_sha256="n" * 64,
        ),
        source="https://example.com/catalog/v1",
        catalog_snapshot_sha256="s" * 64,
        publisher_id="pub-2",
        signature="sig2",
        dependencies=(),
    )
    manifest3 = _make_manifest(
        extension_id="tool-b",
        name="Tool B",
        version="1.5.0",
        publisher="pub-1",
        api_version="0.9",
        permissions=("network.http",),
        entry_points=(ExtensionEntryPoint(name="main", module="tool_b.main", attribute="run"),),
        dependencies=(),
        artifact_sha256="c" * 64,
        artifact_size=512,
        source_sha256="p" * 64,
    )
    entry3 = CatalogEntry(
        identity=PackageIdentity(
            extension_name="tool-b",
            semantic_version="1.5.0",
            package_sha256="c" * 64,
            manifest_sha256="p" * 64,
        ),
        source="https://example.com/catalog/v1",
        catalog_snapshot_sha256="s" * 64,
        publisher_id="pub-1",
        signature="sig3",
        dependencies=(),
    )
    return [(entry1, manifest1), (entry2, manifest2), (entry3, manifest3)]


@pytest.fixture
def published_store(
    catalog_store: InMemoryCatalogStore,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
) -> InMemoryCatalogStore:
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))
    return catalog_store


@pytest.fixture
def client(catalog_service: CatalogService, published_store: InMemoryCatalogStore) -> TestClient:
    """A FastAPI app exposing only the catalog router, auth overridden."""
    app = FastAPI()
    app.state.container = SimpleNamespace(ensure_catalog_service=lambda: catalog_service)
    app.include_router(catalog_api.router)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])
    return TestClient(app)


def test_list_catalog_extensions(client: TestClient):
    """A fresh client discovers catalog candidates with full metadata."""
    response = client.get("/catalog/org-123/extensions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

    ext_map = {(e["extension_name"], e["version"]): e for e in data}
    assert ("tool-a", "1.0.0") in ext_map
    assert ("tool-a", "2.0.0") in ext_map
    assert ("tool-b", "1.5.0") in ext_map

    tool_a_1 = ext_map[("tool-a", "1.0.0")]
    assert tool_a_1["publisher_id"] == "pub-1"
    assert tool_a_1["api_version"] == "1.0"
    # JSON turns tuples into lists — the operator still sees every permission.
    assert tool_a_1["permissions"] == ["network.http", "storage.workspace"]
    assert tool_a_1["package_sha256"] == "a" * 64
    assert tool_a_1["manifest_sha256"] == "m" * 64
    assert tool_a_1["entry_points"] == [
        {"name": "main", "module": "tool_a.main", "attribute": "run"}
    ]


def test_list_catalog_extensions_is_sorted(client: TestClient):
    """The list view is name-then-version ordered, not snapshot order."""
    response = client.get("/catalog/org-123/extensions")
    assert response.status_code == 200
    keys = [(e["extension_name"], e["version"]) for e in response.json()]
    assert keys == [
        ("tool-a", "1.0.0"),
        ("tool-a", "2.0.0"),
        ("tool-b", "1.5.0"),
    ]


def test_list_catalog_extensions_search_and_filter(client: TestClient):
    """Search covers name and publisher; the publisher filter is exact."""
    response = client.get("/catalog/org-123/extensions", params={"search": "TOOL-A"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(e["extension_name"] == "tool-a" for e in data)

    response = client.get("/catalog/org-123/extensions", params={"publisher_id": "pub-1"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(e["publisher_id"] == "pub-1" for e in data)

    response = client.get(
        "/catalog/org-123/extensions",
        params={"search": "tool-b", "publisher_id": "pub-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["extension_name"] == "tool-b"
    assert data[0]["publisher_id"] == "pub-1"

    response = client.get("/catalog/org-123/extensions", params={"search": "no-such-extension"})
    assert response.status_code == 200
    assert response.json() == []


def test_unknown_organization_lists_empty(client: TestClient):
    """An org with no published catalog is an empty discovery result."""
    response = client.get("/catalog/org-other/extensions")
    assert response.status_code == 200
    assert response.json() == []


def test_get_extension_versions_newest_first(client: TestClient):
    """Version history is newest-first with per-version manifest detail."""
    response = client.get("/catalog/org-123/extensions/tool-a")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["version"] == "2.0.0"
    assert data[0]["api_version"] == "1.1"
    assert data[0]["permissions"] == [
        "network.http",
        "storage.workspace",
        "system.filesystem",
    ]
    assert data[1]["version"] == "1.0.0"
    assert data[1]["api_version"] == "1.0"

    response = client.get("/catalog/org-123/extensions/non-existent")
    assert response.status_code == 200
    assert response.json() == []


def test_get_extension_version_detail(client: TestClient):
    """Detail view carries the immutable-artifact digests before download."""
    response = client.get("/catalog/org-123/extensions/tool-a/versions/1.0.0")
    assert response.status_code == 200
    data = response.json()
    assert data["extension_name"] == "tool-a"
    assert data["version"] == "1.0.0"
    assert data["manifest_sha256"] == "m" * 64
    assert data["artifact_sha256"] == "a" * 64
    assert data["source_sha256"] == "m" * 64
    assert data["artifact_size"] == 1024

    response = client.get("/catalog/org-123/extensions/tool-a/versions/3.0.0")
    assert response.status_code == 404

    response = client.get("/catalog/org-123/extensions/non-existent/versions/1.0.0")
    assert response.status_code == 404


def test_catalog_endpoint_requires_auth(
    catalog_service: CatalogService, published_store: InMemoryCatalogStore
):
    """With real auth and configured API keys, a credentialless caller fails."""
    app = FastAPI()
    app.state.container = SimpleNamespace(ensure_catalog_service=lambda: catalog_service)
    app.include_router(catalog_api.router)
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])
    client = TestClient(app)

    response = client.get("/catalog/org-123/extensions")
    assert response.status_code == 401

    # A wrong credential fails closed too.
    response = client.get(
        "/catalog/org-123/extensions",
        headers={"Authorization": "Bearer wrong:s3cret"},
    )
    assert response.status_code == 401


def test_catalog_without_wired_service_is_503():
    """A deployment with no catalog service fails closed, not with a 500.

    The router works over any container that wires ``ensure_catalog_service``;
    an app whose state carries no container has no catalog to serve and says
    so explicitly.
    """
    app = FastAPI()
    app.include_router(catalog_api.router)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    client = TestClient(app)

    response = client.get("/catalog/org-123/extensions")
    assert response.status_code == 503
    assert "No catalog service is configured" in response.json()["detail"]


class TestPublicSurfaceDeclaration:
    """Every @router handler in catalog.py must be declared in ``__all__``.

    FastAPI registers handlers from the decorators, which static import
    scanning cannot see. The module's ``__all__`` (the a2a.py/canvas.py
    convention) is what declares the handlers as the module's public surface
    and keeps them out of the fastapi-route-handler Vulture ledger; a new
    handler that skips the declaration would resurface as unbanked dead-code
    debt and fail the exact-debt-ledger CI gate. This catches that drift here
    first, with an actionable message.
    """

    def test_all_covers_every_route_handler(self) -> None:
        source = Path(str(catalog_api.__file__)).read_text(encoding="utf-8")
        handlers = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
                for dec in node.decorator_list
            )
        }
        declared = set(catalog_api.__all__)
        missing = sorted(handlers - declared)
        assert not missing, (
            f"route handlers missing from catalog.py __all__: {missing}. "
            "FastAPI registers handlers dynamically, so every @router handler "
            "must be declared in the module's __all__ (see a2a.py and the "
            "comment above catalog.py's __all__) rather than re-entering the "
            "fastapi-route-handler Vulture ledger as unbanked debt."
        )
