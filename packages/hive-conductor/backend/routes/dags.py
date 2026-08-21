from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from services.edit_lock import diff_dag_snapshots, mark_edited

from routes.audit import log_audit

router = APIRouter(tags=["dags"])


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
        edges=[
            DAGEdge(id=edge_id, from_node=entry_id, to_node=worker_id),
        ],
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
    """Phase 5 Signal #2: every successful PUT writes a `dag_edit` audit
    entry and marks the changed field paths as edit-locked. The
    optimizer's auto-apply path consults `edit_lock.is_locked()` before
    mutating any field, so manual user overrides win for
    `EDIT_LOCK_DAYS` (default 30) days."""
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
    # `updated_at` always changes; strip it from the diff so audit + lock
    # only see the user-meaningful fields.
    user = getattr(request.state, "user", None) or {}
    actor = str(user.get("id") or "system")
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
    removed = [n for n in dag.nodes if n.id == node_id]
    if not removed:
        raise HTTPException(status_code=404, detail="node not found")
    new_nodes = [n for n in dag.nodes if n.id != node_id]
    new_edges = [e for e in dag.edges if e.from_node != node_id and e.to_node != node_id]
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
        id=str(uuid4()), from_node=body.from_node, to_node=body.to_node, condition=body.condition
    )
    dag = dag.model_copy(update={"edges": [*dag.edges, edge], "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return edge.model_dump(mode="json")


@router.delete("/{dag_id}/edges/{edge_id}")
def remove_edge(dag_id: str, edge_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag = DAGFile(**stores.dags[dag_id])
    removed = [e for e in dag.edges if e.id == edge_id]
    if not removed:
        raise HTTPException(status_code=404, detail="edge not found")
    new_edges = [e for e in dag.edges if e.id != edge_id]
    dag = dag.model_copy(update={"edges": new_edges, "updated_at": _now()})
    stores.dags[dag_id] = dag.model_dump(mode="json")
    return removed[0].model_dump(mode="json")


@router.post("/{dag_id}/run")
async def run_dag(dag_id: str) -> dict:
    if dag_id not in stores.dags:
        raise HTTPException(status_code=404, detail="dag not found")
    dag_data = stores.dags[dag_id]
    log_audit("dag_run", "system", target=dag_id)
    exec_id = str(uuid4())
    try:
        import time as _time

        from services.dag_run_store import get_dag_run_store
        from services.graph_runner import execute_dag

        _start = _time.monotonic()
        store = get_dag_run_store()
        run = await store.start_run(run_id=exec_id)
        # Human-initiated run from the UI — interactive isolation floor (ADR-093)
        result = await execute_dag(dag_data, execution_mode="interactive")
        _elapsed_ms = int((_time.monotonic() - _start) * 1000)
        run.status = "completed"
        run.result = result
        # Store node results as events for eval-judge and UI
        for nid, nr in result.get("node_results", {}).items():
            await store.append_event(
                exec_id,
                event_type="pm_node_completed" if nr.get("success") else "pm_node_failed",
                role=nr.get("role", "worker"),
                capability=nid,
                payload={"source": "llm", "response": nr.get("response", "")[:2000]},
            )
        # Record node metrics (Signal #5)
        try:
            from services.node_metrics_store import NodeObservation
            from services.node_metrics_store import get_store as get_metrics

            metrics = get_metrics()
            for nid, nr in result.get("node_results", {}).items():
                metrics.append(
                    NodeObservation(
                        run_id=exec_id,
                        node_id=nid,
                        node_kind=nr.get("role", ""),
                        project_id="",
                        dag_id=dag_id,
                        phase="COMPLETED" if nr.get("success") else "FAILED",
                        latency_ms=_elapsed_ms // max(result.get("cycles", 1), 1),
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=0.0,
                        model_used=dag_data.get("nodes", [{}])[0].get("model", "gemini-3.5-flash"),
                    )
                )
        except Exception:
            pass
        return {"status": "completed", "execution_id": exec_id, "result": result}
    except Exception as exc:
        import logging

        logging.getLogger("hive.dags").warning("Graph execution failed: %s", exc)
        return {"status": "failed", "execution_id": exec_id, "error": str(exc)}


@router.post("/run-champion")
async def run_champion() -> dict:
    try:
        from services.graph_runner import execute_champion

        result = await execute_champion()
        return {"execution_id": str(uuid4()), "result": result}
    except Exception as exc:
        import logging

        logging.getLogger("hive.dags").warning("Champion execution failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
