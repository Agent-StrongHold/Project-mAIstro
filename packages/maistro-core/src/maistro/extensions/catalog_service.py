"""Private organizational extension catalog service (#979).

The catalog service exposes a snapshot of available extensions for an
organization, with search and metadata inspection. Catalogs are immutable
snapshots; updates create new snapshots.

Each catalog entry points to an immutable artifact via package and manifest
digests, ensuring tamper detection. The service does not grant runtime
authority; that remains with the install service.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.manifest import ExtensionManifest
from maistro.extensions.types import PackageIdentity


@runtime_checkable
class CatalogStore(Protocol):
    """Store for organizational extension catalog snapshots."""

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None: ...

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None: ...


class InMemoryCatalogStore:
    """Simple in-memory catalog store per organization."""

    def __init__(self) -> None:
        self._catalogs: dict[str, list[CatalogEntry]] = {}
        self._manifests: dict[str, dict[PackageIdentity, ExtensionManifest]] = {}

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        """Get the current catalog snapshot for an organization."""
        entries = self._catalogs.get(org_id)
        if entries is None:
            return None
        return ExtensionCatalog(tuple(entries))

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None:
        """Update the catalog for an organization.

        Args:
            org_id: The organization identifier.
            entries: A sequence of (catalog_entry, manifest) tuples.
        """
        catalog_entries: list[CatalogEntry] = []
        manifest_map: dict[PackageIdentity, ExtensionManifest] = {}
        for catalog_entry, manifest in entries:
            catalog_entries.append(catalog_entry)
            manifest_map[catalog_entry.identity] = manifest
        self._catalogs[org_id] = catalog_entries
        self._manifests[org_id] = manifest_map

    def _get_manifest(
        self, org_id: str, identity: PackageIdentity
    ) -> ExtensionManifest | None:
        """Get the manifest for a given identity in the org's catalog.

        Returns None if not available.
        """
        return self._manifests.get(org_id, {}).get(identity)


def _catalog_entry_to_dict(
    entry: CatalogEntry, manifest: ExtensionManifest | None = None
) -> dict[str, object]:
    """Convert a CatalogEntry and its manifest to a dictionary for API responses."""
    result = {
        "extension_name": entry.identity.extension_name,
        "version": entry.identity.semantic_version,
        "package_sha256": entry.identity.package_sha256,
        "manifest_sha256": entry.identity.manifest_sha256,
        "source": entry.source,
        "catalog_snapshot_sha256": entry.catalog_snapshot_sha256,
        "publisher_id": entry.publisher_id,
        "signature": entry.signature,
        "dependencies": [
            {
                "target": dep.target,
                "range": dep.range_text,
                "required": dep.required,
            }
            for dep in entry.dependencies
        ],
    }
    if manifest is not None:
        result.update(
            {
                "api_version": manifest.api_version,
                "permissions": manifest.permissions,
                "entry_points": [
                    {
                        "name": ep.name,
                        "module": ep.module,
                        "attribute": ep.attribute,
                    }
                    for ep in manifest.entry_points
                ],
                "dependencies": [
                    {
                        "target": dep.target,
                        "range": dep.range_text,
                        "required": dep.required,
                    }
                    for dep in manifest.dependencies
                ],
                "artifact_sha256": manifest.artifact_sha256,
                "artifact_size": manifest.artifact_size,
                "source_sha256": manifest.source_sha256,
            }
        )
    return result


class CatalogService:
    """Service for accessing an organization's extension catalog."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        """Get the current catalog snapshot for an organization."""
        return await self._store.get_catalog(org_id)

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None:
        """Update the catalog for an organization."""
        await self._store.set_catalog(org_id, entries)

    async def list_extensions(
        self,
        org_id: str,
        *,
        search: str | None = None,
        publisher_id: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        """List extensions in the catalog, optionally filtered.

        Returns a tuple of extension metadata dictionaries, sorted by
        extension name and then version.
        """
        catalog = await self.get_catalog(org_id)
        if catalog is None:
            return ()

        if isinstance(self._store, InMemoryCatalogStore):
            store = self._store
            # We'll build a list of (entry, manifest) tuples.
            entry_manifest_pairs: list[tuple[CatalogEntry, ExtensionManifest]] = []
            for entry in catalog.entries:
                manifest = store._get_manifest(org_id, entry.identity)
                entry_manifest_pairs.append((entry, manifest))
            # We'll use these pairs for filtering and sorting.
            # For filtering, we can use the entry's fields.
            filtered_pairs: list[tuple[CatalogEntry, ExtensionManifest]] = []
            for entry, manifest in entry_manifest_pairs:
                if publisher_id is not None and entry.publisher_id != publisher_id:
                    continue
                if search is not None:
                    search_lower = search.lower()
                    if (
                        search_lower not in entry.identity.extension_name.lower()
                        and search_lower not in entry.publisher_id.lower()
                    ):
                        continue
                filtered_pairs.append((entry, manifest))
            # Sort by extension name, then version
            def sort_key(pair: tuple[CatalogEntry, ExtensionManifest]) -> tuple[str, SemVer]:
                from maistro.extensions.semver import SemVer

                return (
                    pair[0].identity.extension_name,
                    SemVer.parse(pair[0].identity.semantic_version),
                )
            sorted_pairs = sorted(filtered_pairs, key=sort_key)
            result: list[dict[str, object]] = []
            for entry, manifest in sorted_pairs:
                result.append(_catalog_entry_to_dict(entry, manifest))
            return tuple(result)
        else:
            # If the store is not our in-memory store, we cannot provide
            # manifest data. We'll return the catalog entry data without
            # manifest information.
            entries = catalog.entries
            if publisher_id is not None:
                entries = tuple(e for e in entries if e.publisher_id == publisher_id)
            if search is not None:
                search_lower = search.lower()
                entries = tuple(
                    e
                    for e in entries
                    if search_lower in e.identity.extension_name.lower()
                    or search_lower in e.publisher_id.lower()
                )
            # Sort by extension name, then version (using SemVer for correct ordering)
            def sort_key(e: CatalogEntry):
                from maistro.extensions.semver import SemVer

                return (
                    e.identity.extension_name,
                    SemVer.parse(e.identity.semantic_version),
                )
            sorted_entries = sorted(entries, key=sort_key)
            result: list[dict[str, object]] = []
            for entry in sorted_entries:
                result.append(_catalog_entry_to_dict(entry, None))
            return tuple(result)

    async def get_extension_versions(
        self, org_id: str, extension_name: str
    ) -> tuple[dict[str, object], ...]:
        """Get all versions of a specific extension in the catalog."""
        catalog = await self.get_catalog(org_id)
        if catalog is None:
            return ()

        if isinstance(self._store, InMemoryCatalogStore):
            store = self._store
            # Build a list of (entry, manifest) tuples for the given extension.
            entry_manifest_pairs: list[tuple[CatalogEntry, ExtensionManifest]] = []
            for entry in catalog.entries:
                if entry.identity.extension_name == extension_name:
                    manifest = store._get_manifest(org_id, entry.identity)
                    entry_manifest_pairs.append((entry, manifest))
            # Sort by version descending (newest first)
            def version_sort_key(pair: tuple[CatalogEntry, ExtensionManifest]) -> SemVer:
                from maistro.extensions.semver import SemVer

                return SemVer.parse(pair[0].identity.semantic_version)
            sorted_pairs = sorted(entry_manifest_pairs, key=version_sort_key, reverse=True)
            result: list[dict[str, object]] = []
            for entry, manifest in sorted_pairs:
                result.append(_catalog_entry_to_dict(entry, manifest))
            return tuple(result)
        else:
            entries = tuple(
                e
                for e in catalog.entries
                if e.identity.extension_name == extension_name
            )
            # Sort by version descending (newest first)
            def version_sort_key(e: CatalogEntry):
                from maistro.extensions.semver import SemVer

                return SemVer.parse(e.identity.semantic_version)
            sorted_entries = sorted(entries, key=version_sort_key, reverse=True)
            result: list[dict[str, object]] = []
            for entry in sorted_entries:
                result.append(_catalog_entry_to_dict(entry, None))
            return tuple(result)

    async def get_extension_version(
        self, org_id: str, extension_name: str, version: str
    ) -> dict[str, object] | None:
        """Get metadata for a specific version of an extension."""
        catalog = await self.get_catalog(org_id)
        if catalog is None:
            return None

        if isinstance(self._store, InMemoryCatalogStore):
            store = self._store
            for entry in catalog.entries:
                if (
                    entry.identity.extension_name == extension_name
                    and entry.identity.semantic_version == version
                ):
                    manifest = store._get_manifest(org_id, entry.identity)
                    return _catalog_entry_to_dict(entry, manifest)
        else:
            for entry in catalog.entries:
                if (
                    entry.identity.extension_name == extension_name
                    and entry.identity.semantic_version == version
                ):
                    return _catalog_entry_to_dict(entry, None)
        return None
