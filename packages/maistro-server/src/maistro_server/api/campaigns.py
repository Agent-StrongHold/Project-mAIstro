"""Workspace campaign operator controls over HTTP (#103, SPEC-092626-1831).

The UI and the API write the **same durable records** the core contract
defines: creating a campaign, moving it to a new policy version, and the
pin-next / pause / exclude / human-only controls, parks and per-item records.
Nothing here executes work — these routes manage narrowing policy and its
audit trail, and every write is attributed to the authenticated principal and
the campaign's current ``policy_version`` by the store.

Authorization stays with its existing owners: Workspace membership decides
who may read and steer (VIEW), and who may author or re-version policy
(ADMINISTER). A campaign route grants nothing beyond that membership — the
same rule the core contract enforces on selection (invariant 1).
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.workspaces import WorkspaceStore
from maistro.workspaces.campaigns import (
    Actor,
    ActorKind,
    AutonomyMode,
    CampaignDefinition,
    CampaignPolicy,
    ControlKind,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
)
from maistro.workspaces.campaigns.store import CampaignStore
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_membership,
    require_workspace_owner,
    user_id,
)

router = APIRouter(prefix="/{workspace_id}/campaigns", tags=["campaigns"])


def get_campaign_store(request: Request) -> CampaignStore:
    """Return the exact campaign store selected by the process Container."""
    container = getattr(request.app.state, "container", None)
    store = None
    if container is not None and hasattr(container, "campaign_store"):
        store = container.campaign_store
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No campaign store is configured",
        )
    return cast(CampaignStore, store)


def _actor(auth: RequireAuth) -> Actor:
    return Actor(kind=ActorKind.USER, id=user_id(auth))


class CreateCampaignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"\S")
    project_id: str | None = None
    policy: CampaignPolicy = Field(default_factory=CampaignPolicy)


class UpdatePolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: CampaignPolicy


class SetControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ControlKind
    item_id: str | None = None


class SetItemRecordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode_override: AutonomyMode | None = None
    human_priority: float | None = None


class ParkItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    blocking_dependency: str | None = None
    failing_check: str | None = None
    run_reference: str | None = None
    artifact_references: list[str] = Field(default_factory=list)


class RecordUsageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_usd: float = Field(default=0.0, ge=0)
    minutes: float = Field(default=0.0, ge=0)
    completions: int = Field(default=0, ge=0)


async def _require_campaign(
    store: CampaignStore, workspace_id: str, campaign_id: str
) -> CampaignDefinition:
    campaign = await store.get_campaign(campaign_id)
    if campaign is None or campaign.workspace_id != workspace_id:
        # Do not disclose cross-Workspace campaign identifiers.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


@router.post("", response_model=CampaignDefinition, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    workspace_id: str,
    body: CreateCampaignBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> CampaignDefinition:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    return await store.create_campaign(
        workspace_id=workspace_id,
        name=body.name,
        actor=_actor(auth),
        policy=body.policy,
        project_id=body.project_id,
    )


@router.get("", response_model=list[CampaignDefinition])
async def list_campaigns(
    workspace_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> list[CampaignDefinition]:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    return await store.list_campaigns(workspace_id)


@router.get("/{campaign_id}", response_model=CampaignDefinition)
async def get_campaign(
    workspace_id: str,
    campaign_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> CampaignDefinition:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    return await _require_campaign(store, workspace_id, campaign_id)


@router.post("/{campaign_id}/policy", response_model=CampaignDefinition)
async def update_policy(
    workspace_id: str,
    campaign_id: str,
    body: UpdatePolicyBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> CampaignDefinition:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.update_policy(campaign_id, body.policy, actor=_actor(auth))


@router.get("/{campaign_id}/controls", response_model=list[ControlRecord])
async def list_controls(
    workspace_id: str,
    campaign_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
    active_only: Annotated[bool, Query()] = False,
) -> list[ControlRecord]:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.list_controls(campaign_id, active_only=active_only)


@router.post("/{campaign_id}/controls", response_model=ControlRecord)
async def set_control(
    workspace_id: str,
    campaign_id: str,
    body: SetControlBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> ControlRecord:
    """The UI writes pin-next / pause / exclude / human-only through here.

    Same record, same attribution, same durability as every other writer of
    the contract — the route adds no second path (AC-5)."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    # pin-next, exclude and human-only are item-scoped records; only a pause
    # may be campaign-wide. Refusing here gives the UI a 422 instead of the
    # store's own guard surfacing as a 500.
    if body.kind is not ControlKind.PAUSE and body.item_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{body.kind.value} control requires item_id",
        )
    return await store.set_control(
        campaign_id,
        body.kind,
        actor=_actor(auth),
        item_id=body.item_id,
    )


