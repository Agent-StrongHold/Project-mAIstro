"""Capability platform API (SPEC-184/187).

The canonical, UI-agnostic surface for the capability registry: list slots and
provider health, re-discover providers without a restart, toggle/activate a
slot, and drive the approval inbox (list pending + resolve). The web UI, the
`maistro` CLI, and any TUI are all clients of these routes — no operation is
reachable from only one front-end.

The registry lives in the engine (sourced from the maistro-core Container);
routes reach it via `get_engine().capabilities` rather than a route-local global.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from models.schemas import CapabilitySetting
from pydantic import BaseModel, ConfigDict
from services.engine import get_engine
from starlette.concurrency import run_in_threadpool

from routes.audit import log_audit

logger = logging.getLogger("hive.capabilities")

router = APIRouter(tags=["capabilities"])


def _registry() -> Any:
    return get_engine().capabilities


async def _provider_view(reg: Any, slot: str, name: str) -> dict[str, Any]:
    provider = reg.provider(slot, name)
    healthy: bool | None
    try:
        health = await provider.healthcheck()
        healthy = bool(health.healthy)
    except Exception as exc:  # health probe must never break the listing
        logger.debug("healthcheck failed for %s/%s: %s", slot, name, exc)
        healthy = False
    return {"name": name, "trust_tier": provider.trust_tier, "healthy": healthy}


async def _slot_view(reg: Any, slot: str) -> dict[str, Any]:
    providers = [await _provider_view(reg, slot, n) for n in reg.installed(slot)]
    return {
        "slot": slot,
        "enabled": reg.is_enabled(slot),
        "active_provider": reg.active_name(slot),
        "providers": providers,
    }


@router.get("")
async def list_capabilities() -> dict[str, Any]:
    reg = _registry()
    slots = [await _slot_view(reg, s) for s in sorted(reg.slots())]
    return {"slots": slots}


class DiscoverBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


@router.post("/discover")
async def discover_capabilities(body: DiscoverBody | None = None) -> dict[str, Any]:
    """Re-run the entry-point sweep; newly-installed providers register without a restart."""
    from maistro.capabilities.discovery import discover_into

    reg = _registry()
    count = discover_into(reg)
    log_audit("capability_discover", "system", detail={"registered": count})
    slots = [await _slot_view(reg, s) for s in sorted(reg.slots())]
    return {"registered": count, "slots": slots}


class PatchCapabilityBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = None
    active_provider: str | None = None


@router.patch("/{slot}")
async def patch_capability(slot: str, body: PatchCapabilityBody) -> dict[str, Any]:
    reg = _registry()
    if slot not in reg.slots():
        raise HTTPException(status_code=404, detail=f"unknown capability slot '{slot}'")

    if body.active_provider is not None and body.active_provider not in reg.installed(slot):
        raise HTTPException(
            status_code=400,
            detail=f"provider '{body.active_provider}' is not installed for slot '{slot}'",
        )

    # Snapshot before mutating: the live registry and the durable record must
    # not disagree. Changing the registry first and persisting second left the
    # capability active after a failed request — the caller sees an error and
    # the deployment runs with the change anyway, until restart (Codex, #334).
    previous = _slot_state(reg, slot)
    if body.enabled is not None:
        reg.set_enabled(slot, body.enabled)
    if body.active_provider is not None:
        reg.activate(slot, body.active_provider)

    try:
        # Off the event loop: `_persist_slot` waits on `State.flush`, which is
        # configured for up to ten seconds. Blocking here stalls every other
        # request and websocket in the process for the duration.
        await run_in_threadpool(_persist_slot, reg, slot)
    except Exception:
        _restore_slot(reg, slot, previous)
        raise
    log_audit(
        "capability_patch",
        "system",
        target=slot,
        detail=body.model_dump(exclude_none=True),
    )
    return await _slot_view(reg, slot)


def _slot_state(reg: Any, slot: str) -> tuple[bool, str | None]:
    """The registry's current state for one slot, enough to put it back."""
    return reg.is_enabled(slot), reg.active_name(slot)


def _restore_slot(reg: Any, slot: str, previous: tuple[bool, str | None]) -> None:
    """Undo a live mutation whose durable write did not land.

    Best-effort by necessity — there is nothing better to do if the restore
    itself fails — but never silent: a registry left disagreeing with the record
    is the state this whole path exists to prevent, so it is logged as an error.
    """
    enabled, provider = previous
    try:
        reg.set_enabled(slot, enabled)
        if provider is not None:
            reg.activate(slot, provider)
    except Exception as exc:  # pragma: no cover - the registry does not raise here
        logger.error("capability %s could not be restored after a failed persist: %s", slot, exc)


