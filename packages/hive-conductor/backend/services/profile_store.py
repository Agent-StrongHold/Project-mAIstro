"""Durable user profiles — SPEC-083026-ef62, ADR-083026-3d92.

A profile used to live in `chat_completion._PROFILE_CACHE`, a module global,
mirrored inside a `contextlib.suppress` to a PostgREST table that no migration,
model or DDL in this repository creates. The HTTP route wrote the global; the
chat tools read the table. With PostgREST unconfigured — the default, and what
every tracked Compose profile produces — the tools read `{}` and wrote it back,
so a save through the panel was erased by the next field set in chat (#699).

Three properties of this module are what close that, and each is here on
purpose:

**One owner.** Both surfaces call these functions. There is no second dict.

**No cache.** Every read goes to the store. A process cache is what made the
old arrangement invisible, and it is also what makes a second replica serve a
profile its owner has already changed — the gap #703 had to correct a claim
about one family later. A profile read is one row; there is nothing to save.

**Read-back before acknowledgement.** `PersistedStore.put_raw` enqueues a
closure for `State`'s writer thread and returns, and `State._writer_loop`
swallows what that closure raises. Acknowledging after `put_raw` acknowledges a
write that may never have landed — exactly the trap ADR-082926-0b72 documents
for settings. Every write here flushes, re-reads and compares.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("hive.profile_store")

#: The store namespace. Deliberately the name the unreachable PostgREST table
#: used, so an operator reading either the old code or the new one is looking
#: for the same word.
STORE_NAME = "user_profiles"

#: The envelope shape this build writes and is willing to read. A stored record
#: above this refuses to load rather than being coerced — see `_decode`.
SCHEMA_VERSION = 1


class ProfilePersistenceError(RuntimeError):
    """A write was not observed in the store afterwards.

    Raised for a write that did not land, a read-back that disagreed with what
    was sent, and a delete that left the record behind. All three mean the same
    thing to a caller: do not tell anyone this succeeded.
    """


class ProfileSchemaError(RuntimeError):
    """A stored record cannot be read at this build's schema version."""


class ProfileRecord(BaseModel):
    """The stored envelope. `preferences` is the payload; the rest is about it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    user_id: str
    revision: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    preferences: dict[str, Any] = Field(default_factory=dict)


class ProfileRecordStore(Protocol):
    """The durability seam.

    Two implementations ship: one over `PersistedStore`, one in-process. Tests
    add a third that accepts writes and does not keep them, which is the only
    way to exercise the acknowledgement rule from the outside.
    """

    @property
    def durable(self) -> bool:
        """Whether a write here is expected to survive the process."""

    def read(self, user_id: str) -> str | None:
        """The stored JSON document for `user_id`, or None."""

    def write(self, user_id: str, document: str) -> None:
        """Submit `document` and return once it is as durable as this store gets."""

    def remove(self, user_id: str) -> None:
        """Delete `user_id`'s record, returning once the delete is as durable."""

    def user_ids(self) -> list[str]:
        """Every user id with a stored record."""


class EphemeralProfileRecordStore:
    """In-process record store, labelled as such.

    The Conductor runs without a state database in tests and in `memory://`
    deployments. Those runs go through the same write-and-read-back path, so the
    acknowledgement rule is exercised uniformly — but `durable` is False and the
    API says so, rather than letting an in-memory write wear the shape of a
    durable one (#333).
    """

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    @property
    def durable(self) -> bool:
        return False

    def read(self, user_id: str) -> str | None:
        return self._documents.get(user_id)

    def write(self, user_id: str, document: str) -> None:
        self._documents[user_id] = document

    def remove(self, user_id: str) -> None:
        self._documents.pop(user_id, None)

    def user_ids(self) -> list[str]:
        return sorted(self._documents)


