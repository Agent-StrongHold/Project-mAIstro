"""Diagnosis rule table — normalized symptom → candidate remediation (SPEC-188).

`diagnose()` is pure: a normalized InfraHealth in (as produced by the host_health
monitor), RepairProposals out, no side effects.
"""

from __future__ import annotations

from maistro.capabilities.self_repair_rules import diagnose
from maistro.capabilities.slots.infra import InfraHealth, ResourceHealth


def _health(**sections: ResourceHealth) -> InfraHealth:
    return InfraHealth(ts="2026-05-30T00:00:00Z", resources=dict(sections))


def test_healthy_snapshot_yields_no_proposals() -> None:
    health = _health(
        docker=ResourceHealth("ok", {"containers": [{"name": "litellm", "state": "healthy"}]}),
        storage=ResourceHealth("ok", {"pools": [{"name": "vmpool", "healthy": True}]}),
    )
    assert diagnose(health) == []


def test_unhealthy_container_proposes_restart_container_reversible() -> None:
    health = _health(
        docker=ResourceHealth(
            "degraded", {"containers": [{"name": "litellm", "state": "unhealthy"}]}
        )
    )
    (p,) = diagnose(health)
    assert p.resource == "docker:litellm"
    assert p.action == "restart_container"
    assert p.params == {"name": "litellm"}
    assert p.tier == "reversible"
    assert p.recognized is True


def test_restarting_container_is_propose_only_not_kicked() -> None:
    # Crash-loop: recognized, but never auto-restarted (would feed the loop).
    health = _health(
        docker=ResourceHealth(
            "degraded", {"containers": [{"name": "crashy", "state": "restarting"}]}
        )
    )
    (p,) = diagnose(health)
    assert p.resource == "docker:crashy"
    assert p.action is None
    assert p.recognized is True
    assert "crash-loop" in p.rationale


def test_stopped_container_is_ignored() -> None:
    # Intentional absence — not in auto-remediation scope.
    health = _health(
        docker=ResourceHealth("ok", {"containers": [{"name": "oldjob", "state": "stopped"}]})
    )
    assert diagnose(health) == []


def test_failed_service_proposes_restart_service() -> None:
    health = _health(
        services=ResourceHealth(
            "degraded", {"units": [{"name": "code-server@root", "status": "failed"}]}
        )
    )
    (p,) = diagnose(health)
    assert p.resource == "service:code-server@root"
    assert p.action == "restart_service"
    assert p.params == {"name": "code-server@root"}
    assert p.tier == "reversible"


def test_active_service_is_ignored() -> None:
    health = _health(
        services=ResourceHealth("ok", {"units": [{"name": "ollama", "status": "active"}]})
    )
    assert diagnose(health) == []


def test_degraded_storage_is_propose_only() -> None:
    health = _health(
        storage=ResourceHealth("degraded", {"pools": [{"name": "vmpool", "healthy": False}]})
    )
    (p,) = diagnose(health)
    assert p.resource == "storage:vmpool"
    assert p.action is None  # never auto-acted — data risk
    assert p.recognized is True
    assert "vmpool" in p.rationale


def test_docker_error_section_is_undiagnosed() -> None:
    # docker daemon down → section "down", no containers → undiagnosed, escalate.
    health = _health(docker=ResourceHealth("down", {"error": "docker daemon down"}))
    (p,) = diagnose(health)
    assert p.action is None
    assert p.recognized is False


def test_vms_and_gpu_are_observed_not_diagnosed() -> None:
    health = _health(
        vms=ResourceHealth("ok", {"vms": [{"vmid": "101", "status": "stopped"}]}),
        gpu=ResourceHealth("ok", {"gpus": [{"name": "P40"}]}),
    )
    assert diagnose(health) == []


def test_multiple_problems_yield_multiple_proposals() -> None:
    health = _health(
        docker=ResourceHealth(
            "degraded",
            {
                "containers": [
                    {"name": "a", "state": "unhealthy"},
                    {"name": "b", "state": "healthy"},
                    {"name": "c", "state": "stopped"},
                ]
            },
        ),
        services=ResourceHealth("degraded", {"units": [{"name": "svc", "status": "failed"}]}),
    )
    resources = sorted(p.resource for p in diagnose(health))
    assert resources == ["docker:a", "service:svc"]
