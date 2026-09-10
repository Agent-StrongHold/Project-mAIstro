"""Phase 5 — Signal #3 endpoints for eval-judge.

  POST /v1/eval-judge/{run_id}
      Manually trigger eval-judge on a DurableRun. The caller MUST pass
      the run record (typically pulled from /v1/dag-runs/{run_id}).
      Returns the verdict.

  GET /v1/eval-judge/{run_id}
      Read the persisted verdict for one run.

  GET /v1/eval-judge
      List recent verdicts (capped to `limit`, newest first).

The manual trigger is what the optimizer's scheduler will call between
user runs once Phase 6 lands; for now it lets a user click 'Score this
run' from DagRuns.tsx and read the eval-judge's rationale + topology
proposal verbatim.

The trigger and both read routes — GET /v1/eval-judge/{run_id} (one
verdict) and GET /v1/eval-judge (recent verdicts) — read through
`services.dag_run_inspection`, the same scoped door the dag-runs routes use
(#1174): a run outside the caller's Workspace universe is refused with the
run's usual non-existence response, not scored for whoever asks, and its
verdict — if one was ever recorded — is neither served nor listed
cross-Workspace.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.dag_run_inspection import visible_run_detail, visible_run_ids
from services.eval_judge import get_verdict, score_run

router = APIRouter(tags=["eval-judge"])


def _user_id(request: Request) -> str:
    """Principal for this request — set by AuthMiddleware (see routes/feedback.py)."""
    user = getattr(request.state, "user", None) or {}
    uid = str(user.get("id") or user.get("username") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


@router.get("/{run_id}")
async def read_verdict(run_id: str, request: Request) -> dict[str, Any]:
    # Scope authorization on the RUN happens before the verdict store is
    # touched (#1174): an out-of-scope run gets the run's usual
    # non-existence answer — identical to a missing run's — so the response
    # never confirms a run (or a verdict for it) exists beyond the caller's
    # boundary. "No verdict" is only answerable for a run the caller may
    # already inspect.
    if await visible_run_detail(_user_id(request), run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    v = get_verdict(run_id)
    if v is None:
        raise HTTPException(status_code=404, detail="no verdict for run_id")
    return v


@router.get("")
async def list_verdicts(request: Request, limit: int = 25) -> list[dict[str, Any]]:
    import stores

    verdicts = sorted(
        stores.eval_verdicts.values(),
        key=lambda v: v.get("scored_at", ""),
        reverse=True,
    )
    # The list answers only with verdicts whose run sits inside the caller's
    # Workspace universe — resolved once for the whole page by the same
    # inspection service the by-id read uses (#1174), never by trusting the
    # verdict row's own fields. Filter first, cap second: a page can never
    # smuggle a cross-Workspace row in, whatever the limit asks for.
    visible = await visible_run_ids(
        _user_id(request), (str(v.get("run_id") or "") for v in verdicts)
    )
    return [v for v in verdicts if str(v.get("run_id") or "") in visible][: max(1, min(limit, 100))]


@router.post("/{run_id}")
async def trigger_score(run_id: str, request: Request) -> dict[str, Any]:
    """Score the run captured in dag_run_store. For Phase 5 we score off
    the dag_run_store's run-record-shaped summary (DurableRunRecord
    integration lands when the executor publishes the durable record
    into dag_run_store; until then, this endpoint accepts whatever
    dag_run_store returns and gracefully scores it).

    Scoped like every other run reader (#1174): the projection is read
    through the inspection service, so an out-of-scope run gets the same
    404 a missing one gets — and is never scored.
    """
    run = await visible_run_detail(_user_id(request), run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # dag_run_store's get_run returns a dict; wrap it in a tiny adapter
    # so the eval_judge service can read .run_id / .node_records / etc.
    class _Adapter:
        def __init__(self, d: dict[str, Any]) -> None:
            self.run_id = d.get("id", run_id)
            self.dag_id = d.get("dag_id", "")
            self.project_id = d.get("project_id", "")
            self.status = d.get("status", "")
            # Convert events → minimal node-record shape for the rubric.
            self.node_records = _events_to_node_records(d.get("events") or [])

    return await score_run(_Adapter(run))


def _events_to_node_records(events: list[dict[str, Any]]) -> list[Any]:
    """The dag_run_store records events (not node records); convert the
    pm_node_completed events into a duck-typed list the eval_judge can
    score on."""

    class _NR:
        def __init__(self, **kw: Any) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    by_node: dict[str, _NR] = {}
    for ev in events:
        et = ev.get("event_type", "")
        payload = ev.get("payload") or {}
        nid = str(payload.get("node_id") or ev.get("role") or "")
        if not nid:
            continue
        rec = by_node.setdefault(
            nid,
            _NR(
                node_id=nid,
                kind=ev.get("capability", ""),
                phase="",
                latency_ms=0,
                tokens_in=0,
                tokens_out=0,
                error_code=None,
                error_message=None,
            ),
        )
        if "completed" in et:
            rec.phase = "COMPLETED"
            rec.latency_ms = int(payload.get("latency_ms") or 0)
            rec.tokens_in = int(payload.get("tokens_in") or 0)
            rec.tokens_out = int(payload.get("tokens_out") or 0)
        elif "failed" in et or "error" in et:
            rec.phase = "FAILED"
            rec.error_code = payload.get("error_code")
            rec.error_message = payload.get("error_message")
    return list(by_node.values())
