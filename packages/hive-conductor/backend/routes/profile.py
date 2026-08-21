"""User profile read/write — backs the Inner Temple identity panel.

Shares the same in-memory cache (_PROFILE_CACHE) that the chat-driven
profile_set/profile_get tools use, so a fact saved via chat shows up here
and vice versa. Also best-effort mirrors to PostgREST when configured
(services.pg_store no-ops gracefully when it isn't).
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["profile"])


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


class ProfileBody(BaseModel):
    preferences: dict = {}


@router.get("")
async def get_profile(request: Request) -> dict:
    from services.chat_completion import _PROFILE_CACHE, hydrate_profile_cache

    user_id = _user_id(request)
    await hydrate_profile_cache(user_id)
    return {"preferences": _PROFILE_CACHE.get(user_id, {})}


@router.put("")
async def put_profile(body: ProfileBody, request: Request) -> dict:
    from services.chat_completion import _PROFILE_CACHE
    from services.pg_store import pg_upsert

    user_id = _user_id(request)
    _PROFILE_CACHE[user_id] = body.preferences
    with contextlib.suppress(Exception):
        await pg_upsert("user_profiles", {"id": user_id, "preferences": body.preferences})
    return {"preferences": _PROFILE_CACHE[user_id]}
