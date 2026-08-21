"""Providers backed by the host-health API (:8150) — monitor + action (SPEC-187)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from maistro.capabilities.slots.approval import ApprovalRequest
from maistro.capabilities.slots.infra import (
    ActionResult,
    ActionTier,
    InfraHealth,
    ResourceHealth,
    tier_for,
)
from maistro.capabilities.types import ProviderHealth

if TYPE_CHECKING:
    from maistro.capabilities.http import AsyncHttp
    from maistro.capabilities.slots.approval import Approval

logger = logging.getLogger("maistro.capabilities.host_health")

_SECTIONS = ("gpu", "storage", "docker", "vms", "services")


class HostHealthMonitor:
    """infra_monitor provider: GET /full -> normalized InfraHealth."""

    def __init__(self, http: AsyncHttp) -> None:
        self._http = http

    @property
    def name(self) -> str:
        return "host_health"

    @property
    def slot(self) -> str:
        return "infra_monitor"

    @property
    def trust_tier(self) -> str:
        return "t0"

    def requires(self) -> tuple[str, ...]:
        return ("HOST_HEALTH_URL", "HOST_HEALTH_TOKEN")

    async def healthcheck(self) -> ProviderHealth:
        try:
            await self._http.get_json("/health")
            return ProviderHealth(healthy=True)
        except Exception as exc:
            return ProviderHealth(healthy=False, detail=str(exc))

    async def snapshot(self) -> InfraHealth:
        try:
            data = await self._http.get_json("/full")
        except Exception as exc:
            logger.warning("host-health /full unreachable: %s", exc)
            return InfraHealth(
                ts="",
                resources={s: ResourceHealth(status="down", detail={}) for s in _SECTIONS},
            )
        return InfraHealth(
            ts=str(data.get("timestamp", "")),
            resources={s: _NORMALIZERS[s](_as_dict(data.get(s))) for s in _SECTIONS},
        )


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


# --- /full normalization: the host API's raw shape → a stable contract -------
#
# This is the anti-corruption layer between the host-health API's command-output
# shapes and the contract self_repair's diagnosis reads. It also encodes the host
# author's remediation policy via per-container state: only `unhealthy` (Up but
# healthcheck failing) is an auto-remediation candidate; `restarting`
# (crash-looping) needs a human, not another kick; `stopped` is intentional.

_CONTAINER_OK = "healthy"


def _norm_docker(raw: dict[str, Any]) -> ResourceHealth:
    if str(raw.get("status", "")).lower() == "error":
        return ResourceHealth(status="down", detail={"error": str(raw.get("detail", ""))})
    unhealthy = {str(n) for n in raw.get("unhealthy", []) if isinstance(raw.get("unhealthy"), list)}
    restarting = {
        str(n) for n in raw.get("restarting", []) if isinstance(raw.get("restarting"), list)
    }
    stopped = {str(n) for n in raw.get("stopped", []) if isinstance(raw.get("stopped"), list)}
    names = [str(c.get("name", "")) for c in raw.get("containers", []) if isinstance(c, dict)]
    # If only buckets were provided, derive names from them.
    names = names or sorted(unhealthy | restarting | stopped)

    containers = []
    for name in names:
        if name in unhealthy:
            state = "unhealthy"
        elif name in restarting:
            state = "restarting"
        elif name in stopped:
            state = "stopped"
        else:
            state = _CONTAINER_OK
        containers.append({"name": name, "state": state})

    # Degraded only when there is something actionable/abnormal (unhealthy or
    # crash-looping). `stopped` alone is intentional absence, not degradation.
    degraded = bool(unhealthy or restarting)
    return ResourceHealth(
        status="degraded" if degraded else "ok", detail={"containers": containers}
    )


def _norm_services(raw: dict[str, Any]) -> ResourceHealth:
    systemd = raw.get("systemd")
    units = (
        [{"name": str(u), "status": str(s)} for u, s in systemd.items()]
        if isinstance(systemd, dict)
        else []
    )
    degraded = any(u["status"].lower() == "failed" for u in units)
    return ResourceHealth(status="degraded" if degraded else "ok", detail={"units": units})


def _norm_storage(raw: dict[str, Any]) -> ResourceHealth:
    zpool = str(raw.get("zpool", ""))
    healthy = "healthy" in zpool.lower() and "ERROR" not in zpool
    if not zpool:  # nothing reported → assume ok, no pool to act on
        healthy = True
    pools = [{"name": "vmpool", "healthy": healthy, "detail": zpool}] if zpool else []
    return ResourceHealth(status="ok" if healthy else "degraded", detail={"pools": pools})


def _norm_vms(raw: dict[str, Any]) -> ResourceHealth:
    vms = raw.get("vms")
    norm = (
        [
            {"vmid": str(v.get("vmid", "")), "status": str(v.get("status", ""))}
            for v in vms
            if isinstance(v, dict)
        ]
        if isinstance(vms, list)
        else []
    )
    # No expected-state signal in /full → never auto-degrade (a stopped VM may be
    # intentional). VMs are observed, not auto-remediated, in v1.
    return ResourceHealth(status="ok", detail={"vms": norm})


def _norm_gpu(raw: dict[str, Any]) -> ResourceHealth:
    status = "down" if str(raw.get("status", "")).lower() == "error" else "ok"
    return ResourceHealth(status=status, detail={"gpus": raw.get("gpus", [])})


_NORMALIZERS = {
    "gpu": _norm_gpu,
    "storage": _norm_storage,
    "docker": _norm_docker,
    "vms": _norm_vms,
    "services": _norm_services,
}


_ALLOWED = (
    "restart_container",
    "restart_stack",
    "restart_service",
    "vm_control",
    "docker_logs",
    "docker_prune",
    "ollama_list",
    "ollama_pull",
    "snapraid_status",
)


class HostHealthAction:
    """infra_action provider: POST /action/{name}, tier-gated through approval."""

    def __init__(
        self,
        http: AsyncHttp,
        *,
        autonomy: Literal["approve_all", "auto_safe", "detect_only"] = "auto_safe",
        approval: Approval | None = None,
    ) -> None:
        self._http = http
        self._autonomy = autonomy
        self._approval = approval

    @property
    def name(self) -> str:
        return "host_health"

    @property
    def slot(self) -> str:
        return "infra_action"

    @property
    def trust_tier(self) -> str:
        return "t0"

    def requires(self) -> tuple[str, ...]:
        return ("HOST_HEALTH_URL", "HOST_HEALTH_TOKEN")

    async def healthcheck(self) -> ProviderHealth:
        try:
            await self._http.get_json("/health")
            return ProviderHealth(healthy=True)
        except Exception as exc:
            return ProviderHealth(healthy=False, detail=str(exc))

    def allowed_actions(self) -> tuple[str, ...]:
        return _ALLOWED

    async def act(self, action: str, params: dict[str, Any]) -> ActionResult:
        if action not in _ALLOWED:
            return ActionResult(ok=False, detail=f"action '{action}' not in allowlist")

        tier = tier_for(action, params)

        if self._autonomy == "detect_only":
            return ActionResult(ok=False, detail="autonomy=detect_only: no actions executed")

        needs_approval = tier is ActionTier.DESTRUCTIVE or (
            tier is ActionTier.REVERSIBLE and self._autonomy != "auto_safe"
        )
        if needs_approval:
            if self._approval is None:
                return ActionResult(
                    ok=False,
                    blocked_pending_approval=True,
                    detail="approval required but no approval provider",
                )
            decision = await self._approval.request(
                ApprovalRequest(
                    action=action,
                    params=params,
                    tier=tier.value,
                    requester="infra_action",
                    rationale="",
                )
            )
            if not decision.approved:
                return ActionResult(
                    ok=False, blocked_pending_approval=True, detail="approval denied"
                )

        return await self._execute(action, params)

    async def _execute(self, action: str, params: dict[str, Any]) -> ActionResult:
        try:
            data = await self._http.post_json(f"/action/{action}", params)
        except Exception as exc:
            return ActionResult(ok=False, detail=str(exc))
        ok = str(data.get("status", "")).lower() != "error"
        return ActionResult(ok=ok, detail=str(data.get("detail", "")))
