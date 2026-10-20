"""Admin self-model controls — GET / PATCH mood and personality facets.

Gated to the human-admin lane only (require_admin). Turing's own service key does
NOT reach these — autonomous self-edits flow through the producer/vault scopes,
not human admin power. Mutations land in the calling admin's own cognitive
scope: one admin's PATCH is never observable in another principal's state
(#27/#859).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from maistro.identity import Principal
from maistro_turing.self_model import FACET_TO_TRAIT

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
def get_self_model(admin: Principal = Depends(require_admin)) -> dict:
    st = get_state()
    mood = st.mood_snapshot(admin.actor_id())
    return {
        "mood": {"valence": mood.valence, "arousal": mood.arousal, "focus": mood.focus},
        "facets": st.facet_scores(admin.actor_id()),
    }


@router.patch("/mood")
def patch_mood(patch: MoodPatch, admin: Principal = Depends(require_admin)) -> dict:
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no mood fields provided")
    mood = get_state().set_mood(admin.actor_id(), **fields)
    return {"valence": mood.valence, "arousal": mood.arousal, "focus": mood.focus}


@router.patch("/facet")
def patch_facet(patch: FacetPatch, admin: Principal = Depends(require_admin)) -> dict:
    if patch.facet_id not in FACET_TO_TRAIT:
        raise HTTPException(status_code=400, detail=f"unknown facet: {patch.facet_id}")
    try:
        get_state().set_facet(admin.actor_id(), patch.facet_id, patch.score)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"facet_id": patch.facet_id, "score": patch.score}
