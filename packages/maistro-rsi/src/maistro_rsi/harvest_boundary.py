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


def event_store_audit_sink(event_store: Any, envelope_factory: Any) -> AuditSink:
    """Adapt the canonical EventStore without creating a second event authority.

    The envelope constructor is injected instead of imported: a static import
    of ``maistro.events`` here would put the whole canonical events package
    inside the promotion-path import closure that the containment gate
    (scripts/check-promotion-surface.py) walks, forcing every events module
    onto the RSI containment surface. The canonical composition root sits
    outside that closure and passes ``EventEnvelope`` freely; the boundary
    stays events-agnostic and the store keeps its single event authority.
    """

    async def record(admission: dict[str, object]) -> None:
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
            envelope_factory(
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
    """Fail-closed Warden admission for RSI harvested content.

    Truthfulness rule for the synchronous in-loop seam: an admission whose
    durable audit evidence cannot be confirmed before ``scan_sync`` returns
    (an async audit sink on a live event loop) is reported as
    ``audit_unavailable`` — never as a ``warden_unavailable`` refusal that
    implies a durable record exists while none was written. The scheduled
    delivery keeps the scan-level reason in ``scan_outcome`` and retries a
    corrected record once when the write fails, so transient sink failures
    still persist the truthful not-admitted outcome.
    """

    def __init__(
        self,
        warden: Warden | None | object = _UNSET_WARDEN,
        *,
        correlation: HarvestCorrelation | None = None,
        audit_sink: AuditSink | None = None,
        event_store: Any | None = None,
        envelope_factory: Any | None = None,
        policy_version: str = WARDEN_POLICY_VERSION,
    ) -> None:
        if audit_sink is not None and event_store is not None:
            raise ValueError("provide audit_sink or event_store, not both")
        if event_store is not None and envelope_factory is None:
            # Fail closed rather than silently dropping durable admission
            # evidence: an event store without its envelope constructor cannot
            # record anything.
            raise ValueError("event_store requires the envelope_factory that builds its events")
        self._warden = Warden() if warden is _UNSET_WARDEN else cast(Warden | None, warden)
        self._correlation = correlation or HarvestCorrelation()
        self._audit_sink = audit_sink or (
            event_store_audit_sink(event_store, envelope_factory)
            if event_store is not None
            else None
        )
        self._policy_version = policy_version
        # Strong references for audit records scheduled by the synchronous
        # adapter: the event loop keeps only weak task references, so an
        # unreferenced pending write can be garbage-collected mid-flight.
        self._audit_tasks: set[asyncio.Task[None]] = set()

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
        fallback: the content is refused. When the audit sink is async, its
        write also cannot be confirmed before this method returns, so the
        truthful admission-level outcome is ``audit_unavailable`` (the
        scan-level reason is preserved as ``scan_outcome`` in the audit
        record) and the record is delivered on the live loop, with one
        corrected redelivery attempt if that write fails.
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
        # The async Warden cannot run on a live loop from this synchronous
        # seam, so the scan-level reason is fixed: the scanner was unavailable.
        scan_outcome: AdmissionOutcome = "warden_unavailable"
        outcome = scan_outcome
        audit = self._audit_record(scan_outcome, False, digest, None)
        try:
            confirmed = self._deliver_audit_inline(audit)
        except Exception:
            # Parity with scan(): an admission that cannot be audited is not
            # an admitted admission. The content stays refused either way.
            logger.warning("RSI harvest audit unavailable; refusing content")
            outcome = "audit_unavailable"
            audit = self._audit_record(outcome, False, digest, None, scan_outcome=scan_outcome)
            return HarvestAdmission(False, outcome, digest, None, audit)
        if not confirmed:
            # An async sink write cannot be confirmed before scan_sync
            # returns. Fail closed to a truthful audit_unavailable outcome
            # (never a warden_unavailable refusal that implies a durable
            # record exists), preserve the scan-level reason as
            # ``scan_outcome``, and deliver the record on the live loop.
            outcome = "audit_unavailable"
            audit = self._audit_record(
                outcome,
                False,
                digest,
                None,
                scan_outcome=scan_outcome,
                audit_delivery="scheduled_unconfirmed",
            )
            self._schedule_audit_record(audit)
        return HarvestAdmission(False, outcome, digest, None, audit)

    def _audit_record(
        self,
        outcome: AdmissionOutcome,
        admitted: bool,
        digest: str,
        verdict: WardenVerdict | None,
        *,
        scan_outcome: AdmissionOutcome | None = None,
        audit_delivery: str | None = None,
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
        if scan_outcome is not None:
            # The scan-level refusal reason, kept distinct from the
            # admission-level outcome when audit delivery could not be
            # confirmed (for example the in-loop scheduled path).
            record["scan_outcome"] = scan_outcome
        if audit_delivery is not None:
            record["audit_delivery"] = audit_delivery
        record.update(_correlation_payload(self._correlation, digest))
        return record

    async def _record_audit_async(self, record: dict[str, object]) -> None:
        if self._audit_sink is not None:
            await self._invoke_audit_sink(record)
            return
        logger.info("RSI harvest Warden admission", extra={"audit": record})

    async def _invoke_audit_sink(self, record: dict[str, object]) -> None:
        if self._audit_sink is None:  # pragma: no cover - callers narrow first
            return
        result = self._audit_sink(dict(record))
        if inspect.isawaitable(result):
            await result

    def _deliver_audit_inline(self, record: dict[str, object]) -> bool:
        """Deliver an audit record that can be confirmed before returning.

        Returns ``True`` when the record was durably delivered inline (or no
        sink is configured and process logging is the audit channel), so the
        caller may keep the scan-level outcome. Returns ``False`` when the
        sink is async: delivery cannot be confirmed before ``scan_sync``
        returns, so the caller must fail closed to ``audit_unavailable`` and
        schedule the delivery instead. A raising synchronous sink propagates,
        mirroring :meth:`scan`.
        """
        if self._audit_sink is None:
            logger.info("RSI harvest Warden admission", extra={"audit": record})
            return True
        if inspect.iscoroutinefunction(self._audit_sink):
            return False
        result = self._audit_sink(dict(record))
        if inspect.isawaitable(result):
            # A sync-declared sink returned an awaitable anyway: the captured
            # coroutine or future never ran. Close it and let the scheduled
            # delivery hand the sink the truthful unconfirmed record instead
            # of leaving a stale write racing the corrected one.
            if inspect.iscoroutine(result):
                result.close()
            elif isinstance(result, asyncio.Future):
                result.cancel()
            return False
        return True

    def _schedule_audit_record(self, record: dict[str, object]) -> None:
        """Deliver one audit record from the synchronous adapter.

        This path is only reached from ``scan_sync`` inside a running event
        loop, so the refused outcome can still be recorded: schedule the
        delivery on that loop instead of dropping it as an un-awaited
        coroutine (which loses the refusal evidence and leaks a
        RuntimeWarning). A strong reference is kept until the write settles;
        the loop itself only holds weak task references.
        """
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._deliver_scheduled_audit(record))
        self._audit_tasks.add(task)
        task.add_done_callback(self._audit_tasks.discard)

    async def _deliver_scheduled_audit(self, record: dict[str, object]) -> None:
        """Run one scheduled audit delivery, truthfully and contained.

        The admission decision is already made (and refused) by the time this
        runs. A failed delivery is retried once with an annotation marking the
        retry, so a transiently failing sink still persists the truthful
        ``audit_unavailable`` record rather than silently losing it; a hard
        failure is logged with the outcome and digest only — never content —
        instead of surfacing as an un-retrieved task exception.
        """
        try:
            await self._invoke_audit_sink(record)
            return
        except Exception:
            logger.warning("RSI harvest audit write failed after admission", exc_info=True)
        corrected = dict(record)
        corrected["audit_delivery"] = "retry_after_failure"
        try:
            await self._invoke_audit_sink(corrected)
        except Exception:
            logger.error(
                "RSI harvest audit record undeliverable after retry (outcome=%s digest=%s)",
                record.get("outcome"),
                record.get("content_digest"),
            )


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
