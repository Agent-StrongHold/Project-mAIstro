"""Private organizational extension catalog service (#979).

The catalog service exposes a snapshot of available extensions for an
organization, with search and metadata inspection. Catalogs are immutable
snapshots; updates create new snapshots.

Each catalog entry points to an immutable artifact via package and manifest
digests, ensuring tamper detection. The service does not grant runtime
authority; that remains with the install service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog


@runtime_checkable
class CatalogStore(Protocol):
    """Store for organizational extension catalog snapshots."""

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None: ...

    async def set_catalog(self, org_id: str, catalog: ExtensionCatalog) -> None: ...


class InMemoryCatalogStore:
    """Simple in-memory catalog store per organization."""

    def __init__(self) -> None:
        self._catalogs: dict[str, ExtensionCatalog] = {}

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        return self._catalogs.get(org_id)

    async def set_catalog(self, org_id: str, catalog: ExtensionCatalog) -> None:
        self._catalogs[org_id] = catalog


def _catalog_entry_to_dict(entry: CatalogEntry) -> dict[str, object]:
    """Convert a CatalogEntry to a dictionary for API responses."""
    return {
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


class CatalogService:
    """Service for accessing an organization's extension catalog."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        """Get the current catalog snapshot for an organization."""
        return await self._store.get_catalog(org_id)

    async def set_catalog(self, org_id: str, catalog: ExtensionCatalog) -> None:
        """Update the catalog snapshot for an organization."""
        return await self._store.set_catalog(org_id, catalog)

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
        return tuple(_catalog_entry_to_dict(e) for e in sorted_entries)

    async def get_extension_versions(
        self, org_id: str, extension_name: str
    ) -> tuple[dict[str, object], ...]:
        """Get all versions of a specific extension in the catalog."""
        catalog = await self.get_catalog(org_id)
        if catalog is None:
            return ()

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
        return tuple(_catalog_entry_to_dict(e) for e in sorted_entries)

    async def get_extension_version(
        self, org_id: str, extension_name: str, version: str
    ) -> dict[str, object] | None:
        """Get metadata for a specific version of an extension."""
        catalog = await self.get_catalog(org_id)
        if catalog is None:
            return None

        for entry in catalog.entries:
            if (
                entry.identity.extension_name == extension_name
                and entry.identity.semantic_version == version
            ):
                return _catalog_entry_to_dict(entry)
        return None