class PersistedProfileRecordStore:
    """Record store over `PersistedStore`, draining the writer queue on write.

    `flush` is the drain. Without it `read` races the writer thread and the
    read-back check would pass or fail on timing.
    """

    def __init__(self, persisted: Any, flush: Any, timeout: float = 10.0) -> None:
        self._persisted = persisted
        self._flush = flush
        self._timeout = timeout

    @property
    def durable(self) -> bool:
        return True

    def read(self, user_id: str) -> str | None:
        document = self._persisted.get_raw(STORE_NAME, user_id)
        return str(document) if document is not None else None

    def write(self, user_id: str, document: str) -> None:
        self._persisted.put_raw(STORE_NAME, user_id, document)
        self._flush(timeout=self._timeout)

    def remove(self, user_id: str) -> None:
        self._persisted.delete(STORE_NAME, user_id)
        self._flush(timeout=self._timeout)

    def user_ids(self) -> list[str]:
        return sorted(key for key, _ in self._persisted.list_all_raw(STORE_NAME))


#: Every mutation here is read-modify-write across load, edit, write, read back.
#: Two requests interleaving inside that sequence both read the old record and
#: the second write loses the first's field.
#:
#: Per process, which is the right boundary and not an accident: SPEC-010's
#: State holds exactly one write-mode connection for the conductor's lifetime,
#: so a second process writing this database is already outside the model.
_write_lock = threading.RLock()

_store: ProfileRecordStore = EphemeralProfileRecordStore()


def configure(store: ProfileRecordStore) -> None:
    """Install the record store. Called once, at startup."""
    global _store
    _store = store


def reset(*, store: ProfileRecordStore | None = None) -> None:
    """Return the module to a fresh state. For tests and for re-initialisation."""
    global _store
    _store = store if store is not None else EphemeralProfileRecordStore()


def durable() -> bool:
    """Whether the configured store is expected to outlive the process."""
    return _store.durable


