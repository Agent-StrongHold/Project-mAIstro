from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from maistro.graph.phases import GraphPhase, NodePhase


class GraphEvent(BaseModel):
    type: str
    run_id: str
    node_id: str | None = None
    role: str | None = None
    phase: str | None = None
    timestamp: float = Field(default_factory=time.monotonic)
    detail: dict[str, Any] = Field(default_factory=dict)


def graph_started(run_id: str, **detail: Any) -> GraphEvent:
    return GraphEvent(type="graph_started", run_id=run_id, detail=detail)


def graph_completed(run_id: str, **detail: Any) -> GraphEvent:
    return GraphEvent(
        type="graph_completed", run_id=run_id, phase=GraphPhase.COMPLETED, detail=detail
    )


def graph_failed(run_id: str, **detail: Any) -> GraphEvent:
    return GraphEvent(type="graph_failed", run_id=run_id, phase=GraphPhase.FAILED, detail=detail)


def node_started(run_id: str, node_id: str, role: str, **detail: Any) -> GraphEvent:
    return GraphEvent(
        type="node_started",
        run_id=run_id,
        node_id=node_id,
        role=role,
        phase=NodePhase.RUNNING,
        detail=detail,
    )


def node_completed(run_id: str, node_id: str, role: str, **detail: Any) -> GraphEvent:
    return GraphEvent(
        type="node_completed",
        run_id=run_id,
        node_id=node_id,
        role=role,
        phase=NodePhase.SUCCEEDED,
        detail=detail,
    )


def node_failed(run_id: str, node_id: str, role: str, **detail: Any) -> GraphEvent:
    return GraphEvent(
        type="node_failed",
        run_id=run_id,
        node_id=node_id,
        role=role,
        phase=NodePhase.FAILED,
        detail=detail,
    )


def node_retrying(run_id: str, node_id: str, role: str, **detail: Any) -> GraphEvent:
    return GraphEvent(
        type="node_retrying",
        run_id=run_id,
        node_id=node_id,
        role=role,
        phase=NodePhase.RETRYING,
        detail=detail,
    )


def cycle_started(run_id: str, **detail: Any) -> GraphEvent:
    return GraphEvent(type="cycle_started", run_id=run_id, detail=detail)
