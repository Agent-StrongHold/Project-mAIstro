"""Durable SQLite twin of the extension health/telemetry store (M9-I3, #978).

Same convention as ``extensions/sqlite_store.py``: an injected ``aiosqlite``
connection, plain typed columns for everything that filters or orders, a
JSON payload column each record round-trips through, and an ``ensure_schema``
that runs through the shared ``serialized_schema_upgrade`` discipline. One
connection, one operation lock.

Two tables, both append-only — no ``UPDATE``, no ``DELETE``:

* ``extension_health_events`` — one row per host-recorded invocation
  observation or classified error. ``version`` is stored verbatim from the
  record, so telemetry written by a version that is later upgraded or
  removed stays attributable to that exact version; the scope's active
  pointer decides what reports active, never the telemetry row.
* ``extension_operator_states`` — one row per operator decision
  (enable/disable/quarantine/release) with actor and reason. Decisions are
  never overwritten; the newest row per extension *is* the durable state.
  This is what makes a quarantine or a disable survive a restart, and what
  keeps "who held this, why, when" answerable afterwards.

Retention is declared in ``quality/durable-table-retention.json`` as
``indefinite_by_decision`` (issue #978): health evidence and operator
history are the audit trail the M9-I epic requires to stay interpretable
after upgrades and removals, so no purge path exists by design.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING, cast

from maistro.extensions.health import (
    ExtensionErrorKind,
    ExtensionErrorRecord,
    ExtensionObservation,
    ExtensionOperatorAction,
    ExtensionOperatorState,
    ObservationOutcome,
    OperatorDecision,
)
from maistro.extensions.types import ExtensionScope
from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extension_health_events (
    event_seq INTEGER PRIMARY KEY,
    org_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    extension_id TEXT NOT NULL,
    version TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    error_kind TEXT,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""

_EVENTS_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_extension_health_events_scope
    ON extension_health_events (org_id, workspace_id, extension_id, event_seq)
"""

_DECISIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS extension_operator_states (
    org_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    extension_id TEXT NOT NULL,
    decision_seq INTEGER NOT NULL,
    action TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (org_id, workspace_id, extension_id, decision_seq)
)
"""

_OBSERVATION = "observation"
_ERROR = "error"


def _datetime_field(value: datetime) -> str:
    """Serialize an evidence timestamp, refusing timezone-naive datetimes.

    Durable evidence must round-trip its instant exactly; a naive datetime
    would read back as a different moment depending on the reader's
    assumptions, so it is refused at the write instead.
    """
    if value.tzinfo is None:
        raise ValueError(
            "health evidence datetime must be timezone-aware; "
            "a naive timestamp cannot round-trip its instant"
        )
    return value.isoformat()


def _datetime_value(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(
            f"health evidence datetime {value!r} is timezone-naive; "
            "durable evidence must round-trip its instant exactly"
        )
    return parsed


def observation_payload(observation: ExtensionObservation) -> str:
    """Serialize one observation for the durable payload column."""
    payload: dict[str, object] = {
        "observation_id": observation.observation_id,
        "at": _datetime_field(observation.at),
        "org_id": observation.org_id,
        "workspace_id": observation.workspace_id,
        "extension_id": observation.extension_id,
        "version": observation.version,
        "latency_ms": observation.latency_ms,
        "outcome": observation.outcome.value,
        "cost_units": observation.cost_units,
        "error": (_error_dict(observation.error) if observation.error is not None else None),
    }
    return json.dumps(payload, sort_keys=True)


def _error_dict(error: ExtensionErrorRecord) -> dict[str, object]:
    return {
        "error_id": error.error_id,
        "at": _datetime_field(error.at),
        "org_id": error.org_id,
        "workspace_id": error.workspace_id,
        "extension_id": error.extension_id,
        "version": error.version,
        "kind": error.kind.value,
        "code": error.code,
        "message": error.message,
        "dependency": error.dependency,
        "dependency_version": error.dependency_version,
    }


def _error_from_dict(payload: dict[str, object]) -> ExtensionErrorRecord:
    dependency = cast("str | None", payload["dependency"])
    dependency_version = cast("str | None", payload["dependency_version"])
    return ExtensionErrorRecord(
        error_id=cast("str", payload["error_id"]),
        at=_datetime_value(cast("str", payload["at"])),
        org_id=cast("str", payload["org_id"]),
        workspace_id=cast("str", payload["workspace_id"]),
        extension_id=cast("str", payload["extension_id"]),
        version=cast("str", payload["version"]),
        kind=ExtensionErrorKind(cast("str", payload["kind"])),
        code=cast("str", payload["code"]),
        message=cast("str", payload["message"]),
        dependency=dependency,
        dependency_version=dependency_version,
    )


def observation_from_payload(raw: str) -> ExtensionObservation:
    """Rebuild one observation from its durable payload, failing closed.

    Every enumerated field is re-validated through its StrEnum, so a
    corrupted or forged payload value raises instead of projecting as a
    plausible-but-wrong outcome or error kind.
    """
    payload = json.loads(raw)
    error_raw = payload.get("error")
    error = _error_from_dict(error_raw) if error_raw is not None else None
    return ExtensionObservation(
        observation_id=cast("str", payload["observation_id"]),
        at=_datetime_value(cast("str", payload["at"])),
        org_id=cast("str", payload["org_id"]),
        workspace_id=cast("str", payload["workspace_id"]),
        extension_id=cast("str", payload["extension_id"]),
        version=cast("str", payload["version"]),
        latency_ms=cast("float", payload["latency_ms"]),
        outcome=ObservationOutcome(cast("str", payload["outcome"])),
        cost_units=cast("float | None", payload["cost_units"]),
        error=error,
    )


def decision_payload(decision: OperatorDecision) -> str:
    """Serialize one operator decision for the durable payload column."""
    return json.dumps(
        {
            "decision_id": decision.decision_id,
            "at": _datetime_field(decision.at),
            "org_id": decision.org_id,
            "workspace_id": decision.workspace_id,
            "extension_id": decision.extension_id,
            "action": decision.action.value,
            "state": decision.state.value,
            "actor": decision.actor,
            "reason": decision.reason,
        },
        sort_keys=True,
    )


def decision_from_payload(raw: str) -> OperatorDecision:
    """Rebuild one operator decision from its durable payload."""
    payload = json.loads(raw)
    return OperatorDecision(
        decision_id=cast("str", payload["decision_id"]),
        at=_datetime_value(cast("str", payload["at"])),
        org_id=cast("str", payload["org_id"]),
        workspace_id=cast("str", payload["workspace_id"]),
        extension_id=cast("str", payload["extension_id"]),
        action=ExtensionOperatorAction(cast("str", payload["action"])),
        state=ExtensionOperatorState(cast("str", payload["state"])),
        actor=cast("str", payload["actor"]),
        reason=cast("str", payload["reason"]),
    )


class SqliteExtensionHealthStore:
    """The restart-surviving twin. Must agree with
    :class:`maistro.extensions.health.InMemoryExtensionHealthStore` on every
    rule the health-store conformance suite exercises."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the tables; safe to call concurrently and repeatedly."""
        async with self._lock, serialized_schema_upgrade(self._conn):
            for script in (_SCHEMA, _EVENTS_INDEX_SCHEMA, _DECISIONS_SCHEMA):
                await self._conn.execute(script)
            await self._conn.commit()

    async def append_observation(self, observation: ExtensionObservation) -> None:
        async with self._lock:
            event_seq = await self._next_event_seq()
            await self._conn.execute(
                "INSERT INTO extension_health_events "
                "(event_seq, org_id, workspace_id, extension_id, version, "
                " event_kind, error_kind, occurred_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_seq,
                    observation.org_id,
                    observation.workspace_id,
                    observation.extension_id,
                    observation.version,
                    _OBSERVATION,
                    None,
                    _datetime_field(observation.at),
                    observation_payload(observation),
                ),
            )
            if observation.error is not None:
                await self._insert_error(observation.error, event_seq + 1)
            await self._conn.commit()

    async def append_error(self, error: ExtensionErrorRecord) -> None:
        async with self._lock:
            event_seq = await self._next_event_seq()
            await self._insert_error(error, event_seq)
            await self._conn.commit()

    async def _insert_error(self, error: ExtensionErrorRecord, event_seq: int) -> None:
        """Insert one error row; caller holds the lock and commits."""
        await self._conn.execute(
            "INSERT INTO extension_health_events "
            "(event_seq, org_id, workspace_id, extension_id, version, "
            " event_kind, error_kind, occurred_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_seq,
                error.org_id,
                error.workspace_id,
                error.extension_id,
                error.version,
                _ERROR,
                error.kind.value,
                _datetime_field(error.at),
                json.dumps(_error_dict(error), sort_keys=True),
            ),
        )

    async def _next_event_seq(self) -> int:
        """One past the current maximum event_seq (caller holds the lock)."""
        cursor = await self._conn.execute("SELECT MAX(event_seq) FROM extension_health_events")
        row = await cursor.fetchone()
        return int(row[0]) + 1 if row is not None and row[0] is not None else 1

    async def observations(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        version: str | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionObservation, ...]:
        rows = await self._event_rows(
            scope,
            event_kind=_OBSERVATION,
            extension_id=extension_id,
            version=version,
            limit=limit,
        )
        return tuple(observation_from_payload(payload) for payload in rows)

    async def errors(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        version: str | None = None,
        kind: ExtensionErrorKind | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionErrorRecord, ...]:
        rows = await self._event_rows(
            scope,
            event_kind=_ERROR,
            extension_id=extension_id,
            version=version,
            kind=kind,
            limit=limit,
        )
        return tuple(_error_from_dict(json.loads(payload)) for payload in rows)

    async def _event_rows(
        self,
        scope: ExtensionScope,
        *,
        event_kind: str,
        extension_id: str | None = None,
        version: str | None = None,
        kind: ExtensionErrorKind | None = None,
        limit: int | None = None,
    ) -> list[str]:
        """Matching event payloads, oldest first, newest ``limit`` rows.

        A limit selects the *newest* rows, matching the in-memory twin's
        ``rows[-limit:]`` slice; the DESC scan is reversed before returning.
        """
        clauses = ["org_id = ?", "workspace_id = ?", "event_kind = ?"]
        parameters: list[object] = [scope.org_id, scope.workspace_id, event_kind]
        if extension_id is not None:
            clauses.append("extension_id = ?")
            parameters.append(extension_id)
        if version is not None:
            clauses.append("version = ?")
            parameters.append(version)
        if kind is not None:
            clauses.append("error_kind = ?")
            parameters.append(kind.value)
        query = (
            "SELECT payload FROM extension_health_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY event_seq DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(int(limit))
        async with self._lock:
            cursor = await self._conn.execute(query, parameters)
            rows = list(await cursor.fetchall())
        # DESC scan selected the newest rows; flip back to oldest-first so
        # the read matches the in-memory twin's rows[-limit:] slice.
        rows.reverse()
        return [str(row[0]) for row in rows]

    async def append_decision(self, decision: OperatorDecision) -> None:
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT MAX(decision_seq) FROM extension_operator_states "
                "WHERE org_id = ? AND workspace_id = ? AND extension_id = ?",
                (decision.org_id, decision.workspace_id, decision.extension_id),
            )
            row = await cursor.fetchone()
            decision_seq = int(row[0]) + 1 if row is not None and row[0] is not None else 1
            await self._conn.execute(
                "INSERT INTO extension_operator_states "
                "(org_id, workspace_id, extension_id, decision_seq, action, applied_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.org_id,
                    decision.workspace_id,
                    decision.extension_id,
                    decision_seq,
                    decision.action.value,
                    _datetime_field(decision.at),
                    decision_payload(decision),
                ),
            )
            await self._conn.commit()

    async def decisions(
        self, scope: ExtensionScope, extension_id: str | None = None
    ) -> tuple[OperatorDecision, ...]:
        clauses = ["org_id = ?", "workspace_id = ?"]
        parameters: list[object] = [scope.org_id, scope.workspace_id]
        if extension_id is not None:
            clauses.append("extension_id = ?")
            parameters.append(extension_id)
        query = (
            "SELECT payload FROM extension_operator_states WHERE "
            + " AND ".join(clauses)
            + " ORDER BY extension_id, decision_seq"
        )
        async with self._lock:
            cursor = await self._conn.execute(query, parameters)
            rows = await cursor.fetchall()
        return tuple(decision_from_payload(str(row[0])) for row in rows)
