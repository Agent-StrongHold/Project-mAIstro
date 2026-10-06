"""Tests for the private organizational extension catalog API (#979)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from types import SimpleNamespace

from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.types import PackageIdentity
from maistro_server.api.auth import verify_api_key, AuthenticatedPrincipal
from maistro_server.api import catalog as catalog_api
from maistro.config.settings import Settings, get_settings


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


@pytest.fixture
def catalog_store() -> InMemoryCatalogStore:
    return InMemoryCatalogStore()


@pytest.fixture
def sample_catalog() -> ExtensionCatalog:
    """Create a sample catalog with a few extensions."""
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
    return ExtensionCatalog(entries=(entry1, entry2, entry3))


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


def test_list_catalog_extensions(catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog, catalog_service: CatalogService):
    """Listing extensions via the API works."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))

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
    # Check sorting
    assert data[0]["extension_name"] == "tool-a"
    assert data[0]["version"] == "1.0.0"
    assert data[1]["extension_name"] == "tool-a"
    assert data[1]["version"] == "2.0.0"
    assert data[2]["extension_name"] == "tool-b"
    assert data[2]["version"] == "1.5.0"

    # Clean up overrides
    app.dependency_overrides.clear()


def test_list_catalog_extensions_with_search(catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog, catalog_service: CatalogService):
    """Search and filter work."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))

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


def test_get_extension_versions(catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog, catalog_service: CatalogService):
    """Getting versions for a specific extension works."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))

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
    assert data[1]["version"] == "1.0.0"

    # Non-existent extension
    response = client.get("/catalog/org-123/extensions/non-existent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0

    app.dependency_overrides.clear()


def test_get_extension_version(catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog, catalog_service: CatalogService):
    """Getting a specific version returns the correct metadata."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))

    app = create_app(catalog_service)
    app.dependency_overrides[verify_api_key] = lambda: _principal("test-user")
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])

    client = TestClient(app)
    response = client.get("/catalog/org-123/extensions/tool-a/versions/1.0.0")
    assert response.status_code == 200
    data = response.json()
    assert data["extension_name"] == "tool-a"
    assert data["version"] == "1.0.0"
    assert data["package_sha256"] == "a" * 64
    assert data["manifest_sha256"] == "m" * 64
    assert data["publisher_id"] == "pub-1"
    assert data["signature"] == "sig1"

    # Non-existent version
    response = client.get("/catalog/org-123/extensions/tool-a/versions/3.0.0")
    assert response.status_code == 404

    # Non-existent extension
    response = client.get("/catalog/org-123/extensions/non-existent/versions/1.0.0")
    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_catalog_endpoint_requires_auth(catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog, catalog_service: CatalogService):
    """Unauthenticated requests are rejected."""
    # Set the catalog in the store
    import asyncio
    asyncio.run(catalog_store.set_catalog("org-123", sample_catalog))

    app = create_app(catalog_service)
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["test:s3cret"])
    # Do not override auth dependency; should require auth
    client = TestClient(app)
    response = client.get("/catalog/org-123/extensions")
    # Expecting 401 or 403
    assert response.status_code in (401, 403)

    # Clear any overrides
    app.dependency_overrides.clear()
