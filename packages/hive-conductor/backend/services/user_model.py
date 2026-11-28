"""Design Studio's consumption of the one shared user model (issue #7 row 18).

The milestone exit condition this module serves: "Design Studio consumes the
same persistent Workspace Agent/user-memory/Attention surfaces rather than
defining product-private variants (#777/#773)". This module therefore defines
no store, no second read path and no lookalike service: it composes
:class:`maistro.memory.user_model.service.UserModelService` — the one service
the Workspace Agent runtime and the HTTP API already go through, the same
composition ``maistro_server.main`` makes — over the deployment's PostgreSQL
session factory, the same factory the design services use.

Two deliberate shapes, both inherited from the canonical surfaces:

- **PostgreSQL or nothing.** The durable user model is PostgreSQL-only by
  design (ADR-092526-4391; ``maistro_server.main`` answers the same way with
  a warning). A deployment without the configured database gets ``None``
  here, and the caller degrades by recalling *nothing* — never by falling
  back to a process-local memory that could not survive a restart.
- **Recall only; no write surface.** User-model writes (correct / forget /
  mark-private / consolidation promotion) stay on the Agent and API surfaces
  that already own them. Design Studio is a consumer, so this module exposes
  relevance-gated recall for the work-opening flow and nothing else, which
  keeps ``audit_log`` a construction detail of the shared service rather
  than a second write path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.config.database import resolve_database_url, to_async_url
from maistro.memory.user_model.retrieval import RecallQuery, ScoredFact

if TYPE_CHECKING:
    from maistro.memory.user_model.service import UserModelService

logger = logging.getLogger(__name__)

__all__ = [
    "DESIGN_RECALL_LIMIT",
    "recall_for_design_task",
    "resolve_user_model_service",
]

#: How many recalled facts a Design Studio work-opening surface may assert.
#: Recall already ranks and gates; the cap keeps one surface from turning the
#: model into a profile dump (the exit condition wants consumption, not
#: wholesale reuse).
DESIGN_RECALL_LIMIT = 3


def resolve_user_model_service() -> UserModelService | None:
    """The shared :class:`UserModelService`, or ``None`` when unavailable.

    ``None`` answers the two honest unavailabilities, each logged once per
    call so the degradation is visible at wiring time, not after a restart:

    - the deployment has no configured PostgreSQL database (the durable
      user model has no other backend by design — no in-memory lookalike);
    - the embedded core runtime is not running, so the service's canonical
      audit log — which ``maistro_server.main`` also wires — cannot be
      resolved, and a half-composed service would be a second authority.
    """
    from services.audit_bridge import core_audit_log
    from services.design_service import _get_async_session_factory

    url = to_async_url(resolve_database_url())
    if not url.startswith("postgresql+asyncpg://"):
        logger.warning(
            "design_user_model_offline",
            extra={
                "detail": (
                    "no PostgreSQL database is configured, so Design Studio surfaces "
                    "recall nothing from the user model instead of serving facts "
                    "that could not survive a restart"
                )
            },
        )
        return None
    audit_log = core_audit_log()
    if audit_log is None:
        logger.warning(
            "design_user_model_offline",
            extra={
                "detail": (
                    "the core runtime is not running, so the user model's canonical "
                    "audit log is unavailable and Design Studio recalls nothing"
                )
            },
        )
        return None
    factory = _get_async_session_factory()
    if factory is None:
        logger.warning(
            "design_user_model_offline",
            extra={
                "detail": (
                    "the design database session factory did not start, so Design "
                    "Studio recalls nothing from the user model"
                )
            },
        )
        return None
    from maistro.memory.user_model.pg_store import PostgresUserModelStore
    from maistro.memory.user_model.service import UserModelService

    return UserModelService(store=PostgresUserModelStore(factory), audit_log=audit_log)


async def recall_for_design_task(
    user_id: str,
    task_text: str,
    *,
    workspace_id: str = "",
    service: UserModelService | None = None,
    limit: int = DESIGN_RECALL_LIMIT,
    now: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """Relevance-gated user-model recall for one Design Studio work opening.

    The single shared read path (:meth:`UserModelService.recall_for_task`)
    scores and filters before anything is returned — ownership by the store,
    sensitivity by the query's default ``PERSONAL`` cap — so a fact that does
    not match the requested work is left out even though the caller is
    authorized to read it. Returns provenance-bearing dicts (statement, kind,
    confidence, lineage id) the surface may show; ``None`` when the shared
    service is unavailable or recall failed, so callers degrade by omitting
    the context rather than by asserting an empty model as truth.
    """
    if service is None:
        service = resolve_user_model_service()
    if service is None:
        return None
    query = RecallQuery(
        owner_user_id=user_id,
        task_text=task_text,
        workspace_id=workspace_id,
        now=now if now is not None else datetime.now(UTC),
        limit=limit,
    )
    try:
        scored: list[ScoredFact] = await service.recall_for_task(query)
    except Exception:
        # Recall is enrichment over an already-working interview: a user-model
        # outage must not fail the work opening, and it must be visible.
        logger.exception("design_user_model_recall_failed")
        return None
    return [
        {
            "lineage_id": fact.fact.lineage_id,
            "kind": fact.fact.kind,
            "statement": fact.fact.statement,
            "confidence": round(fact.fact.confidence, 4),
        }
        for fact in scored
    ]
