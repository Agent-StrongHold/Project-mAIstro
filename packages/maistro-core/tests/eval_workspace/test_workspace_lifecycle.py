"""Workspace record lifecycle: hold ownership, park/resume, retire (#107).

The lifecycle exists so a warm pool and an eval harness can share one
authority: the record. These tests pin the invariants that make the record
trustworthy -- one owner at a time, only valid transitions, ownership
released only by its owner, archive terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.eval_workspace import (
    EMPTY_FIXTURES,
    EvalWorkspace,
    EvalWorkspaceService,
    EvalWorkspaceStatus,
    InMemoryEvalWorkspaceStore,
    OwnershipError,
    WorkspaceStateError,
    environment_digest,
)

from .conftest import sandbox_config


def _digest() -> str:
    return environment_digest(
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        fixtures_digest=EMPTY_FIXTURES.digest,
    )


def _provision(service: EvalWorkspaceService, **kw: object) -> EvalWorkspace:
    return service.provision(
        workspace_id=str(kw.pop("workspace_id", "ws-1")),
        project_id=str(kw.pop("project_id", "proj-1")),
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        **kw,  # type: ignore[arg-type]
    )


def test_provision_starts_creating_then_activates(
    service: EvalWorkspaceService,
) -> None:
    workspace = _provision(service)
    assert workspace.status is EvalWorkspaceStatus.PROVISIONING
    assert workspace.environment_digest == _digest()
    ready = service.activate(workspace.workspace_env_id)
    assert ready.status is EvalWorkspaceStatus.AVAILABLE


def test_resume_a_ready_workspace_is_refused(service: EvalWorkspaceService) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    with pytest.raises(WorkspaceStateError, match="not a permitted transition"):
        service.resume(workspace.workspace_env_id)


def test_claim_requires_ready(service: EvalWorkspaceService) -> None:
    workspace = _provision(service)
    with pytest.raises(WorkspaceStateError, match="not AVAILABLE"):
        service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-1")


def test_claim_binds_exactly_one_attempt(service: EvalWorkspaceService) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    claimed = service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-1")
    assert claimed.status is EvalWorkspaceStatus.IN_USE
    assert claimed.owner_attempt_id == "att-1"
    with pytest.raises(WorkspaceStateError, match="not AVAILABLE"):
        service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-2")


def test_release_keeps_warm_or_parks(service: EvalWorkspaceService) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-1")

    released = service.release_from_attempt(
        workspace.workspace_env_id, attempt_id="att-1", keep_warm=True
    )
    assert released.status is EvalWorkspaceStatus.AVAILABLE
    assert released.owner_attempt_id is None

    service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-2")
    parked = service.release_from_attempt(
        workspace.workspace_env_id, attempt_id="att-2", keep_warm=False
    )
    assert parked.status is EvalWorkspaceStatus.PARKED
    resumed = service.resume(workspace.workspace_env_id)
    assert resumed.status is EvalWorkspaceStatus.AVAILABLE


def test_release_by_non_owner_is_an_ownership_violation(
    service: EvalWorkspaceService,
) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-1")
    with pytest.raises(OwnershipError, match="does not own"):
        service.release_from_attempt(workspace.workspace_env_id, attempt_id="att-2")


def test_retiring_is_terminal_and_idempotent(service: EvalWorkspaceService) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    retired = service.archive(workspace.workspace_env_id)
    assert retired.status is EvalWorkspaceStatus.RETIRED
    assert retired.archived_at is not None
    assert service.archive(workspace.workspace_env_id).workspace_env_id == retired.workspace_env_id
    with pytest.raises(WorkspaceStateError, match="retired"):
        service.resume(workspace.workspace_env_id)


def test_cannot_retire_while_held(service: EvalWorkspaceService) -> None:
    workspace = service.activate(_provision(service).workspace_env_id)
    service.claim_for_attempt(workspace.workspace_env_id, attempt_id="att-1")
    with pytest.raises(WorkspaceStateError, match="release it before retiring"):
        service.archive(workspace.workspace_env_id)


def test_owner_binding_is_a_record_invariant() -> None:
    """IN_USE without an owner (or the reverse) cannot exist on any backend."""
    common = {
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "environment_digest": _digest(),
    }
    with pytest.raises(ValueError, match="owner_attempt_id"):
        EvalWorkspace(status=EvalWorkspaceStatus.IN_USE, **common)
    with pytest.raises(ValueError, match="owner_attempt_id"):
        EvalWorkspace(status=EvalWorkspaceStatus.AVAILABLE, owner_attempt_id="att-1", **common)
    with pytest.raises(ValueError, match="archived_at"):
        EvalWorkspace(
            status=EvalWorkspaceStatus.AVAILABLE,
            archived_at=datetime.now(UTC),
            **common,
        )
    with pytest.raises(ValueError, match="archived_at"):
        EvalWorkspace(status=EvalWorkspaceStatus.RETIRED, archived_at=None, **common)


def test_store_refuses_unknown_ids_and_duplicates() -> None:
    store = InMemoryEvalWorkspaceStore()
    workspace = _provision(EvalWorkspaceService(store))
    with pytest.raises(KeyError):
        store.get_workspace("missing")
    with pytest.raises(RuntimeError, match="already exists"):
        store.add_workspace(workspace)