@router.post("/{campaign_id}/controls/{control_id}/clear", response_model=ControlRecord)
async def clear_control(
    workspace_id: str,
    campaign_id: str,
    control_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> ControlRecord:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    control = await store.get_control(control_id)
    if control is None or control.campaign_id != campaign_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control not found")
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.clear_control(control_id, actor=_actor(auth))


@router.get("/{campaign_id}/items", response_model=list[ItemPolicyRecord])
async def list_item_records(
    workspace_id: str,
    campaign_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> list[ItemPolicyRecord]:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.list_item_records(campaign_id)


@router.put("/{campaign_id}/items/{item_id}", response_model=ItemPolicyRecord)
async def set_item_record(
    workspace_id: str,
    campaign_id: str,
    item_id: str,
    body: SetItemRecordBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> ItemPolicyRecord:
    """Set the item's explicit human priority and/or mode override.

    The body is the whole record: a field left ``None`` clears it. The
    priority is stored exactly as given and is never rewritten by the
    system (AC-3)."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.set_item_record(
        campaign_id,
        item_id,
        actor=_actor(auth),
        mode_override=body.mode_override,
        human_priority=body.human_priority,
    )


@router.post("/{campaign_id}/items/{item_id}/park", response_model=ParkRecord)
async def park_item(
    workspace_id: str,
    campaign_id: str,
    item_id: str,
    body: ParkItemBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> ParkRecord:
    """Park stalled/blocked work with evidence (AC-6): the item leaves the
    eligible set until an attributed decision un-parks it."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.park_item(
        campaign_id,
        item_id,
        ParkEvidence(
            reason=body.reason,
            blocking_dependency=body.blocking_dependency,
            failing_check=body.failing_check,
            run_reference=body.run_reference,
            artifact_references=body.artifact_references,
        ),
        actor=_actor(auth),
    )


@router.post("/{campaign_id}/parks/{park_id}/unpark", response_model=ParkRecord)
async def unpark_item(
    workspace_id: str,
    campaign_id: str,
    park_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> ParkRecord:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    park = await store.get_park(park_id)
    if park is None or park.campaign_id != campaign_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Park not found")
    await _require_campaign(store, workspace_id, campaign_id)
    return await store.unpark_item(park_id, actor=_actor(auth))


@router.post("/{campaign_id}/usage")
async def record_usage(
    workspace_id: str,
    campaign_id: str,
    body: RecordUsageBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
) -> dict[str, Any]:
    """Record observed consumption against the campaign's budgets.

    The actor recording usage — the persistent Workspace Agent (#804) in
    practice — is attributed like every other decision writer."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    usage = await store.record_usage(
        campaign_id,
        actor=_actor(auth),
        cost_usd=body.cost_usd,
        minutes=body.minutes,
        completions=body.completions,
    )
    return {
        "cost_usd": usage.cost_usd,
        "minutes": usage.minutes,
        "completions": usage.completions,
    }


@router.get("/{campaign_id}/audit")
async def audit_trail(
    workspace_id: str,
    campaign_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    store: Annotated[CampaignStore, Depends(get_campaign_store)],
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[dict[str, Any]]:
    """Read the audit trail: every decision names its actor and the policy
    version it was made under (AC-8)."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_campaign(store, workspace_id, campaign_id)
    records = await store.audit_trail(campaign_id, limit=limit)
    return [
        {
            "seq": record.seq,
            "at": record.at.isoformat(),
            "actor": {"kind": record.actor.kind.value, "id": record.actor.id},
            "kind": record.kind.value,
            "policy_version": record.policy_version,
            "campaign_id": record.campaign_id,
            "item_id": record.item_id,
            "payload": record.payload,
        }
        for record in records
    ]
