"""Workspace-scoped Home layout: durable, revision-checked, authority-split (#1048).

Workspace Home (#1048) is a composition of miniature projections over canonical
resources. It owns no domain object: a region carries a *reference* —
``(resource_type, resource_id)`` — to a Goal, backlog item, run, chat session
or design surface that its canonical service already owns. Pinning changes
presentation only; saving a layout never copies or forks the referenced
resource, and two regions (or two surfaces) may reference the same resource.

This module holds the durable half of that contract, keyed by the canonical
Workspace ID — not the principal, which is what `services/dashboard_layouts.py`
keys the per-principal dashboard on. The properties it exists to hold are the
ones its dashboard sibling holds, plus one that is Home-specific:

- **A write that did not land is not a success.** Every save is written, read
  back from the durable row (not the cache dict), and refused with
  `LayoutPersistenceError` when what came back is not what went in. The same
  writer-settle discipline as the dashboard: `PersistedStore` queues the
  transaction, so a full disk fails on the writer thread after the request
  would otherwise have answered 200.
- **A save is against a revision.** A stale `expected_revision` is refused
  with `LayoutConflictError` so two concurrent editors cannot silently
  overwrite each other — the same contract `PUT /v1/dashboard/layout` already
  gives the SPA. Both error types are the dashboard module's own classes
  on purpose: one revision contract, one persistence contract, one vocabulary
  for both surfaces.
- **The Agent composes only the unpinned space.** `compose_adaptive` is the
  one write path for the Workspace Agent's adaptive decisions, and it refuses
  — with `PinnedRegionWriteError` — any payload that adds a pinned region,
  unpins one, moves one, or drops one. A user who pins 100% of Home has left
  the Agent nothing to compose, and the service enforces that rather than
  trusting every caller to re-derive it.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.dashboard_layouts import (
    LayoutConflictError,
    LayoutPersistenceError,
    _backend,
    _settle,
)

logger = logging.getLogger("hive.home")

SCHEMA_VERSION = 1

#: The `stores.py` key this service reads and writes. Named for the same
#: reason `dashboard_layouts.STORE_NAME` is: the durable read-back addresses
#: the backend directly, below the store.
STORE_NAME = "home_layouts"

#: Where a region may point. Each kind names the canonical service that owns
#: the referenced resource; `note` is the one region with no resource behind
#: it — a text region the user or the Agent wrote, stored here because it has
#: no other owner and must never masquerade as a Goal/chat/artifact identity.
RegionKind = Literal[
    "goals",
    "backlog",
    "runs",
    "chat",
    "sessions",
    "design",
    "attention",
    "note",
]

REGION_KINDS: tuple[str, ...] = (
    "goals",
    "backlog",
    "runs",
    "chat",
    "sessions",
    "design",
    "attention",
    "note",
)

#: Canonical resource types a region may reference. The type names the
#: authority that owns the identity; Home never mints any of them.
RESOURCE_TYPES: frozenset[str] = frozenset(
    {"goal", "backlog_item", "run", "chat_session", "design_surface", "attention_item", "none"}
)

#: Presentation instances are cheap and bounded. A layout that needs more
#: regions than this is not a layout, it is a data set; refuse rather than
#: store an unbounded array under one workspace key.
MAX_REGIONS = 48

_REGION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_RESOURCE_ID = re.compile(r"^.{1,256}$", re.DOTALL)


class LayoutError(Exception):
    """Base for every way a Home layout operation refuses."""


class PinnedRegionWriteError(LayoutError):
    """The Agent tried to compose space the user pinned.

    Raised for every way a compose payload touches pinned space: adding a
    pinned region, rewriting an existing one, or omitting none — the pinned
    set must survive the compose exactly as it is. The user's pinned layout is
    not the Agent's to edit; the route and the chat tool both go through
    `compose_adaptive`, so this holds no matter which door the Agent takes.
    """


class HomeRegion(BaseModel):
    """One miniature surface slot. A presentation instance, never a domain row.

    `resource_type`/`resource_id` are a foreign reference into the canonical
    service that owns the identity. They are validated as shapes, never
    resolved here: resolving them is the projection read
    (`services.home_projections`), and this module must stay able to store a
    reference to a resource that exists only after the next Goal/Run lands.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: RegionKind
    pinned: bool = False
    resource_type: str = "none"
    resource_id: str | None = None
    position: int = 0
    size: str = "1"
    #: Why this region is here. The Agent fills it when it composes adaptive
    #: space ("this lens fills the focal-range gap you planned"); a pinned
    #: region's reason is the user's, and is never rewritten by a compose.
    reason: str | None = None

    @field_validator("id")
    @classmethod
    def _shape_id(cls, value: str) -> str:
        if not _REGION_ID.fullmatch(value):
            raise ValueError(f"region id {value!r} is not a presentation-instance id")
        return value

    @field_validator("resource_type")
    @classmethod
    def _shape_resource_type(cls, value: str) -> str:
        if value not in RESOURCE_TYPES:
            raise ValueError(f"resource_type {value!r} is not a canonical reference type")
        return value

    @field_validator("resource_id")
    @classmethod
    def _shape_resource_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _RESOURCE_ID.fullmatch(value):
            raise ValueError("resource_id must be 1-256 characters")
        return value

    @field_validator("reason")
    @classmethod
    def _shape_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value[:512] if value else None


