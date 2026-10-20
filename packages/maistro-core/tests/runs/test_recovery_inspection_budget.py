"""Measure inspected records separately from repairs (#1151 / #1098).

These are observations of the public recovery tick, not a new scan-work ceiling.
Counts include nested reconciler reads through the RunStore API, not database
pages/rows examined internally, SQL costs, or continuation-sweep work. A fresh
Container models loss of local scan state, not a process/database restart.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import RunStore, run_cursor_key
from maistro.types.config import AgentConfig


@pytest.fixture
def spine_concurrency_limits() -> RunConcurrencyLimits:
    # The measurement needs eleven simultaneous root Runs for one principal.
    return RunConcurrencyLimits(per_principal=32)


async def _seed(
    store: RunStore,
    workspace: str,
    project_id: str,
    *,
    nodes: int = 1,
    attempts: int = 1,
    unchanged: bool = False,
) -> tuple[str, list[Attempt]]:
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="inspection measurement",
        nodes=[Node(node_id=f"n{i}", node_type="test") for i in range(nodes)]
        + ([Node(node_id="unobserved", node_type="test")] if unchanged else []),
        edges=[],
    )
    run = await store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id="test:inspection"
    )
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    completed = []
    for i in range(nodes):
        node = await store.create_node_run(run.run_id, node_id=f"n{i}")
        await store.transition_node_run(node.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node.node_run_id, RunStatus.RUNNING)
        for ordinal in range(attempts):
            attempt = await store.create_attempt(node.node_run_id)
            await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
            attempt = await store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.COMPLETED if ordinal == attempts - 1 else AttemptStatus.FAILED,
                result={"ordinal": ordinal, "node": i},
            )
        completed.append(attempt)
        if unchanged:
            # Accepted evidence cannot settle a graph with an unobserved node.
            await AttemptLifecycleReconciler(store).reconcile(attempt)
    return run.run_id, completed


async def _snapshot(store: RunStore, run_ids: list[str]) -> list[Any]:
    """All persisted fields, not merely status/count, outside measured reads."""
    result = []
    for run_id in run_ids:
        nodes = await store.list_node_runs(run_id)
        result.append(
            (
                await store.get_run(run_id),
                nodes,
                [await store.list_attempts(node.node_run_id) for node in nodes],
            )
        )
    return result


def _count_reads(store: RunStore, patch: pytest.MonkeyPatch) -> tuple[Counter[str], list[Any]]:
    counts: Counter[str] = Counter()
    pages: list[Any] = []

    def wrap(name: str) -> Any:
        original = getattr(store, name)

        async def measured(*args: Any, **kwargs: Any) -> Any:
            value = await original(*args, **kwargs)
            counts[f"{name}.calls"] += 1
            counts[f"{name}.rows"] += (
                len(value) if name.startswith("list_") else int(value is not None)
            )
            if name == "list_by_status":
                pages.append((args, kwargs, [row.run_id for row in value]))
            return value

        return measured

    for name in (
        "list_by_status",
        "list_node_runs",
        "list_attempts",
        "get_run",
        "get_node_run",
        "get_attempt",
    ):
        patch.setattr(store, name, wrap(name))
    return counts, pages


@pytest.mark.parametrize("prefix_pages", [0, 1, 2, 10])
@pytest.mark.parametrize(("nodes", "attempts"), [(1, 1), (3, 1), (1, 4), (3, 4)])
@pytest.mark.parametrize("peer_first", [False, True], ids=["own-repair", "peer-first"])
async def test_recovery_inspection_measurements(
    spine: Any,
    monkeypatch: pytest.MonkeyPatch,
    prefix_pages: int,
    nodes: int,
    attempts: int,
    peer_first: bool,
) -> None:
    store, workspace, project_id = spine
    config = AgentConfig(router_api_key="test-key", database_url="memory://")
    container = await create_container(config)
    container.run_store = store
    restarted: Container | None = None
    try:
        # Settled history is not a candidate even when it sorts before the prefix.
        historical, terminal = await _seed(store, workspace, project_id)
        await AttemptLifecycleReconciler(store).reconcile(terminal[0])
        prefix = []
        for _ in range(prefix_pages):
            run_id, _ = await _seed(
                store, workspace, project_id, nodes=nodes, attempts=attempts, unchanged=True
            )
            prefix.append(run_id)
        target_id, target_attempts = await _seed(store, workspace, project_id)
        unchanged_before = await _snapshot(store, [historical, *prefix])
        physical_before = await store.list_attempts(target_attempts[0].node_run_id)
        candidates = [await store.get_run(run_id) for run_id in [*prefix, target_id]]
        assert all(run is not None and run.status is RunStatus.RUNNING for run in candidates)
        assert candidates == sorted(candidates, key=run_cursor_key)
        for name in ("create_attempt", "create_node_run"):
            monkeypatch.setattr(store, name, AsyncMock(side_effect=AssertionError("dispatch")))
        monkeypatch.setattr(
            container.invocation_store,
            "create",
            AsyncMock(side_effect=AssertionError("invocation dispatch")),
        )

        original = AttemptLifecycleReconciler.reconcile
        interleavings = 0

        async def reconcile_after_peer(
            self: AttemptLifecycleReconciler, attempt: Attempt, **kwargs: Any
        ) -> NodeRun:
            nonlocal interleavings
            if (
                peer_first
                and attempt.attempt_id == target_attempts[0].attempt_id
                and interleavings == 0
            ):
                interleavings += 1
                # Real canonical peer reconciliation after the before-read.
                await original(AttemptLifecycleReconciler(store), attempt)
            return await original(self, attempt, **kwargs)

        monkeypatch.setattr(AttemptLifecycleReconciler, "reconcile", reconcile_after_peer)
        with monkeypatch.context() as measured_patch:
            first, first_pages = _count_reads(store, measured_patch)
            repairs = await container.recover_abandoned_attempts(limit=1)
        assert repairs == 1
        assert interleavings == int(peer_first)
        assert [page[2] for page in first_pages] == [[run_id] for run_id in [*prefix, target_id]]
        assert [page[1] for page in first_pages] == [
            {"limit": 1, "after": None},
            *[{"limit": 1, "after": run_cursor_key(run)} for run in candidates[:-1]],
        ]
        assert all(page[0] == (RunStatus.RUNNING,) for page in first_pages)
        assert first["list_by_status.rows"] == prefix_pages + 1
        assert first["list_node_runs.rows"] >= prefix_pages * nodes + 1
        assert first["list_attempts.rows"] >= prefix_pages * nodes * attempts + 1
        assert (await store.get_run(target_id)).status is RunStatus.COMPLETED
        assert await _snapshot(store, [historical, *prefix]) == unchanged_before
        assert await store.list_attempts(target_attempts[0].node_run_id) == physical_before

        fixed_point = await _snapshot(store, [historical, *prefix, target_id])
        with monkeypatch.context() as measured_patch:
            repeated, repeated_pages = _count_reads(store, measured_patch)
            assert await container.recover_abandoned_attempts(limit=1) == 0
        assert [page[2] for page in repeated_pages] == [[run_id] for run_id in prefix] + [[]]
        assert repeated["list_by_status.rows"] == prefix_pages
        # Even zero repairs reread accepted nodes and complete Attempt histories.
        assert repeated["list_node_runs.rows"] >= prefix_pages * nodes
        assert repeated["list_attempts.rows"] >= prefix_pages * nodes * attempts
        assert await _snapshot(store, [historical, *prefix, target_id]) == fixed_point

        restarted = await create_container(config)
        restarted.run_store = store
        monkeypatch.setattr(
            restarted.invocation_store,
            "create",
            AsyncMock(side_effect=AssertionError("invocation dispatch")),
        )
        with monkeypatch.context() as measured_patch:
            fresh, fresh_pages = _count_reads(store, measured_patch)
            assert await restarted.recover_abandoned_attempts(limit=1) == 0
        assert fresh == repeated
        assert fresh_pages == repeated_pages
        assert await _snapshot(store, [historical, *prefix, target_id]) == fixed_point
        print(
            "INSPECTION_MEASUREMENT="
            + json.dumps(
                {
                    "store": type(store).__name__,
                    "prefix_pages": prefix_pages,
                    "nodes": nodes,
                    "attempts": attempts,
                    "peer_first": peer_first,
                    "repairs": [repairs, 0, 0],
                    "first": dict(first),
                    "repeated": dict(repeated),
                    "fresh_container": dict(fresh),
                },
                sort_keys=True,
            )
        )
    finally:
        if restarted is not None:
            await restarted.aclose()
        await container.aclose()
