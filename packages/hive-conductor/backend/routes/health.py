from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from config import get_settings
from fastapi import APIRouter, Request, Response
from models.schemas import ReadyResponse

_START = time.monotonic()
_STARTED_AT = datetime.now(UTC).isoformat()

router = APIRouter(tags=["health"])


def _llm_state() -> tuple[bool, bool]:
    """`(llm_configured, allow_stub_llm)` — the F3 degraded-mode signal.

    Lazy + defensive on purpose: /health is a public liveness probe (compose
    and the image healthcheck hit it), so it must never fail because a
    settings import blew up. An unreadable state is reported as "degraded",
    never as healthy.
    """
    try:
        from services.graph_runner import llm_gateway_configured, stub_llm_allowed

        return llm_gateway_configured(), stub_llm_allowed()
    except Exception:
        return False, False


def _memory_decay_state() -> dict:
    """Episodic decay state (SPEC-080126-9e42) — the F3 signal for "memory forgets".

    Same defensive contract as `_llm_state`: /health is a liveness probe and must
    never fail because of this. Unreadable state reports as disabled, never as
    healthy — a false "decay is on" would recreate the silent gap it closes.
    """
    try:
        from services.memory_decay import memory_decay_status

        return memory_decay_status()
    except Exception:
        return {"enabled": False, "state": "unavailable"}


def _memory_decay_running(status: dict) -> bool:
    """True only when decay is actually wired and ticking.

    Configuration alone is insufficient: the driver can be enabled while in
    ``no_store`` state, which means no episodic memory will ever decay.
    """
    return status.get("state") == "running"


def _task_clear_supported() -> bool:
    """Whether this deployment's task backend can bulk-clear.

    Imported inside the function like the other engine lookups here: `/health`
    must answer even when the engine is not wired, and a module-level import
    would make this route depend on a service that may not have started.
    """
    try:
        from services.engine import get_engine

        return bool(get_engine().supports_clear)
    except Exception:
        return False


def _log_redaction_active() -> bool:
    """ADR-064 log-redaction state. Same defensive contract as the probes above:
    unreadable reports as inactive, because a false "secrets are scrubbed" is the
    failure this control exists to prevent."""
    try:
        from logging_setup import redaction_active

        return redaction_active()
    except Exception:
        return False


def _workspace_authority_available() -> bool:
    """Whether Workspace requests can reach their canonical store (#37).

    Unlike the informational checks, this one gates readiness: with a database
    configured and no Container owning it, every Workspace request fails
    closed, so the instance is unusable rather than degraded. Unreadable state
    reports as unavailable, never as ready.
    """
    try:
        from services.workspace_authority import canonical_store_available

        return canonical_store_available()
    except Exception:
        return False


def _optional_routers_state(app: Any) -> dict[str, str | None]:
    """`{module: error | None}` for the optional feature routers (M3-B7, #97).

    `_include_optional_router` records every mount outcome on
    `app.state.optional_routers` precisely so a caller can ask what happened;
    a startup log line is not queryable. Defensive like every probe here:
    /health must answer even if the attribute is missing (a process still
    running older code) or holds something unexpected.
    """
    state = getattr(app.state, "optional_routers", None)
    if not isinstance(state, dict):
        return {}
    return {str(module): (None if error is None else str(error)) for module, error in state.items()}


def _degraded_services(
    *,
    llm_configured: bool,
    memory_decay: dict,
    memory_decay_enabled: bool,
    log_redaction: bool,
    identity: dict,
    identity_required: bool,
    optional_routers: dict[str, str | None],
) -> list[dict[str, str]]:
    """Name every degraded capability and why, in one stable shape (M3-B7, #97).

    `degraded: true` answers *whether* the Conductor is diminished; a
    user-facing operating state has to answer *what* and *why* — the UI banner
    and `hctl status` render this list verbatim, so each reason is written to
    be shown to a person. Order is stable: the always-present capability
    checks first, then the optional routers alphabetically.
    """
    services: list[dict[str, str]] = []
    if not llm_configured:
        services.append(
            {
                "service": "llm_gateway",
                "reason": "no LLM gateway configured (set LITELLM_API_BASE or LITELLM_PROXY_URL)",
            }
        )
    if not memory_decay_enabled:
        services.append(
            {
                "service": "memory_decay",
                "reason": f"episodic decay is not running (state: {memory_decay.get('state', 'unknown')})",
            }
        )
    if not log_redaction:
        services.append(
            {
                "service": "log_redaction",
                "reason": "ADR-064 redaction inactive; secrets may appear in logs",
            }
        )
    if identity_required:
        services.append(
            {
                "service": "identity",
                "reason": f"identity module status: {identity.get('status', 'unknown')}",
            }
        )
    for module, error in sorted(optional_routers.items()):
        if error is not None:
            services.append({"service": f"router:{module}", "reason": error})
    return services


