"""Phase 5 — Signal #4: user thumbs feedback persistence.

Translates a `POST /v1/dag-runs/{run_id}/feedback` (or per-node) call into
a `maistro.memory.outcomes.Outcome` write so the next run's
`get_experience_context(project_id=…)` returns the thumbs-down lines as
a "## User Thumbs-Down Patterns" prompt section.

Design boundary: the route is dumb — validate body + auth, hand off here.
This service holds the outcome shape, the persistence call, and the
canonical Hive-local outcome store singleton.

The store is Hive-local (an InMemoryOutcomeStore instance owned by this
module) so the route can persist signals deterministically even when the
maistro-core engine bridge isn't initialized (e.g. test runs, dev mode
without `MAISTRO_ROUTER_API_KEY`). The maistro bridge can later share
the same instance via `set_outcome_store()` so the optimizer reads from
one source of truth.

Returned shape:
    {"recorded": True, "outcome_id": <int>, "signal": "user_thumb"}
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import Outcome

logger = logging.getLogger(__name__)

ALLOWED_THUMBS = ("up", "down")

# Hive-local default. The maistro bridge can replace this with the
# container's outcome_store via set_outcome_store() so all feedback flows
# into the same place the optimizer reads from.
_store: Any = InMemoryOutcomeStore()


def get_outcome_store() -> Any:
    """Return the currently-bound outcome store. Tests + the bridge can
    swap this via set_outcome_store()."""
    return _store


def set_outcome_store(store: Any) -> None:
    """Bind a different outcome store. Called by the engine bridge at
    boot to point feedback writes at the container's shared store, or
    by tests for isolation."""
    global _store
    _store = store


async def record_thumb(
    *,
    user_id: str,
    project_id: str,
    run_id: str,
    thumb: str,
    comment: str = "",
    node_id: str = "",
    dag_id: str = "",
    task_type: str = "dag_run",
) -> dict[str, Any]:
    """Persist a thumbs-{up,down} signal as a maistro Outcome record.

    The outcome carries `success=True` so it doesn't poison the
    failure-rate aggregate; the optimizer reads `thumb`/`thumb_comment`
    via the get_experience_context narrative path.
    """
    if thumb not in ALLOWED_THUMBS:
        raise ValueError(f"thumb must be one of {ALLOWED_THUMBS!r}, got {thumb!r}")
    if not user_id:
        raise ValueError("user_id is required")
    if not run_id:
        raise ValueError("run_id is required")

    store = get_outcome_store()
    outcome = Outcome(
        task_type=task_type,
        success=True,
        user_id=user_id,
        project_id=project_id,
        dag_run_id=run_id,
        dag_id=dag_id,
        node_id=node_id,
        thumb=thumb,
        thumb_comment=comment or "",
    )
    outcome_id = await store.record(outcome)
    logger.info(
        "feedback_recorded run_id=%s user=%s project=%s thumb=%s node=%s id=%d",
        run_id,
        user_id,
        project_id,
        thumb,
        node_id or "(run)",
        outcome_id,
    )
    return {
        "recorded": True,
        "outcome_id": outcome_id,
        "signal": "user_thumb",
    }
