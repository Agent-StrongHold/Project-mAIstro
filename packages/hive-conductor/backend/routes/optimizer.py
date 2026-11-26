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

Auth: AuthMiddleware authenticates; this module authorizes (#2469). Every
surface resolves its requested proposal or DAG to the canonical owning
Workspace through `services.optimizer_scope` and refuses absent, foreign,
deleted, revoked, and aliasing targets with one non-disclosing 404 — the
coarse `dags.write` middleware grant is a session capability, not
target-scoped authority. Decisions write audit_log + a Signal #4-equivalent
outcome so user judgment becomes input to the NEXT optimizer pass.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from services import optimizer_scope
from services.dag_execution_scope import DagWorkspaceSelectionError
from services.optimizer import (
    DECISION_ACCEPTED,
    DECISION_REJECTED,
    record_decision,
    run_optimizer,
)
from services.optimizer_scope import OptimizerTargetNotAuthorized
from services.request_principal import require_actor_id

router = APIRouter(tags=["optimizer"])


def _user_id(request: Request) -> str:
    return require_actor_id(request)


def _not_found() -> HTTPException:
    """One non-disclosing refusal for absent, foreign, deleted, revoked,
    and aliasing optimizer targets (#2469): the four are indistinguishable
    from the outside, so the boundary cannot become an existence oracle."""
    return HTTPException(status_code=404, detail="optimizer target not found")


@router.post("/{dag_id}/run")
async def trigger_optimizer(
    dag_id: str,
    request: Request,
    apply_auto: bool = False,
    validate: bool = True,
    workspace_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Run optimizer. When validate=True (default), proposals are tested
    against the actual DAG before being surfaced. Only strictly-improving
    mutations are proposed."""
    actor = _user_id(request)
    org_id = str(getattr(request.state, "org_id", "") or "")
    # An explicit Project selection only ever narrows within the authorized
    # Workspace: the scope boundary refuses a Project that names another
    # tenant, so a client-supplied id is a selector, never a grant (#1110).
    requested_project = project_id or str(getattr(request.state, "project_id", "") or "") or None
    try:
        # Workspace selection first (the historical refusal posture), then
        # the DAG's canonical tenancy (#2469): membership in the selected
        # Workspace is not proof the DAG belongs to it. A DAG bound to
        # another tenant, a deleted descriptor, or an aliasing registration
        # shares one 404 — no baseline, no variant, no proposals.
        scope = await optimizer_scope.authorize_dag_run(
            actor,
            dag_id,
            workspace_id=workspace_id or "",
            project_id=requested_project,
        )
    except DagWorkspaceSelectionError as exc:
        raise HTTPException(
            status_code=403, detail="DAG Workspace scope is not authorized"
        ) from exc
    except OptimizerTargetNotAuthorized as exc:
        raise _not_found() from exc
    try:
        result = await run_optimizer(
            dag_id,
            actor=actor,
            apply_auto=apply_auto,
            org_id=org_id,
            project_id=str(getattr(request.state, "project_id", "") or ""),
            # The Workspace this request was authorized against: proposals
            # carry it so candidate registration lands in the authorizing
            # tenant, not the configured default (#861 review).
            workspace_id=str(getattr(scope, "workspace_id", "") or ""),
        )
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
                baseline_result = await execute_dag(dict(dag_data), scope=scope)
                task = dag_data.get("description", dag_data.get("name", ""))
                baseline_eval = await evaluate_dag_run(baseline_result, task)
                baseline = float(baseline_eval.get("total", 0))
            except Exception:
                baseline = 0.0

            validated = await validate_and_filter_proposals(
                dict(dag_data),
                result["proposals"],
                baseline,
                scope=scope,
            )
            # Also test model variants
            from services.validation_gate import hill_climb_models, hill_climb_params

            model_improvements = await hill_climb_models(dict(dag_data), baseline, scope=scope)
            param_improvements = await hill_climb_params(dict(dag_data), baseline, scope=scope)
            validated.extend(model_improvements)
            validated.extend(param_improvements)

            result["proposals"] = validated
            result["validated"] = True
            result["baseline_score"] = baseline
            result["proposals_tested"] = len(validated)

    return result


@router.get("/{dag_id}/proposals")
async def list_for_dag(
    dag_id: str,
    request: Request,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """One DAG's proposals, scoped to the caller's canonical Workspaces.

    Authentication happens in AuthMiddleware; it is not authorization
    (#2469). A DAG claimed by another tenant shares the non-disclosing 404
    with an unknown one, so the list cannot become a tenant oracle."""
    try:
        return await optimizer_scope.visible_dag_proposals(
            _user_id(request), dag_id, decision=decision, limit=limit
        )
    except OptimizerTargetNotAuthorized as exc:
        raise _not_found() from exc


@router.get("/proposals")
async def list_all_proposals(
    request: Request,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Proposals across the caller's Workspace universe, newest first.

    Membership scopes before the page limit, so a foreign tenant's newer
    pending rows cannot push the caller's own proposals out of the page."""
    return await optimizer_scope.visible_proposals(
        _user_id(request), decision=decision, limit=limit
    )


async def _decide(proposal_id: str, request: Request, decision: str) -> dict[str, Any]:
    """Record one manual decision behind the canonical target gate (#2469).

    The proposal resolves to its DAG's registered Workspace identity — never
    merely the stored proposal field — and the caller must hold live write
    membership there. The gate-resolved tenant is what the promotion commits
    into, so a stale or forged Workspace field on the stored row cannot
    redirect a candidate to another tenant.
    """
    actor = _user_id(request)
    try:
        target = await optimizer_scope.authorize_proposal_decision(actor, proposal_id)
    except OptimizerTargetNotAuthorized as exc:
        raise _not_found() from exc
    except optimizer_scope.OptimizerTargetForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        # record_decision awaits the candidate/promotion commit; the response
        # carries the truthful apply_outcome (#861). The workspace is the
        # gate-resolved canonical tenant, not the stored row's claim.
        return await record_decision(
            proposal_id, decision, actor=actor, workspace_id=target.workspace_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/proposals/{proposal_id}/accept")
async def accept_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    return await _decide(proposal_id, request, DECISION_ACCEPTED)


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    return await _decide(proposal_id, request, DECISION_REJECTED)
