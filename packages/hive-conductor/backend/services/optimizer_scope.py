"""Canonical optimizer target-resolution gate (#2469).

The optimizer's HTTP surfaces answered on bare global ids:

- ``GET  /v1/optimizer/proposals``                    — global list
- ``GET  /v1/optimizer/{dag_id}/proposals``           — per-DAG list
- ``POST /v1/optimizer/proposals/{id}/accept|reject`` — manual decision
- ``POST /v1/optimizer/{dag_id}/run``                 — one optimizer pass

``stores.optimizer_proposals`` is projection storage: it answers what a
proposal recorded to whoever holds the id. Authentication is not
authorization, and the middleware's coarse ``dags.write`` grant for
``POST /v1/optimizer`` is a session capability, not target-scoped authority
(#2469). Without a target gate, the lists returned every tenant's stored
proposals (model-authored rationale, source DAG identity, requested
mutations, evaluation evidence), a decision mutated any proposal id, and a
run executed an arbitrary ``dag_id`` under whichever Workspace the caller
selected.

Every optimizer route resolves the requested proposal or DAG to the
canonical Workspace that owns it — the same canonical Workspace/Project
authority every other scoped Hive surface reads (#37, #1174, #1152) — and
refuses absent, foreign, revoked, and aliasing targets with one
non-disclosing 404, before any proposal content, descriptor content, or
execution exists. Resolution rules:

- A proposal's canonical owning Workspace is its DAG's registered
  GraphTemplate Workspace when one is registered; otherwise the Workspace
  the **server** recorded on the proposal when the triggering run was
  authorized (#861 review) — never a caller-supplied value at decision
  time and never a model-authored field.
- When a registration and a proposal recording both exist and disagree, the
  row is an aliasing fault (stale, forged, or rehomed): it is refused, not
  resolved to whichever id the caller asked about, and never silently
  rehomed onto an authorized but unrelated Workspace.
- A proposal or DAG that resolves to no Workspace is visible to no one —
  the fail-closed posture #1174 set for scope-less projection rows.
- A DAG the optimizer may act on must exist in the descriptor store: a run
  against a bare id with no descriptor and no tenancy would mint proposals
  in the caller's tenant for a target that does not exist.

The routes hold no import of the proposal projection at all: the lists, the
decisions, and the run all go through this seam, so there is exactly one
authorization door and no second path a future handler could take around
it. Membership revalidation reads the live canonical store on every
request, so a session (or elevation) that outlives a revocation loses
access with it.

Nor does this module import the projection or descriptor stores directly:
``stores.optimizer_proposals`` and ``stores.dags`` are retiring surfaces
(WORKSPACE-CUTOVER-PLAN section 5) whose ledger entries may not gain a new
importer, so every row lookup, page walk, and descriptor existence check
here is delegated to ``services.optimizer`` — the module the retirement
ledger already names as their consumer (``proposal_rows``,
``stored_proposal``, ``dag_known``). The seam stays read-only and
late-bound, so per-test isolation of ``stores`` keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.dag_execution_scope import DagExecutionScope, authorize_hive_dag_scope

__all__ = [
    "PROPOSAL_READ_LIMIT",
    "OptimizerTargetForbidden",
    "OptimizerTargetNotAuthorized",
    "authorize_dag_run",
    "authorize_proposal_decision",
    "canonical_dag_workspace",
    "canonical_proposal_workspace",
    "visible_dag_proposals",
    "visible_proposals",
]


#: Same page bound `services.optimizer.list_proposals` enforces.
PROPOSAL_READ_LIMIT = 200


class OptimizerTargetNotAuthorized(LookupError):
    """Absent, foreign, deleted, revoked, or aliasing optimizer target.

    The route boundary maps this to the same non-disclosing 404 whether the
    id never existed, belongs to another tenant, was deleted, or its
    membership was revoked: one answer, no existence oracle.
    """


class OptimizerTargetForbidden(PermissionError):
    """A member without write authority asked for a target mutation.

    Unlike :class:`OptimizerTargetNotAuthorized` this names a member the
    canonical store can see, so the route boundary answers 403 — the
    posture `routes.schedules` sets for viewer writes.
    """


@dataclass(frozen=True, slots=True)
class OptimizerTarget:
    """The canonical identity one optimizer request was authorized against."""

    dag_id: str
    workspace_id: str
    proposal_id: str = ""


async def _registered_template_workspaces(dag_id: str) -> set[str]:
    """The Workspaces the DAG's registered GraphTemplate versions name.

    The canonical template store is the immutable registration authority
    (ADR-082926-65bf): ``(template_id, version)`` identity with redefinition
    refused. Versions of one template registered under more than one
    Workspace is a conflicting-identity fault the caller must refuse — this
    module reports it by returning both names so the caller's uniform
    refusal applies.
    """
    from services.optimizer_candidates import template_store

    store = template_store()
    try:
        versions = sorted(await store.versions(dag_id))
    except Exception:  # pragma: no cover - backends do not raise here
        return set()
    workspaces: set[str] = set()
    for version in reversed(versions):
        try:
            template = await store.get(dag_id, version=version)
        except Exception:  # pragma: no cover - backends do not raise here
            template = None
        if template is None:
            continue
        workspace = str(getattr(template, "workspace_id", "") or "").strip()
        if workspace:
            workspaces.add(workspace)
    return workspaces


def _recorded_proposal_workspaces(dag_id: str) -> set[str]:
    """The Workspaces the server recorded on this DAG's stored proposals."""
    from services.optimizer import proposal_rows

    workspaces: set[str] = set()
    for payload in proposal_rows():
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dag_id", "") or "").strip() != dag_id:
            continue
        workspace = str(payload.get("workspace_id", "") or "").strip()
        if workspace:
            workspaces.add(workspace)
    return workspaces


