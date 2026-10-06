"""Tests for the private organizational extension catalog service (#979)."""

from __future__ import annotations

import pytest

from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.types import PackageIdentity


@pytest.fixture
def catalog_store() -> InMemoryCatalogStore:
    return InMemoryCatalogStore()


@pytest.fixture
def catalog_service(catalog_store: InMemoryCatalogStore) -> CatalogService:
    return CatalogService(catalog_store)


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


async def test_get_set_catalog(catalog_service: CatalogService, catalog_store: InMemoryCatalogStore, sample_catalog: ExtensionCatalog):
    """Setting and getting a catalog works."""
    org_id = "org-123"

    # Initially no catalog
    assert await catalog_service.get_catalog(org_id) is None

    # Set the catalog
    await catalog_service.set_catalog(org_id, sample_catalog)

    # Retrieve it
    retrieved = await catalog_service.get_catalog(org_id)
    assert retrieved is not None
    assert len(retrieved.entries) == 3
    assert retrieved.entries[0].identity.extension_name == "tool-a"
    assert retrieved.entries[0].identity.semantic_version == "1.0.0"


async def test_list_extensions(catalog_service: CatalogService, sample_catalog: ExtensionCatalog):
    """Listing extensions returns the expected metadata."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    # List all extensions
    extensions = await catalog_service.list_extensions(org_id)
    assert len(extensions) == 3
    # Should be sorted by name, then version
    assert extensions[0]["extension_name"] == "tool-a"
    assert extensions[0]["version"] == "1.0.0"
    assert extensions[1]["extension_name"] == "tool-a"
    assert extensions[1]["version"] == "2.0.0"
    assert extensions[2]["extension_name"] == "tool-b"
    assert extensions[2]["version"] == "1.5.0"

    # List with search
    extensions = await catalog_service.list_extensions(org_id, search="tool-a")
    assert len(extensions) == 2
    assert all(e["extension_name"] == "tool-a" for e in extensions)

    # List with publisher filter
    extensions = await catalog_service.list_extensions(org_id, publisher_id="pub-1")
    assert len(extensions) == 2
    assert all(e["publisher_id"] == "pub-1" for e in extensions)

    # List with both search and publisher
    extensions = await catalog_service.list_extensions(org_id, search="tool-b", publisher_id="pub-1")
    assert len(extensions) == 1
    assert extensions[0]["extension_name"] == "tool-b"
    assert extensions[0]["publisher_id"] == "pub-1"


async def test_get_extension_versions(catalog_service: CatalogService, sample_catalog: ExtensionCatalog):
    """Getting versions for a specific extension works."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    versions = await catalog_service.get_extension_versions(org_id, "tool-a")
    assert len(versions) == 2
    # Should be sorted by version descending (newest first)
    assert versions[0]["version"] == "2.0.0"
    assert versions[1]["version"] == "1.0.0"

    # Non-existent extension returns empty tuple
    versions = await catalog_service.get_extension_versions(org_id, "non-existent")
    assert len(versions) == 0


async def test_get_extension_version(catalog_service: CatalogService, sample_catalog: ExtensionCatalog):
    """Getting a specific version returns the correct metadata."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    entry = await catalog_service.get_extension_version(org_id, "tool-a", "1.0.0")
    assert entry is not None
    assert entry["extension_name"] == "tool-a"
    assert entry["version"] == "1.0.0"
    assert entry["package_sha256"] == "a" * 64
    assert entry["manifest_sha256"] == "m" * 64
    assert entry["publisher_id"] == "pub-1"
    assert entry["signature"] == "sig1"

    # Non-existent version returns None
    entry = await catalog_service.get_extension_version(org_id, "tool-a", "3.0.0")
    assert entry is None

    # Non-existent extension returns None
    entry = await catalog_service.get_extension_version(org_id, "non-existent", "1.0.0")
    assert entry is None
