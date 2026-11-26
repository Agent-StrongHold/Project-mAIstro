"""Canonical capability-effect adapter for Graph Nodes.

Capability policy may require a durable human decision before an external effect
can run. Graph already owns durable pause/resume semantics, so Nodes translate
the capability-layer pending signal into the existing ``pause_until`` contract
instead of inventing a parallel HITL lifecycle.

The adapter stays a pause adapter (#1192): it never resolves an approval,
invents a principal, or bypasses provider/policy authority. What it can carry
(#1898) is a node-supplied *continuation* — metadata, a fixed deadline, and the
governed request digest — so the durable pause re-enters on the exact paused-for
request instead of a derived one. The caller computes the digest with the
existing ``approval_request_digest`` over the same immutable request it hands
governed invoke; no second hashing algorithm lives here.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, TypeVar

from maistro.capabilities.governed_invocation import InvocationApprovalPending
from maistro.graph.execution_state import thaw_json_value

from .base import (
    PAUSE_AWAITING_HUMAN_APPROVAL,
    pause_until,
)

T = TypeVar("T")

#: Top-level continuation keys the pause contract owns. ``BaseNode.run``
#: expands pause metadata *after* ``paused_reason``, so a carried value under
#: any of these could overwrite the canonical human reason or the replay
#: identity and park the Run on the wrong waker. They are rejected, never
#: silently shadowed or stripped.
_RESERVED_CONTINUATION_KEYS = frozenset(
    {
        "paused_reason",
        "resume_at",
        "replay_effect_key",
        "approval_request_id",
        "effect_key",
        "request_digest",
    }
)

#: A request digest is exactly what ``approval_request_digest`` produces. The
#: adapter checks the shape so a stale or foreign digest cannot silently park a
#: pause that no resume will ever satisfy; it does not compute digests itself.
_REQUEST_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _independent_copy(value: Any) -> Any:
    """Copy a thawed value's mapping/list containers independently."""
    if isinstance(value, Mapping):
        return {str(key): _independent_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_independent_copy(item) for item in value]
    return value


def _copy_continuation(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Reject reserved keys and return an independent thawed copy."""
    reserved = sorted(_RESERVED_CONTINUATION_KEYS.intersection(metadata))
    if reserved:
        raise ValueError(
            "continuation_metadata uses keys reserved by the pause contract: " + ", ".join(reserved)
        )
    # Frozen Graph JSON arrives as MappingProxyType containers that naive
    # deepcopy cannot handle; thaw to ordinary JSON containers first, then
    # copy independently so later caller mutation cannot leak into the
    # persisted pause. No new serialization format is introduced.
    thawed = thaw_json_value(metadata)
    if not isinstance(thawed, Mapping):
        raise ValueError("continuation_metadata must be a mapping")
    return {str(key): _independent_copy(item) for key, item in thawed.items()}


def _require_valid_digest(request_digest: str | None) -> None:
    """Check digest shape so a stale or foreign value cannot park a pause that
    no resume will ever satisfy; the adapter never computes digests itself."""
    if request_digest is None:
        return
    if not isinstance(request_digest, str) or not _REQUEST_DIGEST.fullmatch(request_digest):
        raise ValueError("request_digest must be exactly 64 lowercase hexadecimal characters")


def _require_aware_deadline(resume_at: datetime | None) -> None:
    """A tzinfo object alone is insufficient: only an actual offset pins a
    durable deadline. The supplied value is preserved verbatim -- the adapter
    never normalizes it or derives a new deadline from "now"."""
    if resume_at is None:
        return
    if not isinstance(resume_at, datetime) or resume_at.utcoffset() is None:
        raise ValueError("resume_at must be an aware datetime (utcoffset() must not be None)")


def _validated_continuation(
    continuation_metadata: Mapping[str, Any] | None,
    request_digest: str | None,
    resume_at: datetime | None,
) -> dict[str, Any]:
    """Validate the optional continuation and return its independent copy.

    Every rejection happens here, before the operation is awaited, so a bad
    continuation fails the Attempt before any provider or policy spy runs.
    """
    continuation = (
        {} if continuation_metadata is None else _copy_continuation(continuation_metadata)
    )
    _require_valid_digest(request_digest)
    _require_aware_deadline(resume_at)
    return continuation


async def invoke_capability_effect(
    operation: Callable[[], Awaitable[T]],
    *,
    effect_key: str,
    continuation_metadata: Mapping[str, Any] | None = None,
    resume_at: datetime | None = None,
    request_digest: str | None = None,
) -> T:
    """Run a governed capability effect or durably pause for human approval.

    The keyword-only continuation arguments are optional; omitting all of them
    preserves the original two-key pause metadata, no resume time, and the
    existing return/error propagation. With them, an ``InvocationApprovalPending``
    pause carries the validated continuation plus ``request_digest`` (only when
    supplied), then stamps the canonical ``approval_request_id`` from the
    pending signal and the required ``effect_key`` last so neither can be
    displaced by caller metadata.
    """
    continuation = _validated_continuation(continuation_metadata, request_digest, resume_at)

    try:
        return await operation()
    except InvocationApprovalPending as exc:
        stamped = dict(continuation)
        if request_digest is not None:
            stamped["request_digest"] = request_digest
        stamped["approval_request_id"] = exc.request_id
        stamped["effect_key"] = effect_key
        pause_until(
            PAUSE_AWAITING_HUMAN_APPROVAL,
            resume_at=resume_at,
            metadata=stamped,
        )
        raise AssertionError("pause_until must raise") from exc  # pragma: no cover


__all__ = ["invoke_capability_effect"]
