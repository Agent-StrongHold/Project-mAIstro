"""Durable Conductor settings — SPEC-082926-0b72, ADR-082926-0b72.

`stores.settings` used to be a module-level `SettingsModel` that nothing wrote
anywhere. Four surfaces rebound or mutated it and returned `200`; every one of
those writes was discarded at restart (#334).

Attaching `PersistedStore` alone would not have closed that. `PersistedStore.put`
enqueues a closure for `State`'s writer thread and returns, and
`State._writer_loop` swallows every exception that closure raises — so an
acknowledgement issued after `put` still precedes, and survives, the failure.

So a write here is acknowledged only after it has been **read back** from the
authoritative store and compared to what was sent. Everything else in this
module exists to keep that guarantee true: the envelope so a schema change
cannot silently drop fields, the revision so a concurrent edit is refused rather
than lost, the secret scan so credentials never enter a record designed to be
read back and returned, and the overlay so deliberately volatile values have
somewhere to live that is not the record.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from models.schemas import SettingsModel
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("hive.settings_store")

#: One namespace, one key: settings are a single document, not a collection.
STORE_NAME = "conductor_settings"
RECORD_KEY = "current"

#: The envelope shape this build writes and is willing to read. A stored record
#: above this refuses to load rather than being coerced — see `_decode`.
SCHEMA_VERSION = 1

#: Credential detectors from the shared PII filter. Deliberately not every type
#: it knows: an operator's settings may legitimately carry an email address or
#: the IP of their own host, and refusing those would make the guard something
#: people route around. These nine are secret material by construction.
CREDENTIAL_TYPES = frozenset(
    {
        "api_key",
        "aws_key",
        "bearer_token",
        "connection_string",
        "github_token",
        "gitlab_token",
        "jwt",
        "password",
        "private_key",
    }
)


class SettingsPersistenceError(RuntimeError):
    """A write was not observed in the store afterwards.

    Raised for a write that did not land, a read-back that disagreed with what
    was sent, and a drain that timed out. All three mean the same thing to a
    caller: do not tell anyone this succeeded.
    """


class SettingsConflictError(RuntimeError):
    """A write declared a revision the store has already moved past."""

    def __init__(self, expected: int, current: SettingsRecord) -> None:
        super().__init__(f"settings revision {expected} is stale; store holds {current.revision}")
        self.expected = expected
        self.current = current


class SettingsSecretError(ValueError):
    """A settings value carried secret material.

    Carries the field name and the detected credential type — never the value.
    A rejection that echoes the secret is itself a disclosure, and this one is
    logged and returned over HTTP.
    """

    def __init__(self, field: str, credential_type: str) -> None:
        super().__init__(f"settings field {field!r} carries {credential_type} material")
        self.field = field
        self.credential_type = credential_type


class SettingsSchemaError(RuntimeError):
    """A stored record cannot be read at this build's schema version."""


