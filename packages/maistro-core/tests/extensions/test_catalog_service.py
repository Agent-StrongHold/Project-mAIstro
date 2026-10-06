"""Tests for the private organizational extension catalog service (#979).

Coverage targets the issue's acceptance criteria at the service layer:
discovery with search/filter over publisher and name metadata, inspection of
manifest metadata before any download, snapshot immutability, and the
digest-carrying detail view. The catalog is read-side only, so the tests
also pin the structural separation: no service method returns anything that
resembles install or activation authority.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from maistro.extensions.catalog_service import CatalogService, InMemoryCatalogStore
from maistro.extensions.resolution import (
    CatalogEntry,
    ExtensionCatalog,
    ExtensionDependency,
)
from maistro.extensions.types import (
    ExtensionEntryPoint,
    ExtensionManifest,
    PackageIdentity,
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
        dependencies=(ExtensionDependency(target="tool-a", range_text=">=1.0.0,<3.0.0"),),
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
        dependencies=(ExtensionDependency(target="tool-a", range_text=">=1.0.0,<3.0.0"),),
    )
    return [(entry1, manifest1), (entry2, manifest2), (entry3, manifest3)]


async def test_unknown_organization_has_no_catalog(catalog_service: CatalogService):
    """A fresh instance discovers nothing: no snapshot, no partial data."""
    assert await catalog_service.get_catalog("org-123") is None
    assert await catalog_service.list_extensions("org-123") == ()
    assert await catalog_service.get_extension_versions("org-123", "tool-a") == ()
    assert await catalog_service.get_extension_version("org-123", "tool-a", "1.0.0") is None


async def test_set_and_get_catalog_round_trip(
    catalog_service: CatalogService,
    catalog_store: InMemoryCatalogStore,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Publishing a snapshot stores entries and their inspected manifests."""
    org_id = "org-123"

    await catalog_service.set_catalog(org_id, sample_catalog)

    retrieved = await catalog_service.get_catalog(org_id)
    assert retrieved is not None
    assert len(retrieved.entries) == 3
    assert retrieved.entries[0].identity.extension_name == "tool-a"
    assert retrieved.entries[0].identity.semantic_version == "1.0.0"

    # The inspected manifest snapshots are retrievable per identity.
    first_entry, first_manifest = sample_catalog[0]
    assert await catalog_store.get_manifest(org_id, first_entry.identity) is first_manifest


