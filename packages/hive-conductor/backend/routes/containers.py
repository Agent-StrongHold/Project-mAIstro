from __future__ import annotations

import contextlib
import logging
import os
import re
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from models.schemas import Container
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["containers"])

logger = logging.getLogger(__name__)

# The Conductor's own (trusted, admin-only) container-management feature talks to
# the host Docker daemon. This is NOT the untrusted/sandbox path ADR-058 governs —
# agent/sandbox code uses SandboxProtocol (SPEC-190) and never touches this socket.
# nosemgrep: maistro-mounted-docker-socket -- trusted admin container management, not sandbox code
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")


# Docker identifiers: a leading alphanumeric followed by alphanumerics, "_",
# "." or "-". This single alternative already covers hex ids, since a 12-64 char
# hex string is itself a valid name — an earlier version spelled the hex form out
# as a separate branch, which was dead and made the grammar look stricter than it
# is. Short id prefixes are accepted, and that is correct: the Docker API takes
# them.
#
# Nothing outside this set may reach the URL builders below, because every
# handler interpolates the path parameter straight into a Docker Engine API URL
# and the daemon speaks that API over a socket with no auth of its own. The
# excluded characters are the whole point: "/", "?", "#", "%", ":" and "@" turn
# a container reference into a request for a *different* daemon endpoint. Note
# uvicorn percent-decodes the path before routing, so "%3F" arrives as a literal
# "?" here — `/v1/containers/x%3Fall%3D1` was a real query-injection vector, not
# just the ".." traversal the original comment described. Validate once at the
# boundary rather than escaping per call site: there are six of them, and a
# seventh will be added without the escape.
_CONTAINER_ID_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")


def _validate_container_id(container_id: str) -> str:
    """Return `container_id` if it is a well-formed Docker id/name, else 400."""
    if not _CONTAINER_ID_RE.match(container_id):
        raise HTTPException(status_code=400, detail="Invalid container id")
    return container_id


def _docker_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET), timeout=10.0)


async def _fetch_container_stats(container_id: str) -> dict:
    async with _docker_client() as client:
        with contextlib.suppress(Exception):
            r = await client.get(f"http://localhost/containers/{container_id}/stats?stream=false")
            if r.status_code == 200:
                return r.json()
    return {}


def _parse_created(raw: dict) -> datetime:
    created = raw.get("Created", "")
    if isinstance(created, (int, float)):
        return datetime.fromtimestamp(created, UTC)
    if isinstance(created, str) and created:
        with contextlib.suppress(ValueError, TypeError):
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _parse_started_at(raw: dict) -> datetime | None:
    state = raw.get("State")
    val = state.get("StartedAt") if isinstance(state, dict) else raw.get("StartedAt")
    if not isinstance(val, str) or not val or val == "0001-01-01T00:00:00Z":
        return None
    with contextlib.suppress(ValueError, TypeError):
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _parse_ports(raw: dict) -> list[dict]:
    ports: list[dict] = []
    for p in raw.get("Ports", []):
        entry: dict = {"container": p.get("PrivatePort")}
        if p.get("PublicPort") is not None:
            entry["host"] = p["PublicPort"]
        ports.append(entry)
    return ports


_STATUS_MAP = {
    "running": "running",
    "restarting": "restarting",
}


def _parse_state(raw: dict) -> str:
    state = raw.get("State", "unknown")
    return _STATUS_MAP.get(state, "stopped")


def _extract_stats(stats: dict | None) -> tuple[float, float, float, float, float]:
    if not stats:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    cpu_delta = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    cpu_system = stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    system_delta = stats.get("cpu_stats", {}).get("system_cpu_usage", 0) - stats.get(
        "precpu_stats", {}
    ).get("system_cpu_usage", 0)
    cpu_usage = (
        round(((cpu_delta - cpu_system) / system_delta) * 100.0, 2)
        if system_delta > 0 and cpu_delta > cpu_system
        else 0.0
    )

    mem = stats.get("memory_stats", {})
    mem_usage = round(mem.get("usage", 0) / (1024 * 1024), 2)
    mem_limit = round(mem.get("limit", 0) / (1024 * 1024), 2)

    rx = tx = 0.0
    for ndata in stats.get("networks", {}).values():
        rx += ndata.get("rx_bytes", 0)
        tx += ndata.get("tx_bytes", 0)
    return (
        cpu_usage,
        mem_usage,
        mem_limit,
        round(rx / (1024 * 1024), 2),
        round(tx / (1024 * 1024), 2),
    )


