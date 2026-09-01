"""Compose canonical Workspace identity with Hive-owned presentation state (#37).

The canonical ``maistro.workspaces.WorkspaceStore`` is the only live owner of
Workspace identity, name, membership, and Root Project provisioning. Hive's
historic ``stores.workspaces`` records are migration/recovery input only;
routes and authorization never consult them as authority.

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

from maistro.workspaces.model import WorkspaceRole as CanonicalWorkspaceRole
from maistro.workspaces.store import InMemoryWorkspaceStore, WorkspaceStore
from models.workspace import (
    AgentToolBinding,
    Workspace,
    WorkspaceMember,
    WorkspacePresentation,
    WorkspaceRole,
)
from services.model_store import JsonStore, ModelStore

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
_migration_journal = JsonStore("workspace_convergence_journal")
_quarantine = JsonStore("workspace_convergence_quarantine")
_fallback_store: InMemoryWorkspaceStore | None = None
_initialized_persistence: object | None = None
_migration_lock = asyncio.Lock()
_migrated_store_identity: int | None = None


class LegacyWorkspaceQuarantined(ValueError):
    """A legacy row is malformed and must not block other Workspace imports."""


def _now() -> datetime:
    return datetime.now(UTC)


def _engine_workspace_store() -> WorkspaceStore:
    """Return the canonical store already owned by this process's Container.

    Stub/dev mode has no Container. It receives one in-memory *canonical* store.
    When Hive persistence is configured, ``stores.workspaces`` is retained only
    as restart recovery evidence for that ephemeral canonical store.
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


def canonical_store_for_tests() -> WorkspaceStore:
    """Expose the canonical test seam without making legacy rows authoritative."""
    return _engine_workspace_store()


def _is_durable_store(store: WorkspaceStore) -> bool:
    return not isinstance(store, InMemoryWorkspaceStore)


def _initialize_adapter_stores() -> None:
    """Bind adapter-owned records to Hive's already-selected persistence backend."""
    global _initialized_persistence
    persisted = getattr(stores, "_persisted", None)
    if _initialized_persistence is persisted:
        return
    for adapter_store in (_presentations, _migration_journal, _quarantine):
        adapter_store._persisted = persisted
        adapter_store.initialize()
    _initialized_persistence = persisted


def presentation_store() -> ModelStore[WorkspacePresentation]:
    """Testing/adapter seam for the Hive-owned presentation half only."""
    _initialize_adapter_stores()
    return _presentations


def quarantine_store() -> JsonStore:
    """Inspection seam for malformed legacy rows held out of migration."""
    _initialize_adapter_stores()
    return _quarantine


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


def _validate_import_source(legacy: Workspace) -> WorkspaceMember:
    """Validate the whole roster before the first canonical migration write."""
    if not legacy.id.strip():
        raise LegacyWorkspaceQuarantined("workspace id is blank")
    if not legacy.name.strip():
        raise LegacyWorkspaceQuarantined("workspace name is blank")
    owner = _legacy_owner(legacy)
    if owner is None:
        raise LegacyWorkspaceQuarantined("workspace has no owner")
    seen: set[str] = set()
    for member in legacy.members:
        if not member.user_id.strip():
            raise LegacyWorkspaceQuarantined("workspace has a blank member user_id")
        if member.user_id in seen:
            raise LegacyWorkspaceQuarantined(
                f"workspace has duplicate member user_id {member.user_id!r}"
            )
        seen.add(member.user_id)
    return owner


def _journal_status(workspace_id: str) -> str:
    raw = _migration_journal.get(workspace_id, {})
    return str(raw.get("status", "")) if isinstance(raw, dict) else ""


def _write_journal(workspace_id: str, *, status: str, mode: str) -> None:
    _migration_journal[workspace_id] = {
        "status": status,
        "mode": mode,
        "updated_at": _now().isoformat(),
    }


def _quarantine_source(source_key: str, legacy: Workspace, exc: Exception) -> None:
    _quarantine[source_key] = {
        "workspace_id": legacy.id,
        "reason": str(exc),
        "quarantined_at": _now().isoformat(),
    }
    logger.error(
        "workspace_convergence_quarantined source_key=%s workspace_id=%s reason=%s",
        source_key,
        legacy.id,
        exc,
    )


