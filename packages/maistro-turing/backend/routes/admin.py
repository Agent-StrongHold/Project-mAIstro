"""Admin self-model controls — GET / PATCH mood and personality facets.

Gated to the human-admin lane only (require_admin). Turing's own service key does
NOT reach these — autonomous self-edits flow through the producer/vault scopes,
not human admin power.

Mutations land in the admin's own Workspace scope (#859): the canonical
Workspace is resolved for the authenticated principal and only that scope's
self model changes. Admin power gates *whether* you may call these routes, not
*whose* mind they edit — one admin's PATCH cannot reach another principal's
snapshot, and every write traverses the one validated ``set_mood``/``set_facet``
mutation path on the scoped state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from maistro_turing.self_model import FACET_TO_TRAIT

from ..execution import get_execution_plane
from ..middleware.auth import require_admin
from ..state import get_state

router = APIRouter(tags=["admin"])


class MoodPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    valence: float | None = Field(default=None, ge=-1.0, le=1.0)
    arousal: float | None = Field(default=None, ge=0.0, le=1.0)
    focus: float | None = Field(default=None, ge=0.0, le=1.0)


class FacetPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    facet_id: str
    score: float = Field(ge=1.0, le=5.0)


@router.get("/self-model")
async def get_self_model(admin: dict = Depends(require_admin)) -> dict:
    workspace_id, _project_id = await get_execution_plane().scope_for(str(admin["id"]))
    st = get_state()
    mood = st.mood_snapshot(workspace_id)
    return {
        "workspace_id": workspace_id,
        "mood": {"valence": mood.valence, "arousal": mood.arousal, "focus": mood.focus},
        "facets": st.facet_scores(workspace_id),
    }


@router.patch("/mood")
async def patch_mood(patch: MoodPatch, admin: dict = Depends(require_admin)) -> dict:
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no mood fields provided")
    workspace_id, _project_id = await get_execution_plane().scope_for(str(admin["id"]))
    mood = get_state().set_mood(workspace_id, **fields)
    return {
        "workspace_id": workspace_id,
        "valence": mood.valence,
        "arousal": mood.arousal,
        "focus": mood.focus,
    }


@router.patch("/facet")
async def patch_facet(patch: FacetPatch, admin: dict = Depends(require_admin)) -> dict:
    if patch.facet_id not in FACET_TO_TRAIT:
        raise HTTPException(status_code=400, detail=f"unknown facet: {patch.facet_id}")
    workspace_id, _project_id = await get_execution_plane().scope_for(str(admin["id"]))
    try:
        get_state().set_facet(workspace_id, patch.facet_id, patch.score)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"workspace_id": workspace_id, "facet_id": patch.facet_id, "score": patch.score}