def _map_container(raw: dict, stats: dict | None = None) -> Container:
    cid = raw.get("Id", "")[:12]
    names = raw.get("Names", [])
    name = names[0].lstrip("/") if names else cid
    cpu_usage, mem_usage, mem_limit, net_rx, net_tx = _extract_stats(stats)

    return Container(
        id=cid,
        name=name,
        image=raw.get("Image", ""),
        status=_parse_state(raw),
        ports=_parse_ports(raw),
        cpu_usage=cpu_usage,
        memory_usage_mb=mem_usage,
        memory_limit_mb=mem_limit,
        network_rx_mb=net_rx,
        network_tx_mb=net_tx,
        created_at=_parse_created(raw),
        started_at=_parse_started_at(raw),
        labels=raw.get("Labels") or {},
    )


@router.get("", response_model=list[Container])
async def list_containers() -> list[Container]:
    if not os.path.exists(DOCKER_SOCKET):
        logger.warning("Docker socket %s not available, returning empty list", DOCKER_SOCKET)
        return []
    try:
        async with _docker_client() as client:
            r = await client.get("http://localhost/containers/json?all=true")
            r.raise_for_status()
            raw_list = r.json()
    except Exception:
        logger.warning("Failed to query Docker API, returning empty list", exc_info=True)
        return []

    results: list[Container] = []
    for raw in raw_list:
        results.append(_map_container(raw, None))
    return results


@router.get("/{container_id}", response_model=Container)
async def get_container(container_id: str) -> Container:
    _validate_container_id(container_id)
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.get(f"http://localhost/containers/{container_id}/json")
            r.raise_for_status()
            raw = r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail="container not found"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc

    stats = await _fetch_container_stats(container_id)
    return _map_container(raw, stats)


@router.post("/{container_id}/start")
async def start_container(container_id: str) -> dict:
    _validate_container_id(container_id)
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.post(f"http://localhost/containers/{container_id}/start")
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="start failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc
    return {"status": "started", "id": container_id}


@router.post("/{container_id}/stop")
async def stop_container(container_id: str) -> dict:
    _validate_container_id(container_id)
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.post(f"http://localhost/containers/{container_id}/stop")
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="stop failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc
    return {"status": "stopped", "id": container_id}


@router.post("/{container_id}/restart")
async def restart_container(container_id: str) -> dict:
    _validate_container_id(container_id)
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.post(f"http://localhost/containers/{container_id}/restart")
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="restart failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc
    return {"status": "restarted", "id": container_id}


@router.delete("/{container_id}")
async def delete_container(container_id: str) -> None:
    _validate_container_id(container_id)
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.delete(f"http://localhost/containers/{container_id}?force=true")
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="remove failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc


@router.get("/{container_id}/logs")
async def get_container_logs(container_id: str, tail: int = 100) -> dict:
    _validate_container_id(container_id)
    # `tail` is also interpolated into the Docker URL. FastAPI coerces it to an
    # int, so it cannot carry a separator, but an unbounded value still lets a
    # caller ask the daemon to stream an entire log history into memory.
    tail = max(1, min(tail, 10_000))
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        async with _docker_client() as client:
            r = await client.get(
                f"http://localhost/containers/{container_id}/logs?stdout=true&stderr=true&tail={tail}"
            )
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="logs not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker API error: {exc}") from exc

    return {"id": container_id, "logs": r.text}


class BuildBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    dockerfile: str


@router.post("/build")
def build_container(body: BuildBody) -> dict:
    return {"status": "building", "log": "Building..."}


class SuggestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str


@router.post("/suggest")
def suggest_dockerfile(body: SuggestBody) -> dict:
    return {
        "dockerfile": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nCMD ["python", "main.py"]'
    }
