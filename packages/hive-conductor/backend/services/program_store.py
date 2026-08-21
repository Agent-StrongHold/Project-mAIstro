"""Per-(user, workspace) program context persistence for the program hyperagent.

Keyed by ``f"{user_id}:{project_id}"``, not bare ``user_id`` -- a user's
Persona/Workspace tabs each run an independent interview. ``project_id``
defaults to ``"default"`` so existing single-workspace callers (which never
pass it) are unaffected.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.agents.program_context import ProgramContext

logger = logging.getLogger("hive.program")


def _key(user_id: str, project_id: str) -> str:
    return f"{user_id}:{project_id}"


def get_context(user_id: str, project_id: str = "default") -> ProgramContext:
    import stores

    key = _key(user_id, project_id)
    raw = stores.program_contexts.get(key)
    if raw is not None:
        return ProgramContext.model_validate(raw)

    if project_id == "default":
        # Pre-Phase-B installs persisted this bare-user_id-keyed -- migrate it
        # forward once rather than silently presenting a blank context and
        # orphaning the old record.
        legacy = stores.program_contexts.pop(user_id, None)
        if legacy is not None:
            ctx = ProgramContext.model_validate(legacy)
            stores.program_contexts[key] = ctx.model_dump(mode="json")
            return ctx

    ctx = ProgramContext.empty(user_id, project_id)
    stores.program_contexts[key] = ctx.model_dump(mode="json")
    return ctx


def save_context(ctx: ProgramContext) -> ProgramContext:
    import stores

    stores.program_contexts[_key(ctx.user_id, ctx.project_id)] = ctx.model_dump(mode="json")
    logger.debug(
        "program_context_saved user=%s project=%s step=%s",
        ctx.user_id,
        ctx.project_id,
        ctx.interview_step,
    )
    return ctx


def context_dict(user_id: str, project_id: str = "default") -> dict[str, Any]:
    return get_context(user_id, project_id).model_dump(mode="json")
