"""Durable home for extension install records and transitions (#953, M9-B2).

The store protocol is the persistence seam: the service speaks only to it, so
a PostgreSQL backend can arrive (with B1's identity substrate) without
touching the state machine. The in-memory implementation keeps full record and
transition history for the process lifetime — durable enough for the B2
contract to be tested end to end, explicitly not a restart-surviving store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.extensions.types import (
    ExtensionInstallRecord,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
)


@runtime_checkable
class ExtensionStore(Protocol):
    """Persistence seam for install records and their audit trail."""

    async def save_record(self, record: ExtensionInstallRecord) -> None: ...

    async def get_record(self, install_id: str) -> ExtensionInstallRecord | None: ...

    async def latest_record(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> ExtensionInstallRecord | None:
        """Most recent record for the (scope, extension, version) key."""
        ...

    async def active_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None: ...

    async def set_active(self, record: ExtensionInstallRecord) -> None:
        """Swap the scope's active pointer for the record's extension id.

        Implementations must make this a single atomic replacement: callers
        rely on it for caller-perceived activation atomicity.
        """
        ...

    async def installed_versions(self, scope: ExtensionScope) -> dict[str, str]:
        """extension_id -> version for every ACTIVE record in the scope."""
        ...

    async def records_in_state(self, state: ExtensionState) -> list[ExtensionInstallRecord]: ...

    async def append_transition(self, transition: ExtensionTransition) -> None: ...

    async def transitions_for(self, install_id: str) -> tuple[ExtensionTransition, ...]: ...

    async def next_seq(self) -> int: ...


class InMemoryExtensionStore:
    """Process-lifetime implementation of :class:`ExtensionStore`."""

    def __init__(self) -> None:
        self._records: dict[str, ExtensionInstallRecord] = {}
        self._active: dict[tuple[str, str, str], str] = {}
        self._transitions: list[ExtensionTransition] = []
        self._seq = 0

    async def save_record(self, record: ExtensionInstallRecord) -> None:
        self._records[record.install_id] = record

    async def get_record(self, install_id: str) -> ExtensionInstallRecord | None:
        return self._records.get(install_id)

    async def latest_record(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> ExtensionInstallRecord | None:
        candidates = [
            record
            for record in self._records.values()
            if record.org_id == scope.org_id
            and record.workspace_id == scope.workspace_id
            and record.extension_id == extension_id
            and record.version == version
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda record: record.created_at or datetime.min.replace(tzinfo=UTC),
        )

    async def active_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        install_id = self._active.get((scope.org_id, scope.workspace_id, extension_id))
        if install_id is None:
            return None
        return self._records.get(install_id)

    async def set_active(self, record: ExtensionInstallRecord) -> None:
        self._active[(record.org_id, record.workspace_id, record.extension_id)] = record.install_id

    async def installed_versions(self, scope: ExtensionScope) -> dict[str, str]:
        versions: dict[str, str] = {}
        for record in self._records.values():
            if (
                record.org_id == scope.org_id
                and record.workspace_id == scope.workspace_id
                and record.state is ExtensionState.ACTIVE
            ):
                versions[record.extension_id] = record.version
        return versions

    async def records_in_state(self, state: ExtensionState) -> list[ExtensionInstallRecord]:
        return [record for record in self._records.values() if record.state is state]

    async def append_transition(self, transition: ExtensionTransition) -> None:
        self._transitions.append(transition)

    async def transitions_for(self, install_id: str) -> tuple[ExtensionTransition, ...]:
        return tuple(t for t in self._transitions if t.install_id == install_id)

    async def next_seq(self) -> int:
        self._seq += 1
        return self._seq
