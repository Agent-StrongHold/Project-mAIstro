from __future__ import annotations

from typing import Any

from maistro.capabilities.providers.host_health import HostHealthMonitor


class FakeHttp:
    def __init__(self, payload: dict[str, Any] | None, raise_exc: bool = False) -> None:
        self._payload, self._raise = payload, raise_exc

    async def get_json(self, path: str) -> dict[str, Any]:
        if self._raise:
            raise ConnectionError("unreachable")
        assert path == "/full"
        return self._payload or {}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return {}


async def test_snapshot_maps_sections():
    http = FakeHttp(
        {
            "timestamp": "2026-05-30T00:00:00Z",
            "gpu": {"ok": True},
            "storage": {"ok": True},
            "docker": {"unhealthy": []},
            "vms": [],
            "services": {},
        }
    )
    mon = HostHealthMonitor(http=http)
    health = await mon.snapshot()
    assert set(health.resources) == {"gpu", "storage", "docker", "vms", "services"}
    assert health.ts == "2026-05-30T00:00:00Z"


async def test_snapshot_unreachable_marks_down_not_raises():
    mon = HostHealthMonitor(http=FakeHttp(None, raise_exc=True))
    health = await mon.snapshot()
    assert all(r.status == "down" for r in health.resources.values())


# --- normalization against the real /full shape (SPEC-188 signals) ----------

_REAL_FULL = {
    "timestamp": "2026-05-30T10:00:00Z",
    "gpu": {"status": "ok", "gpus": [{"name": "P40", "temp_c": 45}]},
    "storage": {"mounts": [], "zpool": "all pools are healthy", "snapraid_summary": ""},
    "docker": {
        "total": 4,
        "running": 1,
        "unhealthy": ["litellm"],
        "restarting": ["crashy"],
        "stopped": ["oldjob"],
        "containers": [
            {"name": "litellm", "status": "Up 2h (unhealthy)", "healthy": False},
            {"name": "crashy", "status": "Restarting (1) 5s ago", "healthy": False},
            {"name": "oldjob", "status": "Exited (0) 3d ago", "healthy": False},
            {"name": "good", "status": "Up 5 days", "healthy": True},
        ],
    },
    "vms": {"vms": [{"vmid": "100", "name": "win", "status": "running"}], "lxcs": []},
    "services": {
        "systemd": {"ollama": "active", "code-server@root": "failed"},
        "conductor_stack": {},
    },
}


async def test_docker_containers_normalized_to_states():
    health = await HostHealthMonitor(http=FakeHttp(_REAL_FULL)).snapshot()
    docker = health.resources["docker"]
    states = {c["name"]: c["state"] for c in docker.detail["containers"]}
    assert states == {
        "litellm": "unhealthy",
        "crashy": "restarting",
        "oldjob": "stopped",
        "good": "healthy",
    }


async def test_docker_section_degraded_when_unhealthy_or_restarting():
    health = await HostHealthMonitor(http=FakeHttp(_REAL_FULL)).snapshot()
    assert health.resources["docker"].status == "degraded"


async def test_docker_section_ok_when_only_stopped_or_healthy():
    full = {
        "docker": {
            "stopped": ["oldjob"],
            "containers": [
                {"name": "oldjob", "status": "Exited (0)", "healthy": False},
                {"name": "good", "status": "Up 1d", "healthy": True},
            ],
        }
    }
    health = await HostHealthMonitor(http=FakeHttp(full)).snapshot()
    # stopped is intentional absence → not "degraded"
    assert health.resources["docker"].status == "ok"


async def test_docker_error_section_is_down():
    full = {"docker": {"status": "error", "detail": "ERROR: docker daemon down"}}
    health = await HostHealthMonitor(http=FakeHttp(full)).snapshot()
    assert health.resources["docker"].status == "down"


async def test_services_units_normalized_and_degraded_on_failed():
    health = await HostHealthMonitor(http=FakeHttp(_REAL_FULL)).snapshot()
    services = health.resources["services"]
    units = {u["name"]: u["status"] for u in services.detail["units"]}
    assert units["code-server@root"] == "failed"
    assert units["ollama"] == "active"
    assert services.status == "degraded"


async def test_storage_healthy_zpool_is_ok():
    health = await HostHealthMonitor(http=FakeHttp(_REAL_FULL)).snapshot()
    assert health.resources["storage"].status == "ok"
    assert all(p["healthy"] for p in health.resources["storage"].detail["pools"])


async def test_storage_degraded_zpool():
    full = {"storage": {"zpool": "pool: vmpool\n state: DEGRADED\n  scan: ...", "mounts": []}}
    health = await HostHealthMonitor(http=FakeHttp(full)).snapshot()
    assert health.resources["storage"].status == "degraded"
    assert not health.resources["storage"].detail["pools"][0]["healthy"]


async def test_vms_passthrough_ok():
    health = await HostHealthMonitor(http=FakeHttp(_REAL_FULL)).snapshot()
    vms = health.resources["vms"]
    assert vms.status == "ok"  # no expected-state signal → never auto-degraded
    assert vms.detail["vms"][0]["vmid"] == "100"
