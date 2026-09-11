from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from services.edit_lock import diff_dag_snapshots, mark_edited

from routes.audit import log_audit

router = APIRouter(tags=["dags"])
logger = logging.getLogger("hive.dags")


class DAGNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    role: str
    name: str
    agent_id: str | None = None
    model: str | None = None
    strategy: Literal["react", "plan_execute", "direct", "delegate"] = "react"
    prompt: str | None = None
    config: dict[str, Any] = {}


class DAGEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    from_node: str
    to_node: str | None = None
    condition: str | None = None


class DAGFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str
    nodes: list[DAGNode]
    edges: list[DAGEdge]
    entry_node: str | None = None
    max_cycles: int = 10
    run_scout: bool = False
    status: Literal["draft", "active", "archived"] = "draft"
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or "system")


async def _resolve_run_scope(
    dag_data: Mapping[str, Any], request: Request, workspace_id: str | None
) -> tuple[str, str]:
    """Resolve and authorize the scope used by canonical Run admission.

    A request-selected Workspace is checked at the existing Hive authorization
    boundary before the canonical resolver maps it to its Root Project. The
    resolver remains the single source for the deployment default and for
    project selection; this route only supplies an already-authorized request
    choice when one exists.
    """
    selected_workspace = (
        workspace_id
        or getattr(request.state, "workspace_id", None)
        or dag_data.get("workspace_id")
        or ""
    )
    selected_workspace = str(selected_workspace).strip()
    if selected_workspace:
        from services.dag_execution_scope import (
            DagWorkspaceSelectionError,
            authorize_hive_dag_workspace,
        )

        try:
            authorize_hive_dag_workspace(
                workspace_id=selected_workspace,
                user_id=_actor(request),
            )
        except DagWorkspaceSelectionError as exc:
            raise HTTPException(status_code=403, detail="Workspace not found") from exc

    selected_project = (
        getattr(request.state, "project_id", None) or dag_data.get("project_id") or ""
    )
    from services.canonical_dag_runner import resolve_execution_scope

    return await resolve_execution_scope(
        dag_data,
        workspace_id=selected_workspace or None,
        project_id=str(selected_project).strip() or None,
    )


def _value_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _registered_run_result(graph: Any, record: Any) -> dict[str, Any]:
    """Project canonical Run/NodeRun facts into the existing DAG response shape."""
    run = record.run
    status = str(getattr(getattr(run, "status", None), "value", run.status) or "failed")
    graph_nodes = {node.node_id: node for node in getattr(graph, "nodes", ())}
    node_results: dict[str, dict[str, Any]] = {}
    for node_run in getattr(record, "node_runs", ()):
        node = graph_nodes.get(node_run.node_id)
        raw = _value_mapping(getattr(node, "metadata", {}).get("legacy_node"))
        output = _value_mapping(getattr(node_run, "result", None))
        response = output.get("response")
        if response is None and output:
            response = json.dumps(output, default=str)
        if response is None:
            response = getattr(node_run, "error", None) or ""
        node_status = str(
            getattr(getattr(node_run, "status", None), "value", node_run.status) or "failed"
        )
        node_results[node_run.node_id] = {
            "role": str(output.get("role") or raw.get("role") or "worker"),
            "response": str(response),
            # This is deliberately the canonical NodeRun status, not a second
            # interpretation of an executor result payload.
            "success": node_status == "completed",
            "model": output.get("model") or raw.get("model"),
            **({"isolation": output["isolation"]} if output.get("isolation") else {}),
        }
    graph_state = getattr(record, "graph_state", None)
    blackboard = getattr(graph_state, "blackboard_snapshot", {})
    annotations = blackboard.get("node_annotations", {}) if isinstance(blackboard, Mapping) else {}
    result: dict[str, Any] = {
        "status": status,
        "run_id": record.run_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "cycles": getattr(graph_state, "cycle", 0),
        "node_results": node_results,
        "annotations": dict(annotations) if isinstance(annotations, Mapping) else {},
    }
    error = getattr(run, "error", None)
    if error:
        result["error"] = str(error)
    return result


