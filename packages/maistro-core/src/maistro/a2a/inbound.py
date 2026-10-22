"""Common Warden boundary for peer-controlled A2A representations.

A2A payloads are mappings in most transports, but scanning only their values
would let an attacker hide instructions in a key.  The canonical JSON form is
therefore the one representation passed to Warden and the one downstream code
must consume.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from maistro.security._types import WardenVerdict


@runtime_checkable
class InboundWarden(Protocol):
    """The small Warden surface required at an A2A ingress boundary."""

    async def scan(self, content: str, boundary: str) -> WardenVerdict: ...


def _json_default(value: Any) -> Any:
    """Encode only values with an unambiguous, non-lossy JSON form."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"A2A payload contains non-JSON value {type(value).__name__}")


def canonicalize_inbound(value: Any) -> str:
    """Return the exact deterministic representation supplied to Warden.

    Sorting keys is intentional: attacker-controlled mapping keys are part of
    the scanned text, not metadata discarded by a values-only walker.  A
    serialization failure is an ingress refusal rather than an opportunity to
    pass an opaque object downstream.
    """
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def default_warden() -> InboundWarden:
    """Build the canonical detector without introducing an A2A policy."""
    from maistro.security.warden.detector import Warden

    return Warden()


async def scan_inbound(warden: InboundWarden | None, value: Any) -> WardenVerdict:
    """Scan one A2A representation and fail closed on unavailable policy."""
    if warden is None:
        return WardenVerdict(
            clean=False,
            blocked=True,
            flags=("warden_unavailable",),
        )
    try:
        content = canonicalize_inbound(value)
        return await warden.scan(content, "a2a_inbound")
    except Exception:
        # A scanner or serializer failure must not turn peer data into trusted
        # content.  Keep the reason static so no remote value enters telemetry.
        return WardenVerdict(
            clean=False,
            blocked=True,
            flags=("warden_unavailable",),
        )
