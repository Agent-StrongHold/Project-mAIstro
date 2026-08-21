"""Producer-artifact feed.

GET a paginated list of producer artifacts (blog / reflection / curiosity /
emotion) so the frontend's unified feed can list them, and GET a single artifact
(used by the Astro build to statically render each artifact's own page).

POST is the Turing-internal lane: Turing's producers authenticate with a
narrowly-scoped service key (turing:vault_write) to publish a new artifact.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from maistro.auth import Scope

from ..middleware.auth import require_turing_scope, require_user_or_turing_scope
from ..state import ARTIFACT_KINDS, get_state

router = APIRouter(tags=["feed"])


class PublishArtifactBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    title: str
    body: str


@router.get("")
def list_feed(
    _caller=Depends(require_user_or_turing_scope(Scope.TURING_VAULT_READ)),  # type: ignore[no-untyped-def]
    kind: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    if kind is not None and kind not in ARTIFACT_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind: {kind}")
    items, total = get_state().list_artifacts(kind=kind, offset=offset, limit=limit)
    return {
        "items": [a.to_dict() for a in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{artifact_id}")
def get_artifact(
    artifact_id: str,
    _caller=Depends(require_user_or_turing_scope(Scope.TURING_VAULT_READ)),  # type: ignore[no-untyped-def]
) -> dict:
    artifact = get_state().get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact.to_dict()


@router.post("", status_code=201)
def publish_artifact(
    body: PublishArtifactBody,
    _service=Depends(require_turing_scope(Scope.TURING_VAULT_WRITE)),  # type: ignore[no-untyped-def]
) -> dict:
    if body.kind not in ARTIFACT_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind: {body.kind}")
    artifact = get_state().add_artifact(body.kind, body.title, body.body)
    return artifact.to_dict()
