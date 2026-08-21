"""Replay event model, record store, and tier routing (ADR-055 / SPEC-070226-2b70).

A ``ReplayEvent`` is written for every LLM/tool call flowing through the recording
proxies (``maistro.observability.proxy``). The ``RecordStore`` routes payloads by
:class:`~maistro.observability.tiers.SensitivityTier`:

- ``normal``: full payload stored as-is.
- ``sensitive``: payload encrypted with an injected encryptor callable (the SPEC's
  KMS column, realised as a protocol so products can wire real KMS); reads go
  through :meth:`RecordStore.read_sensitive_payload` and write an access-audit row.
- ``secret``: hash + metadata only — payload bytes are never stored anywhere.

``ReplaySession`` serves recorded responses back to the proxies in replay mode,
matching each call by ``(seq, request_hash)`` and raising
:class:`ReplayDivergenceError` on mismatch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from maistro.observability.tiers import SensitivityTier


def canonical_request_hash(args: dict[str, Any]) -> str:
    """SHA-256 of the canonicalised (sorted-key, compact JSON) request args."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplayEvent:
    """One recorded LLM or tool call."""

    trace_id: str
    span_id: str
    seq: int  # monotonic per trace — replay ordering key
    kind: Literal["llm", "tool"]
    request_hash: str  # sha256 of canonicalised args
    payload: dict[str, Any] | None  # None for secret tier (and sealed sensitive)
    tier: SensitivityTier


@dataclass(frozen=True)
class AccessAuditRecord:
    """One read of a sealed (sensitive-tier) payload."""

    trace_id: str
    seq: int
    accessor: str
    reason: str
    accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ObservabilityRecordError(Exception):
    """Base class for record/replay errors."""


class RecordWriteError(ObservabilityRecordError):
    """A sensitive/secret-tier record could not be persisted within budget."""


class SealedAccessError(ObservabilityRecordError):
    """A sealed payload read was rejected or the record does not exist."""


class ReplayPayloadUnavailableError(ObservabilityRecordError):
    """Replay reached an event whose payload was never persisted (secret tier)."""


class ReplayDivergenceError(ObservabilityRecordError):
    """The live request diverged from the recorded one at a replay position."""

    def __init__(
        self,
        seq: int,
        recorded_hash: str | None,
        attempted_hash: str,
        detail: str = "",
    ) -> None:
        self.seq = seq
        self.recorded_hash = recorded_hash
        self.attempted_hash = attempted_hash
        message = (
            f"replay diverged at seq={seq}: recorded request_hash="
            f"{recorded_hash or '<none — trace exhausted>'} vs attempted "
            f"request_hash={attempted_hash}"
        )
        if detail:
            message += f" ({detail})"
        super().__init__(message)


class RecordStore(Protocol):
    """Storage for replay events with tier routing.

    The SPEC's Postgres schema (``tier``/``payload_encrypted``/``payload_hash``
    columns + ``sealed_access_audit`` table) is realised as this protocol; the
    in-memory implementation below is the reference. A Postgres implementation
    plugs in behind the same interface.
    """

    async def record(self, event: ReplayEvent) -> None:
        """Persist an event, routing its payload by tier."""
        ...

    async def events_for_trace(self, trace_id: str) -> list[ReplayEvent]:
        """Return the trace's events in ``seq`` order (sealed payloads elided)."""
        ...

    async def read_sensitive_payload(
        self, trace_id: str, seq: int, accessor: str, reason: str
    ) -> dict[str, Any]:
        """Decrypt and return a sealed payload; writes an access-audit row."""
        ...


