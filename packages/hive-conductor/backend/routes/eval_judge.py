"""Phase 5 — Signal #3 endpoints for eval-judge.

  POST /v1/eval-judge/{run_id}
      Manually trigger eval-judge on a canonical Run. Returns the verdict.

  GET /v1/eval-judge/{run_id}
      Read the persisted verdict for one run.

  GET /v1/eval-judge
      List recent verdicts (capped to `limit`, newest first).

Authorization is split by method, because the two halves of this surface are
different kinds of act (#2470):

* The reads — GET /{run_id} and GET / — stay the #1174 in-route scoped read:
  `services.dag_run_inspection` answers both, a run outside the caller's
  Workspace universe is refused with the run's usual non-existence response,
  and its verdict — if one was ever recorded — is neither served nor listed
  cross-Workspace. Workspace membership admits reads (#1152).

* The POST is an evaluated-effect mutation, never a read: it launches a real
  LiteLLM model call (billed provider spend) and writes the verdict rows the
  optimizer consumes as improvement-ranking evidence. Three gates stand
  between a request and that effect, each fail-closed:

  1. The HTTP capability `eval.score` (services.authorization PROTECTED_OPS):
     an assigned-and-elevated capability like rsi.execute — the permission
     the #2470 role rule makes an admin's assignment decision, never a
     side effect of Workspace membership.
  2. The canonical mutation gate: the target Run is resolved through the
     shared `RunStoreBoundary.require_run_mutation` — the same
     initiator/administrator rule the #2466 cancel control applies — so only
     the Run's initiating principal or a Workspace administrator gets past,
     and a projection row cannot delegate write authority across Workspaces.
     (No separate "evaluator delegation" authority exists in this tree; until
     one lands, the gate is exactly initiator-or-administrator — fail-closed.)
  3. Terminality: only a terminal Run (completed/failed/cancelled/timed out)
     can be scored; a live Run's evidence is not settled yet.

Evidence semantics (#2470): the verdict is keyed by the canonical Run id and
protected by services.eval_judge — a valid verdict is terminal evidence, so
retrying returns it verbatim (no second model effect, no restart double-fire),
and a later failing/unparseable/unavailable attempt can never downgrade it.
A valid verdict a producer recorded before canonical keying lives under the
projection alias this same authorized read resolved; honoring it verbatim
keeps one paid model effect per logical score across the upgrade and writes
nothing. There is deliberately no automatic re-score or supersede here:
replacing a valid verdict is a governed decision the M2 policy owns, not a
side effect of calling POST again. Audit records the successful scoring
effect with its canonical actor; refused requests mutate nothing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.dag_run_inspection import visible_run_detail, visible_run_ids
from services.eval_judge import get_verdict, is_valid_verdict, score_run
from services.request_principal import require_actor_id

router = APIRouter(tags=["eval-judge"])


def _user_id(request: Request) -> str:
    """Principal for this request — set by AuthMiddleware (see routes/feedback.py)."""
    return require_actor_id(request)


@router.get("/{run_id}")
async def read_verdict(run_id: str, request: Request) -> dict[str, Any]:
    # Scope authorization on the RUN happens before the verdict store is
    # touched (#1174): an out-of-scope run gets the run's usual
    # non-existence answer — identical to a missing run's — so the response
    # never confirms a run (or a verdict for it) exists beyond the caller's
    # boundary. "No verdict" is only answerable for a run the caller may
    # already inspect. Evidence is keyed by canonical Run id (#2470), so a
    # projection-id read falls back to the canonical id this same authorized
    # read resolved — no second authorization, no alias-keyed duplicate row.
    detail = await visible_run_detail(_user_id(request), run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="run not found")
    v = get_verdict(run_id)
    if v is None:
        v = get_verdict(str(detail.get("canonical_run_id") or ""))
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


async def _canonical_scoreable_run(uid: str, run_id: str, detail: dict[str, Any]) -> Any:
    """Resolve the canonical target Run through the shared mutation gate.

    The same object shapes the #2466 cancel control answers from: the engine
    bridge's wired reader triple when one is wired, otherwise the embedded
    Workspace authority fallback (whose refusals stay fail-closed). Absent,
    foreign, and initiator/admin-refused targets all answer the seam's one
    non-disclosing 404; an unreachable canonical authority answers 503.
    """
    from services.engine import get_engine
    from services.workspace_authority import EmbeddedRuntimeUnavailable, canonical_workspace_store

    from maistro.runs.scoped_reads import RunNotVisible
    from maistro.runs.store_boundary import RunStoreBoundary

    canonical_run_id = str(detail.get("canonical_run_id") or detail.get("id") or run_id)
    try:
        engine = get_engine()
    except RuntimeError:
        raise HTTPException(
            status_code=503, detail="canonical execution spine unavailable"
        ) from None
    store = getattr(engine, "run_store", None)
    reader = getattr(engine, "run_reader", None)
    if store is None:
        raise HTTPException(status_code=503, detail="canonical execution spine unavailable")
    try:
        if reader is None:
            # Degraded bridge, exactly as the cancel control degrades: the
            # embedded fallback Workspace authority, fail-closed refusals.
            workspace_store = await canonical_workspace_store()
            boundary = RunStoreBoundary(store, workspace_store, workspace_store.project_store)
        else:
            boundary = RunStoreBoundary(
                reader.run_store, reader.workspace_store, reader.project_store
            )
        run = await boundary.require_run_mutation(canonical_run_id, principal_id=uid)
    except RunNotVisible as exc:
        # Absent, foreign, and initiator/admin-refused targets are the same
        # non-disclosing 404 the read seam answers with (#1152, #2466).
        raise HTTPException(status_code=404, detail="run not found") from exc
    except EmbeddedRuntimeUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="canonical execution spine unavailable"
        ) from exc
    # Projection-to-Run association (#2466): a row filed in one Workspace
    # cannot delegate scoring of a canonical Run filed in another, even when
    # the caller is authorized against that Run's own Workspace. The direct
    # canonical route remains open to whoever the mutation gate admits.
    if run.workspace_id != str(detail.get("workspace_id") or ""):
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/{run_id}")
async def trigger_score(run_id: str, request: Request) -> dict[str, Any]:
    """Score a terminal canonical Run.

    Read visibility never admits a scoring effect (#2470): the POST first
    resolves the canonical target through the mutation gate (initiator or
    Workspace administrator — membership alone refuses like a missing run),
    then requires terminality, then honors the evidence contract — an
    existing valid verdict IS the score and is returned verbatim without a
    second model effect. Only then does the governed scorer run, writing the
    verdict under the canonical Run id with its canonical actor/scope
    provenance; a successful score is audited. Every refusal above happens
    before any model call, verdict write, proposal, usage or audit mutation.
    """
    uid = _user_id(request)
    detail = await visible_run_detail(uid, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="run not found")

    run = await _canonical_scoreable_run(uid, run_id, detail)

    from maistro.runs.model import TERMINAL_RUN_STATUSES

    if run.status not in TERMINAL_RUN_STATUSES:
        # A live Run's evidence is not settled: running/waiting/paused/queued
        # targets refuse with a conflict the authorized caller can act on.
        # The initiator/admin gate already admitted this caller, so the
        # answer may name the refusal honestly (unlike the non-disclosing
        # 404s above, which hide existence from non-mutators).
        raise HTTPException(
            status_code=409, detail="run is not terminal; only a terminal run can be scored"
        )

    canonical_run_id = run.run_id

    # Idempotent scoring (#2470): a valid persisted verdict for this canonical
    # Run is the score. Retry — double-click, replay after restart — returns
    # it verbatim and pays for no new model effect. Replacing it is a
    # governed decision, not a re-POSTable side effect.
    existing = get_verdict(canonical_run_id)
    if is_valid_verdict(existing):
        return existing
    if run_id != canonical_run_id:
        # Evidence recorded before canonical keying lives under the
        # projection alias this same authorized read resolved (#2470).
        # Honoring it verbatim keeps one paid model effect per logical
        # score across the upgrade — and mutates nothing: the durable row
        # stays exactly as recorded, no canonical-keyed duplicate appears.
        alias_evidence = get_verdict(run_id)
        if is_valid_verdict(alias_evidence):
            return alias_evidence

    class _Adapter:
        def __init__(self, d: dict[str, Any]) -> None:
            # Evidence is keyed by the canonical identity the gate just
            # admitted, never by a projection alias (#2470).
            self.run_id = canonical_run_id
            self.dag_id = d.get("dag_id", "")
            self.project_id = d.get("project_id", "")
            self.status = d.get("status", "")
            # Convert events → minimal node-record shape for the rubric.
            self.node_records = _events_to_node_records(d.get("events") or [])

    verdict = await score_run(
        _Adapter(detail),
        actor_id=uid,
        workspace_id=str(detail.get("workspace_id") or ""),
        canonical_run_id=canonical_run_id,
    )
    stored = get_verdict(canonical_run_id)
    if is_valid_verdict(verdict):
        from routes.audit import log_audit

        log_audit(
            "eval_judge_score",
            uid,
            target=canonical_run_id,
            detail={
                "run_id": run_id,
                "canonical_run_id": canonical_run_id,
                "dag_id": str(detail.get("dag_id") or ""),
                "workspace_id": str(detail.get("workspace_id") or ""),
                "score": verdict.get("score"),
                "evaluator_version": verdict.get("evaluator_version"),
            },
        )
    if is_valid_verdict(stored):
        # The caller sees exactly what the evidence store holds — the same
        # row a retry will return (#2470).
        return stored
    return verdict


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
