"""Phase 5 — Signal #4: user thumbs feedback persistence.

Translates a `POST /v1/dag-runs/{run_id}/feedback` (or per-node) call into
a `maistro.memory.outcomes.Outcome` write so the next run's
`get_experience_context(project_id=…)` returns the thumbs-down lines as
a "## User Thumbs-Down Patterns" prompt section.

Design boundary: the route is dumb — validate body + auth, hand off here.
This service holds the outcome shape, the persistence call, and the
canonical Hive-local outcome store singleton.

The default store is Hive-local (an InMemoryOutcomeStore owned by this
module) so the route can persist signals deterministically before the
maistro-core engine bridge is initialized (test runs, dev mode without
`MAISTRO_ROUTER_API_KEY`). `services.engine` calls `set_outcome_store()`
at boot to replace it with the container's durable store, so a thumb
survives a restart and the optimizer reads from one source of truth.

`collect_thumbs` lives here rather than in the optimizer because it is the
only supported way to read this signal. The optimizer and the topology
comparison each used to iterate `store._outcomes` -- a private list that
`InMemoryOutcomeStore` has and neither durable store does, so binding a
durable store would have emptied both readers and raised nothing (#696).

Returned shape:
    {"recorded": True, "outcome_id": <int>, "signal": "user_thumb"}
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.constants import THUMB_WINDOW_DAYS
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


async def collect_thumbs(
    dag_id: str = "",
    *,
    days: int = THUMB_WINDOW_DAYS,
) -> dict[str, dict[str, Any]]:
    """`{node_id: {up, down, comments}}` for one DAG, from the bound store.

    The single reader of the thumbs signal. Both callers previously carried
    their own copy of this loop over `store._outcomes`, which is two places
    for the same aggregation to drift and two places the private attribute
    had to be remembered.

    A node id of `""` is a run-level thumb -- feedback on the whole run rather
    than one node -- and is kept under that key rather than dropped, because
    the optimizer scores it as a baseline against the DAG.
    """
    store = get_outcome_store()
    by_node: dict[str, dict[str, Any]] = {}
    for outcome in await store.list_thumbs(dag_id=dag_id, days=days):
        slot = by_node.setdefault(outcome.node_id or "", {"up": 0, "down": 0, "comments": []})
        if outcome.thumb == "up":
            slot["up"] += 1
        elif outcome.thumb == "down":
            slot["down"] += 1
            if outcome.thumb_comment:
                slot["comments"].append(outcome.thumb_comment)
    return by_node
