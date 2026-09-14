"""The Warden admission boundary for RSI-harvested content.

Harvested repository material is data, not trusted optimizer instructions.  This
module is the one reusable seam used before that material is sent to a model or
written to durable RSI learnings.  It deliberately scans a deterministic
serialization of the *whole* value: mapping keys are content too, as are path
names, nested values, diff text, and metadata.

The boundary only decides content admission.  Quarantine and promotion remain
separate gates owned by :mod:`maistro_rsi.quarantine` and the harvest command.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit, urlunsplit

from maistro.security._types import WardenVerdict
from maistro.security.warden.detector import Warden

logger = logging.getLogger("maistro.rsi.harvest")
_UNSET_WARDEN = object()

# Detector mechanisms are code-owned by ADR-073.  This identifier is audit
# metadata, not a user-configurable allow/deny policy.
WARDEN_POLICY_VERSION = "warden-rsi-harvest-v1"
HARVEST_BOUNDARY = "rsi_harvest_input"

AdmissionOutcome = Literal["admitted", "blocked", "warden_unavailable", "audit_unavailable"]
AuditSink = Callable[[dict[str, object]], object]


class JsonlAuditSink:
    """Small durable adapter for standalone RSI composition roots.

    The canonical application can supply ``event_store_audit_sink`` instead;
    standalone RSI runs have no application event store, so they must still
    persist admission evidence rather than relying on process logs.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, record: dict[str, object]) -> None:
        line = json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def event_store_audit_sink(event_store: Any) -> AuditSink:
    """Adapt the canonical EventStore without creating a second event authority."""

    async def record(admission: dict[str, object]) -> None:
        from maistro.events import EventEnvelope

        workspace_id = str(admission.get("workspace_id") or "")
        stream_scope = (
            ""
            if workspace_id
            else (f"rsi:{admission.get('campaign_id') or admission.get('run_id') or 'harvest'}")
        )
        correlation = str(admission.get("run_id") or admission.get("campaign_id") or "")
        event_type = (
            "security.violation"
            if not admission.get("admitted")
            else str(admission.get("event") or "rsi.harvest.warden_admission")
        )
        await event_store.append(
            EventEnvelope(
                type=event_type,
                payload=dict(admission),
                workspace_id=workspace_id,
                stream_scope=stream_scope,
                project_id=str(admission.get("project_id") or ""),
                run_id=str(admission.get("run_id") or ""),
                attempt_id=str(admission.get("attempt_id") or ""),
                correlation_id=correlation,
                source="maistro_rsi.harvest_boundary",
            )
        )

    return record


@dataclass(frozen=True)
class HarvestCorrelation:
    """Non-secret identifiers attached to one harvest admission decision."""

    workspace_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None
    attempt_id: str | None = None
    source_repository: str | None = None
    source_base: str | None = None
    source_head: str | None = None
    campaign_id: str | None = None
    candidate_id: str | None = None
    artifact_digest: str | None = None


@dataclass(frozen=True)
class HarvestAdmission:
    """A truthful, non-throwing result of a Warden admission attempt."""

    admitted: bool
    outcome: AdmissionOutcome
    digest: str
    verdict: WardenVerdict | None
    audit: dict[str, object]


class HarvestInputRefused(RuntimeError):
    """Raised when harvested content cannot be admitted to trusted context."""

    def __init__(self, result: HarvestAdmission) -> None:
        self.result = result
        super().__init__(f"RSI harvest content was not admitted ({result.outcome})")


