"""A stale sandbox worker cannot publish over a newer Attempt (#79).

#45 fenced the canonical store: `transition_attempt(fencing_token=...)` refuses
a write whose token is not current. That fence stops at the process edge, and a
sandboxed worker is a different process — by #76 sometimes a different kernel.
Everything it publishes crosses a boundary the store has never seen.

The interesting cases here are all the same shape: a worker starts, something
reclaims its lease while it is still running, and then it finishes and tries to
publish. Every test below is a version of that, because it is the only way a
stale write happens in practice — nobody writes a worker that publishes twice
on purpose.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.runs.store import StaleExecutionFence
from maistro.sandbox import SandboxConfig
from maistro.sandbox.commit import fenced_commit
from maistro.sandbox.fence import (
    ENV_ATTEMPT_ID,
    ENV_LEASE_EPOCH,
    ENV_NODE_RUN_ID,
    ENV_TOKEN,
    SandboxFence,
    assert_fence_is_current,
)


async def _leased_attempt(
    *, holder: str = "worker-1", ttl: timedelta = timedelta(minutes=5)
) -> tuple[InMemoryRunStore, SandboxFence, str]:
    """A Run with one RUNNING NodeRun and one leased Attempt on it."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-fence")
    project = await projects.create(
        workspace_id="ws-fence", parent_project_id=root.project_id, name="Fence"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-fence",
        project_id=project.project_id,
        name="fenced",
        nodes=[Node(node_id="step", node_type="test.fence.step")],
    )
    run = await store.create_run(graph, initial_status=RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="step")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder=holder, lease_ttl=ttl)
    assert attempt.execution_lease is not None
    return store, SandboxFence.of(attempt.execution_lease), node_run.node_run_id


# --- what crosses the boundary, and what does not ----------------------------


async def test_the_fence_carries_only_what_a_commit_needs() -> None:
    """Acceptance is explicit: "only the current fence identity needed for its
    work". `holder` is operational topology, and the lease timings invite a
    sandboxed process to judge its own validity — which is exactly the decision
    the fence exists to take away from it."""
    store, fence, _node_run_id = await _leased_attempt(holder="worker-secret-1")
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None

    env = fence.to_env()

    assert set(env) == {ENV_ATTEMPT_ID, ENV_NODE_RUN_ID, ENV_LEASE_EPOCH, ENV_TOKEN}
    serialized = " ".join(env.values())
    assert "worker-secret-1" not in serialized
    assert attempt.execution_lease.issued_at.isoformat() not in serialized


async def test_a_fence_round_trips_through_an_environment() -> None:
    _store, fence, _node_run_id = await _leased_attempt()

    assert SandboxFence.from_env(fence.to_env()) == fence


@pytest.mark.parametrize("missing", [ENV_TOKEN, ENV_ATTEMPT_ID, ENV_LEASE_EPOCH])
async def test_a_partial_fence_reads_as_no_fence(missing: str) -> None:
    """Not a weaker fence — no fence. A caller that reconstructed one anyway
    would present something the store must reject, and would learn that at the
    commit instead of at the read."""
    _store, fence, _node_run_id = await _leased_attempt()
    env = fence.to_env()
    del env[missing]

    assert SandboxFence.from_env(env) is None


async def test_a_non_numeric_epoch_reads_as_no_fence() -> None:
    _store, fence, _node_run_id = await _leased_attempt()
    env = fence.to_env() | {ENV_LEASE_EPOCH: "not-a-number"}

    assert SandboxFence.from_env(env) is None


def test_the_sandbox_config_carries_no_fence_by_default() -> None:
    assert SandboxConfig().fence is None


async def test_the_backend_injects_the_fence_into_the_sandbox_environment(
    tmp_path: object,
) -> None:
    """`--clearenv` means the sandbox starts with nothing, so these four
    variables are the only thing it knows about its own execution identity."""
    from pathlib import Path

    from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend

    _store, fence, _node_run_id = await _leased_attempt()
    backend = BubblewrapSandboxBackend(root=Path(str(tmp_path)), bwrap="/usr/bin/bwrap")

    argv = backend.build_argv(SandboxConfig(fence=fence), Path(str(tmp_path)), ["true"])

    assert "--clearenv" in argv
    for key, value in fence.to_env().items():
        index = argv.index(key)
        assert argv[index - 1] == "--setenv"
        assert argv[index + 1] == value


# --- staleness, in each of the ways it happens -------------------------------


async def test_a_current_fence_is_admitted() -> None:
    store, fence, _node_run_id = await _leased_attempt()

    attempt = await assert_fence_is_current(fence, run_store=store)

    assert attempt.attempt_id == fence.attempt_id


async def test_a_worker_whose_lease_was_reclaimed_is_refused() -> None:
    """The case this exists for, and the one a token comparison alone misses.

    Reclaiming does *not* clear the lease: it cancels the Attempt and leaves
    the token in place. So this worker comes back holding a token that still
    matches, and only the terminal-status check stops it.
    """
    store, fence, _node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )

    with pytest.raises(StaleExecutionFence, match="already cancelled"):
        await assert_fence_is_current(fence, run_store=store)