class HomeLayout(BaseModel):
    """The composed document a client renders. Ordered by `position`."""

    model_config = ConfigDict(extra="forbid")

    regions: list[HomeRegion] = Field(default_factory=list)

    @field_validator("regions")
    @classmethod
    def _bounded_unique(cls, regions: list[HomeRegion]) -> list[HomeRegion]:
        if len(regions) > MAX_REGIONS:
            raise ValueError(f"a Home layout holds at most {MAX_REGIONS} regions")
        seen: set[str] = set()
        for region in regions:
            # One UI component instance has one identity/location: a second
            # region with the same id is not "the same widget twice", it is a
            # malformed layout. Referencing the same *resource* from two
            # regions is fine and expected — that is a projection, not a copy.
            if region.id in seen:
                raise ValueError(f"duplicate region id {region.id!r}")
            seen.add(region.id)
        return sorted(regions, key=lambda r: (r.position, r.id))


class HomeLayoutRecord(BaseModel):
    """What is stored for one Workspace. Same envelope as the dashboard's."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    revision: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    layout: HomeLayout = Field(default_factory=HomeLayout)


#: Serializes read-modify-write, exactly like the dashboard's lock: the
#: revision check and the write have to be one critical section or two
#: concurrent saves both pass against revision N and the later one wins
#: without either being told. Reentrant because `set_region_pinned` is
#: specified as one pin applied through the same save path, not a second
#: write implementation.
_save_lock = threading.RLock()


def _store() -> Any:
    import stores

    return stores.home_layouts


def _empty() -> HomeLayoutRecord:
    return HomeLayoutRecord(layout=HomeLayout())


def default_layout() -> HomeLayout:
    """The composition a Workspace that never saved starts from.

    Nothing is pinned: the user has expressed no pinning preference, so the
    Agent may compose any of it (pin 0%). Regions reference kinds, not
    resources — the projection read resolves what each kind shows now. This is
    offered by `GET` without being stored, like the dashboard's preset: it
    becomes durable when the user or the Agent first saves.
    """
    kinds: list[RegionKind] = [
        "goals",
        "backlog",
        "runs",
        "chat",
        "sessions",
        "design",
        "attention",
    ]
    return HomeLayout(
        regions=[
            HomeRegion(id=f"default-{kind}", kind=kind, pinned=False, position=i)
            for i, kind in enumerate(kinds)
        ]
    )


def load(workspace_id: str) -> HomeLayoutRecord:
    """This Workspace's stored record, or an empty one if it never saved."""
    raw = _store().get(workspace_id)
    if not isinstance(raw, dict):
        return _empty()
    try:
        return HomeLayoutRecord.model_validate(raw)
    except Exception:
        # A layout is a preference: a record a future build wrote (or a past
        # build corrupted) degrades to "not saved yet" rather than bricking
        # Home. The next save replaces it wholesale.
        logger.warning("home layout for workspace %r was unreadable; serving empty", workspace_id)
        return _empty()


