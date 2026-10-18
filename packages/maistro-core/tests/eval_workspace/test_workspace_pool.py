"""Warm-pool claim policy (#107).

The pool serves claims from AVAILABLE workspaces of *exactly* the requested
environment digest. These tests pin the three behaviours that make the pool
safe: a miss is a miss (never a near-miss substitution), a claimed workspace
is never handed to a second Attempt, and released workspaces come back
claimable or parked according to the releasing Attempt's decision.
"""

from __future__ import annotations

from maistro.eval_workspace import (
    EvalWorkspaceService,
    FixtureEntry,
    FixtureManifest,
    WorkspacePool,
    environment_digest,
)

from .conftest import fixture_digest, sandbox_config, scoped_grant


def _digest(fixtures: FixtureManifest | None = None) -> str:
    return environment_digest(
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        fixtures_digest=(fixtures or FixtureManifest()).digest,
    )


def _warm(
    service: EvalWorkspaceService,
    workspace_id: str,
    fixtures: FixtureManifest | None = None,
) -> str:
    ws = service.provision(
        workspace_id=workspace_id,
        project_id="proj-1",
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        fixtures=fixtures or FixtureManifest(),
    )
    return service.activate(ws.workspace_env_id).workspace_env_id


def test_cold_digest_is_a_miss_not_an_error(pool: WorkspacePool) -> None:
    assert pool.claim(_digest(), attempt_id="att-1") is None
    assert pool.warm_count(_digest()) == 0


def test_claim_returns_a_workspace_of_exactly_that_digest(
    pool: WorkspacePool, service: EvalWorkspaceService
) -> None:
    warm = _warm(service, "ws-a")
    other_fixtures = FixtureManifest(
        entries=(FixtureEntry(name="x", content_sha256=fixture_digest(b"x")),)
    )
    _warm(service, "ws-b", fixtures=other_fixtures)

    claimed = pool.claim(_digest(), attempt_id="att-1", run_id="run-1")
    assert claimed is not None
    assert claimed.workspace_env_id == warm
    assert claimed.owner_attempt_id == "att-1"
    assert pool.warm_count(_digest()) == 0
    # The near-miss environment is still warm -- and was not substituted.
    assert pool.warm_count(_digest(other_fixtures)) == 1


def test_near_miss_digest_is_never_served(
    pool: WorkspacePool, service: EvalWorkspaceService
) -> None:
    """Same image, wider egress: a different environment, so a miss."""
    ws = service.provision(
        workspace_id="ws-scoped",
        project_id="proj-1",
        image="python:3.12-slim",
        sandbox=sandbox_config(egress=scoped_grant("pypi.org:443")),
    )
    service.activate(ws.workspace_env_id)
    assert service.get(ws.workspace_env_id).environment_digest != _digest()
    assert pool.claim(_digest(), attempt_id="att-1") is None


def test_claimed_workspace_is_not_served_twice(
    pool: WorkspacePool, service: EvalWorkspaceService
) -> None:
    _warm(service, "ws-a")
    first = pool.claim(_digest(), attempt_id="att-1")
    assert first is not None
    assert pool.claim(_digest(), attempt_id="att-2") is None
    assert service.get(first.workspace_env_id).owner_attempt_id == "att-1"


def test_release_returns_to_pool_or_parks(
    pool: WorkspacePool, service: EvalWorkspaceService
) -> None:
    warm = _warm(service, "ws-a")
    claimed = pool.claim(_digest(), attempt_id="att-1")
    assert claimed is not None

    pool.release(warm, attempt_id="att-1", keep_warm=True)
    assert pool.warm_count(_digest()) == 1
    again = pool.claim(_digest(), attempt_id="att-2")
    assert again is not None and again.workspace_env_id == warm

    pool.release(warm, attempt_id="att-2", keep_warm=False)
    assert pool.warm_count(_digest()) == 0
    assert [ws.workspace_env_id for ws in pool.parked()] == [warm]
    assert pool.claim(_digest(), attempt_id="att-3") is None
    service.resume(warm)
    assert pool.warm_count(_digest()) == 1


def test_fifo_order_for_multiple_warm_workspaces(
    pool: WorkspacePool, service: EvalWorkspaceService
) -> None:
    a = _warm(service, "ws-a")
    b = _warm(service, "ws-b")
    first = pool.claim(_digest(), attempt_id="att-1")
    second = pool.claim(_digest(), attempt_id="att-2")
    assert first is not None and second is not None
    assert [first.workspace_env_id, second.workspace_env_id] == [a, b]
