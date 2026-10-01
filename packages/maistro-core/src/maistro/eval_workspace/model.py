"""Persistent evaluation-workspace records (#107).

This module is *bookkeeping*, deliberately: it records what an evaluation
environment is (its digest), what state it is in (its lifecycle), who owns it
right now (one Attempt at a time), and where it came from (its lineage and the
execution that produced every snapshot). It does **not** spawn, pause, or
kill anything -- the only execution substrate is `maistro.sandbox` behind
`SandboxProtocol`, and the only execution lifecycle is
`Goal -> Graph -> Run -> NodeRun -> Attempt`. A workspace record rides along
that existing lifecycle instead of introducing a competing one.

Ownership follows the repo rule in ADR-083026-e602: a record names the
execution that produced it. Every workspace and snapshot carries a nullable
`run_id` / `node_run_id` / `attempt_id` triple -- nullable, because blank
means "no execution was in scope", which is a different fact from claiming a
Run with an empty id. While an evaluation is using a workspace, the workspace
is *held* by exactly one Attempt; a second Attempt cannot take it, and a
release by anyone else is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _new_id() -> str:
    return uuid4().hex


def _require_non_empty(value: str | None, field_name: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided")


class EvalWorkspaceStatus(StrEnum):
    """Lifecycle of a persistent workspace record.

    PROVISIONING: registered, its backing sandbox may still be coming up.
    AVAILABLE:    usable; eligible for the warm pool and for claims.
    IN_USE:  bound to one Attempt (the owner).
    PARKED:   parked, state preserved; resume returns it to AVAILABLE.
    RETIRED: terminal; the record is kept for provenance, never reused.
    """

    PROVISIONING = "provisioning"
    AVAILABLE = "available"
    IN_USE = "in_use"
    PARKED = "parked"
    RETIRED = "retired"


TERMINAL_WORKSPACE_STATUSES: frozenset[EvalWorkspaceStatus] = frozenset(
    {EvalWorkspaceStatus.RETIRED}
)


class FixtureEntry(BaseModel):
    """One deterministic fixture: a name and the digest of its content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)


