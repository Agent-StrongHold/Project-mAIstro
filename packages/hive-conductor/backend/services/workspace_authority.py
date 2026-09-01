"""Compose canonical Workspace identity with Hive-owned presentation state (#37).

The canonical ``maistro.workspaces.WorkspaceStore`` is the only live owner of
Workspace identity, name, membership, and Root Project provisioning. Hive's
historic ``stores.workspaces`` records are read only by the convergence import
below; routes and authorization never consult them after this module lands.

Hive still owns persona/UI choices. Those are persisted separately as
``WorkspacePresentation`` records keyed by the canonical Workspace ID. The key
is a reference, not another identity namespace.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Final, cast

import stores
from models.workspace import (
    AgentToolBinding,
    Workspace,
    WorkspaceMember,
    WorkspacePresentation,
    WorkspaceRole,
)
from services.model_store import ModelStore

from maistro.workspaces.model import WorkspaceRole as CanonicalWorkspaceRole
from maistro.workspaces.store import InMemoryWorkspaceStore, WorkspaceStore

logger = logging.getLogger("hive.workspace_authority")

_HIVE_TO_CANONICAL_ROLE: Final = {
    "viewer": CanonicalWorkspaceRole.MEMBER,
    "editor": CanonicalWorkspaceRole.CONTRIBUTOR,
    "owner": CanonicalWorkspaceRole.OWNER,
}
_CANONICAL_TO_HIVE_ROLE: Final = {
    CanonicalWorkspaceRole.MEMBER: "viewer",
    CanonicalWorkspaceRole.CONTRIBUTOR: "editor",
    CanonicalWorkspaceRole.OWNER: "owner",
}

_presentations: ModelStore[WorkspacePresentation] = ModelStore(
    "workspace_presentations", WorkspacePresentation
)
_fallback_store: InMemoryWorkspaceStore | None = None
_initialized_persistence: object | None = None
_migration_lock = asyncio.Lock()
_migrated_store_identity: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _engine_workspace_store() -> WorkspaceStore:
    """Return the canonical store already owned by this process's Container.

    Stub/dev mode has no Container. It receives one in-memory *canonical* store,
    not a Hive-private Workspace implementation, so request semantics remain
    usable without creating a second identity model.
    """
    global _fallback_store
    try:
        from services.engine import get_engine

        engine = get_engine()
    except RuntimeError:
        engine = None
    container = getattr(getattr(engine, "_agent_port", None), "container", None)
    store = getattr(container, "workspace_store", None)
    if store is not None:
        return cast(WorkspaceStore, store)
    if _fallback_store is None:
        _fallback_store = InMemoryWorkspaceStore()
    return _fallback_store


def _initialize_presentations() -> None:
    """Bind presentation records to Hive's already-selected persistence backend."""
    global _initialized_persistence
    persisted = getattr(stores, "_persisted", None)
    if _initialized_persistence is persisted:
        return
    _presentations._persisted = persisted
    _presentations.initialize()
    _initialized_persistence = persisted


def presentation_store() -> ModelStore[WorkspacePresentation]:
    """Testing/adapter seam for the Hive-owned half only."""
    _initialize_presentations()
    return _presentations


def _canonical_role(role: WorkspaceRole) -> CanonicalWorkspaceRole:
    return _HIVE_TO_CANONICAL_ROLE[role]


def _hive_role(role: CanonicalWorkspaceRole) -> WorkspaceRole:
    return cast(WorkspaceRole, _CANONICAL_TO_HIVE_ROLE[role])


def _presentation_from_legacy(legacy: Workspace) -> WorkspacePresentation:
    return WorkspacePresentation(
        workspace_id=legacy.id,
        persona_template_id=legacy.persona_template_id,
        checklist=list(legacy.checklist),
        tool_bindings=list(legacy.tool_bindings),
        theme_id=legacy.theme_id,
        voice_tone_override=legacy.voice_tone_override,
        active=legacy.active,
        updated_at=legacy.updated_at,
    )


def _legacy_owner(legacy: Workspace) -> WorkspaceMember | None:
    return next((member for member in legacy.members if member.role == "owner"), None)


async def _migrate_one(store: WorkspaceStore, legacy: Workspace, *, retire_source: bool) -> None:
    """Import one legacy record without ever remapping its Workspace ID."""
    canonical = await store.get(legacy.id)
    created = canonical is None
    if created:
        owner = _legacy_owner(legacy)
        if owner is None:
            raise ValueError(f"legacy Workspace {legacy.id!r} has no owner; refusing import")
        await store.create(
            creator_user_id=owner.user_id,
            name=legacy.name,
            workspace_id=legacy.id,
        )
        for member in legacy.members:
            if member.user_id == owner.user_id:
                continue
            await store.set_membership(
                legacy.id,
                user_id=member.user_id,
                role=_canonical_role(member.role),
            )

    if legacy.id not in _presentations:
        _presentations[legacy.id] = _presentation_from_legacy(legacy)

    # Only a durable canonical destination may retire durable source evidence.
    # An in-memory dev adapter is canonical in semantics but not in durability;
    # deleting the old record there would lose the Workspace on restart.
    if retire_source:
        stores.workspaces.pop(legacy.id, None)
    logger.info(
        "workspace_convergence_import workspace_id=%s created=%s retired_legacy=%s",
        legacy.id,
        created,
        retire_source,
    )


