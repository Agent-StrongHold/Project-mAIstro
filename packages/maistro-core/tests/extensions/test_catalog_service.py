"""Tests for the private organizational extension catalog service (#979)."""

from __future__ import annotations

import json

import pytest

from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.manifest import ExtensionManifest
from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.types import PackageIdentity, ExtensionEntryPoint


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
def catalog_service(catalog_store: InMemoryCatalogStore) -> CatalogService:
    return CatalogService(catalog_store)


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
            ExtensionEntryPoint(name="main", module="tool_a.main", attribute="run"),
        ),
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


async def test_get_set_catalog(catalog_service: CatalogService, catalog_store: InMemoryCatalogStore, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]]):
    """Setting and getting a catalog works."""
    org_id = "org-123"

    # Initially no catalog
    assert await catalog_service.get_catalog(org_id) is None

    # Set the catalog
    await catalog_service.set_catalog(org_id, sample_catalog_with_manifest)

    # Retrieve it
    retrieved = await catalog_service.get_catalog(org_id)
    assert retrieved is not None
    assert len(retrieved.entries) == 3
    assert retrieved.entries[0].identity.extension_name == "tool-a"
    assert retrieved.entries[0].identity.semantic_version == "1.0.0"

    # Check that the manifests are stored
    assert isinstance(catalog_store, InMemoryCatalogStore)
    manifests = catalog_store._manifests.get(org_id, {})
    assert len(manifests) == 3
    assert manifests[sample_catalog_with_manifest[0][0].identity] == sample_catalog_with_manifest[0][1]


async def test_list_extensions(catalog_service: CatalogService, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]]):
    """Listing extensions returns the expected metadata."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog_with_manifest)

    # List all extensions
    # List all extensions
    extensions = await catalog_service.list_extensions(org_id)
    assert len(extensions) == 3
    # Check that we have the expected extensions, regardless of order.
    ext_map = {(e["extension_name"], e["version"]): e for e in extensions}
    assert ("tool-a", "1.0.0") in ext_map
    assert ("tool-a", "2.0.0") in ext_map
    assert ("tool-b", "1.5.0") in ext_map
    # Optionally check the fields.
    assert ext_map[("tool-a", "1.0.0")]["api_version"] == "1.0"
    assert ext_map[("tool-a", "1.0.0")]["permissions"] == ("network.http", "storage.workspace")
    assert ext_map[("tool-a", "2.0.0")]["api_version"] == "1.1"
    assert ext_map[("tool-a", "2.0.0")]["permissions"] == ("network.http", "storage.workspace", "system.filesystem")
    assert ext_map[("tool-b", "1.5.0")]["api_version"] == "0.9"
    assert ext_map[("tool-b", "1.5.0")]["permissions"] == ("network.http",)

    # List with both search and publisher
    extensions = await catalog_service.list_extensions(org_id, search="tool-b", publisher_id="pub-1")
    assert len(extensions) == 1
    assert extensions[0]["extension_name"] == "tool-b"
    assert extensions[0]["publisher_id"] == "pub-1"


async def test_get_extension_versions(catalog_service: CatalogService, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]]):
    """Getting versions for a specific extension works."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog_with_manifest)

    versions = await catalog_service.get_extension_versions(org_id, "tool-a")
    assert len(versions) == 2
    # Should be sorted by version descending (newest first)
    assert versions[0]["version"] == "2.0.0"
    assert versions[0]["api_version"] == "1.1"
    assert versions[0]["permissions"] == ("network.http", "storage.workspace", "system.filesystem")
    assert versions[1]["version"] == "1.0.0"
    assert versions[1]["api_version"] == "1.0"
    assert versions[1]["permissions"] == ("network.http", "storage.workspace")

    # Non-existent extension returns empty tuple
    versions = await catalog_service.get_extension_versions(org_id, "non-existent")
    assert len(versions) == 0


async def test_get_extension_version(catalog_service: CatalogService, sample_catalog_with_manifest: list[tuple[CatalogEntry, ExtensionManifest]]):
    """Getting a specific version returns the correct metadata."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog_with_manifest)

    entry = await catalog_service.get_extension_version(org_id, "tool-a", "1.0.0")
    assert entry is not None
    assert entry["extension_name"] == "tool-a"
    assert entry["version"] == "1.0.0"
    assert entry["api_version"] == "1.0"
    assert entry["permissions"] == ("network.http", "storage.workspace")
    assert entry["artifact_sha256"] == "a" * 64
    assert entry["manifest_sha256"] == "m" * 64

    # Non-existent version returns None
    entry = await catalog_service.get_extension_version(org_id, "tool-a", "3.0.0")
    assert entry is None

    # Non-existent extension returns None
    entry = await catalog_service.get_extension_version(org_id, "non-existent", "1.0.0")
    assert entry is None
