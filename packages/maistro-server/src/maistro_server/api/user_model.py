"""User-model owner controls over HTTP (#1047).

The same ``UserModelService`` the Workspace Agent runtime calls answers these
routes; the API is a thin, owner-authenticated projection of it, never a
second owner. Every route takes the acting user from the authenticated
principal -- never from the request path or body -- so one principal cannot
read, correct or forget another's facts, and a lineage owned by someone else
is indistinguishable from a missing one.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.memory.user_model.retrieval import RecallQuery
from maistro.memory.user_model.service import UserModelService
from maistro.memory.user_model.types import FactSensitivity, UserModelError, UserModelFact
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import user_id as authenticated_user_id

router = APIRouter(prefix="/user-model", tags=["user-model"])

# Every @router handler below is named here (the a2a.py/canvas.py convention):
# FastAPI registers handlers from the decorators, which static import scanning
# cannot see, so without the declaration each handler resurfaces as unbanked
# fastapi-route-handler dead-code debt in the exact-debt-ledger gate.
__all__ = [
    "correct_fact",
    "fact_history",
    "forget_fact",
    "list_my_facts",
    "mark_fact_private",
    "recall_for_task",
    "router",
]

_service: UserModelService | None = None


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None else ""


def configure_user_model_service(service: UserModelService | None) -> None:
    """Bind the deployment's service; ``None`` takes the routes offline (503)."""
    global _service
    _service = service


def get_user_model_service() -> UserModelService:
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The user model requires a durable store; none is configured",
        )
    return _service


UserService = Annotated[UserModelService, Depends(get_user_model_service)]


class CorrectionBody(BaseModel):
    corrected_by: str
    reason: str
    corrected_at: str


class EvidenceBody(BaseModel):
    workspace_id: str = ""
    project_id: str = ""
    memory_id: str = ""
    run_id: str = ""
    artifact_id: str = ""


class FactBody(BaseModel):
    """JSON projection of one ``UserModelFact`` revision."""

    model_config = ConfigDict(extra="forbid")

    lineage_id: str
    fact_id: str
    revision: int
    supersedes: str | None
    owner_user_id: str
    kind: str
    statement: str
    evidence: list[EvidenceBody]
    first_observed: str
    last_observed: str
    last_reinforced: str
    confidence: float
    state: str
    valid_from: str | None
    valid_until: str | None
    sensitivity: str
    reusable: bool
    correction: CorrectionBody | None
    persona_hints: list[str]


def _project(fact: UserModelFact) -> FactBody:
    correction = None
    if fact.correction is not None:
        correction = CorrectionBody(
            corrected_by=fact.correction.corrected_by,
            reason=fact.correction.reason,
            corrected_at=_iso(fact.correction.corrected_at),
        )
    return FactBody(
        lineage_id=fact.lineage_id,
        fact_id=fact.fact_id,
        revision=fact.revision,
        supersedes=fact.supersedes,
        owner_user_id=fact.owner_user_id,
        kind=fact.kind,
        statement=fact.statement,
        evidence=[
            EvidenceBody(
                workspace_id=ref.workspace_id,
                project_id=ref.project_id,
                memory_id=ref.memory_id,
                run_id=ref.run_id,
                artifact_id=ref.artifact_id,
            )
            for ref in fact.evidence
        ],
        first_observed=_iso(fact.first_observed),
        last_observed=_iso(fact.last_observed),
        last_reinforced=_iso(fact.last_reinforced),
        confidence=fact.confidence,
        state=fact.state.value,
        valid_from=_iso(fact.valid_from) or None,
        valid_until=_iso(fact.valid_until) or None,
        sensitivity=fact.sensitivity.value,
        reusable=fact.reusable,
        correction=correction,
        persona_hints=list(fact.persona_hints),
    )


class CorrectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PrivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class RecallBody(BaseModel):
    """What the current task is about; ranking input, never an authorization."""

    model_config = ConfigDict(extra="forbid")

    task_text: str = ""
    persona_hints: tuple[str, ...] = ()
    workspace_id: str = ""
    max_sensitivity: FactSensitivity = FactSensitivity.PERSONAL
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    exclude_kinds: tuple[str, ...] = ()
    limit: int | None = Field(default=None, ge=1)


class RecallItem(BaseModel):
    statement: str
    kind: str
    confidence: float
    score: float
    lineage_id: str
    fact_id: str
    persona_hints: list[str]


def _user_model_error(exc: UserModelError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[FactBody])
async def list_my_facts(service: UserService, auth: RequireAuth) -> list[FactBody]:
    """What MAIstro believes about the authenticated user, with provenance."""
    return [_project(fact) for fact in await service.facts(authenticated_user_id(auth))]


@router.get("/{lineage_id}/history", response_model=list[FactBody])
async def fact_history(lineage_id: str, service: UserService, auth: RequireAuth) -> list[FactBody]:
    """One lineage's revisions; a foreign lineage looks like a missing one."""
    try:
        history = await service.history(lineage_id, acting_user_id=authenticated_user_id(auth))
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such fact") from None
    return [_project(fact) for fact in history]


@router.post("/{lineage_id}/correct", response_model=FactBody)
async def correct_fact(
    lineage_id: str,
    body: CorrectBody,
    service: UserService,
    auth: RequireAuth,
) -> FactBody:
    """Correct a fact about you; the correction carries provenance."""
    try:
        fact = await service.correct(
            lineage_id,
            acting_user_id=authenticated_user_id(auth),
            statement=body.statement,
            reason=body.reason,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such fact") from None
    except UserModelError as exc:
        raise _user_model_error(exc) from None
    return _project(fact)


@router.post("/{lineage_id}/mark-private", response_model=FactBody)
async def mark_fact_private(
    lineage_id: str,
    body: PrivateBody,
    service: UserService,
    auth: RequireAuth,
) -> FactBody:
    """Keep a fact but stop every task from seeing it."""
    try:
        fact = await service.mark_not_reusable(
            lineage_id, acting_user_id=authenticated_user_id(auth), reason=body.reason
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such fact") from None
    except UserModelError as exc:
        raise _user_model_error(exc) from None
    return _project(fact)


@router.delete("/{lineage_id}", response_model=FactBody)
async def forget_fact(
    lineage_id: str,
    service: UserService,
    auth: RequireAuth,
    reason: str = Query(min_length=1),
) -> FactBody:
    """Forget a fact; its statement is purged and its wordings stay blocked."""
    try:
        fact = await service.forget(
            lineage_id, acting_user_id=authenticated_user_id(auth), reason=reason
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such fact") from None
    except UserModelError as exc:
        raise _user_model_error(exc) from None
    return _project(fact)


@router.post("/recall", response_model=list[RecallItem])
async def recall_for_task(
    body: RecallBody, service: UserService, auth: RequireAuth
) -> list[RecallItem]:
    """Relevance-gated recall for one task: surprising relevance, not leakage."""
    query = RecallQuery(
        owner_user_id=authenticated_user_id(auth),
        task_text=body.task_text,
        persona_hints=body.persona_hints,
        workspace_id=body.workspace_id,
        max_sensitivity=body.max_sensitivity,
        min_confidence=body.min_confidence,
        exclude_kinds=body.exclude_kinds,
        limit=body.limit,
    )
    return [
        RecallItem(
            statement=scored.fact.statement,
            kind=scored.fact.kind,
            confidence=scored.fact.confidence,
            score=scored.score,
            lineage_id=scored.fact.lineage_id,
            fact_id=scored.fact.fact_id,
            persona_hints=list(scored.fact.persona_hints),
        )
        for scored in await service.recall_for_task(query)
    ]