async def _record_run_projection(*, dag_id: str, user_id: str, result: dict[str, Any]) -> None:
    """Mirror canonical Run facts into the bounded Recent Runs projection.

    The projection uses the canonical Run id as its own key and copies the
    canonical Run status. It cannot mint a second execution identity or
    recompute whether the DAG succeeded.
    """
    run_id = str(result.get("run_id") or "")
    if not run_id:
        return
    try:
        from services.dag_run_store import get_dag_run_store

        store = get_dag_run_store()
        # The result carries the canonical Workspace/Project the Run was
        # admitted into (`_registered_run_result` mirrors
        # `Run.workspace_id`/`Run.project_id`), so the projection row is born
        # with the scope inspection will later authorize it at (#1174).
        await store.start_run(
            run_id=run_id,
            canonical_run_id=run_id,
            dag_id=dag_id,
            user_id=user_id,
            workspace_id=str(result.get("workspace_id") or ""),
            project_id=str(result.get("project_id") or ""),
        )
        run_status = str(result.get("status") or "failed")
        for node_id, node_result in result.get("node_results", {}).items():
            # A parked NodeRun is not a failed NodeRun. The projection keeps
            # the old started event for non-terminal canonical work, while a
            # terminal Run's unsuccessful node is presented as failed.
            event_type = (
                "pm_node_completed"
                if node_result.get("success")
                else (
                    "pm_node_started"
                    if run_status in {"created", "queued", "running", "waiting", "paused"}
                    else "pm_node_failed"
                )
            )
            await store.append_event(
                run_id,
                event_type=event_type,
                role=node_result.get("role", "worker"),
                capability=node_id,
                payload={
                    "source": "canonical_node_run",
                    "response": node_result.get("response", "")[:2000],
                },
            )
        await store.finish_run(
            run_id,
            status=str(result.get("status") or "failed"),
            result=result,
        )
    except Exception:
        logger.warning(
            "dag_run_projection_not_recorded run_id=%s dag_id=%s",
            run_id,
            dag_id,
            exc_info=True,
        )


@router.get("")
def list_dags() -> list[dict]:
    return list(stores.dags.values())


