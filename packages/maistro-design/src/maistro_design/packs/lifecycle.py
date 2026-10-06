"""Workspace-scoped pack lifecycle contract (M9-F3, #968).

The pack registry (`registry.py`) is global package identity: the manifests
every Workspace shares, immutable while the process runs. This module is the
Workspace-side half of the pack story — *activation*. One activation record
per ``(workspace_id, pack_id)`` answers, for that Workspace alone:

- **is the pack usable here?** (`ENABLED` / `DISABLED` / `REMOVED`; a pack
  with no record is merely `AVAILABLE` — never stored, so an unactivated
  Workspace is not a row of state);
- **which release did this Workspace activate?** The record snapshots the
  exact pack contract (canonical JSON + SHA-256) at activation time; new use
  materializes from the *snapshot*, never silently from whatever the registry
  now ships, so a registry upgrade cannot rewrite what a Workspace runs
  (the explicit `upgrade` moves the snapshot, audited, or nothing does);
- **what has this Workspace overridden?** (`WorkspacePackConfiguration` — a
  narrowing of pack-declared defaults, validated against the activated
  snapshot, stored on the record and nowhere near the global registry).

Invariants inherited from the #793 pack contract and the M9-B2 extension
machine (#953) whose shape this follows:

- **No second identity scheme.** An activation is not a Goal, Run, NodeRun,
  Attempt, Project, or Workspace; it mints none of them. Disabling or
  removing a pack blocks *new* use only — historical canonical objects stay
  exactly what they were (append-only Run stores, Goal-owned Rubric catalog
  value objects, materialized Graph templates).
- **Fail-closed authority.** `execute_backends` are the capability surface a
  pack depends on, and every pack declares at least one. Activation and
  upgrade re-evaluate the Workspace's authorized-backend set each time and
  refuse to widen it silently; an upgrade that needs a backend the Workspace
  has not authorized is blocked and names the missing authority.
- **Audited, atomic transitions.** Every state/version/configuration change
  appends one `PackTransition` and persists it *with* the record through the
  store's single `commit` seam — the durability seam. The in-memory store is
  the reference implementation; a durable backend (SQLite/Postgres) arrives
  behind the same protocol without touching the machine, exactly as the
  extension activation store did in M9-B2.
- **Terminal history.** A store issues no delete: `REMOVED` tombstones the
  record (retaining its manifest snapshot) rather than erasing it, so the
  audit trail survives the pack it describes.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro_design.packs.types import DomainPack, ExecuteBackend, PackId

__all__ = [
    "InMemoryPackLifecycleStore",
    "InvalidLifecycleOperation",
    "PackActivationRecord",
    "PackConcurrentWriteConflict",
    "PackConfigurationInvalid",
    "PackIdentityConflict",
    "PackLifecycleError",
    "PackLifecycleState",
    "PackManifestSnapshot",
    "PackNotEnabled",
    "PackRegistryUpgradeUnavailable",
    "PackTransition",
    "PackTransitionKind",
    "PackUpgradeBlocked",
    "PackUpgradePreflight",
    "SnapshotIntegrityError",
    "WorkspacePackConfiguration",
    "pack_from_snapshot",
    "parse_pack_version",
    "require_non_blank",
    "snapshot_pack",
]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class PackLifecycleError(RuntimeError):
    """Base class for Workspace pack lifecycle failures surfaced to callers."""


class PackNotEnabled(PackLifecycleError):
    """New use was attempted while the pack is not ENABLED in this Workspace.

    One error for never-activated, disabled and removed — the record's state
    is in the message, and `record()` returns the truth for callers that need
    to distinguish.
    """


class InvalidLifecycleOperation(PackLifecycleError):
    """A lifecycle operation was attempted from a state that forbids it."""


class PackRegistryUpgradeUnavailable(PackLifecycleError):
    """An upgrade has nothing to move to: no record, no newer release, or the
    activated pack was already upgraded."""


class PackUpgradeBlocked(PackLifecycleError):
    """Upgrade preflight failed; the reasons name what must change first."""


class PackConfigurationInvalid(PackLifecycleError):
    """A Workspace override references defaults the activated pack does not
    declare. Configuration may only narrow what the pack ships."""


class PackIdentityConflict(PackLifecycleError):
    """The registry's pack changed content under an unchanged version.

    A pack version is global package identity: the same ``(pack_id, version)``
    must always carry the same contract bytes. Detecting the opposite here is
    the guard that keeps a Workspace's stored snapshot meaningful.
    """


class SnapshotIntegrityError(PackLifecycleError):
    """A stored manifest snapshot no longer digests to its recorded SHA-256.

    The snapshot is the evidence of what a Workspace activated; a mismatching
    digest means the evidence was tampered with, and new use refuses to
    materialize from it.
    """


class PackConcurrentWriteConflict(PackLifecycleError):
    """A lifecycle write raced another and lost the compare-and-set.

    `commit` persists only if the stored record is still the one the
    operation read (`expected`). A mismatch means a concurrent operation
    moved the state between the read and the write — the loser raises here
    and re-reads; nothing stale is ever persisted (so, e.g., a slow disable
    cannot overwrite a concurrent `REMOVED` tombstone).
    """


def require_non_blank(value: str, what: str) -> str:
    """Validate an attributed string (actor, reason, workspace id)."""
    if not isinstance(value, str) or not value.strip():
        raise PackLifecycleError(f"{what} is required")
    return value


# --------------------------------------------------------------------------
# Snapshots: the exact pack contract a Workspace activated
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PackManifestSnapshot:
    """The exact pack contract an activation was made from.

    `body` is the pack's canonical JSON serialization (sorted keys, excluded
    none) and `sha256` digests those bytes at snapshot time. Materialization
    re-validates the digest before the bytes are parsed, so what a Workspace
    runs can never drift from what it activated — the pack-side twin of the
    extension machine's `ManifestSnapshot`.
    """

    body: str
    sha256: str


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_pack(pack: DomainPack) -> PackManifestSnapshot:
    """Snapshot a pack contract into its canonical, digest-anchored form."""
    body = pack.model_dump_json()
    return PackManifestSnapshot(body=body, sha256=_sha256_hex(body.encode()))


def pack_from_snapshot(snapshot: PackManifestSnapshot, pack_id: PackId) -> DomainPack:
    """Rebuild the pack from its snapshot, refusing tampered evidence.

    The digest is checked against the *recorded* value before the body is
    parsed: a snapshot that fails integrity never becomes a pack object.
    """
    if _sha256_hex(snapshot.body.encode()) != snapshot.sha256:
        raise SnapshotIntegrityError(
            f"pack {pack_id.value!r} snapshot digest mismatch: stored evidence "
            "does not digest to its recorded sha256"
        )
    return DomainPack.model_validate_json(snapshot.body)


# --------------------------------------------------------------------------
# Lifecycle vocabulary
# --------------------------------------------------------------------------


class PackLifecycleState(StrEnum):
    """Durable states of one Workspace's activation of one pack.

    A pack absent from a Workspace is `AVAILABLE` — registry-visible but
    unactivated — and has no stored row. `ENABLED` permits new use;
    `DISABLED` pauses it (configuration and snapshot retained for re-enable);
    `REMOVED` tombstones the activation after owned-asset cleanup, keeping
    the record and its trail for historical interpretation.
    """

    AVAILABLE = "available"
    ENABLED = "enabled"
    DISABLED = "disabled"
    REMOVED = "removed"


class PackTransitionKind(StrEnum):
    """Which governed operation produced a transition."""

    ENABLE = "enable"
    DISABLE = "disable"
    REMOVE = "remove"
    UPGRADE = "upgrade"
    CONFIGURE = "configure"


class WorkspacePackConfiguration(BaseModel):
    """One Workspace's overrides over a pack's declared defaults.

    Deliberately narrow: `rubric_dimension_ids` selects a subset of the
    pack's declared Rubric dimensions (validated against the activated
    snapshot — an override can only narrow what the pack ships, never
    invent), and `settings` carries JSON-safe pack-defined knobs. `None`
    means "use the pack defaults unchanged".

    The configuration lives on the Workspace's activation record. The global
    registry is never consulted for it and never mutated by it — Workspace
    configuration cannot change what any other Workspace (or the registry)
    sees.

    `frozen=True` is shallow, so the mutable `settings` dict is guarded at
    the store seam instead: the reference store deep-copies records on both
    write and read, so the only way stored `settings` change is a `CONFIGURE`
    transition (a durable backend serializes to JSON, which severs aliasing
    structurally).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_dimension_ids: tuple[str, ...] | None = None
    settings: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_duplicate_dimension_ids(self) -> WorkspacePackConfiguration:
        if self.rubric_dimension_ids is None:
            return self
        if not self.rubric_dimension_ids:
            raise ValueError(
                "rubric_dimension_ids must select at least one dimension; "
                "use None to keep the pack defaults"
            )
        if len(set(self.rubric_dimension_ids)) != len(self.rubric_dimension_ids):
            raise ValueError("rubric_dimension_ids must not repeat a dimension")
        return self


