from __future__ import annotations

import logging
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


async def _record_run_projection(*, dag_id: str, user_id: str, result: dict[str, Any]) -> None:
    """Mirror canonical Run facts into the bounded Recent Runs projection.

    The projection uses the canonical Run id as its own key and copies the
    canonical terminal status. It cannot mint a second execution identity or
    recompute whether the DAG succeeded.
    """
    run_id = str(result.get("run_id") or "")
    if not run_id:
        return
    try:
        from services.dag_run_store import get_dag_run_store

        store = get_dag_run_store()
        await store.start_run(
            run_id=run_id,
            canonical_run_id=run_id,
            dag_id=dag_id,
            user_id=user_id,
        )
        for node_id, node_result in result.get("node_results", {}).items():
            await store.append_event(
                run_id,
                event_type=(
                    "pm_node_completed" if node_result.get("success") else "pm_node_failed"
                ),
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
async def run_dag(dag_id: str, request: Request) -> dict:
    """Execute through one canonical Run and project its facts for the UI."""
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag_data = stores.dags[dag_id]
    actor = _actor(request)
    log_audit("dag_run", actor, target=dag_id)

    from services.graph_runner import CanonicalDagExecutionError, execute_dag

    try:
        result = await execute_dag(
            dag_data,
            user_id=actor,
            execution_mode="interactive",
        )
    except CanonicalDagExecutionError as exc:
        result = exc.result
        await _record_run_projection(dag_id=dag_id, user_id=actor, result=result)
        run_id = result.get("run_id")
        return {
            "status": result.get("status", "failed"),
            "execution_id": run_id,
            "run_id": run_id,
            "error": str(exc),
            "result": result,
        }
    except Exception as exc:
        logger.warning("Graph execution failed: %s", exc)
        return {"status": "failed", "error": str(exc)}

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