@router.get("/{dag_id}")
def get_dag(dag_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    return stores.dags[dag_id]


class CreateDAGBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""


@router.post("", status_code=201)
def create_dag(body: CreateDAGBody) -> dict:
    t = _now()
    entry_id = str(uuid4())
    worker_id = str(uuid4())
    edge_id = str(uuid4())
    dag_id = str(uuid4())
    dag = DAGFile(
        id=dag_id,
        name=body.name,
        description=body.description,
        nodes=[
            DAGNode(id=entry_id, role="queen", name="Conductor"),
            DAGNode(id=worker_id, role="worker", name="Worker"),
        ],
        edges=[DAGEdge(id=edge_id, from_node=entry_id, to_node=worker_id)],
        entry_node=entry_id,
        max_cycles=10,
        run_scout=False,
        status="draft",
        created_at=t,
        updated_at=t,
    )
    stores.dags[dag_id] = dag.model_dump(mode="json")
    log_audit("dag_create", "system", target=dag_id, detail={"name": body.name})
    return dag.model_dump(mode="json")


class UpdateDAGBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    nodes: list[DAGNode] | None = None
    edges: list[DAGEdge] | None = None
    entry_node: str | None = None
    max_cycles: int | None = None
    run_scout: bool | None = None
    status: Literal["draft", "active", "archived"] | None = None


@router.put("/{dag_id}")
def update_dag(dag_id: str, body: UpdateDAGBody, request: Request) -> dict:
    """Persist a DAG edit and lock the fields the user changed."""
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    old_snapshot = dict(stores.dags[dag_id])
    dag = DAGFile(**stores.dags[dag_id])
    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = _now()
    dag = dag.model_copy(update=updates)
    new_snapshot = dag.model_dump(mode="json")
    stores.dags[dag_id] = new_snapshot

    changed_paths = diff_dag_snapshots(old_snapshot, new_snapshot)
    actor = _actor(request)
    if changed_paths:
        mark_edited(dag_id, changed_paths, user_id=actor)
        log_audit(
            action="dag_edit",
            actor=actor,
            target=dag_id,
            detail={"changed": changed_paths, "field_count": len(changed_paths)},
        )
    return new_snapshot


@router.delete("/{dag_id}", status_code=204)
def delete_dag(dag_id: str) -> None:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    stores.dags.pop(dag_id)


@router.post("/{dag_id}/activate")
def activate_dag(dag_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    dag = dag.model_copy(update={"status": "active", "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    log_audit("dag_activate", "system", target=dag_id)
    return dag.model_dump(mode="json")


class AddNodeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    name: str
    agent_id: str | None = None
    model: str | None = None
    strategy: Literal["react", "plan_execute", "direct", "delegate"] = "react"
    prompt: str | None = None
    config: dict[str, Any] = {}


@router.post("/{dag_id}/nodes")
def add_node(dag_id: str, body: AddNodeBody) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    node = DAGNode(
        id=str(uuid4()),
        role=body.role,
        name=body.name,
        agent_id=body.agent_id,
        model=body.model,
        strategy=body.strategy,
        prompt=body.prompt,
        config=body.config,
    )
    dag = dag.model_copy(update={"nodes": [*dag.nodes, node], "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return node.model_dump(mode="json")


@router.delete("/{dag_id}/nodes/{node_id}")
def remove_node(dag_id: str, node_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    removed = [node for node in dag.nodes if node.id == node_id]
    if not removed:
        raise HTTPException(status_code=404, detail="node not found")
    new_nodes = [node for node in dag.nodes if node.id != node_id]
    new_edges = [
        edge for edge in dag.edges if edge.from_node != node_id and edge.to_node != node_id
    ]
    dag = dag.model_copy(update={"nodes": new_nodes, "edges": new_edges, "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return removed[0].model_dump(mode="json")


class AddEdgeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_node: str
    to_node: str | None = None
    condition: str | None = None


@router.post("/{dag_id}/edges")
def add_edge(dag_id: str, body: AddEdgeBody) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    edge = DAGEdge(
        id=str(uuid4()),
        from_node=body.from_node,
        to_node=body.to_node,
        condition=body.condition,
    )
    dag = dag.model_copy(update={"edges": [*dag.edges, edge], "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return edge.model_dump(mode="json")


@router.delete("/{dag_id}/edges/{edge_id}")
def remove_edge(dag_id: str, edge_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    removed = [edge for edge in dag.edges if edge.id == edge_id]
    if not removed:
        raise HTTPException(status_code=404, detail="edge not found")
    new_edges = [edge for edge in dag.edges if edge.id != edge_id]
    dag = dag.model_copy(update={"edges": new_edges, "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return removed[0].model_dump(mode="json")


@router.post("/{dag_id}/run")
async def run_dag(
    dag_id: str,
    request: Request,
    workspace_id: str | None = None,
) -> dict:
    """Execute a saved DAG through the registered canonical Run path."""
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag_data = stores.dags[dag_id]
    actor = _actor(request)
    log_audit("dag_run", actor, target=dag_id)

    from services.dag_agents import get_registry, run_registered_dag

    try:
        resolved_workspace, resolved_project = await _resolve_run_scope(
            dag_data, request, workspace_id
        )
        # The saved DAG is the product's editable definition. Registering its
        # snapshot first makes this route use the same descriptor -> template
        # projection as schedules and other registered-DAG producers.
        get_registry().register(dict(dag_data))
        graph, record = await run_registered_dag(
            dag_id,
            workspace_id=resolved_workspace,
            project_id=resolved_project,
            user_id=actor,
            provenance={"admission_source": "hive_dag_route", "execution_mode": "interactive"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Registered DAG execution failed: %s", exc)
        return {"status": "failed", "error": str(exc)}

    result = _registered_run_result(graph, record)
    await _record_run_projection(dag_id=dag_id, user_id=actor, result=result)
    run_id = result["run_id"]
    return {
        "status": result["status"],
        "execution_id": run_id,
        "run_id": run_id,
        "result": result,
    }


@router.post("/run-champion")
async def run_champion() -> dict:
    try:
        from services.graph_runner import execute_champion

        result = await execute_champion()
        run_id = result.get("run_id")
        return {"execution_id": run_id, "run_id": run_id, "result": result}
    except Exception as exc:
        logger.warning("Champion execution failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
