"""Behavioral tests for the in-memory Builders platform services."""

from __future__ import annotations

import pytest

from maistro.builders.contracts import ArtifactRef, StageEvent
from maistro.builders.services import (
    InMemoryArtifactStore,
    InMemoryEventBus,
    InMemoryGitHubService,
    InMemoryWorkspaceService,
)

# ---------------------------------------------------------------------------
# InMemoryWorkspaceService
# ---------------------------------------------------------------------------


def test_workspace_create_and_resolve() -> None:
    svc = InMemoryWorkspaceService()
    ws = svc.create(run_id="run-1", repo="acme/x", branch="feat")
    assert ws.status == "active"
    assert ws.path == "/workspace/run-1"
    assert svc.resolve(ws.workspace_id) == ws


def test_workspace_cleanup_archives_by_default() -> None:
    svc = InMemoryWorkspaceService()
    ws = svc.create(run_id="run-1", repo="acme/x", branch="feat")
    archived = svc.cleanup(ws.workspace_id)
    assert archived.status == "archived"
    # Identity preserved.
    assert archived.workspace_id == ws.workspace_id
    assert svc.resolve(ws.workspace_id).status == "archived"


def test_workspace_cleanup_delete_when_not_archiving() -> None:
    svc = InMemoryWorkspaceService()
    ws = svc.create(run_id="run-1", repo="acme/x", branch="feat")
    deleted = svc.cleanup(ws.workspace_id, archive=False)
    assert deleted.status == "deleted"


# ---------------------------------------------------------------------------
# InMemoryArtifactStore
# ---------------------------------------------------------------------------


def test_artifact_store_store_and_get() -> None:
    store = InMemoryArtifactStore()
    art = ArtifactRef(type="spec", path="runs/run-1/spec.json", producer="frank")
    store.store(art)
    assert store.get(art.artifact_id) == art


def test_artifact_store_list_for_run_filters_by_path_prefix() -> None:
    store = InMemoryArtifactStore()
    a = ArtifactRef(type="spec", path="runs/run-1/spec.json", producer="frank")
    b = ArtifactRef(type="code", path="runs/run-1/code.py", producer="mason")
    other = ArtifactRef(type="spec", path="runs/run-2/spec.json", producer="frank")
    for art in (a, b, other):
        store.store(art)

    ids = {art.artifact_id for art in store.list_for_run("run-1")}
    assert ids == {a.artifact_id, b.artifact_id}


def test_artifact_store_get_missing_raises() -> None:
    with pytest.raises(KeyError):
        InMemoryArtifactStore().get("nope")


# ---------------------------------------------------------------------------
# InMemoryEventBus
# ---------------------------------------------------------------------------


def _event(run_id: str) -> StageEvent:
    return StageEvent(run_id=run_id, stage="queued", event="created", actor="system", message="m")


def test_event_bus_emit_and_list_all() -> None:
    bus = InMemoryEventBus()
    bus.emit(_event("run-1"))
    bus.emit(_event("run-2"))
    assert len(bus.list_events()) == 2


def test_event_bus_list_filtered_by_run() -> None:
    bus = InMemoryEventBus()
    bus.emit(_event("run-1"))
    bus.emit(_event("run-2"))
    bus.emit(_event("run-1"))
    run1 = bus.list_events(run_id="run-1")
    assert len(run1) == 2
    assert all(e.run_id == "run-1" for e in run1)


# ---------------------------------------------------------------------------
# InMemoryGitHubService
# ---------------------------------------------------------------------------


def test_github_upsert_issue_update_replaces_per_stage() -> None:
    svc = InMemoryGitHubService()
    svc.upsert_issue_update(run_id="r", issue_number=1, stage="queued", body="first")
    svc.upsert_issue_update(run_id="r", issue_number=1, stage="queued", body="second")
    updates = svc.list_issue_updates(run_id="r")
    assert len(updates) == 1
    assert updates[0].body == "second"


def test_github_list_issue_updates_sorted_by_stage() -> None:
    svc = InMemoryGitHubService()
    svc.upsert_issue_update(run_id="r", issue_number=1, stage="tests_written", body="b")
    svc.upsert_issue_update(run_id="r", issue_number=1, stage="acceptance", body="a")
    stages = [u.stage for u in svc.list_issue_updates(run_id="r")]
    assert stages == sorted(stages)


def test_github_open_pr_assigns_incrementing_numbers() -> None:
    svc = InMemoryGitHubService()
    pr1 = svc.open_pr(run_id="r", repo="x", branch="b1", title="t1", body="b")
    pr2 = svc.open_pr(run_id="r", repo="x", branch="b2", title="t2", body="b")
    assert pr1.pr_number == 1
    assert pr2.pr_number == 2
    assert svc.get_pr(1).title == "t1"


def test_github_update_pr_partial_fields() -> None:
    svc = InMemoryGitHubService()
    pr = svc.open_pr(run_id="r", repo="x", branch="b", title="orig", body="orig-body")
    updated = svc.update_pr(pr.pr_number, title="new title")
    assert updated.title == "new title"
    # Untouched field preserved.
    assert updated.body == "orig-body"