async def _ensure_ready() -> WorkspaceStore:
    global _migrated_store_identity
    store = _engine_workspace_store()
    _initialize_presentations()
    identity = id(store)
    if _migrated_store_identity == identity:
        return store

    async with _migration_lock:
        if _migrated_store_identity == identity:
            return store
        retire_source = not isinstance(store, InMemoryWorkspaceStore)
        for legacy in list(stores.workspaces.values()):
            await _migrate_one(store, legacy, retire_source=retire_source)
        _migrated_store_identity = identity
    return store


async def is_member(user_id: str, workspace_id: str | None) -> bool:
    if not workspace_id:
        return False
    store = await _ensure_ready()
    workspace = await store.get(workspace_id)
    if workspace is None:
        return False
    return await store.get_membership(workspace_id, user_id=user_id) is not None


async def member_role(user_id: str, workspace_id: str) -> WorkspaceRole | None:
    store = await _ensure_ready()
    workspace = await store.get(workspace_id)
    if workspace is None:
        return None
    membership = await store.get_membership(workspace_id, user_id=user_id)
    return _hive_role(membership.role) if membership is not None else None


async def get_view(workspace_id: str) -> Workspace | None:
    store = await _ensure_ready()
    canonical = await store.get(workspace_id)
    presentation = _presentations.get(workspace_id)
    if canonical is None or presentation is None:
        return None
    memberships = await store.list_memberships(workspace_id)
    return Workspace(
        id=canonical.workspace_id,
        persona_template_id=presentation.persona_template_id,
        name=canonical.name,
        members=[WorkspaceMember(user_id=m.user_id, role=_hive_role(m.role)) for m in memberships],
        checklist=list(presentation.checklist),
        tool_bindings=list(presentation.tool_bindings),
        theme_id=presentation.theme_id,
        voice_tone_override=presentation.voice_tone_override,
        active=presentation.active,
        created_at=canonical.created_at,
        updated_at=max(canonical.updated_at, presentation.updated_at),
    )


async def visible_view(user_id: str, workspace_id: str) -> Workspace | None:
    if not await is_member(user_id, workspace_id):
        return None
    return await get_view(workspace_id)


async def list_views_for_user(user_id: str) -> list[Workspace]:
    store = await _ensure_ready()
    canonical_workspaces = await store.list_for_user(user_id)
    views: list[Workspace] = []
    for canonical in canonical_workspaces:
        if canonical.workspace_id not in _presentations:
            continue
        view = await get_view(canonical.workspace_id)
        if view is not None:
            views.append(view)
    return views


async def create_workspace(
    *,
    creator_user_id: str,
    name: str,
    persona_template_id: str,
    checklist: list[str],
    theme_id: str,
    voice_tone_override: str | None,
) -> Workspace:
    store = await _ensure_ready()
    canonical = await store.create(creator_user_id=creator_user_id, name=name)
    presentation = WorkspacePresentation(
        workspace_id=canonical.workspace_id,
        persona_template_id=persona_template_id,
        checklist=list(checklist),
        theme_id=theme_id,
        voice_tone_override=voice_tone_override,
        updated_at=_now(),
    )
    try:
        _presentations[canonical.workspace_id] = presentation
    except BaseException:
        await store.delete(canonical.workspace_id)
        raise
    view = await get_view(canonical.workspace_id)
    if view is None:  # pragma: no cover - defensive after successful writes
        raise RuntimeError("canonical Workspace presentation did not compose")
    return view


async def set_member(workspace_id: str, *, user_id: str, role: WorkspaceRole) -> Workspace:
    store = await _ensure_ready()
    await store.set_membership(workspace_id, user_id=user_id, role=_canonical_role(role))
    view = await get_view(workspace_id)
    if view is None:
        raise KeyError(workspace_id)
    return view


async def remove_member(workspace_id: str, *, user_id: str) -> Workspace:
    store = await _ensure_ready()
    await store.remove_membership(workspace_id, user_id=user_id)
    view = await get_view(workspace_id)
    if view is None:
        raise KeyError(workspace_id)
    return view


async def update_presentation(
    workspace_id: str,
    *,
    active: bool | None = None,
    tool_bindings: list[AgentToolBinding] | None = None,
) -> Workspace:
    await _ensure_ready()
    presentation = _presentations.get(workspace_id)
    if presentation is None:
        raise KeyError(workspace_id)
    updates: dict[str, object] = {"updated_at": _now()}
    if active is not None:
        updates["active"] = active
    if tool_bindings is not None:
        updates["tool_bindings"] = list(tool_bindings)
    _presentations[workspace_id] = presentation.model_copy(update=updates)
    view = await get_view(workspace_id)
    if view is None:
        raise KeyError(workspace_id)
    return view


async def delete_workspace(workspace_id: str) -> None:
    store = await _ensure_ready()
    await store.delete(workspace_id)
    _presentations.pop(workspace_id, None)


def reset_for_tests() -> None:
    """Drop process-local adapter state; persisted source data is untouched."""
    global _fallback_store, _initialized_persistence, _migrated_store_identity
    _fallback_store = None
    _initialized_persistence = None
    _migrated_store_identity = None
    _presentations._data.clear()
    _presentations._persisted = None
