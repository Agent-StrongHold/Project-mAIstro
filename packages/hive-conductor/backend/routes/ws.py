"""WebSocket routes for real-time task/mission/DAG streaming."""

from __future__ import annotations

import logging

import stores
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from middleware.auth import origin_allowed, principal_has_permission, resolve_principal
from services.dag_execution_scope import DagWorkspaceSelectionError, authorize_hive_dag_workspace

router = APIRouter(tags=["websocket"])

logger = logging.getLogger("hive.routes.ws")

# Starlette's BaseHTTPMiddleware — which AuthMiddleware subclasses — only sees
# scope["type"] == "http". WebSocket handshakes bypass it entirely, so every
# route here has to authenticate for itself; there is no middleware behind us.
# 1008 is the RFC 6455 "policy violation" close code.
_POLICY_VIOLATION = 1008


async def _authenticate(websocket: WebSocket, permission: str | None = None) -> dict | None:
    """Resolve the caller before `accept()`, or close the handshake.

    Closing *before* accepting makes Starlette answer the handshake with an
    HTTP 403 rather than completing the upgrade and then hanging up, so an
    unauthenticated client never gets a socket at all.
    """
    # CORS never applies to a WebSocket handshake — the browser sends it with
    # cookies attached and no preflight — so the Origin check that CORSMiddleware
    # performs for HTTP has to be repeated here or any page the user visits can
    # open an authenticated socket against this server (cross-site WebSocket
    # hijacking). Non-browser callers send no Origin and are unaffected.
    if not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
        await websocket.close(code=_POLICY_VIOLATION, reason="Origin not allowed")
        return None
    user = resolve_principal(websocket.cookies, websocket.headers.get("authorization"))
    if user is None:
        await websocket.close(code=_POLICY_VIOLATION, reason="Authentication required")
        return None
    if permission is not None and not principal_has_permission(user, permission):
        await websocket.close(code=_POLICY_VIOLATION, reason=f"Permission '{permission}' required")
        return None
    return user


@router.websocket("/tasks/{task_id}")
async def stream_task(websocket: WebSocket, task_id: str) -> None:
    user = await _authenticate(websocket)
    if user is None:
        return
    await websocket.accept()
    try:
        from services.engine import get_engine

        engine = get_engine()
        async for event in engine.iter_task_events(task_id, user_id=str(user["id"])):
            await websocket.send_json(event)
            if event["status"] in ("completed", "failed"):
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        try:
            await websocket.close()
        except Exception as _exc:
            logger.warning(
                "error_swallowed file=%s line=%d: %s",
                "packages/hive-conductor/backend/routes/ws.py",
                30,
                _exc,
            )


@router.websocket("/dags/{dag_id}/run")
async def stream_dag_run(websocket: WebSocket, dag_id: str) -> None:
    """Run a DAG and stream node-by-node progress over WebSocket.

    Gated on `dags.write`, matching `POST /v1/dags` in the HTTP middleware's
    `_PROTECTED_OPS`: this endpoint *executes* the graph, and its nodes include
    harness and synth-DAG kinds. Leaving it ungated made the socket a bypass of
    the elevation the equivalent HTTP route requires.

    #766 begins the product-to-canonical scope convergence at the request
    boundary. An explicit ``workspace_id`` is treated as a selection only and
    is authorized before ``accept()``. Omission temporarily preserves the
    legacy client while DagBuilder is moved onto this contract; it must become
    required before #766 can close. Canonical Project resolution is deliberately
    not invented here while #37 still owns the duplicate Hive Workspace store.
    """
    user = await _authenticate(websocket, permission="dags.write")
    if user is None:
        return

    workspace_id = (websocket.query_params.get("workspace_id") or "").strip()
    if workspace_id:
        try:
            authorize_hive_dag_workspace(workspace_id=workspace_id, user_id=str(user["id"]))
        except DagWorkspaceSelectionError:
            await websocket.close(code=_POLICY_VIOLATION, reason="Workspace not found")
            return

    await websocket.accept()
    if dag_id not in stores.dags:
        await websocket.send_json({"error": "dag not found"})
        await websocket.close()
        return

    dag_data = stores.dags[dag_id]
    try:
        from services.graph_runner import execute_dag_streaming

        async for event in execute_dag_streaming(dag_data):
            await websocket.send_json(event)
            if event.get("status") in ("completed", "failed"):
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await websocket.send_json({"status": "failed", "error": str(exc)})
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("ws_close_failed (already closed): %s", exc)
