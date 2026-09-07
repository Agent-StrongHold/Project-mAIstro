"""One trace, end to end: request → Run → NodeRun → Attempt → Event/Outcome (#63).

Issue #63's first acceptance bullet is a chain, not a set of unit facts: one
trace follows a request through the Run it creates, the NodeRun and Attempt
that execute it, to the canonical Event and the accepted Outcome that record
what happened. Each link has its own test elsewhere; what nothing asserted is
that the *links agree* — that the event the executor emits names the very
Attempt the spine persisted, that the outcome names the same NodeRun, and that
the request id the HTTP seam bound reaches the log lines of that execution.

This drives the real spine (`RunExecutionService` → `AttemptExecutionService`
→ a real store) inside a request-scoped binding exactly as
`RequestIDMiddleware` establishes it, with a durable SQLite canonical event
store as the Event leg. Nothing here mocks a seam to observe it: the
executor is real work that reads its own ambient context and emits through
the store contract.

The Invocation link in the issue's chain is the documented exception: nothing
constructs the Invocation layer on a product path yet (#55, recorded in #717),
so no trace can include one, and this test asserts the chain that exists
rather than inventing that link.
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.events.envelope import EventEnvelope, SqliteEventStore
from maistro.graph import Graph, Node
from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
    execution_context_processor,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunExecutionService
from maistro.runtime import PythonExecutionRuntime

pytestmark = [pytest.mark.contract("behavioral")]


class _Seen:
    """What the executor observed, recorded from inside the execution."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self.log_fields: list[dict[str, Any]] = []
        self.emitted: list[str] = []


async def _store_and_graph() -> tuple[InMemoryRunStore, Graph, str]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="One trace",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return store, graph, project.project_id


def _executor(events: SqliteEventStore, seen: _Seen) -> Any:
    """Real attempt work: emit one canonical event, return one result."""

    async def executor(work_item: Any, context: Any) -> str:
        ambient = current_execution_context()
        seen.contexts.append(ambient)
        # The log leg of the chain: what every log line inside this attempt
        # carries, computed the way `execution_context_processor` computes it.
        seen.log_fields.append(execution_context_processor(None, "info", {"event": "work"}))
        # The Event leg: a producer that spells only what it must — the
        # Workspace that owns the stream — and lets the envelope fill join it
        # to the execution it happened inside.
        stored = await events.append(
            EventEnvelope(
                type="node.executed",
                workspace_id=ambient.workspace_id,
                source="one-trace-test",
                payload={"work": str(work_item)},
            )
        )
        seen.emitted.append(stored.event_id)
        return "done"

    return executor


class TestOneTraceFollowsTheWork:
    async def test_request_run_noderun_attempt_event_outcome_agree(self) -> None:
        store, graph, project_id = await _store_and_graph()
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        seen = _Seen()
        conn = await aiosqlite.connect(":memory:")
        try:
            events = SqliteEventStore(conn)
            await events.ensure_schema()

            # The request seam: what RequestIDMiddleware binds for every
            # HTTP-borne execution, plus the Workspace/Project the requesting
            # route already knows (ADR-083026-1cb1's outer bind).
            with bind_execution_context(
                request_id="req-42", workspace_id="ws-1", project_id=project_id
            ):
                run = await service.create_run(graph)
                node_run, attempt = await service.execute_node(
                    run.run_id,
                    "node-1",
                    "work",
                    {},
                    executor=_executor(events, seen),
                )

            # The executor ran inside the full chain, request included.
            [ambient] = seen.contexts
            assert ambient.request_id == "req-42"
            assert ambient.run_id == run.run_id
            assert ambient.node_run_id == node_run.node_run_id
            assert ambient.attempt_id == attempt.attempt_id
            assert ambient.workspace_id == "ws-1"
            assert ambient.project_id == project_id

            # Every log line of the execution names request and Run together —
            # the join a request makes to the work it caused.
            [log_fields] = seen.log_fields
            assert log_fields["request_id"] == "req-42"
            assert log_fields["run_id"] == run.run_id
            assert log_fields["node_run_id"] == node_run.node_run_id
            assert log_fields["attempt_id"] == attempt.attempt_id

            # The Event names the exact Attempt the spine persisted.
            [event_id] = seen.emitted
            event = await events.get(event_id)
            assert event is not None
            assert event.run_id == run.run_id
            assert event.node_run_id == node_run.node_run_id
            assert event.attempt_id == attempt.attempt_id
            assert event.project_id == project_id
            assert event.correlation_id == run.run_id
            assert event.sequence == 1  # durably sequenced in its Workspace stream

            # The Outcome names the same physical evidence, accepted onto the
            # NodeRun the event claims.
            assert attempt.status is AttemptStatus.COMPLETED
            assert node_run.accepted_outcome is not None
            assert node_run.accepted_outcome.node_run_id == node_run.node_run_id
            assert node_run.accepted_outcome.attempt_result.attempt_id == attempt.attempt_id
            assert node_run.accepted_outcome.attempt_result.node_run_id == node_run.node_run_id
            assert node_run.run_id == run.run_id
        finally:
            await conn.close()

    async def test_a_retry_joins_the_same_trace(self) -> None:
        """AC-2's retry leg, on the same chain: a second Attempt of the same
        NodeRun re-emits under the same Run and joins the first event's stream
        rather than starting a trace of its own."""
        store, graph, project_id = await _store_and_graph()
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        seen = _Seen()
        conn = await aiosqlite.connect(":memory:")
        try:
            events = SqliteEventStore(conn)
            await events.ensure_schema()

            async def failing(work_item: Any, context: Any) -> str:
                raise RuntimeError("first try fails")

            with bind_execution_context(
                request_id="req-43", workspace_id="ws-1", project_id=project_id
            ):
                run = await service.create_run(graph)
                with pytest.raises(RuntimeError, match="first try fails"):
                    await service.execute_node(run.run_id, "node-1", "work", {}, executor=failing)
                first_node_run = (await store.list_node_runs(run.run_id))[0]
                await service.retry_node(
                    first_node_run.node_run_id,
                    "work",
                    {},
                    executor=_executor(events, seen),
                )

            [ambient] = seen.contexts
            assert ambient.request_id == "req-43"
            assert ambient.run_id == run.run_id
            assert ambient.node_run_id == first_node_run.node_run_id
            first_attempts = await store.list_attempts(first_node_run.node_run_id)
            assert len(first_attempts) == 2
            assert ambient.attempt_id == first_attempts[1].attempt_id
            assert ambient.attempt_id != first_attempts[0].attempt_id

            [event_id] = seen.emitted
            event = await events.get(event_id)
            assert event is not None
            assert event.run_id == run.run_id
            assert event.node_run_id == first_node_run.node_run_id
            assert event.attempt_id == ambient.attempt_id
        finally:
            await conn.close()
