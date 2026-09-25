"""The door onto pending and settling human work (#244, #737).

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

from fastapi import APIRouter, HTTPException, Request
from middleware.auth import resolve_principal
from pydantic import BaseModel, ConfigDict, Field
from services.workspace_authority import (
    hitl_membership_mutation_lock,
    is_member,
    list_workspace_ids_for_user,
)

from maistro.graph.durable_runs import HitlAuthorization, cursor_time, expire_hitl_pauses
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
    """The durable graph store holding pending human work.

    Answering, cancelling, expiring, or even listing human pauses is Graph
    lifecycle work: it reads and settles canonical Runs. Without the core
    bridge there is no store to answer from, and the honest response is the
    documented 503 — the same contract the settings and install surfaces use —
    not a 500 from an unhandled refusal, and never a process-local fallback
    store (#1113).
    """
    from services.dag_agents import GraphExecutionUnavailableError, get_run_store

    try:
        return get_run_store()
    except GraphExecutionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _request_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id") or user.get("username") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def _require_workspace_access(request: Request, workspace_id: str) -> None:
    if not await is_member(_request_user_id(request), workspace_id):
        # Do not confirm that an out-of-scope Run exists. This matches the
        # scoped DAG inspection door: missing and unauthorized ids are one
        # answer, while membership remains the canonical authorization check.
        raise HTTPException(status_code=404, detail="run not found")


async def _authorized_record(request: Request, run_id: str) -> Any:
    """Resolve canonical execution state before authorizing or disclosing it."""
    record = await _store().get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    await _require_workspace_access(request, record.run.workspace_id)
    return record


def _hitl_authorization(request: Request, workspace_ids: set[str]) -> HitlAuthorization:
    """Carry live canonical membership into the durable mutation boundary.

    This is the one place request-derived evidence is manufactured: the
    principal comes from the verified session (`_request_user_id` reads the
    auth middleware's stamp), the membership check is the workspace
    authority's own, and the mutation lock is the same one membership
    revocation takes. The store revalidates all of it inside its write, and
    the pending listing revalidates it per disclosed record — the snapshot of
    Workspace ids this authorization carries is a candidate page, never the
    disclosure decision.
    """
    return HitlAuthorization(
        effective_principal=_request_user_id(request),
        workspace_ids=frozenset(workspace_ids),
        membership_check=is_member,
        membership_mutation_lock=hitl_membership_mutation_lock(),
    )


def _session_principal(request: Request) -> str:
    """The verified session principal behind this request, never "system".

    AuthMiddleware stamps ``request.state.user`` for every authenticated
    ``/v1/`` request after resolving the live session; reading that back keeps
    one resolver and one revocation check (ADR-077) per request. The fallback
    re-resolves from the cookie in case a caller reaches the handler without
    the middleware's stamp. A request that still has no principal is recorded
    as *unauthenticated* rather than as the system: an audit trail that names
    a principal who was never verified overclaims in exactly the way the
    crypto-bound approval record (#329 / ADR-090726-9a4e) exists to prevent —
    a human decision must name a verified human, not a convenient default.
    """
    user = getattr(request.state, "user", None) or resolve_principal(
        request.cookies, request.headers.get("Authorization")
    )
    if user is None:
        return "unauthenticated"
    return str(user.get("username") or user.get("id") or "unverified")


def _pending_items(record: Any) -> list[PendingHumanWork]:
    """The human pauses on one record, or none when it waits on a machine.

    A Run can be PAUSED with several nodes waiting independently, which the
    frontier tests already exercise, so this yields per node rather than per
    Run — a queue keyed by Run would hide every pause after the first. The
    NodeRun check keeps a malformed continuation from exposing a pause that is
    not present in canonical execution state.
    """
    pauses = record.graph_state.metadata.get("pauses")
    # `Mapping`, not `dict`: `GraphExecutionState` freezes its metadata, so the
    # values that come back are immutable mappings rather than the dicts they
    # went in as. `_answer_record` in the store reads them the same way.
    if not isinstance(pauses, Mapping):
        return []
    paused_nodes = {
        node_run.node_id for node_run in record.node_runs if node_run.status is RunStatus.PAUSED
    }
    items: list[PendingHumanWork] = []
    for node_id, pause in pauses.items():
        if str(node_id) not in paused_nodes:
            continue
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


#: Ceiling on PAUSED records inspected by one `/pending` request, independent
#: of how many turn out to carry human work. Bounds one request's cost against
#: an arbitrarily large run of machine-only pauses (#1109); it is not the
#: `limit` a caller sees, which bounds *pending items* returned.
_MAX_PENDING_SCAN_RECORDS = 2000

#: Minimum rows requested per page, regardless of how small the caller's
#: `limit` is, so a small item target does not force one PAUSED row per
#: round trip while paging past a long machine-only prefix.
_PENDING_SCAN_PAGE_SIZE = 100


@router.get("/pending")
async def list_pending_human_work(
    request: Request, limit: int = 50, project_id: str | None = None
) -> list[PendingHumanWork]:
    """Everything waiting on a person, without knowing a run_id in advance.

    That last clause is the point: `GET /v1/runs/{run_id}/node-runs` already
    answers "what is this Run doing", and answers nothing for a person who
    does not yet know which Run is blocked on them.

    `limit` bounds *pending items* returned, not a fixed prefix of the
    PAUSED Runs in the store (#1109). Machine-only pauses and pauses outside
    `project_id` carry no items, so filtering a single fixed-size page after
    the fact could return an empty answer forever even while real human work
    sits durably PAUSED further back in the ordering. Instead this pages the
    store's PAUSED listing with an advancing keyset cursor and keeps reading
    until it has enough items, the store runs out of PAUSED Runs, or it has
    inspected `_MAX_PENDING_SCAN_RECORDS` records — the same bounded-scan
    contract `expire_hitl_pauses` uses (#1056).
    """
    user_id = _request_user_id(request)

    # Workspace membership is the canonical visibility boundary for Run data,
    # not the coarse `dags.write` route permission. Resolve every Workspace the
    # principal may see; selecting one default Workspace would hide legitimate
    # work, while omitting this filter leaks every tenant's paused payload.
    allowed_workspace_ids = set(await list_workspace_ids_for_user(user_id))
    if not allowed_workspace_ids:
        return []

    bounded_limit = max(1, min(limit, 200))
    store = _store()
    items: list[PendingHumanWork] = []
    # Workspace scope is applied by the store, before its page limit, so another
    # tenant's backlog cannot hide this caller's pending work (#1240); the
    # keyset walk inside each Workspace is what stops a long machine-only
    # prefix from hiding real human work within it (#1109). Both bounds are
    # load-bearing: the outer one is a security boundary, the inner one a
    # fairness one, and neither subsumes the other.
    # The resolved Workspace-id set is a candidate page, not the disclosure
    # decision: a membership revoked after `list_workspace_ids_for_user` but
    # before a record's payload is read must not receive that payload, so each
    # item-carrying record is revalidated against live canonical membership —
    # the same discovery-mode predicate `list_hitl_due` applies for the expiry
    # path, not a second, weaker check written here.
    authorization = _hitl_authorization(request, allowed_workspace_ids)
    for workspace_id in sorted(allowed_workspace_ids):
        cursor: tuple[str, str] | None = None
        inspected = 0
        while len(items) < bounded_limit and inspected < _MAX_PENDING_SCAN_RECORDS:
            # At least `_PENDING_SCAN_PAGE_SIZE` rows per page even when
            # `bounded_limit` is small: a small item target must not force one
            # row per round trip while paging past a long machine-only prefix.
            page_size = min(
                max(bounded_limit, _PENDING_SCAN_PAGE_SIZE), _MAX_PENDING_SCAN_RECORDS - inspected
            )
            records = await store.list_by_status(
                RunStatus.PAUSED,
                limit=page_size,
                project_id=project_id,
                workspace_id=workspace_id,
                after=cursor,
            )
            if not records:
                break
            inspected += len(records)
            for record in records:
                record_items = _pending_items(record)
                # Recheck only records about to disclose a payload: a
                # machine-only pause carries nothing a revocation could
                # withhold, and the recheck costs one live membership read.
                if record_items and not await authorization.permits(record.run.workspace_id):
                    continue
                items.extend(record_items)
            # Must be the store's own cursor spelling, not a bare isoformat:
            # `list_by_status` compares the cursor against a UTC-normalized key,
            # so a `created_at` printed at any other offset would order one way
            # and filter the other, and this walk would silently stop advancing.
            cursor = (cursor_time(records[-1].run.created_at), records[-1].run_id)
        if len(items) >= bounded_limit:
            break
    return items[:bounded_limit]


@router.get("/{run_id}/{node_id}")
async def inspect_human_work(run_id: str, node_id: str, request: Request) -> PendingHumanWork:
    """Inspect one pending node only after canonical Workspace authorization."""
    record = await _authorized_record(request, run_id)
    for item in _pending_items(record):
        if item.node_id == node_id:
            return item
    # Missing, foreign, terminal, and non-HITL nodes share one refusal so this
    # detail door cannot become an existence oracle.
    raise HTTPException(status_code=404, detail="run not found")


@router.post("/expire")
async def expire_human_work(request: Request, limit: int = 100) -> dict[str, Any]:
    """Run one bounded expiry tick against the caller's canonical Workspaces.

    The expiry tick is still lifecycle work owned by the durable store, but an
    HTTP caller is not a scheduler with global authority. Its effective
    principal is resolved here and the canonical store filters the timeout
    candidates before any settlement is requested.
    """
    user_id = _request_user_id(request)
    authorization = _hitl_authorization(
        request,
        set(await list_workspace_ids_for_user(user_id)),
    )
    store = _store()
    expired = await expire_hitl_pauses(
        store,
        limit=max(1, min(limit, 200)),
        authorization=authorization,
    )
    run_ids = [record.run_id for record in expired]
    if run_ids:
        log_audit("hitl_expire", _session_principal(request), detail={"run_ids": run_ids})
    return {"expired": len(run_ids), "run_ids": run_ids}


@router.post("/{run_id}/{node_id}/cancel")
async def cancel_human_work(run_id: str, node_id: str, request: Request) -> dict[str, Any]:
    """Request canonical cancellation of one durable human pause."""
    store = _store()
    record = await _authorized_record(request, run_id)
    try:
        updated = await store.cancel_hitl(
            run_id,
            node_id,
            workspace_id=record.run.workspace_id,
            authorization=_hitl_authorization(request, {record.run.workspace_id}),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit(
        "hitl_cancel", _session_principal(request), target=run_id, detail={"node_id": node_id}
    )
    return {
        "run_id": run_id,
        "node_id": node_id,
        "run_status": updated.run.status.value,
    }


@router.post("/{run_id}/{node_id}/answer")
async def answer_human_work(
    run_id: str, node_id: str, body: HumanAnswer, request: Request
) -> dict[str, Any]:
    """Answer one paused node, resuming its Run.

    The store performs the validation and the state change; this maps its three
    refusals onto distinct statuses. The pre-read exists to *choose the status*,
    not to re-decide the answer — the store is called regardless and its verdict
    is final, so a race between the read and the call surfaces as its error
    rather than as a wrong code.
    """
    store = _store()
    # Resolve and authorize the canonical target before validating or scanning
    # answer content, so an unauthorized identifier cannot reach any answer
    # handling branch.
    record = await _authorized_record(request, run_id)
    answer = body.model_dump()
    if _RESERVED_ANSWER_KEY in answer:
        # Refused rather than silently overwritten: a responder naming the
        # pause it is answering is claiming the execution state of the node
        # that was waiting on it.
        raise HTTPException(
            status_code=422, detail=f"{_RESERVED_ANSWER_KEY!r} is reserved for execution state"
        )

    if record.run.status is not RunStatus.PAUSED:
        raise HTTPException(
            status_code=409, detail=f"run is {record.run.status.value}, not paused on human input"
        )
    if not any(item.node_id == node_id for item in _pending_items(record)):
        raise HTTPException(status_code=409, detail="node is not awaiting a human answer")

    # Untrusted input crossing into a Run's state, which later nodes read
    # (CLAUDE.md decision 6). Scanned with the same detector the harness and
    # the Agent Builder use rather than a second, weaker check written here.
    try:
        verdict = await scan_config(answer)
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if verdict["status"] != "clean":
        # Findings include scanner paths derived from attacker-controlled keys;
        # retain only bounded metadata so a blocked answer cannot write secrets
        # into the audit trail or echo them in the refusal response.
        finding_count = len(verdict["findings"])
        log_audit(
            "hitl_answer_blocked",
            _session_principal(request),
            target=run_id,
            detail={"node_id": node_id, "finding_count": finding_count},
        )
        raise HTTPException(
            status_code=422,
            detail={"error": "answer failed security scan", "finding_count": finding_count},
        )

    try:
        updated = await store.submit_hitl_answer(
            run_id,
            node_id,
            answer,
            workspace_id=record.run.workspace_id,
            authorization=_hitl_authorization(request, {record.run.workspace_id}),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The audit record names the verified principal who answered, not "system"
    # (#329 / ADR-090726-9a4e): this write settles a human decision, so its
    # evidence must say which human.
    log_audit(
        "hitl_answer", _session_principal(request), target=run_id, detail={"node_id": node_id}
    )
    return {
        "run_id": run_id,
        "node_id": node_id,
        "run_status": updated.run.status.value,
        "still_pending": [item.node_id for item in _pending_items(updated)],
    }