def _persistence_status() -> dict:
    """Per-family durability/ack mode (#333, #1179).

    Every Conductor mutation path acknowledges at the State writer's commit —
    the write APIs raise instead of accepting a command into the queue — so
    the mode a family reports is `durable-ack` (survives restart; 2xx means
    committed) or `ephemeral`/`memory` (process-lifetime, labelled as such).
    Same defensive contract as the probes above: /health must never fail
    because of this, so an unreadable state reports as `unknown`, never as
    durable.
    """
    try:
        from services import profile_store, settings_store
        from services.registration_policy import durable as registration_durable
        from stores import persistence_backend

        configured = persistence_backend() is not None
        return {
            "ack": "state-commit" if configured else "process-memory",
            "families": {
                "model_json_stores": "durable-ack" if configured else "memory",
                "settings": "durable-ack" if settings_store.durable() else "ephemeral",
                "profiles": "durable-ack" if profile_store.durable() else "ephemeral",
                "registration_policy": "durable-ack" if registration_durable() else "ephemeral",
            },
        }
    except Exception:
        # A persistence map that cannot be read must not claim durability.
        return {"ack": "unknown", "families": {}}


@router.get("/health")
def health(request: Request) -> dict:
    settings = get_settings()
    uptime = time.monotonic() - _START
    try:
        from services.foundation import get_foundation

        f = get_foundation()
        vault_enabled = f.vault_available
        state_enabled = f.state_available
        privilege_available = f.privilege_available
        reactor_available = f.reactor_available
    except RuntimeError:
        vault_enabled = False
        state_enabled = False
        privilege_available = False
        reactor_available = False
    llm_configured, allow_stub_llm = _llm_state()
    try:
        from services.identity_health import identity_health, identity_is_required

        identity = identity_health()
        identity_required = identity_is_required(identity)
    except Exception:
        # A public liveness probe must not turn a probe implementation failure
        # into a 500; an unreadable identity status is explicitly degraded.
        identity = {"status": "misconfigured", "reason": "health_probe_failed"}
        identity_required = True
    memory_decay = _memory_decay_state()
    memory_decay_enabled = _memory_decay_running(memory_decay)
    log_redaction = _log_redaction_active()
    optional_routers = _optional_routers_state(request.app)
    degraded_services = _degraded_services(
        llm_configured=llm_configured,
        memory_decay=memory_decay,
        memory_decay_enabled=memory_decay_enabled,
        log_redaction=log_redaction,
        identity=identity,
        identity_required=identity_required,
        optional_routers=optional_routers,
    )

    return {
        "status": "ok",
        "version": "0.9.0",
        # Capability, not health: the missions UI uses it to decide whether to
        # offer bulk-clear at all (#190 review).
        "task_clear_supported": _task_clear_supported(),
        "uptime_seconds": uptime,
        "started_at": _STARTED_AT,
        "router_model": settings.chat_default_model,
        "vault_enabled": vault_enabled,
        "state_enabled": state_enabled,
        "privilege_enabled": privilege_available,
        "reactor_enabled": reactor_available,
        # F3: report degradation, do not become an outage. `status` stays "ok"
        # and this endpoint stays 200 — it is the liveness probe.
        "llm_configured": llm_configured,
        "allow_stub_llm": allow_stub_llm,
        # SPEC-080126-9e42: decay off means memory never forgets, which
        # contradicts a documented product behaviour — degraded, never silent.
        "memory_decay": memory_decay,
        "memory_decay_enabled": memory_decay_enabled,
        # ADR-064: off means log lines carry API keys and connection strings
        # verbatim, which SECURITY.md says they do not. Degraded, never silent.
        "log_redaction_active": log_redaction,
        # Identity is optional in the supported no-crypto profile, but a
        # selected identity module must never disappear into a generic 200.
        "identity": identity,
        "identity_required": identity_required,
        # #333/#1179: the durability/ack mode per store family — whether a
        # 2xx from a mutation route means the State writer committed it.
        "persistence": _persistence_status(),
        # M3-B7 (#97): a user-facing operating state names what is degraded.
        # `optional_routers` is the raw mount outcome per feature router;
        # `degraded_services` is the human-readable rendering of every
        # degraded capability, which the UI banner and `hctl status` show.
        "optional_routers": optional_routers,
        "degraded_services": degraded_services,
        "degraded": bool(degraded_services),
    }


@router.get("/health/ready")
def ready(response: Response) -> ReadyResponse:
    try:
        from services.foundation import get_foundation

        f = get_foundation()
        checks = {
            "api": True,
            "vault": f.vault_available,
            "state": f.state_available,
            "privilege": f.privilege_available,
            "reactor": f.reactor_available,
        }
    except RuntimeError:
        checks = {"api": True, "vault": False, "state": False, "privilege": False, "reactor": False}
    # Informational only: `ready` stays keyed on "api" so a missing LLM gateway
    # degrades the conductor without taking it out of rotation.
    checks["llm"] = _llm_state()[0]
    checks["memory_decay"] = _memory_decay_running(_memory_decay_state())
    try:
        from services.identity_health import identity_health

        checks["identity"] = identity_health()["status"] in {"operational", "disabled"}
    except Exception:
        checks["identity"] = False
    checks["log_redaction"] = _log_redaction_active()
    checks["workspace_authority"] = _workspace_authority_available()
    is_ready = checks["api"] and checks["workspace_authority"]
    if not is_ready:
        # 503 so the image and Compose healthchecks, which only look at the
        # status code, take the instance out of rotation.
        response.status_code = 503
    return ReadyResponse(ready=is_ready, checks=checks)
