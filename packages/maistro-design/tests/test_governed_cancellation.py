"""M7-A11 explore: an in-flight Invocation follows canonical cancellation.

Acceptance under test (#987 contract, "Cancellation / pause"):

- cancelling the wave cancels the canonical Run, and the in-flight explore
  Invocation is left ``UNKNOWN`` — the fence park does not pretend the call
  vanished, and the Run never shows a thesis the call did not return.

The governed design nodes own no cancellation machinery: they dispatch through
the canonical ``ModelChatEgress`` → ``InvocationExecutionService``, so the
pause/stop contract is the canonical one. This test proves the design wave
actually rides it rather than catching ``CancelledError`` into a fake success.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

#: Every Invocation in this scope is created after the epoch, so a far-past
#: staleness bound makes ``list_ambiguous`` return exactly the UNKNOWN rows.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_CANCELLED_OUTCOME = "provider invocation cancelled with unknown external outcome"


async def test_a_cancelled_explore_wave_leaves_the_invocation_unknown(
    monkeypatch: pytest.MonkeyPatch,
    governed: Any,
    governed_kit: Any,
) -> None:
    """Cancel mid-flight: Run cancelled, Invocation UNKNOWN, no thesis shown."""

    from maistro.capabilities.invocation import InvocationStatus
    from maistro.graph.durable_runs import run_durable_graph
    from maistro.graph.durable_runs.launch import durable_graph_launch_provenance
    from maistro.runs.model import AttemptStatus, RunStatus
    from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

    entered = asyncio.Event()

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            # Never reached: the wave is cancelled while the call is parked.
            return {
                "choices": [{"message": {"role": "assistant", "content": "{}"}}],
            }

    class _Client:
        is_closed = False

        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, *a: Any, **kw: Any) -> _Resp:
            entered.set()
            # Park the physical call until the test cancels the walk.
            await asyncio.Event().wait()
            return _Resp()

    import maistro.http

    monkeypatch.setattr(
        maistro.http, "get_shared_client", lambda *a, **kw: _Client(), raising=False
    )

    graph = governed_kit.wave_graph(governed, width=1)
    run = await governed.run_store.create_run(
        graph,
        provenance=durable_graph_launch_provenance(inputs={}, blackboard_metadata={}),
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        goal_id=governed_kit.goal_id,
        goal_revision=governed_kit.goal_revision,
    )
    nodes = governed_kit.design_nodes(governed)

    def node_resolver(node_id: str, walk_graph: Any) -> Any:
        spec = next(node for node in walk_graph.nodes if node.node_id == node_id)
        return nodes[spec.node_type]

    task = asyncio.create_task(
        run_durable_graph(
            graph,
            store=governed.durable_store,
            node_resolver=node_resolver,
            run_store=governed.run_store,
            run_id=run.run_id,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The canonical Run is cancelled — not silently completed, and not failed
    # as if the model had answered.
    cancelled = await governed.run_store.get_run(run.run_id)
    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED

    # The in-flight Invocation is UNKNOWN: the remote outcome cannot be proven
    # absent, so the fence park records ambiguity rather than a thesis.
    invocations = await governed.effects.invocation_store.list_ambiguous(stale_before=_EPOCH)
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.status is InvocationStatus.UNKNOWN
    assert invocation.error == _CANCELLED_OUTCOME
    assert invocation.run_id == run.run_id
    # The Attempt that dispatched it is not reported as completed.
    attempt = await governed.run_store.get_attempt(invocation.attempt_id)
    assert attempt is not None
    assert attempt.status is not AttemptStatus.COMPLETED

    # And the Run shows no thesis the call never returned.
    thesis_runs = [
        node_run
        for node_run in await governed.run_store.list_node_runs(run.run_id)
        if node_run.node_id.startswith("thesis-")
    ]
    assert all(node_run.accepted_outcome is None for node_run in thesis_runs)
