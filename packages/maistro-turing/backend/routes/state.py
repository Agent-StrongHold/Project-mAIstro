"""GET the live self-model snapshot — mood, personality facets, drives.

Read-only; any authenticated human (or the dashboard island) may view it.
The snapshot is the requesting principal's own cognitive scope (#859): one
user's (or admin's) mutations never appear in another principal's view. Wired
to the real maistro_turing.self_model types and compute_drives().
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from maistro.identity import Principal
from maistro_turing.producers import compute_drives
from maistro_turing.self_model import CANONICAL_FACETS

from ..middleware.auth import require_user
from ..state import SELF_ID, get_state

router = APIRouter(tags=["state"])


@router.get("/snapshot")
def snapshot(user: Principal = Depends(require_user)) -> dict:
    st = get_state()
    mood = st.mood_snapshot(user.actor_id())
    facet_scores = st.facet_scores(user.actor_id())
    drives = compute_drives(facet_scores, mood)

    personality = {
        trait.value: {facet: facet_scores[facet] for facet in facets}
        for trait, facets in CANONICAL_FACETS.items()
    }

    return {
        "self_id": SELF_ID,
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
