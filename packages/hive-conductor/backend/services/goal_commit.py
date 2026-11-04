"""Commit a brief interview draft to the canonical Goal store (#805, #1823).

When the engine exposes a scoped Goal writer, ``commit_brief_as_goal`` maps
``commit_brief`` output to :class:`GoalRevisionDraft` and creates revision 1.
Without that seam the caller keeps ``written: []`` — the same honest answer
the program ``/brief/draft`` route held before the writer existed.

**#804 hard limits (not implemented here):** overnight Workspace Agent cadence,
Goal reconciler loops, Sorrel timeline UI, CreativeBrief persistence (#774),
artifact reconciliation, and RunStore unification (#251). This module only
creates revision 1 from an interview draft through ``ScopedGoalStore`` —
authorization unchanged (#1174).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("hive.goal_commit")

_BRIEF_FIELD_ORDER = (
    "outcome",
    "channel",
    "source",
    "deadline",
    "voice",
    "claims",
    "mode",
)


def brief_draft_to_goal_revision(draft: dict[str, Any], *, author: str) -> Any:
    """Map a ``commit_brief`` draft to the canonical Goal revision shape."""
    from maistro.goals import GoalRevisionDraft

    fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    subject = str(fields.get("subject") or "").strip()
    opening = str(draft.get("opening") or "").strip()
    desired_state = subject or opening or "Video brief committed from chat interview"

    success_conditions: list[str] = []
    for key in _BRIEF_FIELD_ORDER:
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            success_conditions.append(f"{key}: {value.strip()}")

    notes = draft.get("notes")
    stop_conditions: list[str] = []
    if isinstance(notes, list):
        stop_conditions.extend(str(note).strip() for note in notes if str(note).strip())
    if not stop_conditions:
        stop_conditions.append("Brief superseded or withdrawn by the workspace owner")

    return GoalRevisionDraft(
        desired_state=desired_state,
        success_conditions=tuple(success_conditions),
        stop_conditions=tuple(stop_conditions),
        author=author,
    )


async def _project_id_for_workspace(workspace_id: str) -> str | None:
    from services.hitl_authorization import _project_store
    from services.workspace_authority import canonical_store_for_tests

    candidates: list[Any] = []
    primary = await _project_store()
    if primary is not None:
        candidates.append(primary)
    fallback = getattr(canonical_store_for_tests(), "project_store", None)
    if fallback is not None and fallback not in candidates:
        candidates.append(fallback)

    for project_store in candidates:
        try:
            root = await project_store.root_for_workspace(workspace_id)
        except Exception:
            continue
        return str(root.project_id)

    logger.warning("brief goal commit skipped: no root project for workspace %s", workspace_id)
    return None


async def commit_brief_as_goal(
    user_id: str, workspace_id: str, draft: dict[str, Any]
) -> str | None:
    """Create a Goal from a brief draft when the canonical writer is wired.

    Returns the new ``goal_id``, or ``None`` when no Goal store is available
    in this process (typical Docker/homelab without the core container bridge).
    """
    from services.engine import get_engine
    from services.workspace_agent import resolve_workspace_agent

    reader = get_engine().goal_reader
    if reader is None or not hasattr(reader, "create_goal"):
        return None

    project_id = await _project_id_for_workspace(workspace_id)
    if not project_id:
        logger.warning("brief goal commit skipped: no project for workspace %s", workspace_id)
        return None

    try:
        agent = await resolve_workspace_agent(workspace_id)
    except Exception:
        logger.warning(
            "brief goal commit skipped: workspace agent unavailable for %s", workspace_id
        )
        return None

    revision = brief_draft_to_goal_revision(draft, author=user_id)
    try:
        goal = await reader.create_goal(
            principal_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            agent_id=agent.id,
            draft=revision,
        )
    except Exception:
        logger.exception("brief goal commit failed for workspace %s", workspace_id)
        return None
    return str(goal.goal_id)