def _safe_value(value: Any, active: set[int] | None = None) -> Any:
    """Convert arbitrary structured input without dropping keys or values."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    identity = id(value)
    if identity in active:
        return "<cycle>"
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            # Pair records preserve attacker-controlled keys without JSON key
            # coercion or collisions (for example, 1 versus "1").
            return {
                "__mapping__": [
                    {"key": _safe_value(key, active), "value": _safe_value(item, active)}
                    for key, item in value.items()
                ]
            }
        if isinstance(value, (str, bytes, bytearray)):
            return value.decode("utf-8", "replace") if not isinstance(value, str) else value
        if isinstance(value, Sequence | set | frozenset):
            return [
                _safe_value(item, active)
                for item in (
                    value if not isinstance(value, (set, frozenset)) else sorted(value, key=str)
                )
            ]
        if is_dataclass(value):
            return _safe_value(
                {field.name: getattr(value, field.name) for field in fields(value)}, active
            )
        if hasattr(value, "model_dump"):
            return _safe_value(value.model_dump(), active)
        if hasattr(value, "dict"):
            return _safe_value(value.dict(), active)
        return repr(value)
    finally:
        active.remove(identity)


def serialize_harvest_input(value: Any) -> str:
    """Serialize every semantically visible part of harvested input."""
    return json.dumps(_safe_value(value), ensure_ascii=False, sort_keys=True, default=str)


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_repository(value: str | None) -> str | None:
    """Keep repository identity while removing URL credentials and query data."""
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "<invalid-repository>"
    return value


def _correlation_payload(correlation: HarvestCorrelation, digest: str) -> dict[str, object]:
    data: dict[str, object] = {
        "workspace_id": correlation.workspace_id,
        "project_id": correlation.project_id,
        "run_id": correlation.run_id,
        "attempt_id": correlation.attempt_id,
        "source_repository": _safe_repository(correlation.source_repository),
        "source_base": correlation.source_base,
        "source_head": correlation.source_head,
        "campaign_id": correlation.campaign_id,
        "candidate_id": correlation.candidate_id,
        "artifact_digest": correlation.artifact_digest or digest,
    }
    return {key: value for key, value in data.items() if value is not None}


class WardenHarvestBoundary:
    """Fail-closed Warden admission for RSI harvested content."""

    def __init__(
        self,
        warden: Warden | None | object = _UNSET_WARDEN,
        *,
        correlation: HarvestCorrelation | None = None,
        audit_sink: AuditSink | None = None,
        event_store: Any | None = None,
        policy_version: str = WARDEN_POLICY_VERSION,
    ) -> None:
        if audit_sink is not None and event_store is not None:
            raise ValueError("provide audit_sink or event_store, not both")
        self._warden = Warden() if warden is _UNSET_WARDEN else cast(Warden | None, warden)
        self._correlation = correlation or HarvestCorrelation()
        self._audit_sink = audit_sink or (
            event_store_audit_sink(event_store) if event_store is not None else None
        )
        self._policy_version = policy_version

    async def scan(self, value: Any) -> HarvestAdmission:
        content = serialize_harvest_input(value)
        digest = _digest(content)
        verdict: WardenVerdict | None = None
        outcome: AdmissionOutcome = "admitted"
        if self._warden is None:
            outcome = "warden_unavailable"
        else:
            try:
                verdict = await self._warden.scan(content, boundary=HARVEST_BOUNDARY)
                if not verdict.clean:
                    outcome = "blocked"
            except Exception:
                # A scanner failure is not a clean verdict. Keep exception text
                # out of the audit record because providers can echo secrets.
                logger.warning("RSI harvest Warden unavailable; refusing content")
                outcome = "warden_unavailable"

        admitted = outcome == "admitted"
        audit = self._audit_record(outcome, admitted, digest, verdict)
        try:
            await self._record_audit_async(audit)
        except Exception:
            logger.warning("RSI harvest audit unavailable; refusing content")
            outcome = "audit_unavailable"
            admitted = False
            audit = self._audit_record(outcome, admitted, digest, verdict)
        return HarvestAdmission(admitted, outcome, digest, verdict, audit)

    async def admit(self, value: Any) -> str:
        """Scan input and return its serialized form only when admitted."""
        result = await self.scan(value)
        if not result.admitted:
            raise HarvestInputRefused(result)
        return serialize_harvest_input(value)

    def scan_sync(self, value: Any, *, allow_thread: bool = False) -> HarvestAdmission:
        """Synchronous adapter for the CLI and synchronous judge seams.

        Running inside an event loop cannot safely block it to execute the
        async Warden. That is an unavailable policy decision, not an allow-all
        fallback.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.scan(value))
        if allow_thread:
            # Synchronous RSI seams (the proposer and regression judge) can be
            # called from an async coordinator. Run the async Warden in an
            # isolated worker rather than turning a clean input into a refusal.
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, self.scan(value)).result()
        content = serialize_harvest_input(value)
        digest = _digest(content)
        audit = self._audit_record("warden_unavailable", False, digest, None)
        with contextlib.suppress(Exception):
            self._record_audit(audit)
        return HarvestAdmission(False, "warden_unavailable", digest, None, audit)

    def _audit_record(
        self,
        outcome: AdmissionOutcome,
        admitted: bool,
        digest: str,
        verdict: WardenVerdict | None,
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "event": "rsi.harvest.warden_admission",
            "boundary": HARVEST_BOUNDARY,
            "policy_version": self._policy_version,
            "outcome": outcome,
            "admitted": admitted,
            "content_digest": digest,
            "flags": list(verdict.flags) if verdict else [],
            "confidence": verdict.confidence if verdict else None,
        }
        record.update(_correlation_payload(self._correlation, digest))
        return record

    async def _record_audit_async(self, record: dict[str, object]) -> None:
        if self._audit_sink is not None:
            result = self._audit_sink(dict(record))
            if inspect.isawaitable(result):
                await result
            return
        logger.info("RSI harvest Warden admission", extra={"audit": record})

    def _record_audit(self, record: dict[str, object]) -> None:
        if self._audit_sink is not None:
            result = self._audit_sink(dict(record))
            if inspect.isawaitable(result):
                raise RuntimeError("async audit sinks require an async composition root")
            return
        logger.info("RSI harvest Warden admission", extra={"audit": record})


