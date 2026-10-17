"""Per-(user, workspace) brief interview persistence (SPEC-091726-7c2a).

One interview at a time per person per workspace, keyed like
``program_store``: ``f"{user_id}:{project_id}"``. The interview is chat
state, not a Goal: nothing here is a Goal or CreativeBrief record, and
clearing it after a draft is produced (or on "never mind") loses nothing
that was ever committed.
"""

from __future__ import annotations

import logging

from maistro.agents.brief_interview import BriefInterview

logger = logging.getLogger("hive.program")


def _key(user_id: str, project_id: str) -> str:
    return f"{user_id}:{project_id}"


def get_interview(user_id: str, project_id: str) -> BriefInterview | None:
    import stores

    raw = stores.brief_interviews.get(_key(user_id, project_id))
    if raw is None:
        return None
    return BriefInterview.model_validate(raw)


def save_interview(user_id: str, project_id: str, state: BriefInterview) -> BriefInterview:
    import stores

    stores.brief_interviews[_key(user_id, project_id)] = state.model_dump(mode="json")
    logger.debug(
        "brief_interview_saved user=%s project=%s answered=%s",
        user_id,
        project_id,
        sorted(state.answers),
    )
    return state


def clear_interview(user_id: str, project_id: str) -> bool:
    import stores

    return stores.brief_interviews.pop(_key(user_id, project_id), None) is not None
