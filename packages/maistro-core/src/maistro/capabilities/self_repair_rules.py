"""Diagnosis rule table for self_repair (SPEC-188).

Pure: maps a **normalized** InfraHealth snapshot (produced by the host_health
monitor's anti-corruption layer) to candidate RepairProposals. Every emitted
action is one already on the infra_action allowlist — diagnosis never
synthesizes new actions. Unknown symptoms produce an ``undiagnosed`` proposal
(recognized=False) so the loop escalates rather than guesses.

Policy is grounded in the host-health API's own classification:
  docker container state ∈ {healthy, unhealthy, restarting, stopped}
    - unhealthy  (Up but healthcheck failing) → restart_container (reversible)
    - restarting (crash-looping)              → propose-only: needs a human, not another kick
    - stopped    (Exited/Dead)                → ignored: intentional absence
  services units: status "failed"             → restart_service (reversible)
  storage pools:  healthy=False               → propose-only (data risk)
  vms / gpu: observed, not auto-remediated in v1 (no expected-state signal).
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.slots.infra import ActionTier, InfraHealth
from maistro.capabilities.slots.self_repair import RepairProposal

_DEGRADED = {"degraded", "down"}


def diagnose(health: InfraHealth) -> list[RepairProposal]:
    """Return one proposal per problem entity in the snapshot (empty if healthy)."""
    proposals: list[RepairProposal] = []
    for section, resource in health.resources.items():
        before = len(proposals)
        handler = _SECTION_HANDLERS.get(section)
        if handler is not None:
            proposals.extend(handler(resource.detail))
        # Section flagged degraded/down but no entity matched a rule → undiagnosed.
        if before == len(proposals) and resource.status in _DEGRADED:
            proposals.append(
                RepairProposal(
                    resource=section,
                    symptom="undiagnosed",
                    action=None,
                    tier="",
                    rationale=f"{section} {resource.status} with no recognized cause",
                    recognized=False,
                )
            )
    return proposals


def _items(detail: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = detail.get(key)
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []


def _diagnose_docker(detail: dict[str, Any]) -> list[RepairProposal]:
    out: list[RepairProposal] = []
    for c in _items(detail, "containers"):
        name = str(c.get("name", ""))
        state = str(c.get("state", "")).lower()
        if state == "unhealthy":
            out.append(
                RepairProposal(
                    resource=f"docker:{name}",
                    symptom="container unhealthy",
                    action="restart_container",
                    params={"name": name},
                    tier=ActionTier.REVERSIBLE.value,
                    rationale=f"container {name} Up but failing its healthcheck",
                )
            )
        elif state == "restarting":
            # Crash-loop: the host API flags these for human attention. Restarting
            # again would just feed the loop — propose-only, escalate.
            out.append(
                RepairProposal(
                    resource=f"docker:{name}",
                    symptom="container crash-looping",
                    action=None,
                    tier="",
                    rationale=f"container {name} restarting (crash-loop) — needs a human, not another kick",
                    recognized=True,
                )
            )
        # stopped / healthy → no proposal (stopped is intentional absence).
    return out


def _diagnose_services(detail: dict[str, Any]) -> list[RepairProposal]:
    out: list[RepairProposal] = []
    for u in _items(detail, "units"):
        if str(u.get("status", "")).lower() == "failed":
            name = str(u.get("name", ""))
            out.append(
                RepairProposal(
                    resource=f"service:{name}",
                    symptom="unit failed",
                    action="restart_service",
                    params={"name": name},
                    tier=ActionTier.REVERSIBLE.value,
                    rationale=f"systemd unit {name} failed",
                )
            )
    return out


def _diagnose_storage(detail: dict[str, Any]) -> list[RepairProposal]:
    # Storage degradation is data risk — recognized but never auto-acted.
    out: list[RepairProposal] = []
    for pool in _items(detail, "pools"):
        if pool.get("healthy") is False:
            name = str(pool.get("name", ""))
            out.append(
                RepairProposal(
                    resource=f"storage:{name}",
                    symptom="zpool not healthy",
                    action=None,
                    tier="",
                    rationale=f"pool {name} not healthy — human review (data risk)",
                    recognized=True,
                )
            )
    return out


_SECTION_HANDLERS = {
    "docker": _diagnose_docker,
    "services": _diagnose_services,
    "storage": _diagnose_storage,
    # vms / gpu: observed only in v1 — no auto-remediation rule.
}