async def canonical_dag_workspace(dag_id: str) -> str:
    """The Workspace a DAG's optimizer surface is bound to, or ``''``.

    Resolution order: the DAG's registered GraphTemplate Workspace — the
    canonical, immutable registration — wins whenever one exists, and any
    proposal recording that contradicts it is refused per row (not
    rehomed). Without a registration, the one Workspace recorded across
    the DAG's proposals is the tenant of record; two recordings without a
    registration is an unresolvable aliasing fault:
    :class:`OptimizerTargetNotAuthorized`, never a guess. ``''`` is the
    only claimable answer; every other refusal is fail-closed.
    """
    if not dag_id.strip():
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    registered = await _registered_template_workspaces(dag_id)
    if len(registered) > 1:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    registered_workspace = next(iter(registered)) if registered else ""
    if registered_workspace:
        return registered_workspace
    recorded = _recorded_proposal_workspaces(dag_id)
    if len(recorded) > 1:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    return next(iter(recorded)) if recorded else ""


async def canonical_proposal_workspace(
    payload: dict[str, Any],
    *,
    dag_tenancy: str | None = None,
) -> str:
    """The canonical owning Workspace of one stored proposal payload.

    The DAG's canonical tenancy (registration first, then the union of its
    proposal recordings) is the target of record; a row that names a
    different tenant — or a row on a DAG whose tenancy is an aliasing
    fault — resolves to nothing and discloses itself to no one.
    `dag_tenancy` may be precomputed by the caller (one union walk per
    request, not per row).
    """
    dag_id = str(payload.get("dag_id", "") or "").strip()
    recorded = str(payload.get("workspace_id", "") or "").strip()
    if not dag_id:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    registered = await _registered_template_workspaces(dag_id)
    if len(registered) > 1:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    registered_workspace = next(iter(registered)) if registered else ""
    if registered_workspace and recorded and registered_workspace != recorded:
        # A proposal naming a tenant its own DAG's registration contradicts
        # is stale, forged, or rehomed. It discloses itself to no one.
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    workspace = registered_workspace or recorded
    if dag_tenancy is None:
        dag_tenancy = await canonical_dag_workspace(dag_id)
    if workspace != dag_tenancy:
        # The row's claim and the DAG's canonical tenancy disagree — a
        # forged or rehomed record among a tenant's honest rows (#2469):
        # neither the row nor the surface answers while the conflict stands.
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    return workspace


async def _member_role(user_id: str, workspace_id: str) -> str | None:
    """The caller's live canonical role in the Workspace, or None."""
    from services.workspace_authority import member_role

    if not user_id.strip() or not workspace_id.strip():
        return None
    try:
        return await member_role(user_id, workspace_id)
    except Exception:  # pragma: no cover - authority outage refuses closed
        return None