class FixtureManifest(BaseModel):
    """The deterministic fixture set an environment is seeded with.

    Frozen and digest-addressed: the manifest digest folds into the
    environment digest, so changing one fixture's content changes the
    environment's identity. That is the point -- an eval comparison across
    different fixtures is not a matched comparison, and the digest refuses to
    pretend otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[FixtureEntry, ...] = ()

    def validate_unique_names(self) -> FixtureManifest:
        names = [entry.name for entry in self.entries]
        if len(names) != len(set(names)):
            raise ValueError("fixture manifest entries must have unique names")
        return self

    @property
    def digest(self) -> str:
        """Deterministic digest over the sorted (name, content) pairs."""
        from maistro.eval_workspace.digest import canonical_json, sha256_hex

        payload = canonical_json(sorted((e.name, e.content_sha256) for e in self.entries))
        return sha256_hex(payload)


EMPTY_FIXTURES = FixtureManifest()


class EvalWorkspace(BaseModel):
    """A persistent, forkable evaluation environment record.

    The backing environment is whatever the caller runs behind
    `SandboxProtocol` -- this record is its durable identity, ownership, and
    lineage. `environment_digest` is computed by the substrate at provision
    time and never edited afterwards: an environment that could quietly change
    identity would make every matched comparison built on it meaningless.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_env_id: str = Field(default_factory=_new_id)
    workspace_id: str
    project_id: str
    environment_digest: str = Field(min_length=64, max_length=64)
    status: EvalWorkspaceStatus = EvalWorkspaceStatus.PROVISIONING

    #: The execution that produced this workspace (ADR-083026-e602).
    #: None means no execution was in scope, not an empty id.
    produced_run_id: str | None = None
    produced_node_run_id: str | None = None
    produced_attempt_id: str | None = None

    #: The Attempt currently using this workspace. Set iff status is IN_USE.
    owner_attempt_id: str | None = None

    #: Lineage. A forked workspace names its parent and the snapshot whose
    #: state it started from; a provisioned workspace has neither.
    parent_workspace_env_id: str | None = None
    forked_from_snapshot_id: str | None = None

    #: Digest of the recorded start/restored state, when one exists. Two
    #: workspaces with equal `environment_digest` AND equal non-None
    #: `start_state_digest` are an identical-start-state matched pair.
    start_state_digest: str | None = Field(default=None, min_length=64, max_length=64)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_workspace(self) -> EvalWorkspace:
        for name in (
            "workspace_id",
            "project_id",
        ):
            value = getattr(self, name)
            if not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in (
            "produced_run_id",
            "produced_node_run_id",
            "produced_attempt_id",
            "parent_workspace_env_id",
            "forked_from_snapshot_id",
        ):
            _require_non_empty(getattr(self, name), name)

        self.validate_invariants()
        return self

    def validate_invariants(self) -> None:
        """The paired-field invariants, enforced wherever the record is written.

        These hold only when status and its companion field move together, so
        they cannot be per-assignment rules -- they are checked at the write
        door (`EvalWorkspaceStore.save_workspace` re-runs the model
        validator), the same place the canonical run store checks its fence.
        """
        held = self.status is EvalWorkspaceStatus.IN_USE
        if held != bool(self.owner_attempt_id):
            raise ValueError(
                "owner_attempt_id must be set exactly when status is IN_USE "
                f"(status={self.status.value}, owner={self.owner_attempt_id!r})"
            )
        retired = self.status is EvalWorkspaceStatus.RETIRED
        if retired != (self.archived_at is not None):
            raise ValueError(
                "archived_at must be set exactly when status is RETIRED "
                f"(status={self.status.value}, archived_at={self.archived_at!r})"
            )
        if self.parent_workspace_env_id is not None and self.forked_from_snapshot_id is None:
            raise ValueError("a forked workspace must name the snapshot it forked from")


class WorkspaceSnapshot(BaseModel):
    """An immutable, digest-addressed capture of a workspace's state.

    Captured state content lives wherever the caller stored it; what persists
    here is its digest, its environment, and the execution that produced it.
    A snapshot is only ever created against one environment (its
    `environment_digest`), and restoring it into a workspace of a different
    environment is refused -- that is what keeps `start_state_digest`
    comparable across workspaces.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(default_factory=_new_id)
    workspace_env_id: str
    environment_digest: str = Field(min_length=64, max_length=64)
    #: Digest of the captured state content itself (sha256 of the bytes).
    content_digest: str = Field(min_length=64, max_length=64)

    produced_run_id: str | None = None
    produced_node_run_id: str | None = None
    produced_attempt_id: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_snapshot(self) -> WorkspaceSnapshot:
        for name in ("workspace_env_id",):
            _require_non_empty(getattr(self, name), name)
        for name in ("produced_run_id", "produced_node_run_id", "produced_attempt_id"):
            _require_non_empty(getattr(self, name), name)
        return self


def start_states_match(a: EvalWorkspace, b: EvalWorkspace) -> bool:
    """Whether two workspaces are an identical-start-state matched pair.

    Both the environment and the recorded start state must be equal, and the
    start state must actually be recorded: two freshly provisioned workspaces
    with equal digests have never been proven to start identically, so they
    do not match until each has a start state on record.
    """
    if a.start_state_digest is None or b.start_state_digest is None:
        return False
    return (
        a.environment_digest == b.environment_digest
        and a.start_state_digest == b.start_state_digest
    )


__all__ = [
    "EMPTY_FIXTURES",
    "TERMINAL_WORKSPACE_STATUSES",
    "EvalWorkspace",
    "EvalWorkspaceStatus",
    "FixtureEntry",
    "FixtureManifest",
    "WorkspaceSnapshot",
    "start_states_match",
]