def _messages_for_scan(messages: Any, *, skip_system: bool) -> Any:
    if not skip_system or isinstance(messages, (str, bytes, bytearray)):
        return messages
    if isinstance(messages, Sequence):
        return [
            message
            for message in messages
            if not isinstance(message, Mapping) or message.get("role") != "system"
        ]
    return messages


class WardenGuardedCallable:
    """Protect a synchronous model callable before it sees harvested context."""

    def __init__(
        self,
        inner: Callable[..., Any],
        boundary: WardenHarvestBoundary,
        *,
        skip_system: bool = False,
        allow_thread: bool = True,
    ) -> None:
        self._inner = inner
        self._boundary = boundary
        self._skip_system = skip_system
        self._allow_thread = allow_thread

    def __call__(self, messages: Any, **kwargs: Any) -> Any:
        # The tool schemas are also model-visible structured input. Include
        # them with the transcript so a hostile tool name/description or key
        # cannot hide outside the scanned message content.
        payload = {
            "messages": _messages_for_scan(messages, skip_system=self._skip_system),
            "call_kwargs": kwargs,
        }
        result = self._boundary.scan_sync(payload, allow_thread=self._allow_thread)
        if not result.admitted:
            raise HarvestInputRefused(result)
        return self._inner(messages, **kwargs)


async def guarded_async_call(
    inner: Callable[..., Any],
    messages: Any,
    boundary: WardenHarvestBoundary,
    *,
    skip_system: bool = False,
    **kwargs: Any,
) -> Any:
    """Scan model messages before invoking an async model callable."""
    payload = {
        "messages": _messages_for_scan(messages, skip_system=skip_system),
        "call_kwargs": kwargs,
    }
    result = await boundary.scan(payload)
    if not result.admitted:
        raise HarvestInputRefused(result)
    return await inner(messages, **kwargs)


__all__ = [
    "HARVEST_BOUNDARY",
    "WARDEN_POLICY_VERSION",
    "HarvestAdmission",
    "HarvestCorrelation",
    "HarvestInputRefused",
    "JsonlAuditSink",
    "WardenGuardedCallable",
    "WardenHarvestBoundary",
    "event_store_audit_sink",
    "guarded_async_call",
    "serialize_harvest_input",
]
