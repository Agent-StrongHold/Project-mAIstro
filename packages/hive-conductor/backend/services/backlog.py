"""Canonical BacklogItem service — the one write path for Conductor backlog.

Every backlog mutation — create, edit, prioritize, reorder, block/unblock,
decompose, pin, pause, archive — goes through this service. The HTTP surface
(``routes.backlog``) is a thin adapter over it, and the board/list/detail UI
(#99) is a client of that surface. There is no second backlog store and no
UI-local authority: until the cutover issue (#102) lands, the UI edits through
exactly this service and is explicitly marked non-authoritative (see
``UI_AUTHORITY``).

Authorization is fail closed:

- an unauthenticated caller never reaches the service (401 at the boundary);
- a personal item (no workspace) is readable/editable only by its owner, and
  everyone else gets the same "not found" answer, so the service is not an
  existence oracle for other people's work;
- a workspace item is readable by members only, and a read-only (viewer)
  member's edit attempt is refused with 403 rather than silently ignored.

Concurrent editors are handled with optimistic concurrency: every mutation
names the ``version`` it read; a mismatch raises :class:`VersionConflictError`
carrying the current item so the loser can reload and reapply.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import stores
from models.backlog import (
    AUTONOMY_MODES,
    BACKLOG_STATUSES,
    RISK_LEVELS,
    BacklogItem,
    ProvenanceEntry,
)
from pydantic import ValidationError

from services import workspace_authority

#: Machine-readable authority statement surfaced by the API and shown by the
#: UI (#102). Before the cutover the UI is a preview surface over the
#: canonical service, never a second authority; once the recorded authority
#: cutover has run (quality/backlog-authority.json, written by
#: scripts/backlog_cutover.py), the UI's edits land in the database that is
#: now the work-source of record, and the flag reads true.
UI_AUTHORITY: dict[str, Any] = {
    "canonical_service": "services.backlog",
    "ui_authoritative": False,
    "cutover_issue": 102,
}

#: Override for the committed authority marker; tests point this at a temp
#: file so the flip is provable without mutating the repository.
AUTHORITY_MARKER_ENV = "MAISTRO_BACKLOG_AUTHORITY_FILE"


def _authority_marker_path() -> Path | None:
    override = os.environ.get(AUTHORITY_MARKER_ENV)
    if override:
        path = Path(override)
        return path if path.exists() else None
    default = Path(__file__).resolve().parents[4] / "quality" / "backlog-authority.json"
    return default if default.exists() else None


def ui_authority_snapshot() -> dict[str, Any]:
    """The current authority statement, read from the committed marker.

    A missing or unreadable marker means the pre-cutover default: the
    hand-maintained Markdown backlog is canonical and this UI is explicitly
    non-authoritative. Failures to read never flip authority on.
    """
    authority, revision = "markdown", 0
    path = _authority_marker_path()
    if path is not None:
        try:
            record = json.loads(path.read_text())
            authority = str(record.get("authority", "markdown"))
            revision = int(record.get("revision") or 0)
        except (OSError, ValueError, TypeError):
            authority, revision = "markdown", 0
    return {
        "canonical_service": "services.backlog",
        "ui_authoritative": authority == "db",
        "cutover_issue": 102,
        "authority": authority,
        "authority_revision": revision,
    }


#: Provenance is inspection data, not an event log; cap it so a long-lived
#: item cannot grow without bound. Oldest entries fall off first.
_PROVENANCE_CAP = 200

_EDITABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "status",
        "priority",
        "acceptance_evidence",
        "source",
        "risk",
        "autonomy_mode",
        "goal_id",
        "goal_revision",
        "dependencies",
        "pinned",
        "paused",
        "paused_reason",
        "archived",
        "blocked_reason",
        # Deliberately absent: ``workspace_id``. Generic edits authorize the
        # caller against the item's current scope only, so a workspace editor
        # could otherwise publish an item into any workspace whose id they
        # know. Scope is set at creation (which checks destination
        # membership); moving between workspaces must go through an explicit,
        # destination-authorized path, not a field edit.
    }
)


class BacklogError(Exception):
    """Base class; the route layer maps subclasses onto HTTP statuses."""


class BacklogNotFoundError(BacklogError):
    """The item does not exist, or the caller may not know it does."""


class BacklogNotAuthorizedError(BacklogError):
    """The caller can see the item but may not change it."""


class VersionConflictError(BacklogError):
    """The caller's edit names a stale version; ``current`` is the live row."""

    def __init__(self, current: BacklogItem) -> None:
        super().__init__(f"version conflict: item is at version {current.version}")
        self.current = current


