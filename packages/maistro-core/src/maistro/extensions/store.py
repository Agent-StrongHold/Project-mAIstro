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
    PinEvent,
    PinRecord,
    RemovalNote,
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

    # -- B3 (#954): post-install lifecycle ---------------------------------

    async def clear_active(self, scope: ExtensionScope, extension_id: str) -> None:
        """Drop the scope's active pointer for the extension, if set.

        Disable and remove use this to stop invocation resolution
        immediately; the pointer must never outlive the authority.
        """
        ...

    async def get_pin(self, scope: ExtensionScope, extension_id: str) -> PinRecord | None: ...

    async def set_pin(self, pin: PinRecord) -> None:
        """Write the scope's pin for the record's extension (one per key)."""
        ...

    async def clear_pin(self, scope: ExtensionScope, extension_id: str) -> bool:
        """Remove the pin, returning whether one existed."""
        ...

    async def append_pin_event(self, event: PinEvent) -> None: ...

    async def pin_events(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[PinEvent, ...]: ...

    async def append_removal_note(self, note: RemovalNote) -> None: ...

    async def removal_notes_for(self, install_id: str) -> tuple[RemovalNote, ...]: ...


class InMemoryExtensionStore:
    """Process-lifetime implementation of :class:`ExtensionStore`.

    Append-only by policy: records are replaced with new immutable versions,
    and transitions, pin events and removal notes are only ever appended.
    Canonical evidence therefore survives disable and remove (#954's
    retention criterion) for the process lifetime; the durable twin is a
    PostgreSQL backend behind the same protocol.
    """

    def __init__(self) -> None:
        self._records: dict[str, ExtensionInstallRecord] = {}
        self._active: dict[tuple[str, str, str], str] = {}
        self._transitions: list[ExtensionTransition] = []
        self._pins: dict[tuple[str, str, str], PinRecord] = {}
        self._pin_events: list[PinEvent] = []
        self._removal_notes: list[RemovalNote] = []
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

    # -- B3 (#954): post-install lifecycle ---------------------------------

    async def clear_active(self, scope: ExtensionScope, extension_id: str) -> None:
        self._active.pop((scope.org_id, scope.workspace_id, extension_id), None)

    async def get_pin(self, scope: ExtensionScope, extension_id: str) -> PinRecord | None:
        return self._pins.get((scope.org_id, scope.workspace_id, extension_id))

    async def set_pin(self, pin: PinRecord) -> None:
        self._pins[(pin.org_id, pin.workspace_id, pin.extension_id)] = pin

    async def clear_pin(self, scope: ExtensionScope, extension_id: str) -> bool:
        return self._pins.pop((scope.org_id, scope.workspace_id, extension_id), None) is not None

    async def append_pin_event(self, event: PinEvent) -> None:
        self._pin_events.append(event)

    async def pin_events(self, scope: ExtensionScope, extension_id: str) -> tuple[PinEvent, ...]:
        return tuple(
            event
            for event in self._pin_events
            if event.org_id == scope.org_id
            and event.workspace_id == scope.workspace_id
            and event.extension_id == extension_id
        )

    async def append_removal_note(self, note: RemovalNote) -> None:
        self._removal_notes.append(note)

    async def removal_notes_for(self, install_id: str) -> tuple[RemovalNote, ...]:
        return tuple(note for note in self._removal_notes if note.install_id == install_id)