def effective(workspace_id: str) -> HomeLayoutRecord:
    """What Home actually renders: the stored record, else the default."""
    record = load(workspace_id)
    if record.revision:
        return record
    return record.model_copy(update={"layout": default_layout()})


def _validate_resource_pairs(regions: list[HomeRegion]) -> None:
    for region in regions:
        if region.kind == "note":
            if region.resource_type != "none" or region.resource_id is not None:
                raise LayoutError("a note region references no canonical resource")
            continue
        if region.resource_type == "none" or region.resource_id is None:
            # A live region may leave the reference unset — the projection
            # read resolves the kind to whatever the canonical service holds
            # now — but it must not name a type it does not reference.
            if region.resource_type != "none" and region.resource_id is None:
                raise LayoutError(
                    f"region {region.id!r} references resource_type "
                    f"{region.resource_type!r} without a resource_id"
                )
            continue


def _write(workspace_id: str, record: HomeLayoutRecord) -> None:
    """One upsert. Any refusal becomes a persistence failure, not a 500."""
    try:
        _store()[workspace_id] = record.model_dump(mode="json")
    except Exception as exc:
        raise LayoutPersistenceError(
            f"the home layout store refused the write for workspace {workspace_id!r}: {exc}"
        ) from exc


def _read_back(workspace_id: str, written: HomeLayoutRecord) -> HomeLayoutRecord:
    """Confirm the write against the durable row, not the cache in front of it.

    Same failure, same cure as the dashboard (`services/dashboard_layouts.py`):
    the store updates its dict before the backend is touched, and the SQLite
    backend queues the transaction — so only settling the writer and reading
    the row can tell a landed write from an acknowledged one. No backend
    configured means the dict is all there is: a deployment that chose
    in-memory state, whose durability refusal lives elsewhere (#333).
    """
    store = _store()
    backend = _backend(store)
    if backend is None:
        confirmed = load(workspace_id)
    else:
        _settle(backend)
        confirmed = _from_document(backend.get_raw(STORE_NAME, workspace_id), workspace_id)
    if confirmed.revision != written.revision:
        raise LayoutPersistenceError(
            f"the home layout for workspace {workspace_id!r} read back at revision "
            f"{confirmed.revision}, not the {written.revision} just written"
        )
    return confirmed


def _from_document(document: str | None, workspace_id: str) -> HomeLayoutRecord:
    if not document:
        return _empty()
    try:
        return HomeLayoutRecord.model_validate(json.loads(document))
    except Exception:
        logger.warning("home layout document for workspace %r was unreadable", workspace_id)
        return _empty()


def save_layout(
    workspace_id: str,
    layout: HomeLayout,
    *,
    expected_revision: int | None = None,
) -> HomeLayoutRecord:
    """Store the user's full layout, or raise. Returns what was read back.

    This is the *user* authority: pin 0%, some, or 100% of Home; move, resize,
    add, remove. Nothing here restricts pinning, because a user save is the
    one place pinning is allowed to change.

    `expected_revision` absent means last-write-wins, exactly the dashboard's
    contract, so both surfaces behave the same way under two editors.
    """
    _validate_resource_pairs(layout.regions)
    with _save_lock:
        stored = load(workspace_id)
        if expected_revision is not None and expected_revision != stored.revision:
            raise LayoutConflictError(expected_revision, stored)
        written = HomeLayoutRecord(
            schema_version=SCHEMA_VERSION,
            revision=stored.revision + 1,
            updated_at=datetime.now(UTC),
            layout=layout,
        )
        _write(workspace_id, written)
        return _read_back(workspace_id, written)


