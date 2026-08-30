"""User profile read/write — backs the Inner Temple identity panel.

Every handler here goes through `services.profile_store`, which is also what
the chat-driven `profile_get` / `profile_set` / `profile_delete` tools use, so
a fact saved in the panel is the same record a fact saved in chat lands in.
That was not true before #699: this route wrote a module-global dict and the
tools read a PostgREST table no migration creates, so neither could see the
other's writes and the panel's saves were silently overwritten.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.profile_store import ProfilePersistenceError, ProfileSchemaError

router = APIRouter(tags=["profile"])


def _user_id(request: Request) -> str:
    """The principal this request's profile belongs to.

    There is no fallback identity. This used to return the literal `"dev"` for
    a request whose principal carried neither an id nor a username, which would
    have pointed every such caller at one shared profile — a scope leak on
    user-identifying content. `/v1/profile` is behind the auth middleware, so a
    request with no principal at all is already 401; this covers the rest.
    """
    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id") or user.get("username") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


class ProfileBody(BaseModel):
    preferences: dict = {}


@router.get("")
async def get_profile(request: Request) -> dict:
    from services import profile_store

    user_id = _user_id(request)
    try:
        record = profile_store.load(user_id)
    except ProfileSchemaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "preferences": record.preferences,
        "revision": record.revision,
        "durable": profile_store.durable(),
    }


@router.put("")
async def put_profile(body: ProfileBody, request: Request) -> dict:
    """Replace the profile, and acknowledge only what the store read back.

    The previous implementation wrote a dict, mirrored to PostgREST inside a
    `contextlib.suppress`, and returned the body it had been handed — a 200 for
    a write that reached nothing. A storage failure is a 503 here.
    """
    from services import profile_store

    user_id = _user_id(request)
    try:
        record = profile_store.save(user_id, body.preferences)
    except (ProfilePersistenceError, ProfileSchemaError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "preferences": record.preferences,
        "revision": record.revision,
        "durable": profile_store.durable(),
    }


@router.delete("")
async def delete_profile(request: Request) -> dict:
    """Remove the whole record.

    The record, not its contents: saving `{}` would leave "I deleted my
    profile" and "my profile is empty" as the same stored state, and a profile
    is user-authored, user-identifying content whose deletion is not optional
    (SPEC-083026-ef62).
    """
    from services import profile_store

    user_id = _user_id(request)
    try:
        existed = profile_store.delete(user_id)
    except ProfilePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"deleted": existed}
