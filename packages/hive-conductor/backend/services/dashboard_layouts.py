"""Per-principal dashboard layouts, in the boundary the deployment configures.

The layout used to live in a module dict mirrored to a JSON file inside the
image, with the write wrapped in a bare `except` — so a container recreate lost
every layout, and a read-only filesystem lost one silently while the API said
`{"ok": true}`. ADR-082926-3b80 moves it to `stores.dashboard_layouts`, a
`JsonStore` like every other durable Conductor collection: one key per
principal, one upsert per save, into whatever `PersistedStore` the deployment
wired.

Two properties this module exists to hold:

- **A write that did not land is not a success.** `save` writes, reads back, and
  raises `LayoutPersistenceError` when what came back is not what went in. The
  route turns that into a 503. Nothing catches it in between.
- **A save is against a revision.** Every record carries one. A caller may pass
  `expected_revision`; a stale one is refused with `LayoutConflictError` rather
  than silently overwriting the other editor.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.dashboard_safety import sanitize_dashboard_layout

SCHEMA_VERSION = 1

#: Serializes read-modify-write. The revision check and the write have to be one
#: critical section or two concurrent saves both read revision N, both pass the
#: expectation, and the later one wins without either being told.
_save_lock = threading.Lock()


class LayoutError(Exception):
    """Base for every way a layout operation refuses."""


class LayoutPersistenceError(LayoutError):
    """The layout was not durably stored. Never raised for a write that landed."""


class LayoutConflictError(LayoutError):
    """The stored revision moved since the caller read it."""

    def __init__(self, expected: int, stored: LayoutRecord) -> None:
        super().__init__(
            f"the layout is at revision {stored.revision}, not the {expected} this save expected"
        )
        self.expected = expected
        self.stored = stored


class LayoutRecord(BaseModel):
    """What is stored for one principal.

    `extra="forbid"`: a record read back with a field this build does not know
    came from a future build, and guessing at it would quietly drop whatever it
    meant.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    revision: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    layout: dict[str, Any] = Field(default_factory=lambda: {"widgets": []})


def _store() -> Any:
    # Imported here rather than at module scope: `stores` imports a long chain of
    # models, and a service module that pulls it in at import time makes every
    # test that touches this file pay for the whole graph.
    import stores

    return stores.dashboard_layouts


def _empty() -> LayoutRecord:
    return LayoutRecord(layout={"widgets": []})


def load(principal: str) -> LayoutRecord:
    """This principal's record, or an empty one if it has never saved.

    A stored document this build cannot parse is returned as empty rather than
    raised: a layout is a preference, and refusing to render the dashboard
    because one widget list is malformed helps nobody. The next save replaces it.
    """
    raw = _store().get(principal)
    if not isinstance(raw, dict):
        return _empty()
    try:
        record = LayoutRecord.model_validate(raw)
    except Exception:
        return _empty()
    return record.model_copy(update={"layout": sanitize_dashboard_layout(record.layout)})


def save(
    principal: str, layout: dict[str, Any], *, expected_revision: int | None = None
) -> LayoutRecord:
    """Store this principal's layout, or raise. Returns what was read back.

    `expected_revision` is the caller's claim about what it edited. Absent, the
    save is last-write-wins — what the SPA does today — and the returned record
    carries the new revision so a client can start checking.
    """
    safe = sanitize_dashboard_layout(layout)
    with _save_lock:
        stored = load(principal)
        if expected_revision is not None and expected_revision != stored.revision:
            raise LayoutConflictError(expected_revision, stored)
        written = LayoutRecord(
            schema_version=SCHEMA_VERSION,
            revision=stored.revision + 1,
            updated_at=datetime.now(UTC),
            layout=safe,
        )
        _write(principal, written)
        return _read_back(principal, written)


def _write(principal: str, record: LayoutRecord) -> None:
    """One upsert. Any refusal becomes a persistence failure, not a 500."""
    try:
        _store()[principal] = record.model_dump(mode="json")
    except Exception as exc:
        raise LayoutPersistenceError(
            f"the layout store refused the write for {principal!r}: {exc}"
        ) from exc


def _read_back(principal: str, written: LayoutRecord) -> LayoutRecord:
    """Confirm the write by reading it, so a store that accepts and drops fails.

    The failure this catches is the one the old code could not: a write that
    raises nothing and stores nothing.
    """
    confirmed = load(principal)
    if confirmed.revision != written.revision:
        raise LayoutPersistenceError(
            f"the layout for {principal!r} read back at revision {confirmed.revision}, "
            f"not the {written.revision} just written"
        )
    return confirmed
