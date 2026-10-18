"""GET the live self-model snapshot — mood, personality facets, drives.

Read-only; any authenticated human (or the dashboard island) may view it.
Wired to the real maistro_turing.self_model types and compute_drives().

The snapshot is the caller's own Workspace scope (#859): the execution plane
resolves the canonical Workspace for the authenticated principal, and the
read touches only that scope's state. One user's — or one admin's — self-model
mutations can never appear in another user's snapshot, and the response names
the Workspace it was read from so provenance is explicit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from maistro_turing.producers import compute_drives
from maistro_turing.self_model import CANONICAL_FACETS

from ..execution import get_execution_plane
from ..middleware.auth import require_user
from ..state import SELF_ID, get_state

router = APIRouter(tags=["state"])


@router.get("/snapshot")
async def snapshot(user: dict = Depends(require_user)) -> dict:
    workspace_id, _project_id = await get_execution_plane().scope_for(str(user["id"]))
    st = get_state()
    mood = st.mood_snapshot(workspace_id)
    facet_scores = st.facet_scores(workspace_id)
    drives = compute_drives(facet_scores, mood)

    personality = {
        trait.value: {facet: facet_scores[facet] for facet in facets}
        for trait, facets in CANONICAL_FACETS.items()
    }

    return {
        "self_id": SELF_ID,
        "workspace_id": workspace_id,
        "mood": {
            "valence": mood.valence,
            "arousal": mood.arousal,
            "focus": mood.focus,
            "updated_at": mood.updated_at.isoformat(),
        },
        "personality": personality,
        "drives": {
            "creative_urge": drives.creative_urge,
            "curiosity": drives.curiosity,
            "diligence": drives.diligence,
            "restlessness": drives.restlessness,
        },
    }
