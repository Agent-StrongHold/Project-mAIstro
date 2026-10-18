"""The caller's personal default Workspace (#1037, ADR-092326-7ed7).

A conversation-only turn from a surface that selects no Workspace runs in the
caller's default Workspace. It is an ordinary canonical Workspace, created on
first need through `services.workspace_authority` with the caller as owner.

Which Workspace is the default is decided by an insert-once claim keyed
`{user_id}#{generation}`. The claim's durable half is the persistence
backend's primary key, so two writers racing a first request cannot both
win: the loser deletes the Workspace it just made and adopts the winner's.
Resolution starts at the caller's latest generation, so a default that was
deleted, or that the caller no longer owns, is retired for good -- the next
generation is claimed for a new one, and re-adding the caller to the old
Workspace never makes it the default again.
"""

from __future__ import annotations

import asyncio
import weakref
from datetime import UTC, datetime
from typing import Any

import stores
from models.workspace import Workspace

from services import workspace_authority
from services.model_store import JsonStore

DEFAULT_WORKSPACE_NAME = "Personal"
#: Hive presentation persona of a default Workspace. Not a shipped Workspace
#: persona, so no persona spawns are materialized into it.
DEFAULT_WORKSPACE_PERSONA = "personal"
CLAIM_STORE = "default_workspace_claims"

_claims = JsonStore(CLAIM_STORE)
_bound_persistence: object | None = None
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


class DefaultWorkspaceUnavailable(RuntimeError):
    """The claimed default exists and is the caller's, but this process cannot
    compose its view yet. Retryable; never a reason to mint a second default."""


def claim_key(user_id: str, generation: int) -> str:
    return f"{user_id}#{generation}"


def _latest_generation(store: JsonStore, user_id: str) -> int:
    latest = 0
    for key, _claim in store.items():
        owner, _, generation = key.rpartition("#")
        if owner == user_id and generation.isdigit():
            latest = max(latest, int(generation))
    # The cache is loaded once per bind; another process may have claimed
    # later generations since. Claims are insert-once and contiguous, so
    # probing forward from the cached head finds the durable one.
    while store.refresh(claim_key(user_id, latest + 1)):
        latest += 1
    return latest


def _claims_store() -> JsonStore:
    """Bind the claim store to Hive's selected persistence backend, once per backend."""
    global _bound_persistence
    persisted = getattr(stores, "_persisted", None)
    if _bound_persistence is not persisted:
        _claims._data.clear()
        _claims._persisted = persisted
        _claims.initialize()
        _bound_persistence = persisted
    return _claims


def _lock_for(user_id: str) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


async def _current_default(user_id: str, claim: Any) -> Workspace | None:
    """The claimed Workspace while it exists and the caller still owns it."""
    workspace_id = claim.get("workspace_id") if isinstance(claim, dict) else None
    if not isinstance(workspace_id, str) or not workspace_id:
        return None
    canonical = await workspace_authority.canonical_workspace_store()
    if await canonical.get(workspace_id) is None:
        return None
    if await workspace_authority.member_role(user_id, workspace_id) != "owner":
        return None
    view = await workspace_authority.get_view(workspace_id)
    if view is None:
        raise DefaultWorkspaceUnavailable(
            f"default workspace {workspace_id} exists but its presentation is not loaded here"
        )
    return view


async def _create_and_claim(user_id: str, generation: int) -> Workspace | None:
    """Create a Workspace and claim it; None when another writer won the claim."""
    view = await workspace_authority.create_workspace(
        creator_user_id=user_id,
        name=DEFAULT_WORKSPACE_NAME,
        persona_template_id=DEFAULT_WORKSPACE_PERSONA,
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    claim = {
        "user_id": user_id,
        "workspace_id": view.id,
        "generation": generation,
        "claimed_at": datetime.now(UTC).isoformat(),
    }
    try:
        won = _claims_store().put_if_absent(claim_key(user_id, generation), claim)
    except BaseException:
        await workspace_authority.delete_workspace(view.id)
        raise
    if won:
        return view
    await workspace_authority.delete_workspace(view.id)
    return None


async def resolve_default_workspace(user_id: str) -> Workspace:
    """Return the caller's default Workspace, creating it exactly once."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("a default Workspace needs an authenticated principal")
    async with _lock_for(user_id):
        claims = _claims_store()
        generation = _latest_generation(claims, user_id)
        while True:
            key = claim_key(user_id, generation)
            if key not in claims:
                created = await _create_and_claim(user_id, generation)
                if created is not None:
                    return created
                # Lost the claim: `put_if_absent` loaded the winner's record,
                # so re-reading this generation adopts it.
                continue
            view = await _current_default(user_id, claims.get(key))
            if view is not None:
                return view
            generation += 1


def reset_for_tests() -> None:
    """Drop process-local claim state; persisted claims are untouched."""
    global _bound_persistence
    _bound_persistence = None
    _claims._data.clear()
    _claims._persisted = None