class BacklogValidationError(BacklogError):
    """The change itself is malformed (bad enum, unknown dependency, cycle)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _get(item_id: str) -> BacklogItem | None:
    return stores.backlog_items.get(item_id)


async def _resolve_role(actor: str, item: BacklogItem) -> str | None:
    """``"owner"``/``"editor"``/``"viewer"`` for visible items, else None.

    None means the actor has no relationship to the item; callers turn that
    into the same not-found answer a missing id gets.
    """
    if item.workspace_id:
        role = await workspace_authority.member_role(actor, item.workspace_id)
        return str(role) if role is not None else None
    return "owner" if item.owner_id == actor else None


async def _require_visible(actor: str, item: BacklogItem) -> str:
    role = await _resolve_role(actor, item)
    if role is None:
        raise BacklogNotFoundError("backlog item not found")
    return role


async def _require_editor(actor: str, item: BacklogItem) -> None:
    role = await _require_visible(actor, item)
    if role == "viewer":
        raise BacklogNotAuthorizedError("viewers can read a workspace's backlog but not edit it")


def _visible_to(actor: str, item: BacklogItem, role: str | None) -> bool:
    return role is not None


def _record(
    item: BacklogItem, actor: str, action: str, detail: dict[str, Any] | None = None
) -> None:
    item.provenance.append(
        ProvenanceEntry(actor=actor, action=action, at=_now(), detail=detail or {})
    )
    if len(item.provenance) > _PROVENANCE_CAP:
        del item.provenance[: len(item.provenance) - _PROVENANCE_CAP]


def _validate_dependencies(item: BacklogItem, dependencies: list[str]) -> None:
    if len(set(dependencies)) != len(dependencies):
        raise BacklogValidationError("dependencies must not repeat an item")
    if item.id in dependencies:
        raise BacklogValidationError("an item cannot depend on itself")
    for dep_id in dependencies:
        if _get(dep_id) is None:
            raise BacklogValidationError(f"unknown dependency: {dep_id}")
    # Cycle check: following dependency edges from the new set must never
    # come back to the item being edited.
    seen: set[str] = set()
    stack = list(dependencies)
    while stack:
        current = stack.pop()
        if current == item.id:
            raise BacklogValidationError("dependency cycle: an item cannot depend on its own chain")
        if current in seen:
            continue
        seen.add(current)
        other = _get(current)
        if other is not None:
            stack.extend(other.dependencies)


def _apply_field_changes(item: BacklogItem, changes: dict[str, Any]) -> list[str]:
    """Validate-and-assign the editable subset; returns applied field names.

    The model validates every assignment (``validate_assignment``), so an out-
    of-range priority or a bad enum is refused here rather than stored.
    """
    applied: list[str] = []
    try:
        for field, value in changes.items():
            if field not in _EDITABLE_FIELDS:
                raise BacklogValidationError(f"field is not editable: {field}")
            if field == "status" and value not in BACKLOG_STATUSES:
                raise BacklogValidationError(f"unknown status: {value}")
            if field == "autonomy_mode" and value not in AUTONOMY_MODES:
                raise BacklogValidationError(f"unknown autonomy mode: {value}")
            if field == "risk" and value not in RISK_LEVELS:
                raise BacklogValidationError(f"unknown risk level: {value}")
            if field == "dependencies":
                if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
                    raise BacklogValidationError("dependencies must be a list of item ids")
                _validate_dependencies(item, list(value))
            setattr(item, field, value)
            applied.append(field)
    except ValidationError as exc:
        raise BacklogValidationError(str(exc)) from exc
    return applied


async def list_items(
    actor: str,
    *,
    workspace_id: str | None = None,
    include_archived: bool = False,
) -> list[BacklogItem]:
    """Items the actor can see, board-ordered: priority, then rank, then age."""
    visible: list[tuple[tuple[int, float, datetime], BacklogItem]] = []
    for item in stores.backlog_items.values():
        role = await _resolve_role(actor, item)
        if not _visible_to(actor, item, role):
            continue
        if item.archived and not include_archived:
            continue
        if workspace_id is not None and item.workspace_id != workspace_id:
            continue
        visible.append(((item.priority, item.rank, item.created_at), item))
    visible.sort(key=lambda pair: pair[0])
    return [item for _, item in visible]


async def get_detail(actor: str, item_id: str) -> dict[str, Any]:
    """The item plus everything the detail view inspects, resolved by title."""
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_visible(actor, item)

    def summary(other: BacklogItem) -> dict[str, Any]:
        return {
            "id": other.id,
            "title": other.title,
            "status": other.status,
            "archived": other.archived,
        }

    async def visible_summaries(candidates):
        # Related items leak through the same visibility rule as the main
        # item: a private personal item or another workspace's item must
        # not expose even its id/title/status to this caller.
        return [
            summary(other)
            for other in candidates
            if other is not None and await _resolve_role(actor, other) is not None
        ]

    dependencies = await visible_summaries(_get(dep_id) for dep_id in item.dependencies)
    dependents = await visible_summaries(
        other for other in stores.backlog_items.values() if item.id in other.dependencies
    )
    children = await visible_summaries(
        other
        for other in stores.backlog_items.values()
        if other.parent_id == item.id and not other.archived
    )
    return {
        "item": item.model_dump(mode="json"),
        "dependencies": dependencies,
        "dependents": dependents,
        "children": children,
        "authority": ui_authority_snapshot(),
    }


async def create_item(
    actor: str,
    *,
    title: str,
    workspace_id: str | None = None,
    **fields: Any,
) -> BacklogItem:
    """Create an item owned by ``actor``.

    A workspace-scoped item requires the actor to be an editing member
    (viewer-role members cannot create work either).
    """
    if not actor:
        raise BacklogNotAuthorizedError("an authenticated actor is required")
    if workspace_id:
        role = await workspace_authority.member_role(actor, workspace_id)
        if role is None:
            raise BacklogNotFoundError("workspace not found")
        if role == "viewer":
            raise BacklogNotAuthorizedError(
                "viewers can read a workspace's backlog but not edit it"
            )

    unknown = set(fields) - _EDITABLE_FIELDS - {"rank"}
    if unknown:
        raise BacklogValidationError(f"unknown field(s): {', '.join(sorted(unknown))}")
    try:
        item = BacklogItem(
            id=str(uuid4()),
            title=title,
            owner_id=actor,
            workspace_id=workspace_id or None,
            created_at=_now(),
            updated_at=_now(),
            **fields,
        )
    except ValidationError as exc:
        raise BacklogValidationError(str(exc)) from exc
    if item.dependencies:
        _validate_dependencies(item, item.dependencies)
    _record(item, actor, "created", {"title": item.title})
    stores.backlog_items[item.id] = item
    return item


async def update_item(
    actor: str,
    item_id: str,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> BacklogItem:
    """Edit the editable fields, guarded by the caller's observed version."""
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_editor(actor, item)
    if expected_version != item.version:
        raise VersionConflictError(item)
    # Stage the whole edit on a copy: _get() hands back the object the store
    # itself holds, so in-place mutation would leak partial edits (and the
    # version/provenance bump) into reads whenever a later check refuses the
    # patch. The stored object is replaced only after every step validates.
    staged = item.model_copy(deep=True)
    applied = _apply_field_changes(staged, changes)
    if staged.archived and "archived" not in applied:
        raise BacklogValidationError("restore the item before editing it")
    if "status" in applied and staged.status == "blocked" and "blocked_reason" not in applied:
        # Leaving the blocked column through a plain edit clears the stale
        # park evidence; an explicit unblock sets its own record either way.
        staged.blocked_reason = None
    staged.version += 1
    staged.updated_at = _now()
    _record(staged, actor, "updated", {"fields": applied})
    stores.backlog_items[staged.id] = staged
    return staged