async def test_published_snapshot_is_immutable_against_later_input_mutation(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Mutating the published-from sequence cannot rewrite catalog history.

    A catalog is a snapshot: what an operator inspected must still be what
    resolution later runs against, so aliasing the caller's mutable list
    would be a tampering vector the store must not have.
    """
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    sample_catalog.append(
        (
            CatalogEntry(
                identity=PackageIdentity(
                    extension_name="rogue",
                    semantic_version="1.0.0",
                    package_sha256="d" * 64,
                    manifest_sha256="q" * 64,
                ),
                source="https://attacker.example/v1",
                catalog_snapshot_sha256="t" * 64,
                publisher_id="pub-x",
                signature="sigx",
                dependencies=(),
            ),
            _make_manifest(
                extension_id="rogue",
                name="Rogue",
                version="1.0.0",
                publisher="pub-x",
                api_version="1.0",
                permissions=("system.all",),
                entry_points=(),
                dependencies=(),
                artifact_sha256="d" * 64,
                artifact_size=1,
                source_sha256="q" * 64,
            ),
        )
    )

    retrieved = await catalog_service.get_catalog(org_id)
    assert retrieved is not None
    assert len(retrieved.entries) == 3
    assert all(entry.identity.extension_name != "rogue" for entry in retrieved.entries)


async def test_entries_are_frozen_records(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Catalog entries resist in-place tampering after publication."""
    await catalog_service.set_catalog("org-123", sample_catalog)
    catalog = await catalog_service.get_catalog("org-123")
    assert catalog is not None

    entry = catalog.entries[0]
    with pytest.raises(AttributeError):
        entry.publisher_id = "attacker"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        entry.signature = "forged"  # type: ignore[misc]


async def test_list_extensions_returns_metadata_and_manifest_detail(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Listing exposes publisher/digest metadata plus manifest detail."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    extensions = await catalog_service.list_extensions(org_id)
    assert len(extensions) == 3
    ext_map = {(e["extension_name"], e["version"]): e for e in extensions}
    assert ("tool-a", "1.0.0") in ext_map
    assert ("tool-a", "2.0.0") in ext_map
    assert ("tool-b", "1.5.0") in ext_map

    tool_a_1 = ext_map[("tool-a", "1.0.0")]
    assert tool_a_1["publisher_id"] == "pub-1"
    assert tool_a_1["package_sha256"] == "a" * 64
    assert tool_a_1["manifest_sha256"] == "m" * 64
    assert tool_a_1["signature"] == "sig1"
    assert tool_a_1["api_version"] == "1.0"
    assert tool_a_1["permissions"] == ("network.http", "storage.workspace")
    assert tool_a_1["artifact_sha256"] == "a" * 64

    # The entry declaring a dependency surfaces it for operator inspection.
    tool_b = ext_map[("tool-b", "1.5.0")]
    assert tool_b["dependencies"] == [
        {"target": "tool-a", "range": ">=1.0.0,<3.0.0", "required": True}
    ]


async def test_list_extensions_sorts_by_name_then_semver(
    catalog_service: CatalogService,
):
    """Ordering is name-then-version with semantic, not lexicographic, order.

    9.0.0 sorts before 10.0.0 — a plain string sort would invert them.
    """
    entries = []
    for version, artifact_byte in (("10.0.0", "1"), ("9.0.0", "2")):
        manifest = _make_manifest(
            extension_id="tool-c",
            name="Tool C",
            version=version,
            publisher="pub-1",
            api_version="1.0",
            permissions=(),
            entry_points=(),
            dependencies=(),
            artifact_sha256=artifact_byte * 64,
            artifact_size=1,
            source_sha256=artifact_byte * 64,
        )
        entry = CatalogEntry(
            identity=PackageIdentity(
                extension_name="tool-c",
                semantic_version=version,
                package_sha256=artifact_byte * 64,
                manifest_sha256=artifact_byte * 64,
            ),
            source="s",
            catalog_snapshot_sha256="s" * 64,
            publisher_id="pub-1",
            signature="sig",
            dependencies=(),
        )
        entries.append((entry, manifest))

    await catalog_service.set_catalog("org-1", entries)
    listed = await catalog_service.list_extensions("org-1")
    assert [e["version"] for e in listed] == ["9.0.0", "10.0.0"]


async def test_list_extensions_search_and_publisher_filter(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Search matches name or publisher case-insensitively; filter is exact."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    by_name = await catalog_service.list_extensions(org_id, search="TOOL-A")
    assert len(by_name) == 2
    assert all(e["extension_name"] == "tool-a" for e in by_name)

    by_publisher_substring = await catalog_service.list_extensions(org_id, search="pub-2")
    assert len(by_publisher_substring) == 1
    assert by_publisher_substring[0]["publisher_id"] == "pub-2"

    by_publisher = await catalog_service.list_extensions(org_id, publisher_id="pub-1")
    assert len(by_publisher) == 2
    assert all(e["publisher_id"] == "pub-1" for e in by_publisher)

    combined = await catalog_service.list_extensions(org_id, search="tool-b", publisher_id="pub-1")
    assert len(combined) == 1
    assert combined[0]["extension_name"] == "tool-b"

    no_match = await catalog_service.list_extensions(org_id, search="no-such-extension")
    assert no_match == ()


async def test_get_extension_versions_newest_first(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Version history is semantic-ordered newest first, per extension."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    versions = await catalog_service.get_extension_versions(org_id, "tool-a")
    assert [v["version"] for v in versions] == ["2.0.0", "1.0.0"]
    assert versions[0]["api_version"] == "1.1"
    assert versions[0]["permissions"] == (
        "network.http",
        "storage.workspace",
        "system.filesystem",
    )

    # Versions of another extension do not leak into this history.
    assert await catalog_service.get_extension_versions(org_id, "non-existent") == ()


async def test_get_extension_version_detail_and_misses(
    catalog_service: CatalogService,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """Exact-version detail carries the immutable-artifact digests."""
    org_id = "org-123"
    await catalog_service.set_catalog(org_id, sample_catalog)

    entry = await catalog_service.get_extension_version(org_id, "tool-a", "1.0.0")
    assert entry is not None
    assert entry["extension_name"] == "tool-a"
    assert entry["version"] == "1.0.0"
    assert entry["manifest_sha256"] == "m" * 64
    assert entry["artifact_sha256"] == "a" * 64
    assert entry["source_sha256"] == "m" * 64

    assert await catalog_service.get_extension_version(org_id, "tool-a", "3.0.0") is None
    assert await catalog_service.get_extension_version(org_id, "non-existent", "1.0.0") is None


async def test_entries_without_served_manifests_stay_inspectable(
    catalog_service: CatalogService,
    catalog_store: InMemoryCatalogStore,
    sample_catalog: list[tuple[CatalogEntry, ExtensionManifest]],
):
    """A store that serves no manifests still yields digest-level metadata.

    Catalog availability of the manifest snapshot and availability of the
    entry metadata are decoupled: an operator can always see who published
    what version under which digests, even where the manifest body is
    unavailable.
    """

    class ManifestlessStore:
        """Serves the snapshot but no manifest bodies."""

        async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
            snapshot = await catalog_store.get_catalog(org_id)
            return snapshot

        async def set_catalog(
            self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
        ) -> None:
            await catalog_store.set_catalog(org_id, entries)

        async def get_manifest(
            self, org_id: str, identity: PackageIdentity
        ) -> ExtensionManifest | None:
            return None

    stripped = CatalogService(ManifestlessStore())
    org_id = "org-123"
    await stripped.set_catalog(org_id, sample_catalog)

    listed = await stripped.list_extensions(org_id)
    assert len(listed) == 3
    tool_a_1 = listed[0]
    assert tool_a_1["extension_name"] == "tool-a"
    assert tool_a_1["package_sha256"] == "a" * 64
    assert tool_a_1["publisher_id"] == "pub-1"
    # Manifest claims are absent, never invented.
    assert "api_version" not in tool_a_1
    assert "permissions" not in tool_a_1
    assert "artifact_sha256" not in tool_a_1

    detail = await stripped.get_extension_version(org_id, "tool-a", "1.0.0")
    assert detail is not None
    assert detail["manifest_sha256"] == "m" * 64
    assert "entry_points" not in detail


def test_service_surface_offers_no_runtime_authority():
    """The catalog can read metadata but cannot grant execution authority.

    The install lifecycle (#953) is the canonical host authority; the catalog
    service exposes no install, activate, or load capability at all.
    """
    service_methods = {name for name, member in vars(CatalogService).items() if callable(member)}
    assert service_methods == {
        "__init__",
        "get_catalog",
        "set_catalog",
        "list_extensions",
        "get_extension_versions",
        "get_extension_version",
        "_with_manifests",
    }
    assert not any("install" in name or "activat" in name for name in service_methods)