async def _visible_rows(
    user_id: str,
    *,
    dag_id: str = "",
    decision: str = "",
) -> list[dict[str, Any]]:
    """Stored proposals inside the caller's canonical Workspace universe.

    Membership scopes **before** any page limit, so a foreign tenant's
    newer rows cannot push the caller's own proposals out of the page (the
    #1240 discipline). Rows that resolve to no Workspace, and rows whose
    tenancy is an aliasing fault, are visible to no one.
    """
    from services.workspace_authority import list_workspace_ids_for_user

    allowed = {
        workspace
        for workspace in await list_workspace_ids_for_user(user_id)
        if str(workspace or "").strip()
    }
    if not allowed:
        return []
    wanted_dag = dag_id.strip()
    visible: list[dict[str, Any]] = []
    tenancy_cache: dict[str, str] = {}
    from services.optimizer import proposal_rows

    for stored in proposal_rows():
        if not isinstance(stored, dict):
            continue
        row_dag = str(stored.get("dag_id", "") or "").strip()
        if wanted_dag and row_dag != wanted_dag:
            continue
        if decision and stored.get("decision") != decision:
            continue
        payload = dict(stored)
        try:
            if row_dag not in tenancy_cache:
                tenancy_cache[row_dag] = await canonical_dag_workspace(row_dag)
            workspace = await canonical_proposal_workspace(
                payload, dag_tenancy=tenancy_cache[row_dag]
            )
        except OptimizerTargetNotAuthorized:
            continue
        if workspace in allowed:
            visible.append(payload)
    visible.sort(key=lambda item: item.get("created_at", "") or "", reverse=True)
    return visible


async def visible_proposals(
    user_id: str,
    *,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """The global proposal list, scoped to the caller's Workspace universe."""
    rows = await _visible_rows(user_id, decision=decision)
    return rows[: max(1, min(limit, PROPOSAL_READ_LIMIT))]


async def visible_dag_proposals(
    user_id: str,
    dag_id: str,
    *,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """One DAG's proposal list, scoped to the caller's Workspace universe.

    An absent descriptor and a foreign (claimed by another tenant) DAG
    share the non-disclosing refusal; an unclaimed DAG has nothing to
    disclose and answers the empty list.
    """
    dag_id = dag_id.strip()
    from services.optimizer import dag_known

    if not dag_id or not dag_known(dag_id):
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    claimed = await canonical_dag_workspace(dag_id)
    if claimed:
        if await _member_role(user_id, claimed) is None:
            raise OptimizerTargetNotAuthorized("optimizer target not found")
        rows = await _visible_rows(user_id, dag_id=dag_id, decision=decision)
    else:
        rows = []
    return rows[: max(1, min(limit, PROPOSAL_READ_LIMIT))]


async def authorize_proposal_decision(user_id: str, proposal_id: str) -> OptimizerTarget:
    """Resolve and authorize one manual accept/reject against its owner.

    The proposal is resolved to its canonical owning Workspace — the DAG's
    registered template identity first, never merely the stored proposal
    field — and the caller must hold live canonical membership in that
    Workspace, with write authority for the decision itself. Absent,
    foreign, deleted, revoked, scope-less, and aliasing targets share one
    non-disclosing refusal; a member without write authority (a viewer) is
    forbidden, not foreign, and answers 403.
    """
    from services.optimizer import dag_known, stored_proposal

    proposal_id = proposal_id.strip()
    payload = stored_proposal(proposal_id)
    if payload is None:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    dag_id = str(payload.get("dag_id", "") or "").strip()
    if not dag_id:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    # A deleted or missing target DAG refuses the decision: the promotion
    # surface the decision drives no longer exists.
    if not dag_known(dag_id):
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    workspace = await canonical_proposal_workspace(payload)
    if not workspace:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    role = await _member_role(user_id, workspace)
    if role is None:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    if role == "viewer":
        raise OptimizerTargetForbidden(
            "optimizer decision requires write authority in the owning Workspace"
        )
    return OptimizerTarget(dag_id=dag_id, workspace_id=workspace, proposal_id=proposal_id)


async def authorize_dag_run(
    user_id: str,
    dag_id: str,
    *,
    workspace_id: str,
    project_id: str | None = None,
) -> DagExecutionScope:
    """Authorize one optimizer pass over a DAG the requesting scope owns.

    The Workspace selection is admitted through the canonical
    ``authorize_hive_dag_scope`` boundary exactly as before (unknown,
    archived, and non-member selections share its refusal — that answer
    keeps its historical 403); then the requested DAG is resolved to its
    canonical tenancy. A DAG bound to another Workspace refuses — the
    selected Workspace's membership is not proof the DAG belongs to it
    (#2469) — and a DAG with no descriptor in the store refuses as absent.
    Both answers are the same non-disclosing 404; neither a baseline nor a
    proposal can exist for them.
    """
    from services.optimizer import dag_known

    scope = await authorize_hive_dag_scope(
        workspace_id=workspace_id, user_id=user_id, project_id=project_id
    )
    dag_id = dag_id.strip()
    if not dag_id or not dag_known(dag_id):
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    claimed = await canonical_dag_workspace(dag_id)
    if claimed and claimed != scope.workspace_id:
        raise OptimizerTargetNotAuthorized("optimizer target not found")
    return scope
