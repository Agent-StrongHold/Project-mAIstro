"""Tests for the private organizational extension catalog API (#979)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from types import SimpleNamespace

from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.manifest import ExtensionManifest
from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.types import PackageIdentity, ExtensionEntryPoint
from maistro_server.api.auth import verify_api_key, AuthenticatedPrincipal
from maistro_server.api import catalog as catalog_api
from maistro.config.settings import Settings, get_settings


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
        "extension_id": extension_id,
        "name": name,
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "permissions": list(permissions),
        "entry_points": [{"name": ep.name, "module": ep.module, "attribute": ep.attribute} for ep in entry_points],
        "dependencies": [{"target": dep.target, "range": dep.range_text} for dep in dependencies],
        "artifact_sha256": artifact_sha256,
        "artifact_size": artifact_size,
        "source_sha256": source_sha256,
    }
    raw = json.dumps(manifest_dict, sort_keys=True).encode("utf-8")
    return ExtensionManifest(
        raw=raw,
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
    )


@pytest.fixture
def catalog_store() -> InMemoryCatalogStore:
    return InMemoryCatalogStore()


@pytest.fixture
def sample_catalog_with_manifest() -> list[tuple[CatalogEntry, ExtensionManifest]]:
    """Create a sample catalog with a few extensions and their manifests."""
    manifest1 = _make_manifest(
        extension_id="tool-a",
        name="Tool A",
        version="1.0.0",
        publisher="pub-1",
        api_version="1.0",
        permissions=("network.http", "storage.workspace"),
        entry_points=(
    manifest_dict = {
        "manifest_version": 1,
        "extension_id": extension_id,
        "name": name,
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "permissions": permissions,
        "entry_points": [{"name": ep.name, "module": ep.module, "attribute": ep.attribute} for ep in entry_points],
        "dependencies": [{"target": dep.target, "range": dep.range_text} for dep in dependencies],
        "artifact_sha256": artifact_sha256,
        "artifact_size": artifact_size,
        "source_sha256": source_sha256,
    }
        extension_id="tool-a",
        name="Tool A",
        version="2.0.0",
        publisher="pub-2",
        api_version="1.1",
        permissions=("network.http", "storage.workspace", "system.filesystem"),
        entry_points=(
            ExtensionEntryPoint(name="main", module="tool_a.main", attribute="run"),
        ),
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
        entry_points=(
            ExtensionEntryPoint(name="main", module="tool_b.main", attribute="run"),
        ),
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
def catalog_service(catalog_store: InMemoryCatalogStore) -> CatalogService:
    return CatalogService(catalog_store)


def create_app(catalog_service: CatalogService) -> FastAPI:
    """Create a FastAPI app with the catalog service overridden in the container."""
    app = FastAPI()
    app.state.container = SimpleNamespace(
        ensure_catalog_service=lambda: catalog_service
    )
    app.include_router(catalog_api.router)
    return app


def test_list_catalog_extensions(catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]], catalog_service: CatalogService):
    """Listing extensions via the API works."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog(org_id="org-123", entries=sample_catalog_with_manifest))

    app = create_app(catalog_service)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    # Override settings to require API keys
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])

    client = TestClient(app)
    response = client.get(
        "/catalog/org-123/extensions",
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # Check that we have the expected extensions, regardless of order.
    ext_map = {(e["extension_name"], e["version"]): e for e in data}
    assert ("tool-a", "1.0.0") in ext_map
    assert ("tool-a", "2.0.0") in ext_map
    assert ("tool-b", "1.5.0") in ext_map
    # Check the fields.
    assert ext_map[("tool-a", "1.0.0")]["api_version"] == "1.0"
    assert ext_map[("tool-a", "1.0.0")]["permissions"] == ("network.http", "storage.workspace")
    assert ext_map[("tool-a", "2.0.0")]["api_version"] == "1.1"
    assert ext_map[("tool-a", "2.0.0")]["permissions"] == ("network.http", "storage.workspace", "system.filesystem")
    assert ext_map[("tool-b", "1.5.0")]["api_version"] == "0.9"
    assert ext_map[("tool-b", "1.5.0")]["permissions"] == ("network.http",)

    # Clean up overrides
    app.dependency_overrides.clear()


def test_list_catalog_extensions_with_search(catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]], catalog_service: CatalogService):
    """Search and filter work."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog(org_id="org-123", entries=sample_catalog_with_manifest))

    app = create_app(catalog_service)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])

    client = TestClient(app)
    # Search for "tool-a"
    response = client.get(
        "/catalog/org-123/extensions",
        params={"search": "tool-a"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(d["extension_name"] == "tool-a" for d in data)

    # Filter by publisher
    response = client.get(
        "/catalog/org-123/extensions",
        params={"publisher_id": "pub-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(d["publisher_id"] == "pub-1" for d in data)

    # Combine search and publisher
    response = client.get(
        "/catalog/org-123/extensions",
        params={"search": "tool-b", "publisher_id": "pub-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["extension_name"] == "tool-b"
    assert data[0]["publisher_id"] == "pub-1"

    app.dependency_overrides.clear()


def test_get_extension_versions(catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]], catalog_service: CatalogService):
    """Getting versions for a specific extension works."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog(org_id="org-123", entries=sample_catalog_with_manifest))

    app = create_app(catalog_service)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])

    client = TestClient(app)
    response = client.get("/catalog/org-123/extensions/tool-a")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Newest first
    assert data[0]["version"] == "2.0.0"
    assert data[0]["api_version"] == "1.1"
    assert data[0]["permissions"] == ("network.http", "storage.workspace", "system.filesystem")
    assert data[1]["version"] == "1.0.0"
    assert data[1]["api_version"] == "1.0"
    assert data[1]["permissions"] == ("network.http", "storage.workspace")

    # Non-existent extension
    response = client.get("/catalog/org-123/extensions/non-existent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0

    app.dependency_overrides.clear()


def test_get_extension_version(catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]], catalog_service: CatalogService):
    """Getting a specific version returns the correct metadata."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog(org_id="org-123", entries=sample_catalog_with_manifest))

    app = create_app(catalog_service)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])

    client = TestClient(app)
    response = client.get("/catalog/org-123/extensions/tool-a/versions/1.0.0")
    assert response.status_code == 200
    data = response.json()
    assert data["extension_name"] == "tool-a"
    assert data["version"] == "1.0.0"
    assert data["api_version"] == "1.0"
    assert data["permissions"] == ("network.http", "storage.workspace")
    assert data["artifact_sha256"] == "a" * 64
    assert data["manifest_sha256"] == "m" * 64

    # Non-existent version
    response = client.get("/catalog/org-123/extensions/tool-a/versions/3.0.0")
    assert response.status_code == 404

    # Non-existent extension
    response = client.get("/catalog/org-123/extensions/non-existent/versions/1.0.0")
    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_catalog_endpoint_requires_auth(catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]], catalog_service: CatalogService):
    """Unauthenticated requests are rejected."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog(org_id="org-123", entries=sample_catalog_with_manifest))

    app = create_app(catalog_service)
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])
    # Do not override auth dependency; should require auth
    client = TestClient(app)
    response = client.get("/catalog/org-123/extensions")
    # Expecting 401 or 403
    assert response.status_code in (401, 403)

    # Clear any overrides
    app.dependency_overrides.clear()