async def reorder_item(
    actor: str,
    item_id: str,
    *,
    expected_version: int,
    rank: float,
    status: str | None = None,
) -> BacklogItem:
    """A drag-and-drop move: new rank, optionally a new column."""
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_editor(actor, item)
    if expected_version != item.version:
        raise VersionConflictError(item)
    if status is not None:
        if status not in BACKLOG_STATUSES:
            raise BacklogValidationError(f"unknown status: {status}")
        item.status = status
        if status != "blocked":
            item.blocked_reason = None
    item.rank = float(rank)
    item.version += 1
    item.updated_at = _now()
    _record(item, actor, "reordered", {"rank": item.rank, "status": item.status})
    stores.backlog_items[item.id] = item
    return item


async def set_blocked(
    actor: str,
    item_id: str,
    *,
    expected_version: int,
    blocked: bool,
    reason: str | None = None,
) -> BacklogItem:
    """Block (park with evidence) or unblock, as one attributed record."""
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_editor(actor, item)
    if expected_version != item.version:
        raise VersionConflictError(item)
    if blocked:
        if not reason or not reason.strip():
            raise BacklogValidationError("blocking requires a reason — that is the evidence")
        item.status = "blocked"
        item.blocked_reason = reason.strip()
        action = "blocked"
    else:
        item.status = "todo"
        item.blocked_reason = None
        action = "unblocked"
    item.version += 1
    item.updated_at = _now()
    _record(item, actor, action)
    stores.backlog_items[item.id] = item
    return item


