"""WebSocket routes for real-time task/mission/DAG streaming."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

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


async def _stream_canonical_outcome(websocket: WebSocket, result: dict[str, Any]) -> None:
    """Project one canonical execution result onto the historical frames.

    The frame shape is the one ``execute_dag_streaming`` established and
    DagBuilder's Run button renders: ``node_complete`` per node, then one
    terminal frame whose ``run_id`` is the canonical Run id.
    """
    for node_id, node_result in result.get("node_results", {}).items():
        await websocket.send_json(
            {
                "status": "node_complete",
                "node_id": node_id,
                "role": node_result.get("role", "worker"),
                "response": node_result.get("response", ""),
                "success": bool(node_result.get("success")),
                "run_id": result.get("run_id"),
            }
        )
    final: dict[str, Any] = {
        "status": str(result.get("status") or "failed"),
        "run_id": result.get("run_id"),
    }
    if final["status"] == "completed":
        final["cycles"] = result.get("cycles", 0)
        final["annotations"] = result.get("annotations", {})
    else:
        final["error"] = str(result.get("error") or f"canonical Run ended {final['status']}")
    await websocket.send_json(final)


@router.websocket("/dags/{dag_id}/run")
async def stream_dag_run(websocket: WebSocket, dag_id: str) -> None:
    """Run a registered DAG and stream its canonical Run/NodeRun outcomes.

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

    #736 puts this socket — the shipped DagBuilder Run button — on the same
    registered-descriptor -> canonical Run seam as ``POST /v1/dags/{dag_id}/run``.
    The frames keep the historical streaming shape; every ``run_id`` is the
    canonical Run id, and the Recent Runs projection records the same identity
    the HTTP route records.
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
    user_id = str(user["id"])
    entry = dag_data.get("entry_node") or (
        dag_data.get("nodes", [{}])[0].get("id") if dag_data.get("nodes") else ""
    )
    from routes.dags import _execute_registered_dag, _public_failure, _record_run_projection

    try:
        await websocket.send_json(
            {"status": "started", "node_count": len(dag_data.get("nodes", [])), "entry": entry}
        )
        result = await _execute_registered_dag(
            dag_id,
            dag_data,
            user_id=user_id,
            selected_workspace=workspace_id or None,
            admission_source="hive_dag_ws_route",
        )
        await _record_run_projection(dag_id=dag_id, user_id=user_id, result=result)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Registered DAG execution failed", exc_info=exc)
        with contextlib.suppress(Exception):
            await websocket.send_json({"status": "failed", "error": _public_failure(exc)})
    else:
        await _stream_canonical_outcome(websocket, result)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("ws_close_failed (already closed): %s", exc)