def set_region_pinned(
    workspace_id: str,
    region_id: str,
    *,
    pinned: bool,
    expected_revision: int | None = None,
) -> HomeLayoutRecord:
    """Pin or unpin one region — the smallest user-authority operation.

    One operation, one door: the route, the Agent tool and any future client
    all land here, so "pinning is a presentation change, not a fork" is
    enforced (and tested) once. The region must already exist in the stored
    or default layout: pinning is not creation.
    """
    with _save_lock:
        stored = load(workspace_id)
        if stored.revision == 0:
            # Pinning into a Workspace that never saved persists the default
            # composition with the one pin applied — the layout the user is
            # looking at, not an empty one that would silently drop the rest.
            stored = stored.model_copy(update={"layout": default_layout()})
        if expected_revision is not None and expected_revision != stored.revision:
            raise LayoutConflictError(expected_revision, stored)
        regions = [r.model_copy() for r in stored.layout.regions]
        target = next((r for r in regions if r.id == region_id), None)
        if target is None:
            raise LayoutError(f"no region {region_id!r} in the layout")
        target.pinned = pinned
        return save_layout(
            workspace_id,
            HomeLayout(regions=regions),
            expected_revision=stored.revision,
        )


def compose_adaptive(
    workspace_id: str,
    adaptive_regions: list[HomeRegion],
    *,
    expected_revision: int | None = None,
) -> HomeLayoutRecord:
    """Write the Agent's composition of the unpinned space. Pinned space is refused.

    This is the *Agent* authority, and its whole boundary in one function: the
    payload may only contain unpinned regions, and the stored pinned regions
    must survive the compose exactly as they are — same id, kind, pin state,
    resource reference, position, size and reason. Anything else raises
    `PinnedRegionWriteError` and changes nothing. A user who pinned 100% of
    Home therefore cannot have their layout rewritten by the Agent no matter
    what the Agent's model decided, and the Agent never needs browser/UI
    automation to fill its share: this function is the whole mechanism.

    Unpinned regions absent from the payload are dropped: the Agent owns the
    unpinned space's *composition*, including what it removes. The unpinned
    space itself is whatever the user left unpinned — a layout with no
    unpinned region (pin 100%, or an explicitly emptied Home) leaves the Agent
    nothing to compose, and a non-empty payload for one is refused rather
    than grown into the user's fixed layout.
    """
    for region in adaptive_regions:
        if region.pinned:
            raise PinnedRegionWriteError(
                f"region {region.id!r} is pinned: the Agent composes only unpinned space"
            )
    _validate_resource_pairs(adaptive_regions)
    with _save_lock:
        stored = load(workspace_id)
        if expected_revision is not None and expected_revision != stored.revision:
            raise LayoutConflictError(expected_revision, stored)
        # What the user is actually looking at: a never-saved Workspace shows
        # the default composition, so that is the space being composed.
        visible = stored.layout if stored.revision else default_layout()
        if not any(not r.pinned for r in visible.regions) and adaptive_regions:
            raise PinnedRegionWriteError(
                "the user left no unpinned space: every region of Home is pinned "
                "or explicitly empty, so there is nothing for the Agent to compose"
            )
        pinned = [r for r in visible.regions if r.pinned]
        pinned_ids = {r.id for r in pinned}
        overlap = pinned_ids & {r.id for r in adaptive_regions}
        if overlap:
            raise PinnedRegionWriteError(
                f"the compose payload rewrites pinned region(s) {sorted(overlap)}"
            )
        layout = HomeLayout(regions=[*pinned, *adaptive_regions])
        written = HomeLayoutRecord(
            schema_version=SCHEMA_VERSION,
            revision=stored.revision + 1,
            updated_at=datetime.now(UTC),
            layout=layout,
        )
        _write(workspace_id, written)
        return _read_back(workspace_id, written)