def _decode(user_id: str, document: str) -> ProfileRecord:
    """Parse a stored document, refusing a version this build cannot read.

    Read as raw JSON before validation on purpose. `ProfileRecord` forbids extra
    fields, so a record written by a newer build would fail validation with a
    message about an unknown key rather than about the version — and a model
    that *ignored* extras would drop those fields on the next write, turning a
    downgrade into data loss with nothing to see.
    """
    try:
        raw = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ProfileSchemaError(f"stored profile for {user_id!r} is not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileSchemaError(f"stored profile for {user_id!r} is not an object")

    version = raw.get("schema_version", 0)
    if not isinstance(version, int):
        raise ProfileSchemaError(
            f"stored profile for {user_id!r} carries a non-integer schema version: {version!r}"
        )
    if version > SCHEMA_VERSION:
        raise ProfileSchemaError(
            f"stored profile for {user_id!r} is at schema version {version}; this build "
            f"reads {SCHEMA_VERSION} and will not coerce a newer record"
        )
    try:
        return ProfileRecord.model_validate(raw)
    except ValueError as exc:
        raise ProfileSchemaError(
            f"stored profile for {user_id!r} failed validation: {exc}"
        ) from exc


def _read(user_id: str) -> str | None:
    """Read one document, translating a store's own failure into ours.

    The reader can fail for reasons that have nothing to do with the record: an
    I/O error, a permission change, a malformed database, exhausted file
    descriptors. Left alone those cross the service boundary unclassified, and
    the route answers 500 for what is a storage failure — while the write path
    beside it already answers the documented 503 (Codex, #699). Wrapped here, at
    the seam, rather than caught wider up where it would swallow programming
    errors too.
    """
    try:
        return _store.read(user_id)
    except ProfilePersistenceError:
        raise
    except Exception as exc:
        raise ProfilePersistenceError(
            f"the profile store could not be read for {user_id!r}: {exc}"
        ) from exc


def load(user_id: str) -> ProfileRecord:
    """Read `user_id`'s record, or an empty one when nothing is stored.

    Seeding does not write. A read must not create a record, or a single `GET`
    against a read-only or failing store would report a success it never had.
    """
    if not user_id:
        raise ValueError("a profile is addressed by a principal; user_id is empty")
    document = _read(user_id)
    if document is None:
        return ProfileRecord(user_id=user_id)
    return _decode(user_id, document)


def preferences(user_id: str) -> dict[str, Any]:
    """`user_id`'s preferences.

    Freshly decoded from the store on every call, so the dict handed back is
    the caller's own and mutating it reaches nothing. That is a property of
    having no cache, not of a defensive copy — a copy here would be dead code,
    and a test for one passes whether or not the copy is made.
    """
    return load(user_id).preferences


def user_ids() -> list[str]:
    """Every user id with a stored profile."""
    try:
        return _store.user_ids()
    except ProfilePersistenceError:
        raise
    except Exception as exc:
        raise ProfilePersistenceError(f"the profile store could not be listed: {exc}") from exc


def save(user_id: str, values: dict[str, Any]) -> ProfileRecord:
    """Persist `values` as `user_id`'s whole profile, returning what was read back.

    Raises `ProfilePersistenceError` when the store did not end up holding what
    was sent.
    """
    with _write_lock:
        stored = load(user_id)
        written = ProfileRecord(
            schema_version=SCHEMA_VERSION,
            user_id=user_id,
            revision=stored.revision + 1,
            updated_at=datetime.now(UTC),
            preferences=values,
        )
        _write(user_id, written.model_dump_json())
        return _read_back(user_id, written)


def set_field(user_id: str, field: str, value: Any) -> ProfileRecord:
    """Set one profile field, leaving the rest of the record alone."""
    if not field:
        raise ValueError("a profile field must be named")
    with _write_lock:
        values = load(user_id).preferences
        values[field] = value
        return save(user_id, values)


def delete_field(user_id: str, field: str) -> ProfileRecord:
    """Remove one profile field. Raises `KeyError` when it is not set."""
    if not field:
        raise ValueError("a profile field must be named")
    with _write_lock:
        values = load(user_id).preferences
        if field not in values:
            raise KeyError(field)
        del values[field]
        return save(user_id, values)


def delete(user_id: str) -> bool:
    """Remove `user_id`'s record entirely. Returns whether one was there.

    The record, not its contents. Saving `{}` would make "I deleted my profile"
    and "my profile is empty" the same stored state, and the first is a request
    the system has to be able to honour on user-authored, user-identifying
    content.
    """
    if not user_id:
        raise ValueError("a profile is addressed by a principal; user_id is empty")
    with _write_lock:
        existed = _read(user_id) is not None
        try:
            _store.remove(user_id)
        except Exception as exc:
            raise ProfilePersistenceError(
                f"the profile store refused the delete for {user_id!r}: {exc}"
            ) from exc
        if _read(user_id) is not None:
            raise ProfilePersistenceError(
                f"profile for {user_id!r} was still stored after the delete"
            )
        return existed


def _write(user_id: str, document: str) -> None:
    """Submit `document`, translating a store's own refusal into ours.

    `State.submit` raises a bare `RuntimeError` when the writer is closed or its
    queue is full. Left alone it crosses the service boundary unclassified and
    the route returns 500 instead of the 503 this surface documents for a
    storage failure — so it is wrapped here, at the seam, rather than caught
    wider up where it would swallow programming errors too.
    """
    try:
        _store.write(user_id, document)
    except ProfilePersistenceError:
        raise
    except Exception as exc:
        raise ProfilePersistenceError(
            f"the profile store refused the write for {user_id!r}: {exc}"
        ) from exc


def _read_back(user_id: str, written: ProfileRecord) -> ProfileRecord:
    """Confirm the store holds `written`, or refuse to acknowledge it.

    Compares the decoded record rather than the two JSON strings: a store is
    entitled to round-trip the document through its own serialisation, and a
    byte comparison would fail on key order while a record that genuinely
    disagreed on a value would be caught either way.
    """
    document = _read(user_id)
    if document is None:
        raise ProfilePersistenceError(
            f"profile write for {user_id!r} was not observed in the store afterwards; "
            "nothing is stored"
        )
    try:
        confirmed = _decode(user_id, document)
    except ProfileSchemaError as exc:
        raise ProfilePersistenceError(
            f"profile write for {user_id!r} read back unreadable: {exc}"
        ) from exc
    if confirmed.revision != written.revision or confirmed.preferences != written.preferences:
        raise ProfilePersistenceError(
            f"profile write for {user_id!r} read back different from what was sent "
            f"(revision {confirmed.revision}, expected {written.revision})"
        )
    return confirmed
