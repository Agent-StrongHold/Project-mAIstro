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
        import contextlib
        import logging

        from services.dag_run_store import get_dag_run_store
        from services.graph_runner import execute_dag

        store = get_dag_run_store()
        await store.start_run(run_id=exec_id, dag_id=dag_id)
        # Human-initiated run from the UI — interactive isolation floor (ADR-093)
        result = await execute_dag(dag_data, execution_mode="interactive")
        # Store node results as events for eval-judge and UI
        for nid, nr in result.get("node_results", {}).items():
            await store.append_event(
                exec_id,
                event_type="pm_node_completed" if nr.get("success") else "pm_node_failed",
                role=nr.get("role", "worker"),
                capability=nid,
                payload={"source": "llm", "response": nr.get("response", "")[:2000]},
            )
        # Record node metrics (Signal #5).
        #
        # Only what this path measured. It knows each node's outcome and the
        # model that node was actually called with, and nothing about any
        # individual node's latency, tokens, or cost. Those used to be filled
        # in with the whole-DAG elapsed time divided by the cycle count and
        # zeroes -- so the optimizer, which weights cost at 0.15, scored every
        # variant as free and every node as equally fast (#698). The DAG-level
        # timer went with them: it existed only to be divided.
        #
        # `model_used` is not among them. The first version of this change
        # dropped it with the rest, because the old code reached for the *first
        # node's* model behind a hardcoded fallback and called that the model
        # for every node. But `graph_runner` resolves and reports each node's
        # own model now, so this is a measurement and not a guess -- and
        # without it `topology_compare`, whose default grouping is
        # `model_used`, collapses every new observation into one `(unset)`
        # bucket and can no longer compare model variants at all (Codex, #698).
        # A tool node runs no model and reports none, which is correct.
        #
        # `project_id` is likewise absent rather than `""`: this route carries
        # no project scope, and an empty string is a value the project filter
        # matches against.
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
                        model_used=str(nr.get("model", "")),
                    )
                )
        except Exception:
            # Named rather than bare: a metrics write must not fail a DAG run
            # that already produced a result, but an operator has to be able
            # to find out that the observations were dropped.
            logging.getLogger("hive.dags").warning(
                "node_metrics_not_recorded execution_id=%s dag_id=%s",
                exec_id,
                dag_id,
                exc_info=True,
            )
        # After the events, so a reader that sees `completed` sees the events
        # that justify it. This used to assign `run.status` and `run.result`
        # to a dataclass that declared neither, so the run stayed `running`
        # with no `finished_at` forever (#697).
        #
        # Suppressed, and that is the point: inside the surrounding `try` a
        # failed history write would land in the `except` below and report the
        # *execution* as failed -- for a DAG that had already succeeded, and
        # whose run record `finish_run` marks completed before it persists. The
        # caller would be told one thing and the history would say another
        # (Codex, #697).
        with contextlib.suppress(Exception):
            await store.finish_run(exec_id, status="completed", result=result)
        return {"status": "completed", "execution_id": exec_id, "result": result}
    except Exception as exc:
        import contextlib
        import logging

        logging.getLogger("hive.dags").warning("Graph execution failed: %s", exc)
        # The failure branch left the run `running` with no `finished_at` for
        # the life of the process -- the same defect as the success branch,
        # and the one a reader is more likely to go looking for. Suppressed
        # because the response the caller gets must not depend on whether the
        # history write succeeded; the execution already failed and that is
        # what is being reported.
        with contextlib.suppress(Exception):
            from services.dag_run_store import get_dag_run_store

            await get_dag_run_store().finish_run(exec_id, status="failed")
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
