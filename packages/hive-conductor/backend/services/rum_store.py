"""In-process collector for the SPA's perceived-load telemetry (#1420).

The reporter in the frontend (`frontend/src/lib/rum.ts`) batches events to
`POST /v1/rum/events`. This store is the receiving side: a bounded ring of
observations an operator can read back through `GET /v1/rum/events` and
aggregate through `GET /v1/rum/events/summary`.

The decisions this encodes are the ones #1420 requires be explicit:

- **Operator / destination.** The collector is the Conductor itself, on the
  same origin the app is served from. The instance maintainer is the
  operator; there is no third-party sink. Access = whatever can
  authenticate to this instance.
- **Enable/disable.** Off unless `RUM_INGEST_ENABLED=true`. While disabled
  the route answers 202 and *discards* — fail-closed, nothing is buffered
  or logged. The frontend is separately off unless its build set
  `VITE_RUM_ENABLED=true`; both sides must opt in for a fact to exist.
- **Sampling/batching.** The client samples per session and batches to at
  most 25 events per request (a cap the route also enforces); the server
  does no further sampling.
- **Retention/deletion.** In-memory only, newest-keeping ring bounded by
  `RUM_MAX_EVENTS` (default 500). A restart is the deletion policy; there
  is nothing to purge from disk because nothing is written to disk.
- **Schema.** `hive.rum.v1` — see `docs/RUM.md` for the field contract.
  The store projects every event onto the approved fields as defense in
  depth: even a client that ignored the frontend redaction rules cannot
 *store* a field the schema does not name. A request id failing the same
  charset `RequestIDMiddleware` enforces is treated as absent, so the
  collector cannot become a laundering path for arbitrary header values.
  The envelope's `build_id` / `session_id` are re-validated against the same
  charset the route enforces and stamped onto each stored observation: the
  build-over-build comparison the summary exists for needs them retained.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from typing import Any, Literal

from config import get_settings

#: Wire schema version this store accepts; matches `rumSchema.ts`.
RUM_SCHEMA = "hive.rum.v1"

#: Mirrors `maistro.observability.middleware`'s accepted request-ID charset.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: Same charset the ingest route enforces for the envelope identifiers.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Storage bound clamps — an operator cannot configure an unbounded sink.
MIN_MAX_EVENTS = 50
MAX_MAX_EVENTS = 10_000
DEFAULT_MAX_EVENTS = 500

WebVitalName = Literal["LCP", "load"]
ApiOutcome = Literal["ok", "http_error", "timeout", "network_error"]


def _finite_non_negative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _nearest_rank(ordered: list[float], percentile: float) -> float:
    """Nearest-rank percentile: the smallest value at or above ``percentile``
    of the data (0-indexed rank ``ceil(p * n) - 1``). For 20 samples the p95
    rank is the 19th ordered value — not the maximum, which ``int(n * 0.95)``
    would select — and an even-sized p50 takes the lower middle."""
    rank = math.ceil(percentile * len(ordered)) - 1
    return ordered[max(0, rank)]


def _bounded_str(
    value: Any, *, max_length: int, pattern: re.Pattern[str] | None = None
) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or len(value) > max_length:
        return None
    if pattern is not None and not pattern.match(value):
        return None
    return value


def _valid_route_and_ts(event: dict[str, Any]) -> tuple[str, float] | None:
    """The two fields every event type shares: a bounded route template and a
    numeric timestamp. None when either is missing or malformed."""
    route = _bounded_str(event.get("route"), max_length=80)
    if route is None:
        return None
    ts = event.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    return route, ts


def project_web_vital(event: Any) -> dict[str, Any] | None:
    """Project one client event onto the approved `web_vital` fields.

    Returns None (event dropped, never an exception) when the shape is not
    reportable. This is the server-side half of the redaction contract.
    """
    if not isinstance(event, dict):
        return None
    if event.get("type") != "web_vital":
        return None
    name = event.get("name")
    if name not in ("LCP", "load"):
        return None
    value_ms = event.get("value_ms")
    if not _finite_non_negative(value_ms):
        return None
    common = _valid_route_and_ts(event)
    if common is None:
        return None
    route, ts = common
    return {
        "type": "web_vital",
        "name": name,
        "value_ms": float(value_ms),
        "route": route,
        "ts": ts,
    }


def project_api_request(event: Any) -> dict[str, Any] | None:
    """Project one client event onto the approved `api_request` fields.

    Same contract as `project_web_vital` for the API-client event: duration
    and outcome class, the normalized route template, and — only when it
    survives the charset check — the server's own request id. Raw URLs,
    bodies, error objects and any other field the client might have
    attached are not read at all, so they cannot be stored.
    """
    if not isinstance(event, dict):
        return None
    if event.get("type") != "api_request":
        return None
    method = event.get("method")
    if not isinstance(method, str) or not re.fullmatch(r"[A-Z]{3,10}", method):
        return None
    status_class = event.get("status_class")
    if status_class not in (0, 2, 3, 4, 5):
        return None
    outcome = event.get("outcome")
    if outcome not in ("ok", "http_error", "timeout", "network_error"):
        return None
    duration_ms = event.get("duration_ms")
    if not _finite_non_negative(duration_ms):
        return None
    common = _valid_route_and_ts(event)
    if common is None:
        return None
    route, ts = common
    raw_request_id = event.get("request_id")
    if raw_request_id is not None and not isinstance(raw_request_id, str):
        return None
    request_id = (
        _bounded_str(raw_request_id, max_length=128, pattern=_REQUEST_ID_RE)
        if raw_request_id is not None
        else None
    )
    if raw_request_id is not None and request_id is None:
        # A value the server's own middleware would have rejected must not
        # enter the store: fail the event, not the field.
        return None
    return {
        "type": "api_request",
        "method": method,
        "route": route,
        "status_class": status_class,
        "outcome": outcome,
        "duration_ms": float(duration_ms),
        "request_id": request_id,
        "ts": ts,
    }


class RumStore:
    """Bounded, in-memory ring of accepted RUM observations."""

    def __init__(self, *, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque()
        self.max_events = max(MIN_MAX_EVENTS, min(int(max_events), MAX_MAX_EVENTS))
        self.received_batches = 0
        self.rejected_events = 0

    def ingest(
        self,
        events: list[Any],
        *,
        build_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        """Project and store one client batch; return how many were kept.

        The envelope's `build_id` / `session_id` are stamped onto every kept
        observation (re-validated here as defense in depth); a batch whose
        identifiers fail the charset is rejected wholesale — a value the
        ingest route would have refused must not enter the store, and the
        identifiers describe the batch, not a single event.

        Invalid events count as rejected and are dropped — a malformed batch
        is never an error the client must handle.
        """
        safe_build = _bounded_str(build_id, max_length=64, pattern=_IDENTIFIER_RE)
        safe_session = _bounded_str(session_id, max_length=64, pattern=_IDENTIFIER_RE)
        kept = 0
        with self._lock:
            self.received_batches += 1
            if (build_id is not None and safe_build is None) or (
                session_id is not None and safe_session is None
            ):
                self.rejected_events += len(events)
                return 0
            for event in events:
                projected = project_web_vital(event) or project_api_request(event)
                if projected is None:
                    self.rejected_events += 1
                    continue
                projected["build_id"] = safe_build
                projected["session_id"] = safe_session
                projected["received_at"] = time.time()
                self._events.append(projected)
                kept += 1
            while len(self._events) > self.max_events:
                self._events.popleft()
        return kept

    def list_events(self, limit: int = 200) -> dict[str, Any]:
        """Newest-last slice of the ring, with a truncation flag."""
        limit = max(1, min(int(limit), self.max_events))
        with self._lock:
            events = list(self._events)
        truncated = len(events) > limit
        return {"events": events[-limit:], "total": len(events), "truncated": truncated}

    def summary(self) -> dict[str, Any]:
        """Group the ring by (build, type, metric, route, outcome, status class).

        Deliberately coarse: the grouping dimensions are exactly the ones
        #1420 names for spotting a regression — build, metric, normalized
        route, outcome, status class. Splitting by build is what makes the
        build-over-build comparison possible while several builds share the
        ring. Request and session ids are NOT group keys (they would
        fragment aggregation into one group per id); correlate either
        through `GET /v1/rum/events` instead. Percentiles are computed over
        the retained window only, which `window_events` reports so nobody
        reads p95 as a forever number.
        """
        groups: dict[tuple[Any, ...], list[float]] = {}
        with self._lock:
            events = list(self._events)
        for event in events:
            if event["type"] == "web_vital":
                key = (
                    event["build_id"],
                    event["type"],
                    event["name"],
                    event["route"],
                    "",
                    0,
                )
            else:
                key = (
                    event["build_id"],
                    event["type"],
                    event["method"],
                    event["route"],
                    event["outcome"],
                    event["status_class"],
                )
            value = event["value_ms"] if event["type"] == "web_vital" else event["duration_ms"]
            groups.setdefault(key, []).append(value)
        summarized = []
        for key, values in sorted(groups.items(), key=lambda kv: str(kv[0])):
            ordered = sorted(values)
            summarized.append(
                {
                    "build_id": key[0],
                    "type": key[1],
                    "metric": key[2],
                    "route": key[3],
                    "outcome": key[4] or None,
                    "status_class": key[5],
                    "count": len(values),
                    "min_ms": ordered[0],
                    "p50_ms": _nearest_rank(ordered, 0.5),
                    "p95_ms": _nearest_rank(ordered, 0.95),
                    "max_ms": ordered[-1],
                }
            )
        with self._lock:
            return {
                "groups": summarized,
                "window_events": len(events),
                "received_batches": self.received_batches,
                "rejected_events": self.rejected_events,
            }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self.received_batches = 0
            self.rejected_events = 0


_singleton: RumStore | None = None
#: Guards first construction. FastAPI runs these sync handlers in worker
#: threads, and an unlocked check-then-assign lets the first two concurrent
#: RUM requests each build a store — one batch would vanish when the global
#: reference is overwritten. Single-flight construction instead.
_singleton_lock = threading.Lock()


def get_store() -> RumStore:
    """The process-wide store, sized once from settings."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                try:
                    configured = get_settings().rum_max_events
                except Exception:
                    configured = DEFAULT_MAX_EVENTS
                _singleton = RumStore(max_events=configured)
    return _singleton


def rum_ingest_enabled() -> bool:
    """Whether the operator opted this instance in (`RUM_INGEST_ENABLED`)."""
    try:
        return bool(get_settings().rum_ingest_enabled)
    except Exception:
        return False
