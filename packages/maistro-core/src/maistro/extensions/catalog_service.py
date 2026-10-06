"""Private organizational extension catalog service (#979).

Read-side surface over an organization's private catalog snapshot: listing,
search/filter, per-extension version history, and per-version detail down to
the inspected manifest snapshot. Every entry points at immutable bytes —
the package and manifest SHA-256 digests travel with the identity, so what
an operator inspects is digested and what an install later verifies is the
same digest. Tampered artifacts therefore fail at install time even if the
catalog itself was fooled.

The catalog is discovery and inspection only. Nothing here installs,
activates, or grants runtime authority: the governed install lifecycle
(#953) remains the only path from catalog metadata to running code, and it
re-derives every authority decision from its own records. Because this
service never consults the install store (and is never consulted by it), a
catalog outage cannot disable already-installed pinned extensions — the two
availability domains are structurally separate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog
from maistro.extensions.semver import SemVer
from maistro.extensions.types import ExtensionManifest, PackageIdentity


@runtime_checkable
class CatalogStore(Protocol):
    """Store for an organization's catalog snapshot and inspected manifests.

    The entry tuple is the snapshot resolution would run against; the
    manifest map holds the per-identity inspected snapshots operators read
    before deciding to download. A store that cannot serve a manifest for
    some identity returns ``None`` — the entry's digest metadata stays
    inspectable either way.
    """

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None: ...

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None: ...

    async def get_manifest(
        self, org_id: str, identity: PackageIdentity
    ) -> ExtensionManifest | None: ...


class InMemoryCatalogStore:
    """Process-lifetime catalog store, one snapshot per organization.

    ``set_catalog`` replaces the whole snapshot: catalogs are immutable
    revisions, and an update is a new revision, not a mutation.
    """

    def __init__(self) -> None:
        self._catalogs: dict[str, ExtensionCatalog] = {}
        self._manifests: dict[str, dict[PackageIdentity, ExtensionManifest]] = {}

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        """Get the current catalog snapshot for an organization."""
        return self._catalogs.get(org_id)

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None:
        """Replace the catalog snapshot for an organization.

        The snapshot is frozen at call time: later mutation of the caller's
        sequence cannot rewrite published history.
        """
        pairs = list(entries)
        self._catalogs[org_id] = ExtensionCatalog(tuple(entry for entry, _manifest in pairs))
        self._manifests[org_id] = {entry.identity: manifest for entry, manifest in pairs}

    async def get_manifest(
        self, org_id: str, identity: PackageIdentity
    ) -> ExtensionManifest | None:
        """The inspected manifest snapshot for one identity, if published."""
        return self._manifests.get(org_id, {}).get(identity)


def _catalog_entry_to_dict(
    entry: CatalogEntry, manifest: ExtensionManifest | None
) -> dict[str, object]:
    """Render one catalog entry for the API and service surfaces.

    Identity digests, source, publisher and signature are entry metadata and
    always present. The manifest-dependent fields (API version, requested
    permissions, entry points, artifact size and source digest) come from the
    inspected manifest snapshot and are present only when it is available —
    an operator never sees manifest claims that cannot be anchored to bytes.
    """
    result: dict[str, object] = {
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
                "artifact_sha256": manifest.artifact_sha256,
                "artifact_size": manifest.artifact_size,
                "source_sha256": manifest.source_sha256,
            }
        )
    return result


def _name_then_version(
    pair: tuple[CatalogEntry, ExtensionManifest | None],
) -> tuple[str, SemVer]:
    """Listing order: extension name, then semantic version ascending."""
    entry = pair[0]
    return (entry.identity.extension_name, entry.version)


def _version_descending(
    pair: tuple[CatalogEntry, ExtensionManifest | None],
) -> SemVer:
    """Version-history order: newest release first."""
    return pair[0].version


class CatalogService:
    """Read-side catalog surface for one organization's private catalog.

    Search and detail only: the service filters the snapshot, pairs entries
    with their inspected manifests, and reports digest metadata verbatim. It
    holds no install or activation authority and offers no way to acquire
    any.
    """

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    async def get_catalog(self, org_id: str) -> ExtensionCatalog | None:
        """The current catalog snapshot for an organization, if published."""
        return await self._store.get_catalog(org_id)

    async def set_catalog(
        self, org_id: str, entries: Sequence[tuple[CatalogEntry, ExtensionManifest]]
    ) -> None:
        """Publish a new catalog snapshot for an organization."""
        await self._store.set_catalog(org_id, entries)

    async def _with_manifests(
        self, org_id: str, entries: Sequence[CatalogEntry]
    ) -> list[tuple[CatalogEntry, ExtensionManifest | None]]:
        """Pair each entry with its inspected manifest, when one is served."""
        return [
            (entry, await self._store.get_manifest(org_id, entry.identity)) for entry in entries
        ]

    async def list_extensions(
        self,
        org_id: str,
        *,
        search: str | None = None,
        publisher_id: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        """List catalog entries, optionally filtered, sorted for inspection.

        ``search`` matches the extension name or publisher id
        case-insensitively; ``publisher_id`` filters exactly. Ordering is
        extension name then semantic version, so an operator reading the
        list sees a stable, version-aware index rather than snapshot order.
        """
        catalog = await self._store.get_catalog(org_id)
        if catalog is None:
            return ()
        entries = catalog.entries
        if publisher_id is not None:
            entries = tuple(entry for entry in entries if entry.publisher_id == publisher_id)
        if search is not None:
            needle = search.lower()
            entries = tuple(
                entry
                for entry in entries
                if needle in entry.identity.extension_name.lower()
                or needle in entry.publisher_id.lower()
            )
        pairs = sorted(await self._with_manifests(org_id, entries), key=_name_then_version)
        return tuple(_catalog_entry_to_dict(entry, manifest) for entry, manifest in pairs)

    async def get_extension_versions(
        self, org_id: str, extension_name: str
    ) -> tuple[dict[str, object], ...]:
        """Every published version of one extension, newest first."""
        catalog = await self._store.get_catalog(org_id)
        if catalog is None:
            return ()
        matches = [
            entry for entry in catalog.entries if entry.identity.extension_name == extension_name
        ]
        pairs = sorted(
            await self._with_manifests(org_id, matches),
            key=_version_descending,
            reverse=True,
        )
        return tuple(_catalog_entry_to_dict(entry, manifest) for entry, manifest in pairs)

    async def get_extension_version(
        self, org_id: str, extension_name: str, version: str
    ) -> dict[str, object] | None:
        """Detail for exactly one published version, or ``None``."""
        catalog = await self._store.get_catalog(org_id)
        if catalog is None:
            return None
        for entry in catalog.entries:
            if (
                entry.identity.extension_name == extension_name
                and entry.identity.semantic_version == version
            ):
                manifest = await self._store.get_manifest(org_id, entry.identity)
                return _catalog_entry_to_dict(entry, manifest)
        return None
