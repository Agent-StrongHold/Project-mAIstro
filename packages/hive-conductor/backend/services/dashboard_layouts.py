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

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.dashboard_safety import sanitize_dashboard_layout

logger = logging.getLogger("hive.dashboard")

SCHEMA_VERSION = 1

#: The `stores.py` key this service reads and writes. Named here because the
#: durable read-back addresses the backend directly, below the store.
STORE_NAME = "dashboard_layouts"

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


#: How long to wait for the state writer to drain before reading a write back.
#: Short on purpose: this runs inside a request, and a writer that has not
#: drained in this long is a writer that is not going to.
_FLUSH_TIMEOUT_S = 5.0


def _store() -> Any:
    # Imported here rather than at module scope: `stores` imports a long chain of
    # models, and a service module that pulls it in at import time makes every
    # test that touches this file pay for the whole graph.
    import stores

    return stores.dashboard_layouts


def _backend(store: Any) -> Any:
    """The `PersistedStore` behind this store, or None if it has none.

    A `JsonStore` keeps a dict *and* a backend, and `__setitem__` updates the
    dict first. Reading the dict back therefore confirms nothing: it is the
    value we just put there. The durable answer is one layer down.
    """
    return getattr(store, "_persisted", None)


def _settle(backend: Any) -> None:
    """Wait for the writer queue to drain, so a failed write has already failed.

    `PersistedStore.put_raw` submits a transaction to `State`'s writer thread and
    returns. Without this, a full disk is logged by that thread some time after
    the request has answered 200 -- the exact shape of "acknowledged a write that
    did not happen" this module exists to remove.
    """
    state = getattr(backend, "_state", None)
    flush = getattr(state, "flush", None)
    if callable(flush):
        flush(timeout=_FLUSH_TIMEOUT_S)


def _empty() -> LayoutRecord:
    return LayoutRecord(layout={"widgets": []})


#: Principals that start from a shipped template. Here rather than in the route
#: because the route is not the only caller: the chat widget tool edits the same
#: layout, and a second copy of this map is a second answer to "what is this
#: user looking at".
PRESETS: dict[str, str] = {
    "demo": "pm-command-center",
}

#: Shipped templates, in the image. Catalogue rather than user state, which is
#: why reading them off disk here is not the boundary violation #340 removed.
_TEMPLATES = Path(__file__).resolve().parent.parent / "data" / "demo_dashboards"


def preset_for(principal: str) -> dict[str, Any] | None:
    """The template this principal starts from, if any. Read, never written.

    Seeding used to persist from inside the `GET` handler, inside a bare
    `except`, which made a read depend on a write succeeding and then hid it
    when it did not. The preset becomes durable when the user saves.
    """
    preset = PRESETS.get(principal)
    if not preset:
        return None
    path = _TEMPLATES / f"{preset}.json"
    if not path.is_file():
        return None
    try:
        return sanitize_dashboard_layout(json.loads(path.read_text()))
    except (OSError, ValueError) as exc:
        logger.warning("preset %s could not be read: %s", preset, exc)
        return None


def _from_mapping(raw: Any) -> LayoutRecord:
    """A stored record, or an empty one if it is not one this build understands.

    A layout is a preference: refusing to render the dashboard because one
    widget list is malformed helps nobody, and the next save replaces it.
    """
    if not isinstance(raw, dict):
        return _empty()
    try:
        record = LayoutRecord.model_validate(raw)
    except Exception:
        return _empty()
    return record.model_copy(update={"layout": sanitize_dashboard_layout(record.layout)})


def _from_document(document: str | None) -> LayoutRecord:
    """The same, for the JSON the durable backend hands back."""
    if not document:
        return _empty()
    try:
        return _from_mapping(json.loads(document))
    except ValueError:
        return _empty()


def load(principal: str) -> LayoutRecord:
    """This principal's record, or an empty one if it has never saved."""
    return _from_mapping(_store().get(principal))


def effective(principal: str) -> LayoutRecord:
    """What the principal is actually looking at: their record, or their preset.

    The preset is offered by `GET` without being stored, so a caller that edits
    `load()` and saves the result replaces the preset with whatever it added --
    which is what the chat widget tool did, and why every preset widget
    disappeared the first time a user asked for one.
    """
    record = load(principal)
    if record.revision:
        return record
    seeded = preset_for(principal)
    return record if seeded is None else record.model_copy(update={"layout": seeded})


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
    """Confirm the write against the durable row, not the cache in front of it.

    The failure this catches is the one the old code could not: a write that
    raises nothing and stores nothing. Two kinds of nothing, both real —

    - the store keeps a dict updated before the backend is touched, so reading
      the dict reads back what this process just put there; and
    - the SQLite backend *queues* the transaction, so a disk that is full fails
      on the writer thread after the request would otherwise have answered.

    So: settle the writer, then read the row. With no backend configured there
    is no row and the dict is all there is — that is a deployment that chose
    in-memory state, and the refusal for a deployment that asked for durability
    and did not get it is `services/durability.py`'s (#333), not this module's.
    """
    store = _store()
    backend = _backend(store)
    if backend is None:
        confirmed = load(principal)
    else:
        _settle(backend)
        confirmed = _from_document(backend.get_raw(STORE_NAME, principal))
    if confirmed.revision != written.revision:
        raise LayoutPersistenceError(
            f"the layout for {principal!r} read back at revision {confirmed.revision}, "
            f"not the {written.revision} just written"
        )
    return confirmed