async def test_a_superseded_token_is_refused() -> None:
    """A newer lease exists on the same Attempt: the worker is publishing into
    an execution someone else now owns."""
    store, fence, node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    renewed = await store.renew_lease(
        fence.attempt_id,
        fencing_token=fence.fencing_token,
        ttl=timedelta(minutes=5),
    )
    assert renewed.execution_lease is not None
    stale = SandboxFence(
        attempt_id=fence.attempt_id,
        node_run_id=node_run_id,
        lease_epoch=fence.lease_epoch,
        fencing_token="a-token-from-a-previous-life",
    )

    with pytest.raises(StaleExecutionFence, match="newer lease"):
        await assert_fence_is_current(stale, run_store=store)


async def test_a_fence_for_an_attempt_that_no_longer_exists_is_refused() -> None:
    store, fence, node_run_id = await _leased_attempt()
    vanished = SandboxFence(
        attempt_id="attempt-that-never-was",
        node_run_id=node_run_id,
        lease_epoch=fence.lease_epoch,
        fencing_token=fence.fencing_token,
    )

    with pytest.raises(StaleExecutionFence, match="no longer exists"):
        await assert_fence_is_current(vanished, run_store=store)


async def test_a_mismatched_epoch_is_refused() -> None:
    """The same staleness caught by number rather than by identity, which is
    what makes a replayed old token visible."""
    store, fence, node_run_id = await _leased_attempt()
    replayed = SandboxFence(
        attempt_id=fence.attempt_id,
        node_run_id=node_run_id,
        lease_epoch=fence.lease_epoch + 5,
        fencing_token=fence.fencing_token,
    )

    with pytest.raises(StaleExecutionFence, match="lease epoch"):
        await assert_fence_is_current(replayed, run_store=store)


# --- the guard, and the side effect it is there to stop ----------------------


async def test_a_fenced_commit_runs_the_publish_when_the_fence_is_current() -> None:
    store, fence, _node_run_id = await _leased_attempt()
    published: list[str] = []

    async def _publish() -> str:
        published.append("branch")
        return "pushed"

    result = await fenced_commit(fence, _publish, run_store=store, description="promote branch")

    assert result == "pushed"
    assert published == ["branch"]


async def test_a_stale_commit_does_not_run_the_publish_at_all() -> None:
    """The ordering is the substance. Checking afterwards would mean the branch
    was already pushed — a report of the failure rather than its prevention."""
    store, fence, _node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )
    published: list[str] = []

    async def _publish() -> str:
        published.append("branch")  # pragma: no cover - must never run
        return "pushed"

    with pytest.raises(StaleExecutionFence):
        await fenced_commit(fence, _publish, run_store=store, description="promote branch")

    assert published == [], "a stale worker must not reach its side effect"


async def test_a_slow_worker_reclaimed_mid_flight_is_refused_at_the_door() -> None:
    """The delayed-worker race, played out in order: the worker starts, its
    lease lapses and is reclaimed while it is still working, and only then does
    it come back to publish."""
    store, fence, _node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    published: list[str] = []

    async def _slow_publish() -> str:
        published.append("artifact")  # pragma: no cover - must never run
        return "uploaded"

    async def _worker() -> None:
        await asyncio.sleep(0.05)  # the work
        await fenced_commit(fence, _slow_publish, run_store=store, description="upload artifact")

    task = asyncio.create_task(_worker())
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )

    with pytest.raises(StaleExecutionFence):
        await task
    assert published == []


async def test_two_workers_race_and_only_the_current_one_publishes() -> None:
    """Both believe they are executing this Attempt. Exactly one is right, and
    the store is what decides — not whichever finished first."""
    store, first, node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    attempt = await store.get_attempt(first.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    renewed = await store.renew_lease(
        first.attempt_id, fencing_token=first.fencing_token, ttl=timedelta(minutes=5)
    )
    assert renewed.execution_lease is not None
    second = SandboxFence.of(renewed.execution_lease)
    stale_first = SandboxFence(
        attempt_id=first.attempt_id,
        node_run_id=node_run_id,
        lease_epoch=first.lease_epoch,
        fencing_token="superseded-token",
    )
    published: list[str] = []

    async def _publish(label: str) -> str:
        published.append(label)
        return label

    results = await asyncio.gather(
        fenced_commit(second, lambda: _publish("current"), run_store=store, description="w2"),
        fenced_commit(stale_first, lambda: _publish("stale"), run_store=store, description="w1"),
        return_exceptions=True,
    )

    assert results[0] == "current"
    assert isinstance(results[1], StaleExecutionFence)
    assert published == ["current"]


# --- backend independence ----------------------------------------------------


async def test_fencing_does_not_depend_on_which_backend_ran_the_work() -> None:
    """The fence is adjudicated against the canonical store, so a fake-backed
    sandbox and a bubblewrap-backed one are refused by the same rule for the
    same reason. A backend that could weaken this would be a backend that
    decides its own containment."""
    from maistro.sandbox.backends.fake import FakeSandboxBackend

    store, fence, _node_run_id = await _leased_attempt(ttl=timedelta(seconds=1))
    backend = FakeSandboxBackend()
    instance = await backend.spawn(config=SandboxConfig(fence=fence))
    attempt = await store.get_attempt(fence.attempt_id)
    assert attempt is not None and attempt.execution_lease is not None
    await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )

    with pytest.raises(StaleExecutionFence):
        await assert_fence_is_current(fence, run_store=store)

    await backend.destroy(instance)