def _persist_slot(reg: Any, slot: str) -> None:
    """Mirror the live slot state into settings so toggles survive restart.

    "Survive restart" is what the old body claimed and did not do: it rebound a
    module attribute (#334). The write is durable now, and a store that will not
    take it raises rather than leaving the registry and the record disagreeing
    with each other in silence.
    """
    from services import settings_store

    values = settings_store.current()
    caps = dict(values.capabilities)
    caps[slot] = CapabilitySetting(
        enabled=reg.is_enabled(slot),
        active_provider=reg.active_name(slot),
    )
    settings_store.save(values.model_copy(update={"capabilities": caps}))


# --- Approval inbox -----------------------------------------------------


def _approval_inbox() -> Any | None:
    """The approval provider that supports pending()/resolve() (the inbox)."""
    reg = _registry()
    name = reg.active_name("approval") or "inbox"
    provider = reg.provider("approval", name)
    if not _is_inbox(provider):
        provider = reg.provider("approval", "inbox")
    return provider if _is_inbox(provider) else None


def _is_inbox(provider: Any) -> bool:
    return provider is not None and hasattr(provider, "pending") and hasattr(provider, "resolve")


def _approval_view(req: Any) -> dict[str, Any]:
    return {
        "request_id": req.request_id,
        "action": req.action,
        "params": req.params,
        "tier": req.tier,
        "requester": req.requester,
        "rationale": req.rationale,
    }


# --- self_repair (SPEC-188) -------------------------------------------------


def _self_repair_provider() -> Any | None:
    reg = _registry()
    name = reg.active_name("self_repair") or "rule_based_repair"
    provider = reg.provider("self_repair", name)
    return provider if (provider is not None and hasattr(provider, "run_once")) else None


def _proposal_view(result: Any) -> dict[str, Any]:
    p = result.proposal
    return {
        "resource": p.resource,
        "symptom": p.symptom,
        "action": p.action,
        "params": p.params,
        "tier": p.tier,
        "rationale": p.rationale,
        "decision": str(result.decision),
        "detail": result.detail,
    }


def _cycle_view(provider: Any) -> dict[str, Any]:
    cycle = provider.last_cycle
    proposals = [_proposal_view(r) for r in cycle.results] if cycle is not None else []
    return {
        "ts": cycle.ts if cycle is not None else "",
        "proposals": proposals,
        "governor": provider.governor_state(),
    }


@router.get("/self-repair/proposals")
def self_repair_proposals() -> dict[str, Any]:
    provider = _self_repair_provider()
    if provider is None:
        return {"ts": "", "proposals": [], "governor": {}}
    return _cycle_view(provider)


@router.post("/self-repair/run")
async def self_repair_run() -> dict[str, Any]:
    from services.capabilities_wiring import run_self_repair_once

    cycle = await run_self_repair_once(_registry())
    if cycle is None:
        raise HTTPException(
            status_code=503, detail="self_repair unavailable (disabled or no provider)"
        )
    log_audit("self_repair_run", "system", detail={"proposals": len(cycle.results)})
    provider = _self_repair_provider()
    if provider is not None:
        return _cycle_view(provider)
    return {"ts": cycle.ts, "proposals": [], "governor": {}}


@router.get("/approvals")
def list_approvals() -> dict[str, Any]:
    inbox = _approval_inbox()
    if inbox is None:
        return {"pending": []}
    return {"pending": [_approval_view(r) for r in inbox.pending()]}


class ResolveApprovalBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approved: bool
    actor: str = ""


@router.post("/approvals/{request_id}")
def resolve_approval(request_id: str, body: ResolveApprovalBody) -> dict[str, Any]:
    inbox = _approval_inbox()
    if inbox is None:
        raise HTTPException(status_code=503, detail="no approval inbox available")
    resolved = inbox.resolve(request_id, approved=body.approved, actor=body.actor)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"no pending approval '{request_id}'")
    log_audit(
        "approval_resolve",
        body.actor or "system",
        target=request_id,
        detail={"approved": body.approved},
        severity="warning",
    )
    return {"resolved": True, "request_id": request_id, "approved": body.approved}