@dataclass(frozen=True)
class PackActivationRecord:
    """One Workspace's durable activation of one pack — and its overrides."""

    workspace_id: str
    pack_id: PackId
    state: PackLifecycleState
    #: The pack release this Workspace activated. New use materializes from
    #: `manifest`, which is this version's snapshot — never the registry's
    #: current release (that move is an explicit, audited `upgrade`).
    version: str
    manifest: PackManifestSnapshot
    configuration: WorkspacePackConfiguration
    enabled_by: str
    activated_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PackTransition:
    """One audited lifecycle transition (canonical evidence, #968)."""

    seq: int
    at: datetime
    kind: PackTransitionKind
    workspace_id: str
    pack_id: PackId
    actor: str
    from_state: PackLifecycleState
    to_state: PackLifecycleState
    from_version: str
    to_version: str
    reason: str


# --------------------------------------------------------------------------
# Upgrade preflight
# --------------------------------------------------------------------------

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_pack_version(version: str) -> tuple[int, int, int]:
    """Parse a pack release version into its comparable triple."""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise PackLifecycleError(f"malformed pack version: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


@dataclass(frozen=True)
class PackUpgradePreflight:
    """The answer to "may this Workspace move to the registry's release?".

    `blocked_by` carries one human-readable reason per failed check; an empty
    tuple means the upgrade may proceed. The deltas are the operator-facing
    diff between the activated release and the target: backends the target
    newly requires (authority the Workspace must hold) and configured Rubric
    dimension ids the target no longer declares (configuration that would not
    survive the move).
    """

    workspace_id: str
    pack_id: PackId
    current_version: str = ""
    target_version: str = ""
    can_upgrade: bool = False
    blocked_by: tuple[str, ...] = ()
    new_backends: tuple[ExecuteBackend, ...] = ()
    unauthorized_backends: tuple[ExecuteBackend, ...] = ()
    dropped_rubric_dimensions: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Store: the durability seam
# --------------------------------------------------------------------------


@runtime_checkable
class PackLifecycleStore(Protocol):
    """Persistence seam for activation records and their audit trail.

    One record per ``(workspace_id, pack_id)``; one append-only transition
    trail. `commit` is the single write seam — record and transition persist
    together or not at all, which is what makes a lifecycle transition
    restart-safe: a crash between compute and commit leaves the previous
    state, a crash after it leaves the new state plus its evidence.

    `commit` is also the concurrency seam. Async reads and writes suspend,
    so between an operation's `get_record` and its `commit` another
    operation may move the record (e.g. removal tombstones while a stale
    disable is in flight). `expected` closes that window with a
    compare-and-set: the caller passes exactly the record it read (or
    `None` when it read no record), and the store persists only if the
    stored row still matches — otherwise it raises
    `PackConcurrentWriteConflict` and nothing is written. A durable backend
    implements this with a state/revision-conditional update under its
    transaction; the check and the write must be one atomic step.
    """

    async def commit(
        self,
        record: PackActivationRecord,
        transition: PackTransition,
        *,
        expected: PackActivationRecord | None,
    ) -> None:
        """Persist `record` and append `transition` atomically, iff the
        stored record still equals `expected` (`None` = still absent)."""
        ...

    async def get_record(
        self, workspace_id: str, pack_id: PackId
    ) -> PackActivationRecord | None: ...

    async def records_for_workspace(self, workspace_id: str) -> list[PackActivationRecord]: ...

    async def transitions_for(
        self, workspace_id: str, pack_id: PackId
    ) -> tuple[PackTransition, ...]:
        """The pack's full transition trail for this Workspace, oldest first."""
        ...

    async def next_seq(self) -> int: ...


class InMemoryPackLifecycleStore:
    """Reference implementation. Process-lifetime, like the extension
    activation store's in-memory twin; the protocol is the durability
    contract a durable backend implements without touching the service."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, PackId], PackActivationRecord] = {}
        self._transitions: list[PackTransition] = []
        self._seq = 0

    async def commit(
        self,
        record: PackActivationRecord,
        transition: PackTransition,
        *,
        expected: PackActivationRecord | None,
    ) -> None:
        key = (record.workspace_id, record.pack_id)
        current = self._records.get(key)
        if current != expected:
            raise PackConcurrentWriteConflict(
                f"concurrent write on pack {record.pack_id.value!r} in workspace "
                f"{record.workspace_id!r}: expected "
                f"{expected.state.value if expected is not None else 'no record'}, "
                f"found {current.state.value if current is not None else 'no record'}"
            )
        # Compare-and-set then write with no await between: atomic in the
        # event loop, mirroring the single-statement conditional update a
        # durable backend must issue. The write stores a deep copy so a
        # caller's record (and the mutable `settings` dict inside its
        # configuration) cannot alias the stored activation.
        self._records[key] = deepcopy(record)
        self._transitions.append(transition)

    async def get_record(self, workspace_id: str, pack_id: PackId) -> PackActivationRecord | None:
        record = self._records.get((workspace_id, pack_id))
        return None if record is None else deepcopy(record)

    async def records_for_workspace(self, workspace_id: str) -> list[PackActivationRecord]:
        return [
            deepcopy(self._records[key])
            for key in sorted(self._records, key=lambda key: (key[1], key[0]))
            if key[0] == workspace_id
        ]

    async def transitions_for(
        self, workspace_id: str, pack_id: PackId
    ) -> tuple[PackTransition, ...]:
        return tuple(
            transition
            for transition in self._transitions
            if transition.workspace_id == workspace_id and transition.pack_id is pack_id
        )

    async def next_seq(self) -> int:
        self._seq += 1
        return self._seq
