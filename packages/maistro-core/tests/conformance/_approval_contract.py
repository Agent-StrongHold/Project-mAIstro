"""The durable ApprovalStore contract, as runnable checks (#892).

Same discipline as ``_invocation_contract.py``: one behavior-level contract,
written once against :class:`maistro.capabilities.approval_store.ApprovalStore`
and run unchanged against its three production implementations. The contract
encodes what the protocol and its consumers document:

- an approval request is persisted pending, then resolved exactly once by a
  named verified principal (#329 / ADR-090726-9a4e: the actor is never
  defaulted, because a decision nobody can attribute cannot be audited);
- creation is idempotent by effect identity — the second request for the
  same (run, node_run, binding, effect) is answered with the first row, so
  one human decision governs one effect;
- a terminal decision is immutable: re-resolution returns the first
  disposition regardless of who asks or how they vote;
- absence is explicit (``None`` from ``get``, ``KeyError`` from ``resolve``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    DurableApproval,
)
from maistro.capabilities.slots.approval import ApprovalRequest

from ._invocation_contract import ConformanceViolation


def _request(ns: str, request_id: str, effect_key: str) -> ApprovalRequest:
    return ApprovalRequest(
        action="external_write",
        params={"path": f"/tmp/{ns}/{effect_key}", "request_digest": ""},
        tier="trusted",
        requester="conformance",
        rationale="one controlled write",
        request_id=request_id,
    )


def _approval(
    ns: str, request_id: str, effect_key: str, node_run_id: str = "node-run-1"
) -> DurableApproval:
    return DurableApproval(
        request=_request(ns, request_id, effect_key),
        workspace_id=f"ws-{ns}",
        project_id=f"project-{ns}",
        run_id=f"run-{ns}",
        node_run_id=node_run_id,
        attempt_id="attempt-1",
        binding_id=f"binding-{ns}",
        effect_key=effect_key,
    )


def _fail(text: str) -> ConformanceViolation:
    return ConformanceViolation(text)


async def pending_approvals_round_trip(store: Any, leg: Any) -> None:
    """create → get returns the same pending record, digest-bound and detached."""
    ns = uuid.uuid4().hex
    approval = _approval(ns, f"req-{ns}", "gate:write")
    await store.create(approval)
    got = await store.get(f"req-{ns}")
    if got is None:
        raise _fail("get() returned None for an approval create() just accepted")
    if got.status is not ApprovalStatus.PENDING:
        raise _fail(f"a fresh approval must be pending, got {got.status!r}")
    if got.actor or got.resolved_at is not None:
        raise _fail("a pending approval must name no actor and no resolution time")
    if got.request_digest != approval.request_digest:
        raise _fail(
            "readback lost the request digest binding: "
            f"{got.request_digest!r} != {approval.request_digest!r}"
        )
    for field in (
        "workspace_id",
        "project_id",
        "run_id",
        "node_run_id",
        "binding_id",
        "effect_key",
    ):
        if getattr(got, field) != getattr(approval, field):
            raise _fail(f"readback {field} drifted from the stored approval")
    # A readback is a copy: mutating it must not corrupt the stored record.
    got.request.params["path"] = "/mutated"
    again = await store.get(f"req-{ns}")
    if again is None or again.request.params["path"] == "/mutated":
        raise _fail("mutating a readback changed the stored approval")


async def missing_approvals_are_absent_not_errors(store: Any, leg: Any) -> None:
    """get() of a missing id is None; resolve() of a missing id is KeyError."""
    ns = uuid.uuid4().hex
    if await store.get(f"req-{ns}-absent") is not None:
        raise _fail("get() invented an approval for an id that was never stored")
    try:
        await store.resolve(f"req-{ns}-absent", approved=True, actor="conformance")
    except KeyError:
        return
    raise _fail("resolve() of a missing approval did not raise KeyError")


async def create_is_idempotent_by_effect_identity(store: Any, leg: Any) -> None:
    """The second request for one effect is answered with the first row."""
    ns = uuid.uuid4().hex
    first = await store.create(_approval(ns, f"req-{ns}-first", "gate:write"))
    second = await store.create(_approval(ns, f"req-{ns}-second", "gate:write"))
    if second.request.request_id != first.request.request_id:
        raise _fail(
            "create() for an effect that already has a pending approval minted "
            f"{second.request.request_id!r} instead of returning "
            f"{first.request.request_id!r}"
        )
    if await store.get(f"req-{ns}-second") is not None:
        raise _fail("the refused duplicate request was persisted anyway")


async def create_refuses_a_duplicate_request_id(store: Any, leg: Any) -> None:
    """A request_id is a primary key: a second create with it is refused.

    The refusal *type* is deliberately not pinned: the in-memory reference
    raises ``ValueError`` while the durable twins leak their drivers'
    constraint errors (``sqlite3.IntegrityError`` /
    ``asyncpg.UniqueViolationError``) — finding F5. Until an owner picks the
    canonical mapping, the portable property is "refuses".
    """
    ns = uuid.uuid4().hex
    await store.create(_approval(ns, f"req-{ns}", "gate:write"))
    try:
        await store.create(_approval(ns, f"req-{ns}", "gate:other", node_run_id="node-run-9"))
    except Exception:
        return
    raise _fail("create() silently accepted a duplicate request_id")


async def resolve_requires_a_verified_actor(store: Any, leg: Any) -> None:
    """A decision that cannot be attributed to a principal must not settle."""
    ns = uuid.uuid4().hex
    approval = _approval(ns, f"req-{ns}", "gate:write")
    await store.create(approval)
    for actor in ("", "   ", "\t"):
        try:
            await store.resolve(f"req-{ns}", approved=True, actor=actor)
        except ValueError:
            continue
        raise _fail(f"resolve() accepted the unattributable actor {actor!r}")
    if (await store.get(f"req-{ns}")).status is not ApprovalStatus.PENDING:
        raise _fail("a refused resolution changed the pending approval")


async def resolve_is_idempotent_and_first_decision_wins(store: Any, leg: Any) -> None:
    """One effect, one decision: later calls return the first disposition."""
    ns = uuid.uuid4().hex
    await store.create(_approval(ns, f"req-{ns}", "gate:write"))
    first = await store.resolve(f"req-{ns}", approved=True, actor="alice")
    if first.status is not ApprovalStatus.APPROVED or first.actor != "alice":
        raise _fail(f"the first resolution landed as {first.status}/{first.actor!r}")
    if first.resolved_at is None:
        raise _fail("a resolved approval must carry resolved_at")
    second = await store.resolve(f"req-{ns}", approved=False, actor="mallory")
    if second.status is not ApprovalStatus.APPROVED or second.actor != "alice":
        raise _fail(f"re-resolution overwrote the first decision: {second.status}/{second.actor!r}")


async def a_resolved_approval_survives_a_restart(store: Any, leg: Any) -> None:
    """The decision that releases a worker must outlive the worker."""
    ns = uuid.uuid4().hex
    await store.create(_approval(ns, f"req-{ns}", "gate:write"))
    first = await store.resolve(f"req-{ns}", approved=True, actor="alice")
    readback = await (await leg.restart()).get(f"req-{ns}")
    if readback is None:
        raise _fail("the resolved approval vanished across a restart")
    if readback.status is not first.status or readback.actor != first.actor:
        raise _fail(f"the decision drifted across a restart: {readback.status}/{readback.actor!r}")
    if readback.resolved_at is None:
        raise _fail("resolved_at was lost across a restart")


APPROVAL_CHECKS: dict[str, Callable[[Any, Any], Awaitable[None]]] = {
    check.__name__: check
    for check in (
        pending_approvals_round_trip,
        missing_approvals_are_absent_not_errors,
        create_is_idempotent_by_effect_identity,
        create_refuses_a_duplicate_request_id,
        resolve_requires_a_verified_actor,
        resolve_is_idempotent_and_first_decision_wins,
        a_resolved_approval_survives_a_restart,
    )
}

__all__ = ["APPROVAL_CHECKS", "ConformanceViolation", *APPROVAL_CHECKS.keys()]
