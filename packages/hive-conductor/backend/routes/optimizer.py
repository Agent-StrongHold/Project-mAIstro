"""Phase 6 — Optimizer endpoints.

  POST /v1/optimizer/{dag_id}/run
      Run one optimizer pass. Query: ?apply_auto=false (default).
      Returns the ranked proposal list + auto_applied count.

  GET /v1/optimizer/{dag_id}/proposals
      List proposals for one DAG. Query: ?decision=pending|accepted|rejected.

  GET /v1/optimizer/proposals
      List proposals across all DAGs (newest first).

  POST /v1/optimizer/proposals/{proposal_id}/accept
  POST /v1/optimizer/proposals/{proposal_id}/reject
      Record the user's decision on a propose-only proposal.

Auth: AuthMiddleware. Decisions write audit_log + a Signal #4-equivalent
outcome so user judgment becomes input to the NEXT optimizer pass.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.optimizer import (
    DECISION_ACCEPTED,
    DECISION_REJECTED,
    list_proposals,
    record_decision,
    run_optimizer,
)

router = APIRouter(tags=["optimizer"])


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = str(user.get("id") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


@router.post("/{dag_id}/run")
async def trigger_optimizer(
    dag_id: str,
    request: Request,
    apply_auto: bool = False,
    validate: bool = True,
) -> dict[str, Any]:
    """Run optimizer. When validate=True (default), proposals are tested
    against the actual DAG before being surfaced. Only strictly-improving
    mutations are proposed."""
    actor = _user_id(request)
    try:
        result = run_optimizer(dag_id, actor=actor, apply_auto=apply_auto)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # Validation gate: test each proposal by running variant B
    if validate and result.get("proposals"):
        import stores

        dag_data = stores.dags.get(dag_id)
        if dag_data:
            from services.benchmark_eval import evaluate_dag_run
            from services.graph_runner import execute_dag
            from services.validation_gate import validate_and_filter_proposals

            # Run current DAG to get REAL baseline score (not historical)
            try:
                baseline_result = await execute_dag(dict(dag_data))
                task = dag_data.get("description", dag_data.get("name", ""))
                baseline_eval = await evaluate_dag_run(baseline_result, task)
                baseline = float(baseline_eval.get("total", 0))
            except Exception:
                baseline = 0.0

            validated = await validate_and_filter_proposals(
                dict(dag_data),
                result["proposals"],
                baseline,
            )
            # Also test model variants
            from services.validation_gate import hill_climb_models, hill_climb_params

            model_improvements = await hill_climb_models(dict(dag_data), baseline)
            param_improvements = await hill_climb_params(dict(dag_data), baseline)
            validated.extend(model_improvements)
            validated.extend(param_improvements)

            result["proposals"] = validated
            result["validated"] = True
            result["baseline_score"] = baseline
            result["proposals_tested"] = len(validated)

    return result


@router.get("/{dag_id}/proposals")
def list_for_dag(
    dag_id: str,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    return list_proposals(dag_id=dag_id, decision=decision, limit=limit)


@router.get("/proposals")
def list_all_proposals(
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    return list_proposals(decision=decision, limit=limit)


@router.post("/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    actor = _user_id(request)
    try:
        return record_decision(proposal_id, DECISION_ACCEPTED, actor=actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    actor = _user_id(request)
    try:
        return record_decision(proposal_id, DECISION_REJECTED, actor=actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
