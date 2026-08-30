"""The door onto pending human work (#244).

The HITL loop is complete in the library and had no entry point. Four node
kinds pause, the durable executor maps a human pause onto `RunStatus.PAUSED`
tied to Run *and* NodeRun, and `DurableRunStore.submit_hitl_answer` validates
and applies an answer — but nothing outside tests ever called it, and nothing
could ask "what is waiting on a human?" across Runs. A human could neither
discover they were blocking a Run nor unblock it.

This module is the door and nothing else. It transitions nothing itself: the
store stays the only lifecycle authority (#48's fifth criterion), and every
refusal here is one the store already raises, translated into a status code
rather than re-decided.

It lives in hive-conductor rather than maistro-server for a forced reason,
not a preference: nothing wires a `DurableRunStore` outside this package.
`services/dag_agents.py` holds the only one in the system, so this is where
the pending work actually is. When that store converges onto the canonical
spine (#44 / ADR-082826-d9f5), this module keeps working unchanged — it is
written against the `DurableRunStore` interface, which that convergence
preserves.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from maistro.runs.model import RunStatus
from routes.agents import ScanBudgetExceeded, scan_config
from routes.audit import log_audit

router = APIRouter(tags=["hitl"])

#: The pause kind the durable executor stamps for a human pause, as opposed to
#: a machine wait. `graph_state.metadata["pauses"]` carries it per node, which
#: is why this listing needs no node-registry lookup: the pause entry declares
#: what it is.
_HUMAN_PAUSE_KIND = "hitl"

#: A responder must not be able to name the execution state of the node it is
#: answering, so the store stamps the real pause under this key *after* the
#: caller's own keys. Rejected on the way in as well, so a forged value never
#: reaches the scan budget or the store.
_RESERVED_ANSWER_KEY = "_pause"


class PendingHumanWork(BaseModel):
    """One node waiting on a person."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    node_id: str
    project_id: str
    #: The payload the node paused carrying — its question, draft, or review
    #: subject. Rendering a queue without it would show that something is
    #: blocked while hiding what is being asked.
    payload: dict[str, Any] = Field(default_factory=dict)
    paused_at: str | None = None


class HumanAnswer(BaseModel):
    model_config = ConfigDict(extra="allow")


def _store() -> Any:
    """The durable graph store holding pending human work."""
    from services.dag_agents import get_run_store

    return get_run_store()


def _pending_items(record: Any) -> list[PendingHumanWork]:
    """The human pauses on one record, or none when it waits on a machine.

    A Run can be PAUSED with several nodes waiting independently, which the
    frontier tests already exercise, so this yields per node rather than per
    Run — a queue keyed by Run would hide every pause after the first.
    """
    pauses = record.graph_state.metadata.get("pauses")
    # `Mapping`, not `dict`: `GraphExecutionState` freezes its metadata, so the
    # values that come back are immutable mappings rather than the dicts they
    # went in as. `_answer_record` in the store reads them the same way.
    if not isinstance(pauses, Mapping):
        return []
    items: list[PendingHumanWork] = []
    for node_id, pause in pauses.items():
        if not isinstance(pause, Mapping) or pause.get("kind") != _HUMAN_PAUSE_KIND:
            continue
        metadata = pause.get("metadata")
        items.append(
            PendingHumanWork(
                run_id=record.run.run_id,
                node_id=str(node_id),
                project_id=record.run.project_id,
                payload=dict(metadata) if isinstance(metadata, Mapping) else {},
                paused_at=str(pause["paused_at"]) if pause.get("paused_at") else None,
            )
        )
    return items


@router.get("/pending")
async def list_pending_human_work(
    limit: int = 50, project_id: str | None = None
) -> list[PendingHumanWork]:
    """Everything waiting on a person, without knowing a run_id in advance.

    That last clause is the point: `GET /v1/runs/{run_id}/node-runs` already
    answers "what is this Run doing", and answers nothing for a person who
    does not yet know which Run is blocked on them.
    """
    store = _store()
    records = await store.list_by_status(
        RunStatus.PAUSED, limit=max(1, min(limit, 200)), project_id=project_id
    )
    return [item for record in records for item in _pending_items(record)]


@router.post("/{run_id}/{node_id}/answer")
async def answer_human_work(run_id: str, node_id: str, body: HumanAnswer) -> dict[str, Any]:
    """Answer one paused node, resuming its Run.

    The store performs the validation and the state change; this maps its three
    refusals onto distinct statuses. The pre-read exists to *choose the status*,
    not to re-decide the answer — the store is called regardless and its verdict
    is final, so a race between the read and the call surfaces as its error
    rather than as a wrong code.
    """
    answer = body.model_dump()
    if _RESERVED_ANSWER_KEY in answer:
        # Refused rather than silently overwritten: a responder naming the
        # pause it is answering is claiming the execution state of the node
        # that was waiting on it.
        raise HTTPException(
            status_code=422, detail=f"{_RESERVED_ANSWER_KEY!r} is reserved for execution state"
        )

    store = _store()
    record = await store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if record.run.status is not RunStatus.PAUSED:
        raise HTTPException(
            status_code=409, detail=f"run is {record.run.status.value}, not paused on human input"
        )
    if node_id not in record.graph_state.active_node_ids:
        raise HTTPException(status_code=409, detail="node is not awaiting an answer")

    # Untrusted input crossing into a Run's state, which later nodes read
    # (CLAUDE.md decision 6). Scanned with the same detector the harness and
    # the Agent Builder use rather than a second, weaker check written here.
    try:
        verdict = await scan_config(answer)
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if verdict["status"] != "clean":
        log_audit(
            "hitl_answer_blocked",
            "system",
            target=run_id,
            detail={"node_id": node_id, "findings": verdict["findings"]},
        )
        raise HTTPException(
            status_code=422,
            detail={"error": "answer failed security scan", "findings": verdict["findings"]},
        )

    try:
        updated = await store.submit_hitl_answer(run_id, node_id, answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit("hitl_answer", "system", target=run_id, detail={"node_id": node_id})
    return {
        "run_id": run_id,
        "node_id": node_id,
        "run_status": updated.run.status.value,
        "still_pending": [item.node_id for item in _pending_items(updated)],
    }