class SettingsRecord(BaseModel):
    """The stored envelope. `values` is the payload; everything else is about it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    revision: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    values: SettingsModel


class SettingsRecordStore(Protocol):
    """The durability seam.

    Two implementations ship: one over `PersistedStore`, one in-process. Tests
    add a third that accepts writes and does not keep them, which is the only
    way to exercise the acknowledgement rule from the outside.
    """

    @property
    def durable(self) -> bool:
        """Whether a write here is expected to survive the process."""

    def read(self) -> str | None:
        """The stored JSON document, or None when nothing is stored."""

    def write(self, document: str) -> None:
        """Submit `document` and return once it is as durable as this store gets."""


class EphemeralSettingsRecordStore:
    """In-process record store, labelled as such.

    The Conductor runs without a state database in tests and in `memory://`
    deployments. Those runs still go through the whole write-and-read-back path,
    so the acknowledgement rule is exercised uniformly — but `durable` is False
    and the API says so, rather than letting an in-memory write wear the shape
    of a durable one. (#333 owns making the *choice* of this mode explicit; this
    only makes the resulting state legible.)
    """

    def __init__(self) -> None:
        self._document: str | None = None

    @property
    def durable(self) -> bool:
        return False

    def read(self) -> str | None:
        return self._document

    def write(self, document: str) -> None:
        self._document = document


class PersistedSettingsRecordStore:
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

    def read(self) -> str | None:
        document = self._persisted.get_raw(STORE_NAME, RECORD_KEY)
        return str(document) if document is not None else None

    def write(self, document: str) -> None:
        self._persisted.put_raw(STORE_NAME, RECORD_KEY, document)
        self._flush(timeout=self._timeout)


#: `save` is read-modify-write across three steps — load, compare the revision,
#: write, read back — and two requests interleaving inside it both pass the
#: revision check and both write, so the second is never refused with the 409
#: the API promises (Codex, #334). One lock makes the sequence atomic.
#:
#: Per process, which is the right boundary and not an accident: SPEC-010's
#: State holds exactly one write-mode connection for the conductor's lifetime,
#: so a second process writing this database is already outside the model. A
#: deployment that ever runs two writers needs a store-level compare-and-swap,
#: and would need one for every other store too.
_save_lock = threading.Lock()

_store: SettingsRecordStore = EphemeralSettingsRecordStore()
_cache: SettingsRecord | None = None
_preview: dict[str, Any] = {}


def configure(store: SettingsRecordStore) -> None:
    """Install the record store and drop the cache. Called once, at startup."""
    global _store, _cache
    _store = store
    _cache = None


def reset(*, store: SettingsRecordStore | None = None) -> None:
    """Return the module to a fresh state. For tests and for re-initialisation."""
    global _store, _cache
    _store = store if store is not None else EphemeralSettingsRecordStore()
    _cache = None
    _preview.clear()


def durable() -> bool:
    """Whether the configured store is expected to outlive the process."""
    return _store.durable


def _decode(document: str) -> SettingsRecord:
    """Parse a stored document, migrating forward and refusing forward versions.

    Read as raw JSON before validation on purpose. `SettingsRecord` forbids
    extra fields, so a record written by a newer build would fail validation
    with a message about an unknown key rather than about the version — and a
    model that *ignored* extras would drop those fields on the next write,
    turning a downgrade into data loss with nothing to see.
    """
    try:
        raw = json.loads(document)
    except json.JSONDecodeError as exc:
        raise SettingsSchemaError(f"stored settings are not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsSchemaError("stored settings are not an object")

    version = raw.get("schema_version", 0)
    if not isinstance(version, int):
        raise SettingsSchemaError(
            f"stored settings carry a non-integer schema version: {version!r}"
        )
    if version > SCHEMA_VERSION:
        raise SettingsSchemaError(
            f"stored settings are at schema version {version}; this build reads "
            f"{SCHEMA_VERSION} and will not coerce a newer record"
        )
    raw = _migrate(raw, version)
    try:
        return SettingsRecord.model_validate(raw)
    except ValueError as exc:
        raise SettingsSchemaError(f"stored settings failed validation: {exc}") from exc


def _migrate(raw: dict[str, Any], version: int) -> dict[str, Any]:
    """Bring an older envelope up to `SCHEMA_VERSION`.

    Version 0 is the pre-envelope shape: a bare `SettingsModel` document with no
    wrapper at all. Nothing in a released build wrote one, but a record written
    by a branch that landed before the envelope did would look exactly like it,
    and reading it as an envelope with a missing payload would lose the settings
    it holds.
    """
    if version >= SCHEMA_VERSION:
        return raw
    if version == 0:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": 0,
            "updated_at": datetime.now(UTC).isoformat(),
            "values": raw,
        }
    raw["schema_version"] = SCHEMA_VERSION  # pragma: no cover - no such version yet
    return raw


def load() -> SettingsRecord:
    """Read the record from the store, seeding defaults when nothing is stored.

    Seeding does not write. A read must not create a record, or a single `GET`
    against a read-only or failing store would report a success it never had.
    """
    global _cache
    document = _store.read()
    if document is None:
        from settings_defaults import default_settings

        _cache = SettingsRecord(values=default_settings())
        return _cache
    _cache = _decode(document)
    return _cache


def record() -> SettingsRecord:
    """The current record, loading it on first use."""
    if _cache is None:
        return load()
    return _cache


def current() -> SettingsModel:
    """The current settings payload, as a copy.

    A copy because `routes/setup.py` demonstrated the alternative: it assigned
    `stores.settings.default_model` in place, which no write-through wrapper
    could have seen. Handing out a copy makes that mistake inert instead of
    silent.
    """
    return record().values.model_copy(deep=True)


def save(values: SettingsModel, *, expected_revision: int | None = None) -> SettingsRecord:
    """Persist `values` and return the record read back from the store.

    Raises `SettingsSecretError` for credential material, `SettingsConflictError`
    for a stale `expected_revision`, and `SettingsPersistenceError` when the
    store did not end up holding what was sent.
    """
    reject_secret_material(values)

    with _save_lock:
        stored = load()
        if expected_revision is not None and expected_revision != stored.revision:
            raise SettingsConflictError(expected_revision, stored)

        written = SettingsRecord(
            schema_version=SCHEMA_VERSION,
            revision=stored.revision + 1,
            updated_at=datetime.now(UTC),
            values=values,
        )
        _write(written.model_dump_json())

        confirmed = _read_back(written)
        global _cache
        _cache = confirmed
        return confirmed


def _write(document: str) -> None:
    """Submit `document`, translating a store's own refusal into ours.

    `State.submit` raises a bare `RuntimeError` when the writer is closed or its
    queue is full. Left alone it crosses the service boundary unclassified and
    the route returns 500 instead of the 503 this surface documents for a
    storage failure (Codex, #334) — so it is wrapped here, at the seam, rather
    than caught wider up where it would swallow programming errors too.
    """
    try:
        _store.write(document)
    except SettingsPersistenceError:
        raise
    except Exception as exc:
        raise SettingsPersistenceError(f"the settings store refused the write: {exc}") from exc


def _read_back(written: SettingsRecord) -> SettingsRecord:
    """Confirm the store holds `written`, or refuse to acknowledge it.

    Compares the decoded record rather than the two JSON strings: a store is
    entitled to round-trip the document through its own serialisation, and a
    byte comparison would fail on key order while a record that genuinely
    disagreed on a value would be caught either way.
    """
    document = _store.read()
    if document is None:
        raise SettingsPersistenceError(
            "settings write was not observed in the store afterwards; nothing is stored"
        )
    try:
        confirmed = _decode(document)
    except SettingsSchemaError as exc:
        raise SettingsPersistenceError(f"settings write read back unreadable: {exc}") from exc
    if confirmed.revision != written.revision or confirmed.values != written.values:
        raise SettingsPersistenceError(
            "settings write read back different from what was sent "
            f"(revision {confirmed.revision}, expected {written.revision})"
        )
    return confirmed


def reject_secret_material(values: SettingsModel) -> None:
    """Refuse a payload carrying credentials. Secrets belong in the vault (SPEC-011).

    Each field is scanned on its own so the rejection can name one, and only
    scalar leaves are scanned — a container's `repr` would introduce quotes and
    separators that the `api_key`/`password` detectors read as assignment
    syntax, inventing findings out of punctuation.
    """
    from maistro.security.sentinel.pii_filter import scan_for_pii

    for field, value in _scalar_leaves(values.model_dump(mode="json")):
        for match in scan_for_pii(value):
            if match.pii_type in CREDENTIAL_TYPES:
                raise SettingsSecretError(field, match.pii_type)


def _scalar_leaves(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Every string leaf in `payload`, paired with its dotted path."""
    if isinstance(payload, str):
        return [(prefix or "<root>", payload)]
    if isinstance(payload, dict):
        leaves: list[tuple[str, str]] = []
        for key, value in payload.items():
            leaves.extend(_scalar_leaves(value, f"{prefix}.{key}" if prefix else str(key)))
        return leaves
    if isinstance(payload, list):
        leaves = []
        for index, value in enumerate(payload):
            leaves.extend(_scalar_leaves(value, f"{prefix}[{index}]"))
        return leaves
    return []


def preview() -> dict[str, Any]:
    """The volatile overlay: deliberately in-process, never part of the record."""
    return dict(_preview)


def set_preview(overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge `overrides` into the volatile overlay and return it."""
    _preview.update(overrides)
    return dict(_preview)


def clear_preview() -> dict[str, Any]:
    """Drop every volatile override. The durable record is not consulted."""
    _preview.clear()
    return {}
