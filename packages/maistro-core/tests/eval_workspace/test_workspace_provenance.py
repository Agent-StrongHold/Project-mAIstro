"""Canonical Run/Attempt ownership and provenance of workspace records (#107).

Per ADR-083026-e602, every record of what an execution made names the
execution that made it: nullable `run_id` / `node_run_id` / `attempt_id`,
where blank means "no execution was in scope" and an unresolved id must not
silently fetch everything. Per the issue, ownership while an evaluation runs
is canonical: one Attempt owns a workspace at a time, and a Run can be asked
what workspace state it produced.
"""

from __future__ import annotations

import pytest

from maistro.eval_workspace import (
    EvalWorkspaceNotFound,
    EvalWorkspaceService,
    EvalWorkspaceStatus,
    FixtureManifest,
    WorkspaceSnapshot,
    environment_digest,
)
from maistro.eval_workspace.store import (
    DuplicateWorkspaceError,
    InMemoryEvalWorkspaceStore,
)

from .conftest import fixture_digest, sandbox_config

_DIGEST = environment_digest(
    image="python:3.12-slim",
    sandbox=sandbox_config(),
    fixtures_digest=FixtureManifest().digest,
)


def _provision(service: EvalWorkspaceService, **kw: object) -> str:
    ws = service.provision(
        workspace_id=str(kw.pop("workspace_id", "ws-1")),
        project_id=str(kw.pop("project_id", "proj-1")),
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        **kw,  # type: ignore[arg-type]
    )
    return ws.workspace_env_id


def _claimed_workspace(service: EvalWorkspaceService) -> str:
    env_id = _provision(service, run_id="run-1", node_run_id="nr-1", attempt_id="att-1")
    service.activate(env_id)
    claimed = service.claim_for_attempt(
        env_id, attempt_id="att-2", node_run_id="nr-2", run_id="run-2"
    )
    assert claimed.owner_attempt_id == "att-2"
    return env_id


def test_workspace_names_its_producing_execution(
    service: EvalWorkspaceService,
) -> None:
    ws = service.provision(
        workspace_id="ws-x",
        project_id="proj-1",
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        run_id="run-42",
        node_run_id="nr-42",
        attempt_id="att-42",
    )
    assert (ws.produced_run_id, ws.produced_node_run_id, ws.produced_attempt_id) == (
        "run-42",
        "nr-42",
        "att-42",
    )


def test_produced_by_run_answers_what_did_this_run_produce(
    service: EvalWorkspaceService,
) -> None:
    env_id = _claimed_workspace(service)
    service.snapshot(env_id, state=b"s", run_id="run-2", attempt_id="att-2")

    workspaces, snapshots = service.produced_by_run("run-1")
    assert [ws.workspace_env_id for ws in workspaces] == [env_id]
    assert snapshots == []

    _, run2_snapshots = service.produced_by_run("run-2")
    assert len(run2_snapshots) == 1
    assert isinstance(run2_snapshots[0], WorkspaceSnapshot)


def test_blank_run_id_returns_nothing_not_everything(
    service: EvalWorkspaceService,
) -> None:
    """An unresolved id silently fetching the wrong set is the failure e602
    exists to prevent; "which records did no execution produce" is a
    different question and must not be answered by the same call."""
    _provision(service, workspace_id="ws-unattributed")
    workspaces, snapshots = service.produced_by_run("")
    assert workspaces == []
    assert snapshots == []


def test_claim_ownership_is_visible_from_the_single_authority(
    service: EvalWorkspaceService,
    store: InMemoryEvalWorkspaceStore,
) -> None:
    """Store and service share one record set: both answer identically."""
    env_id = _claimed_workspace(service)
    by_owner = store.find_by_owner("att-2")
    assert [ws.workspace_env_id for ws in by_owner] == [env_id]
    assert service.get(env_id).status is EvalWorkspaceStatus.IN_USE


def test_snapshot_names_its_producing_attempt(
    service: EvalWorkspaceService,
) -> None:
    env_id = _provision(service)
    ready = service.activate(env_id)
    snap = service.snapshot(
        ready.workspace_env_id,
        state=b"captured",
        run_id="run-7",
        node_run_id="nr-7",
        attempt_id="att-7",
    )
    assert (snap.produced_run_id, snap.produced_node_run_id, snap.produced_attempt_id) == (
        "run-7",
        "nr-7",
        "att-7",
    )
    assert snap.environment_digest == _DIGEST


def test_snapshots_must_name_a_recorded_workspace_and_be_unique() -> None:
    """Provenance pointing nowhere is not persisted; ids are not reused."""
    store = InMemoryEvalWorkspaceStore()
    snap = WorkspaceSnapshot(
        workspace_env_id="ghost",
        environment_digest=_DIGEST,
        content_digest=fixture_digest(b"state"),
    )
    with pytest.raises(EvalWorkspaceNotFound):
        store.add_snapshot(snap)

    ws = _provision(EvalWorkspaceService(store))
    real = WorkspaceSnapshot(
        workspace_env_id=ws,
        environment_digest=_DIGEST,
        content_digest=fixture_digest(b"state"),
    )
    store.add_snapshot(real)
    with pytest.raises(DuplicateWorkspaceError):
        store.add_snapshot(real)


def test_snapshot_digest_is_of_the_captured_bytes(
    service: EvalWorkspaceService,
) -> None:
    """The content digest is computed from the capture, not self-declared."""
    env_id = _provision(service)
    ready = service.activate(env_id)
    snap = service.snapshot(ready.workspace_env_id, state=b"exact bytes")
    assert snap.content_digest == fixture_digest(b"exact bytes")