async def set_operator_flag(
    actor: str,
    item_id: str,
    *,
    expected_version: int,
    flag: str,
    value: bool,
    reason: str | None = None,
) -> BacklogItem:
    """Pin / pause / archive — the durable operator controls.

    Each is a single attributed record on the item; clearing it is recorded
    the same way (SPEC-092626-1831 operator controls).
    """
    if flag not in ("pinned", "paused", "archived"):
        raise BacklogValidationError(f"unknown operator flag: {flag}")
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_editor(actor, item)
    if expected_version != item.version:
        raise VersionConflictError(item)
    setattr(item, flag, value)
    if flag == "paused":
        item.paused_reason = reason.strip() if value and reason and reason.strip() else None
    if flag == "archived" and value:
        item.pinned = False
    item.version += 1
    item.updated_at = _now()
    _record(item, actor, f"{'set' if value else 'cleared'}_{flag}")
    stores.backlog_items[item.id] = item
    return item


async def decompose_item(
    actor: str,
    item_id: str,
    *,
    expected_version: int,
    children: list[dict[str, Any]],
) -> list[BacklogItem]:
    """Split an item into child items; the parent stays as the umbrella."""
    item = _get(item_id)
    if item is None:
        raise BacklogNotFoundError("backlog item not found")
    await _require_editor(actor, item)
    if expected_version != item.version:
        raise VersionConflictError(item)
    if not children:
        raise BacklogValidationError("decomposition needs at least one child")

    created: list[BacklogItem] = []
    for spec in children:
        title = str(spec.get("title") or "").strip()
        if not title:
            raise BacklogValidationError("every child needs a title")
        child = BacklogItem(
            id=str(uuid4()),
            title=title,
            description=str(spec.get("description") or ""),
            owner_id=item.owner_id,
            workspace_id=item.workspace_id,
            parent_id=item.id,
            priority=item.priority,
            autonomy_mode=item.autonomy_mode,
            source=item.source,
            created_at=_now(),
            updated_at=_now(),
        )
        created.append(child)

    for child in created:
        _record(child, actor, "created", {"title": child.title, "parent": item.id})
        stores.backlog_items[child.id] = child
    item.version += 1
    item.updated_at = _now()
    _record(item, actor, "decomposed", {"children": [c.id for c in created]})
    stores.backlog_items[item.id] = item
    return created