async def _sync_fallback_recovery_evidence(
    store: WorkspaceStore,
    workspace_id: str,
) -> None:
    """Persist enough source evidence to rebuild an ephemeral canonical fallback.

    This record is never consulted for authorization. It exists only because an
    in-memory canonical store cannot survive process restart while Hive's
    persisted store can.
    """
    if _is_durable_store(store):
        return
    canonical = await store.get(workspace_id)
    presentation = _presentations.get(workspace_id)
    if canonical is None or presentation is None:
        return
    memberships = await store.list_memberships(workspace_id)
    recovery = Workspace(
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
    stores.workspaces[workspace_id] = recovery


async def _copy_import_roster(store: WorkspaceStore, legacy: Workspace) -> None:
    """Idempotently copy the validated roster; safe to resume after interruption."""
    for member in legacy.members:
        await store.set_membership(
            legacy.id,
            user_id=member.user_id,
            role=_canonical_role(member.role),
        )


async def _migrate_one(
    store: WorkspaceStore,
    source_key: str,
    legacy: Workspace,
    *,
    retire_source: bool,
) -> None:
    """Import one source without remapping identity or treating partial work as complete."""
    canonical = await store.get(legacy.id) if legacy.id.strip() else None
    status = _journal_status(legacy.id) if legacy.id.strip() else ""
    managed_import = status == "importing"
    created = False

    if canonical is None:
        owner = _validate_import_source(legacy)
        _write_journal(legacy.id, status="importing", mode="legacy_import")
        canonical = await store.create(
            creator_user_id=owner.user_id,
            name=legacy.name,
            workspace_id=legacy.id,
            created_at=legacy.created_at,
            updated_at=legacy.updated_at,
        )
        managed_import = True
        created = True
    elif managed_import:
        _validate_import_source(legacy)

    # Only an import started by this adapter owns the right to replay source
    # membership. A canonical Workspace that pre-dated the migration remains
    # authoritative and stale legacy membership is ignored.
    if managed_import:
        await _copy_import_roster(store, legacy)

    if legacy.id not in _presentations:
        _presentations[legacy.id] = _presentation_from_legacy(legacy)

    if retire_source:
        _write_journal(legacy.id, status="complete", mode="legacy_import")
        # Representation retirement is not logical Workspace deletion: using
        # ModelStore.pop() here would invoke the agent-materialization cascade.
        stores.workspaces.retire_record(source_key, None)
    else:
        # Keep the migration source synchronized as recovery evidence before
        # declaring the import complete. On restart a fresh fallback can replay
        # this exact canonical state.
        await _sync_fallback_recovery_evidence(store, legacy.id)
        _write_journal(legacy.id, status="complete", mode="fallback_recovery")

    _quarantine.pop(source_key, None)
    logger.info(
        "workspace_convergence_import workspace_id=%s created=%s resumed=%s retired_legacy=%s",
        legacy.id,
        created,
        managed_import and not created,
        retire_source,
    )


async def _ensure_ready() -> WorkspaceStore:
    global _migrated_store_identity
    store = _engine_workspace_store()
    _initialize_adapter_stores()
    identity = id(store)
    if _migrated_store_identity == identity:
        return store

    async with _migration_lock:
        if _migrated_store_identity == identity:
            return store
        retire_source = _is_durable_store(store)
        for source_key, legacy in list(stores.workspaces.items()):
            try:
                await _migrate_one(
                    store,
                    source_key,
                    legacy,
                    retire_source=retire_source,
                )
            except LegacyWorkspaceQuarantined as exc:
                _quarantine_source(source_key, legacy, exc)
                continue
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
        await _sync_fallback_recovery_evidence(store, canonical.workspace_id)
        _write_journal(
            canonical.workspace_id,
            status="complete",
            mode="fallback_recovery" if not _is_durable_store(store) else "canonical_create",
        )
    except BaseException:
        if canonical.workspace_id in stores.workspaces:
            stores.workspaces.retire_record(canonical.workspace_id, None)
        _presentations.pop(canonical.workspace_id, None)
        await store.delete(canonical.workspace_id)
        raise
    view = await get_view(canonical.workspace_id)
    if view is None:
        raise RuntimeError("canonical Workspace presentation did not compose")
    return view


async def set_member(workspace_id: str, *, user_id: str, role: WorkspaceRole) -> Workspace:
    store = await _ensure_ready()
    await store.set_membership(workspace_id, user_id=user_id, role=_canonical_role(role))
    await _sync_fallback_recovery_evidence(store, workspace_id)
    view = await get_view(workspace_id)
    if view is None:
        raise KeyError(workspace_id)
    return view


async def remove_member(workspace_id: str, *, user_id: str) -> Workspace:
    store = await _ensure_ready()
    await store.remove_membership(workspace_id, user_id=user_id)
    await _sync_fallback_recovery_evidence(store, workspace_id)
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
    store = await _ensure_ready()
    presentation = _presentations.get(workspace_id)
    if presentation is None:
        raise KeyError(workspace_id)
    updates: dict[str, object] = {"updated_at": _now()}
    if active is not None:
        updates["active"] = active
    if tool_bindings is not None:
        updates["tool_bindings"] = list(tool_bindings)
    _presentations[workspace_id] = presentation.model_copy(update=updates)
    await _sync_fallback_recovery_evidence(store, workspace_id)
    view = await get_view(workspace_id)
    if view is None:
        raise KeyError(workspace_id)
    return view


async def delete_workspace(workspace_id: str) -> None:
    store = await _ensure_ready()
    await store.delete(workspace_id)
    _presentations.pop(workspace_id, None)
    _migration_journal.pop(workspace_id, None)
    if workspace_id in stores.workspaces:
        # This is a real logical deletion, so the normal pop lifecycle applies.
        stores.workspaces.pop(workspace_id, None)


def reset_for_tests() -> None:
    """Drop process-local adapter state; persisted source data is untouched."""
    global _fallback_store, _initialized_persistence, _migrated_store_identity
    _fallback_store = None
    _initialized_persistence = None
    _migrated_store_identity = None
    for adapter_store in (_presentations, _migration_journal, _quarantine):
        adapter_store._data.clear()
        adapter_store._persisted = None
