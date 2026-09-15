"""Executing a chat turn as a physical Attempt under its Run (#223).

The chat half of what #143 did for tasks, and it starts from exactly the same
place. #131 gave every chat turn a canonical Run over a one-node Graph, and
execution did not follow: `Container.route_request` admitted the Run, moved it
to RUNNING, and then called `conduit.route_request`, which dispatched straight
to `agent.handle`. So the Run's node had no NodeRun, nothing recorded that a
physical try started or how long it took, and `GET /v1/runs/{run_id}/node-runs`
was an endpoint that was correct and always empty.

The seam it should go through already existed and is the one tasks use:
`RunExecutionService.execute_node`. What is missing is the adapter between two
shapes — the Conduit returns an OpenAI-shaped dict and treats a refusal as an
ordinary answer, while Runtime takes an opaque work item plus a context and
reads a raised exception as failure. That adapter is this module.

Three things it decides, because nothing below it can.

**A refusal is a completion.** The Conduit answers a Gate block, a Sentinel
block or an empty roster as an ordinary assistant message — with
`finish_reason="content_filter"` for the first two. Nothing failed: the system
did exactly what it is supposed to do, and it did it successfully. Recording a
FAILED Attempt would make every refused turn look like an outage on a dashboard
that counts them, and would put refusals in the same bucket a provider being
down lands in.

**A raised exception is a failure**, and it keeps travelling. Since #142 the
Conduit re-raises rather than answering, and the endpoint above maps the
exception *type* to 502 or 504 — so the Attempt must record the failure and
then let the exception continue, not swallow it into a return value.

**What the Attempt persists.** `chat_turn_outcome` already decides how much of
a turn's answer the *Run* keeps, and why: a chat Run is an audit record and the
transcript lives in `maistro.sessions` (ADR-082326-c126). The Attempt reuses it
rather than inventing a second, larger copy — the physical record of a turn
should not be able to hold more of the conversation than the logical one.

**A recording failure after the dispatch is not a licence to dispatch again
(#1108).** Half the spine writes happen *after* the model has answered — the
Attempt's COMPLETED transition, the NodeRun and Run reconciliation behind it —
and a `RunIntegrityError` from any of them used to look, to the caller, exactly
like one raised before the turn ever reached the model. The caller's fallback
was a fresh dispatch, so a store hiccup while persisting an answer cost a second
model call, a second set of agent side effects, and a second assistant message
while the first answer's evidence sat on disk. `execute` now says which side of
the dispatch the spine failed on: `ChatDispatchUnrecorded` carries the answer
that already exists, so the caller can hand it back without asking again, and
the durable Attempt is left exactly where the lease sweep and the reconciler
read it.

What it deliberately does not do is rewrite the Run's `agent_selection`
provenance. That marker means "no agent was resolvable at *admission* time",
which stays true however the turn goes; the question a reader actually has —
which agent ran — is now answered by the Attempt, on the record of the thing
that ran. Mutating admission provenance after the fact would make the Run's
own history disagree with itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from maistro.runs.chat_admission import chat_turn_outcome
from maistro.runs.model import NodeRun
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

#: `executor_id` recorded on every Attempt a chat turn drives, the way
#: `TASK_EXECUTOR_ID` names the task runner. It answers "what kind of work was
#: this" on a record that otherwise only knows it ran.
CHAT_EXECUTOR_ID = "conduit"

#: Where the Attempt records the agent that handled the turn, read from the
#: key `Conduit.route_request` sets. Absent when no agent ran.
ATTEMPT_AGENT_KEY = "agent"

#: The Conduit's own key for the same thing. Imported by value rather than from
#: `maistro.conduit` on purpose: `runs` must not depend on the request pipeline
#: — `conduit` already imports from `runs`, and the reverse edge would close a
#: cycle. A test pins the two spellings together.
_CONDUIT_AGENT_KEY = "agent"

#: One chat dispatch: takes nothing, returns the Conduit's OpenAI-shaped dict.
#: A thunk rather than a signature mirroring `route_request`, so this module
#: never learns the pipeline's argument list — the caller has already bound it.
ChatDispatch = Callable[[], Awaitable[dict[str, Any]]]

#: The canonical execution lease TTL every chat Attempt carries (#1170). One
#: number on purpose: the schedule consumer already runs on `timedelta(seconds=30)`
#: (`consumption.DEFAULT_SCHEDULE_LEASE_TTL`), and two entry points recovering at
#: different speeds would mean a crash is an outage on one and a blip on the
#: other. A chat turn is never the work the TTL cuts off — while this process
#: lives, the heartbeat renews at TTL/3 and a slow answer finishes (AC-8); the
#: TTL only starts counting when the process can no longer say it is alive,
#: which is the one situation ADR-082526-b36a exists for. A deployment that
#: runs `Container.recover_abandoned_attempts` on its tick — the collector the
#: same ADR names — gets reclaiming chat Attempts with no further wiring.
DEFAULT_CHAT_LEASE_TTL = timedelta(seconds=30)


class ChatDispatchUnrecorded(RunIntegrityError):
    """The turn was answered, and the spine could not record that it was (#1108).

    Raised in place of the underlying `RunIntegrityError` whenever that error
    surfaced *after* the dispatch was awaited: the Attempt's COMPLETED write,
    or the NodeRun/Run reconciliation that follows it. It carries the answer
    so the caller can return it without a second dispatch — the model already
    did the work, and the durable record is a recovery matter, not a reason
    to do the work twice. The original store failure is the `__cause__`.
    """

    def __init__(self, run_id: str, *, response: dict[str, Any]) -> None:
        self.run_id = run_id
        self.response = response
        super().__init__(
            f"chat Run {run_id!r} was answered but its Attempt could not be recorded; "
            "the answer must not be dispatched again"
        )


class _TurnDispatch:
    """One dispatch, and what became of it.

    Read back by `execute` when the spine fails around it: whether the model
    was reached at all, what it answered, or what it raised — the three facts
    that decide whether the failure is safe to retry.
    """

    def __init__(self, dispatch: ChatDispatch) -> None:
        self._dispatch = dispatch
        self.started = False
        self.response: dict[str, Any] | None = None
        self.error: BaseException | None = None

    async def run(self, _work_item: Any, _context: Any) -> dict[str, Any]:
        self.started = True
        try:
            response = await self._dispatch()
        except BaseException as exc:
            self.error = exc
            raise
        self.response = response
        return attempt_result(response)


def attempt_result(response: dict[str, Any]) -> dict[str, Any]:
    """The JSON-safe evidence one chat turn leaves on its Attempt.

    `chat_turn_outcome` decides the size, for the reason given in the module
    docstring. The agent is added because it is the one thing about a chat turn
    the logical record cannot say — admission ran before it was chosen.
    """
    evidence = chat_turn_outcome(response)
    agent = response.get(_CONDUIT_AGENT_KEY)
    if isinstance(agent, str) and agent:
        evidence[ATTEMPT_AGENT_KEY] = agent
    return evidence


class ChatAttemptExecutor:
    """Run one chat turn as an Attempt under its Run's single NodeRun.

    Holds no per-turn state: the NodeRun to retry under is read from the store
    each time, so two workers and a restarted process reach the same answer.
    Shaped after `TaskAttemptExecutor` deliberately — the two entry points have
    the same spine and should not grow two different ideas of how to use it.

    Every Attempt is created leased (`DEFAULT_CHAT_LEASE_TTL`) and its lease is
    renewed from this process while the turn runs, so a worker that dies
    mid-turn leaves a RUNNING Attempt the canonical sweep can reclaim instead
    of one nothing will ever inspect again (#1170). `lease_ttl=None` opts out
    and is exactly the pre-#1170 behaviour ADR-082526-b36a shipped as the
    default for every caller; chat opts in at the constructor rather than at
    each wiring site so a future caller cannot quietly reintroduce the
    un-leaseable Attempt by forgetting the argument. A non-positive TTL is
    refused by `AttemptExecutionService` at construction, before any NodeRun
    exists to orphan.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        runtime: ExecutionRuntime | None = None,
        timeout_s: float | None = None,
        lease_ttl: timedelta | None = DEFAULT_CHAT_LEASE_TTL,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            # Rejected here rather than by `AttemptExecutionService`, which
            # would only see it after the NodeRun exists — leaving a created
            # NodeRun with no Attempt under it: an execution record that is
            # incomplete rather than absent.
            raise ValueError("timeout_s must be > 0")
        self._runs = run_store
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
            lease_ttl=lease_ttl,
        )
        # Explicitly None. A chat turn carries no deadline of its own, and
        # inventing a global one here would start cutting off long answers that
        # have always been allowed to finish — a behaviour change dressed as
        # plumbing. Giving chat a real deadline is #43's.
        self._timeout_s = timeout_s
        # Unlike `timeout_s`, the lease defaults to something real. An expiring
        # lease never cuts work off — it only makes the Attempt *reclaimable*
        # once nothing renews it — so the old None default would have kept chat
        # outside the recovery contract this executor exists to join.
        self._lease_ttl = lease_ttl

    async def execute(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        dispatch: ChatDispatch,
    ) -> dict[str, Any]:
        """Route one turn, leaving a NodeRun and an Attempt behind.

        Returns the Conduit's response unchanged. Re-raises whatever the
        dispatch raised, after the Attempt has recorded the failure — and still
        re-raises it when recording the failure failed as well, because the
        dispatch's own exception is the one the endpoint maps to a status code.

        A `RunIntegrityError` from the spine is re-raised as
        `ChatDispatchUnrecorded` when it surfaced after the dispatch was
        awaited (#1108), so a caller can tell a turn that never reached the
        model from one whose answer exists and merely went unrecorded — and
        never asks the model again for the latter. Before the dispatch it is
        re-raised as it is: nothing physical happened, and the caller's own
        rule for that case still applies.
        """
        node_id = await self._node_id(run_id)
        existing = await self._node_run_for(run_id, node_id)
        turn = _TurnDispatch(dispatch)

        # The work item is the turn itself. Bounded by the same rule the
        # Attempt's result is: the messages are what the turn *was*, and the
        # Run's node already carries the description, so this records the shape
        # of the request rather than a second transcript of it.
        work_item = {"messages": len(messages)}
        context = {"run_id": run_id, "node_id": node_id}
        try:
            if existing is None:
                await self._service.execute_node(
                    run_id,
                    node_id,
                    work_item,
                    context,
                    executor=turn.run,
                    executor_id=CHAT_EXECUTOR_ID,
                    timeout_s=self._timeout_s,
                )
            else:
                # A re-run of the same turn is a second Attempt under the same
                # logical NodeRun, not a second NodeRun. Creating another
                # NodeRun would say the Run grew a node, which is false: the
                # Graph has one, and it was tried twice.
                await self._service.retry_node(
                    existing.node_run_id,
                    work_item,
                    context,
                    executor=turn.run,
                    executor_id=CHAT_EXECUTOR_ID,
                    timeout_s=self._timeout_s,
                )
        except RunIntegrityError as exc:
            if not turn.started:
                raise
            if turn.error is not None:
                # The dispatch failed and then the spine could not record that
                # it did. The failure the caller can act on is the dispatch's;
                # the store's is chained behind it.
                raise turn.error from exc
            if turn.response is None:  # pragma: no cover - a dispatch returns or raises
                raise
            raise ChatDispatchUnrecorded(run_id, response=turn.response) from exc
        if turn.response is None:  # pragma: no cover - unreachable: run always fills it
            raise RunIntegrityError("chat Attempt completed without capturing its response")
        return turn.response

    async def _node_id(self, run_id: str) -> str:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"Run {run_id!r} does not exist")
        nodes = run.graph.materialize().nodes
        if len(nodes) != 1:
            raise RunIntegrityError(
                f"chat Run {run_id!r} has {len(nodes)} Graph nodes; a turn admits exactly one"
            )
        return nodes[0].node_id

    async def _node_run_for(self, run_id: str, node_id: str) -> NodeRun | None:
        node_runs = [nr for nr in await self._runs.list_node_runs(run_id) if nr.node_id == node_id]
        return node_runs[-1] if node_runs else None


__all__ = [
    "ATTEMPT_AGENT_KEY",
    "CHAT_EXECUTOR_ID",
    "DEFAULT_CHAT_LEASE_TTL",
    "ChatAttemptExecutor",
    "ChatDispatch",
    "ChatDispatchUnrecorded",
    "attempt_result",
]