class InMemoryRecordStore:
    """Reference :class:`RecordStore` with tier routing.

    Args:
        encryptor / decryptor: injected callables standing in for the KMS
            envelope (``bytes -> bytes``). Defaults are identity functions.
    """

    def __init__(
        self,
        encryptor: Callable[[bytes], bytes] | None = None,
        decryptor: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._encryptor = encryptor or (lambda b: b)
        self._decryptor = decryptor or (lambda b: b)
        self._events: dict[str, list[ReplayEvent]] = {}
        self._sealed: dict[tuple[str, int], bytes] = {}
        self._audit: list[AccessAuditRecord] = []
        self._lock = asyncio.Lock()

    @property
    def access_audit(self) -> list[AccessAuditRecord]:
        return list(self._audit)

    async def record(self, event: ReplayEvent) -> None:
        stored = event
        if event.tier is SensitivityTier.SENSITIVE:
            if event.payload is not None:
                plaintext = json.dumps(event.payload, default=str).encode("utf-8")
                ciphertext = self._encryptor(plaintext)
                self._sealed[(event.trace_id, event.seq)] = ciphertext
            stored = replace(event, payload=None)
        elif event.tier is SensitivityTier.SECRET:
            # Hash + metadata only — payload bytes are never stored.
            stored = replace(event, payload=None)
        async with self._lock:
            self._events.setdefault(event.trace_id, []).append(stored)

    async def events_for_trace(self, trace_id: str) -> list[ReplayEvent]:
        async with self._lock:
            events = list(self._events.get(trace_id, []))
        return sorted(events, key=lambda e: e.seq)

    async def read_sensitive_payload(
        self, trace_id: str, seq: int, accessor: str, reason: str
    ) -> dict[str, Any]:
        ciphertext = self._sealed.get((trace_id, seq))
        if ciphertext is None:
            raise SealedAccessError(f"no sealed payload for trace={trace_id} seq={seq}")
        self._audit.append(
            AccessAuditRecord(trace_id=trace_id, seq=seq, accessor=accessor, reason=reason)
        )
        plaintext = self._decryptor(ciphertext)
        result: dict[str, Any] = json.loads(plaintext.decode("utf-8"))
        return result


class ReplaySession:
    """Serves a recorded trace back to the proxies, in original ``seq`` order.

    Shared by the LLM and tool proxies of one replay run so the per-trace
    monotonic cursor spans both kinds.
    """

    def __init__(self, store: RecordStore, trace_id: str, accessor: str = "replay") -> None:
        self._store = store
        self.trace_id = trace_id
        self._accessor = accessor
        self._events: list[ReplayEvent] | None = None
        self._cursor = 0
        self._lock = asyncio.Lock()

    async def _load(self) -> list[ReplayEvent]:
        if self._events is None:
            self._events = await self._store.events_for_trace(self.trace_id)
        return self._events

    async def next_response(
        self, kind: Literal["llm", "tool"], args: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the recorded response for the next call in the trace.

        Raises :class:`ReplayDivergenceError` when the live call's kind or
        canonical request hash differs from the recorded event at this position.
        """
        attempted_hash = canonical_request_hash(args)
        async with self._lock:
            events = await self._load()
            if self._cursor >= len(events):
                raise ReplayDivergenceError(
                    seq=self._cursor,
                    recorded_hash=None,
                    attempted_hash=attempted_hash,
                    detail="more live calls than recorded events",
                )
            event = events[self._cursor]
            if event.kind != kind:
                raise ReplayDivergenceError(
                    seq=event.seq,
                    recorded_hash=event.request_hash,
                    attempted_hash=attempted_hash,
                    detail=f"recorded kind={event.kind!r}, attempted kind={kind!r}",
                )
            if event.request_hash != attempted_hash:
                raise ReplayDivergenceError(
                    seq=event.seq,
                    recorded_hash=event.request_hash,
                    attempted_hash=attempted_hash,
                )
            self._cursor += 1

        if event.tier is SensitivityTier.SECRET:
            raise ReplayPayloadUnavailableError(
                f"seq={event.seq} is secret-tier: payload was never persisted"
            )
        if event.tier is SensitivityTier.SENSITIVE:
            payload = await self._store.read_sensitive_payload(
                self.trace_id, event.seq, accessor=self._accessor, reason="replay"
            )
        else:
            payload = event.payload or {}
        response = payload.get("response")
        if not isinstance(response, dict):
            raise ReplayPayloadUnavailableError(
                f"seq={event.seq}: recorded payload has no response"
            )
        return response


__all__ = [
    "AccessAuditRecord",
    "InMemoryRecordStore",
    "ObservabilityRecordError",
    "RecordStore",
    "RecordWriteError",
    "ReplayDivergenceError",
    "ReplayEvent",
    "ReplayPayloadUnavailableError",
    "ReplaySession",
    "SealedAccessError",
    "canonical_request_hash",
]
