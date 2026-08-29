from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import MCPServer, MCPTool
from pydantic import BaseModel, ConfigDict

from maistro.http import shared_client
from maistro.security.outbound import OutboundBlockedError, outbound_origin
from maistro.security.ssrf import OPERATIONAL_BLOCKS

router = APIRouter(tags=["mcp"])

logger = logging.getLogger(__name__)

#: Per-request ceiling on concurrent MCP health checks. A single GET /servers
#: used to issue one request per stored server simultaneously.
HEALTH_FANOUT_LIMIT = 8

#: A health check only needs the status line. Kept short so one unresponsive
#: server cannot hold the whole listing open.
HEALTH_TIMEOUT_SECONDS = 3.0


def _user_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    return str(uid) if uid else None


async def _health_check(server: MCPServer, *, user_id: str | None = None) -> MCPServer:
    from services.mcp_client import test_mcp_server
    from services.mcp_defaults import is_atlassian_rovo_url

    if is_atlassian_rovo_url(server.url):
        result = await test_mcp_server(server.id, user_id=user_id, url=server.url)
        status = "connected" if result.get("ok") else "connecting"
        return server.model_copy(
            update={
                "status": status,
                "last_ping": datetime.now(UTC),
            }
        )
    now = datetime.now(UTC)
    try:
        async with shared_client(timeout=HEALTH_TIMEOUT_SECONDS) as client:
            r = await client.get(server.url)
            if r.status_code < 500:
                return server.model_copy(
                    update={"status": "connected", "last_ping": now, "last_error": None}
                )
    except OutboundBlockedError as exc:
        # Not every block is a refusal. The guard fails closed on a host it
        # cannot resolve, which is the same situation as a server being down --
        # so `OPERATIONAL_BLOCKS` falls through to `disconnected` below, and
        # only an actual policy decision becomes `error`.
        #
        # Collapsing the two would replace one inaccuracy with another: a
        # standing authorization decision hidden behind a transient-looking
        # status, or a stopped server reported as a configuration fault (#368).
        #
        # The origin is logged, never the full URL: a stored MCP URL can carry
        # a token in its query string or userinfo.
        if exc.reason not in OPERATIONAL_BLOCKS:
            logger.warning(
                "mcp health refused by outbound policy: server=%s origin=%s reason=%s",
                server.id,
                outbound_origin(server.url),
                exc.reason or "unspecified",
            )
            return server.model_copy(
                update={
                    "status": "error",
                    "last_ping": now,
                    "last_error": (
                        f"refused by outbound policy ({exc.reason or 'unspecified'}): "
                        f"the origin {outbound_origin(server.url)} is not configured "
                        f"for this deployment"
                    ),
                }
            )
        logger.info("mcp health check could not reach server=%s reason=%s", server.id, exc.reason)
    except httpx.HTTPError as exc:
        logger.info("mcp health check failed: server=%s error=%s", server.id, type(exc).__name__)
    except Exception:
        # Last resort, and deliberately not the blanket this replaced (#430).
        #
        # `POST /v1/mcp/servers` takes `url` as an unrestricted string, and
        # `list_servers` gathers over every stored record, so anything escaping
        # here fails the listing for *every* server rather than one row. Two
        # such escapes were live: `outbound_origin` re-parsing a URL the guard
        # had already refused, and `UnicodeError` from the resolver. Both are
        # fixed at their source; this is the net under the next one.
        #
        # It reports `error`, not `disconnected`, and logs at ERROR with a
        # traceback. The pre-#368 handler swallowed everything into
        # `disconnected` -- which reads as "start the server" and is the exact
        # defect #368 removed. A net that recreates it is not worth having.
        logger.exception("mcp health check raised unexpectedly: server=%s", server.id)
        return server.model_copy(
            update={
                "status": "error",
                "last_ping": now,
                "last_error": (
                    "this server could not be checked: the health check itself "
                    "failed. See the Conductor log for the cause."
                ),
            }
        )
    return server.model_copy(
        update={"status": "disconnected", "last_ping": now, "last_error": None}
    )


@router.get("/servers", response_model=list[MCPServer])
async def list_servers(request: Request) -> list[MCPServer]:
    """List every stored MCP server, health-checked with a bounded fan-out.

    The fan-out used to be `asyncio.gather` over the whole store, so one GET
    opened one connection per registered server at once. A caller who can add
    servers could therefore turn a single request into arbitrarily many
    concurrent outbound connections (#368). The semaphore caps that at
    `HEALTH_FANOUT_LIMIT` without changing the result.
    """
    uid = _user_id(request)
    servers = list(stores.mcp_servers.values())
    limit = asyncio.Semaphore(HEALTH_FANOUT_LIMIT)

    async def bounded(server: MCPServer) -> MCPServer:
        async with limit:
            return await _health_check(server, user_id=uid)

    checked = await asyncio.gather(*[bounded(s) for s in servers])
    for s in checked:
        stores.mcp_servers[s.id] = s
    return list(checked)


@router.get("/servers/{server_id}", response_model=MCPServer)
def get_server(server_id: str) -> MCPServer:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    return stores.mcp_servers[server_id]


class CreateServerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    url: str


@router.post("/servers", response_model=MCPServer, status_code=201)
def add_server(body: CreateServerBody) -> MCPServer:
    sid = str(uuid4())
    server = MCPServer(
        id=sid,
        name=body.name,
        description=body.description,
        url=body.url,
        status="connecting",
        tools_count=0,
    )
    stores.mcp_servers[sid] = server
    return server


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: str) -> None:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    stores.mcp_servers.pop(server_id)


@router.post("/servers/{server_id}/scan")
def scan_server(server_id: str) -> dict:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    return {"findings": [], "status": "clean"}


class McpTestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    server_id: str | None = None


@router.post("/test")
async def test_mcp_connection(body: McpTestBody, request: Request) -> dict:
    """Headless connectivity test (container runtime — uses Credentials vault)."""
    from services.mcp_client import test_mcp_server

    uid = _user_id(request)
    if body.server_id:
        if body.server_id not in stores.mcp_servers:
            raise HTTPException(status_code=404, detail="server not found")
        srv = stores.mcp_servers[body.server_id]
        return await test_mcp_server(srv.id, user_id=uid, url=srv.url)

    results = []
    for srv in stores.mcp_servers.values():
        results.append(await test_mcp_server(srv.id, user_id=uid, url=srv.url))
    return {"results": results}


@router.get("/tools", response_model=list[MCPTool])
def list_tools() -> list[MCPTool]:
    return list(stores.mcp_tools.values())


class DiscoverBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str


@router.post("/discover")
def discover_tools(body: DiscoverBody) -> dict:
    return {"tools": [], "status": "scanning"}
