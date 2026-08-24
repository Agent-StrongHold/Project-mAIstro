"""A chat turn is a physical Attempt under its Run's NodeRun (#223).

The chat half of what #143 proved for tasks. Before this, `Container.route_request`
admitted a Run over a one-node Graph and then dispatched straight to the agent —
so the node had no NodeRun, nothing recorded that a try started or how long it
took, and `GET /v1/runs/{run_id}/node-runs` was correct and always empty.

These go through `create_container()` rather than constructing the executor
directly, because the wiring is what is being checked: an adapter nothing calls
proves nothing about whether a turn reaches the spine.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.runs.chat_execution import (
    ATTEMPT_AGENT_KEY,
    CHAT_EXECUTOR_ID,
    ChatAttemptExecutor,
    attempt_result,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES, AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

MESSAGES = [{"role": "user", "content": "hi"}]


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


class _Conduit:
    """Stands in for the real Conduit, which needs agents this test has not.

    Returns the OpenAI-shaped dict `route_request` returns, including the
    `agent` key it now sets — this is the seam's whole input.
    """

    def __init__(
        self,
        *,
        content: str = "the answer",
        finish_reason: str = "stop",
        agent: str | None = "general",
        raises: Exception | None = None,
    ) -> None:
        self.calls = 0
        self._raises = raises
        self._response: dict[str, Any] = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ]
        }
        if agent is not None:
            self._response["agent"] = agent

    async def route_request(self, messages: list[dict[str, Any]], **_kw: Any) -> dict[str, Any]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return dict(self._response)


async def _spine(container: Container, run_id: str) -> tuple[Any, list[Any]]:
    """The NodeRun and its Attempts for a Run's single node."""
    node_runs = await container.run_store.list_node_runs(run_id)
    assert len(node_runs) == 1, f"expected one NodeRun, got {len(node_runs)}"
    return node_runs[0], await container.run_store.list_attempts(node_runs[0].node_run_id)


class TestATurnLeavesAPhysicalRecord:
    async def test_a_turn_produces_one_node_run_and_one_attempt(self) -> None:
        """The gap this closes, stated directly."""
        container = await _container()
        container.conduit = _Conduit()

        result = await container.route_request(MESSAGES)

        node_run, attempts = await _spine(container, result["run_id"])
        assert node_run.status is RunStatus.COMPLETED
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.COMPLETED

    async def test_the_attempt_names_the_executor(self) -> None:
        """`executor_id` answers "what kind of work was this" on a record that
        otherwise only knows it ran — the same job `TASK_EXECUTOR_ID` does."""
        container = await _container()
        container.conduit = _Conduit()

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        assert attempts[0].executor_id == CHAT_EXECUTOR_ID

    async def test_the_attempt_names_the_agent_that_ran(self) -> None:
        """The one thing about a chat turn the logical record cannot say:
        admission happens before the agent is chosen, so the Run's own
        `agent_selection` says `deferred` and always will."""
        container = await _container()
        container.conduit = _Conduit(agent="researcher")

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        assert attempts[0].result[ATTEMPT_AGENT_KEY] == "researcher"

    async def test_the_turns_answer_is_unchanged_by_the_recording(self) -> None:
        """The seam is a recorder, not a filter. A caller sees what the Conduit
        returned, `run_id` aside."""
        container = await _container()
        container.conduit = _Conduit(content="42")

        result = await container.route_request(MESSAGES)

        assert result["choices"][0]["message"]["content"] == "42"


class TestARefusalIsACompletion:
    """A Gate block, a Sentinel block or an empty roster is the system doing
    exactly what it should. Recording a FAILED Attempt would put refusals in
    the bucket a provider outage lands in, and make every refused turn look
    like an incident on a dashboard that counts them."""

    async def test_a_content_filtered_turn_completes_its_attempt(self) -> None:
        container = await _container()
        container.conduit = _Conduit(
            content="Request blocked: prompt injection", finish_reason="content_filter"
        )

        result = await container.route_request(MESSAGES)

        node_run, attempts = await _spine(container, result["run_id"])
        assert attempts[0].status is AttemptStatus.COMPLETED
        assert node_run.status is RunStatus.COMPLETED

    async def test_the_refusal_is_on_the_attempts_record(self) -> None:
        """What was refused, and that it was a refusal — the Attempt reuses
        `chat_turn_outcome`, so it keeps the same bounded answer the Run does."""
        container = await _container()
        container.conduit = _Conduit(
            content="Request blocked: prompt injection", finish_reason="content_filter"
        )

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        assert attempts[0].result["finish_reason"] == "content_filter"
        assert "prompt injection" in attempts[0].result["answer"]

    async def test_an_empty_roster_completes_rather_than_failing(self) -> None:
        """`No agents available.` is a misconfiguration, not a crash — and the
        Conduit answers it rather than raising. The Attempt must agree."""
        container = await _container()
        container.conduit = _Conduit(content="No agents available.", agent=None)

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        assert attempts[0].status is AttemptStatus.COMPLETED
        assert ATTEMPT_AGENT_KEY not in attempts[0].result


class TestAFailureIsRecordedAndKeepsTravelling:
    async def test_a_raising_dispatch_fails_the_attempt(self) -> None:
        container = await _container()
        container.conduit = _Conduit(raises=RuntimeError("upstream exploded"))

        with pytest.raises(RuntimeError, match="upstream exploded"):
            await container.route_request(MESSAGES)

        runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
        _, attempts = await _spine(container, runs[0].run_id)
        assert attempts[0].status is AttemptStatus.FAILED

    async def test_the_run_still_reaches_a_terminal_state(self) -> None:
        """The half that broke when execution moved onto the spine.

        A failed Attempt parks its NodeRun, and a Run with no other active node
        parks too — and WAITING has no edge to FAILED. Without resuming first,
        every failed chat turn would have been left WAITING, which is exactly
        the "a process died here" signal terminalization exists to prevent.
        """
        container = await _container()
        container.conduit = _Conduit(raises=RuntimeError("upstream exploded"))

        with pytest.raises(RuntimeError):
            await container.route_request(MESSAGES)

        runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
        assert runs[0].status is RunStatus.FAILED
        assert runs[0].status in TERMINAL_RUN_STATUSES

    async def test_the_exception_reaches_the_caller_intact(self) -> None:
        """The endpoint above maps the exception *type* to 502 or 504. An
        adapter that swallowed it into a return value would cost the status
        code a client branches on."""
        container = await _container()
        container.conduit = _Conduit(raises=TimeoutError("deadline"))

        with pytest.raises(TimeoutError):
            await container.route_request(MESSAGES)


class TestATurnIsNeverRefusedForWantOfARecord:
    async def test_a_turn_with_no_run_is_still_answered(self) -> None:
        """The existing rule, unchanged. Without a chat admitter there is no
        Run to hang a NodeRun on — and the chat path has no receipt to fall
        back on, so refusing would turn "cannot record" into "cannot answer"."""
        container = await _container()
        conduit = _Conduit(content="42")
        container.conduit = conduit
        container.chat_admitter = None  # type: ignore[assignment]

        result = await container.route_request(MESSAGES)

        assert result["choices"][0]["message"]["content"] == "42"
        assert conduit.calls == 1

    async def test_a_broken_spine_is_not_a_broken_turn(self) -> None:
        """Same rule one layer down. `RunIntegrityError` means this process
        could not write the spine — a Run deleted underneath the turn, or a
        Graph that is not the one node a turn admits. The answer still goes
        out; it is the record that is missing, and it was missing before."""
        container = await _container()
        conduit = _Conduit(content="42")
        container.conduit = conduit

        async def _vanished(_run_id: str) -> None:
            return None

        container.run_store.get_run = _vanished  # type: ignore[method-assign]

        result = await container.route_request(MESSAGES)

        assert result["choices"][0]["message"]["content"] == "42"
        assert conduit.calls == 1


class TestARetryIsASecondAttemptNotASecondNodeRun:
    """The Graph has one node. A retry is a second Attempt under the same
    logical NodeRun — creating another NodeRun would say the Run grew a node,
    which is false: it was tried twice.

    The retry follows a *failed* Attempt, because that is the only shape a
    retry has. A completed Attempt terminalizes its NodeRun and the spine
    correctly refuses to run another under it; a failed one parks the NodeRun
    WAITING, which is what "retryable" means here.

    Driven through the executor directly rather than through `route_request`,
    which terminalizes the Run on the way out — a chat turn is over when it is
    answered. This is the seam's behaviour for a caller retrying while the Run
    is still open, which is what #42's chronology criterion is about.
    """

    @staticmethod
    async def _open_run(container: Container) -> str:
        run = await container.chat_admitter.admit(MESSAGES)
        await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
        await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        return run.run_id

    @staticmethod
    def _dispatching(conduit: _Conduit) -> Any:
        async def _dispatch() -> dict[str, Any]:
            return await conduit.route_request(MESSAGES)

        return _dispatch

    async def _failed_then_succeeded(self, container: Container) -> str:
        run_id = await self._open_run(container)
        executor = ChatAttemptExecutor(container.run_store)
        with pytest.raises(RuntimeError):
            await executor.execute(
                run_id, MESSAGES, self._dispatching(_Conduit(raises=RuntimeError("boom")))
            )
        await executor.execute(run_id, MESSAGES, self._dispatching(_Conduit()))
        return run_id

    async def test_a_retry_keeps_one_node_run(self) -> None:
        container = await _container()

        run_id = await self._failed_then_succeeded(container)

        node_run, attempts = await _spine(container, run_id)
        assert len(attempts) == 2
        assert all(a.node_run_id == node_run.node_run_id for a in attempts)

    async def test_the_retry_does_not_rewrite_the_failure(self) -> None:
        """`retry creates a new chronological Attempt rather than rewriting
        history` — #42's second acceptance criterion, on this path. The failed
        Attempt is still there, still failed, still first."""
        container = await _container()

        run_id = await self._failed_then_succeeded(container)

        _, attempts = await _spine(container, run_id)
        assert [a.ordinal for a in attempts] == [1, 2]
        assert attempts[0].status is AttemptStatus.FAILED
        assert attempts[1].status is AttemptStatus.COMPLETED
        assert attempts[0].created_at <= attempts[1].created_at


class TestTheAttemptResult:
    def test_it_reuses_the_runs_own_bound(self) -> None:
        """A chat Run is an audit record and the transcript lives in
        `maistro.sessions` (ADR-082326-c126). The physical record of a turn
        must not be able to hold more of the conversation than the logical
        one, so the Attempt takes `chat_turn_outcome`'s answer verbatim rather
        than keeping a second, larger copy."""
        long_answer = "x" * 10_000
        response = {
            "choices": [{"message": {"content": long_answer}, "finish_reason": "stop"}],
            "agent": "general",
        }

        evidence = attempt_result(response)

        assert evidence["answer_truncated"] is True
        assert len(evidence["answer"]) < len(long_answer)

    def test_a_blank_agent_is_omitted_rather_than_recorded(self) -> None:
        """An empty name would read as an agent that ran and had no name,
        which is a different claim from "no agent ran"."""
        response = {"choices": [{"message": {"content": "hi"}}], "agent": ""}

        assert ATTEMPT_AGENT_KEY not in attempt_result(response)

    def test_a_non_string_agent_is_omitted(self) -> None:
        """The key comes from a dict an agent may have produced itself, so its
        type is not guaranteed. A record is not the place to find that out."""
        response = {"choices": [{"message": {"content": "hi"}}], "agent": 7}

        assert ATTEMPT_AGENT_KEY not in attempt_result(response)


class TestTheKeysAgree:
    def test_the_conduit_and_the_recorder_spell_the_agent_the_same(self) -> None:
        """`runs` cannot import `conduit` — `conduit` already imports `runs`,
        and the reverse edge would close a cycle — so the key is written twice.
        This is what keeps the two copies from drifting apart silently, which
        would show up as every Attempt losing its agent and nothing failing."""
        from maistro.conduit import DISPATCHED_AGENT_KEY

        assert DISPATCHED_AGENT_KEY == ATTEMPT_AGENT_KEY


class TestConstruction:
    def test_a_non_positive_timeout_is_refused_before_anything_exists(self) -> None:
        """Rejected here rather than by `AttemptExecutionService`, which would
        only see it after the NodeRun exists — leaving a created NodeRun with
        no Attempt under it: a record that is incomplete rather than absent."""
        container_store = None
        with pytest.raises(ValueError, match="timeout_s must be > 0"):
            ChatAttemptExecutor(container_store, timeout_s=0)  # type: ignore[arg-type]


class TestInAgentDelegationCreatesNoNodeRun:
    """ADR-082426-6201's first decision, proven where it is actually visible.

    The other delegation tests drive `Agent.handle` directly, so they can show
    the chain is built but not that the spine stayed one node deep — an agent
    on its own has no RunStore to leave a NodeRun in. This drives a *real*
    delegating agent through the chat seam, which is the only place both facts
    are observable at once.
    """

    @staticmethod
    def _delegating_conduit() -> Any:
        """A Conduit stand-in that really delegates, rather than describing it.

        `_Conduit` returns a canned dict; that would prove nothing here,
        because the claim is about what the agent layer does underneath.
        """
        from maistro.agents.base import Agent
        from maistro.agents.strategies.delegate import DelegateStrategy
        from maistro.conduit import DISPATCHED_AGENT_KEY
        from maistro.types.agent import AgentIdentity, ReasoningResult

        class _Warden:
            async def scan(self, _text: str, _surface: str) -> Any:
                return type("V", (), {"clean": True, "flags": ()})()

        class _Context:
            async def build(
                self, messages: list[dict[str, Any]], _identity: Any, **_kw: Any
            ) -> tuple[list[dict[str, Any]], list[int]]:
                return messages, []

        class _Prompts:
            async def get(self, _name: str) -> str:
                return ""

        class _Leaf:
            async def reason(
                self, _messages: Any, _model: Any, _llm: Any, **_kw: Any
            ) -> ReasoningResult:
                return ReasoningResult(response="delegated answer", done=True)

        def _agent(name: str, strategy: Any, resolver: Any = None) -> Agent:
            return Agent(
                identity=AgentIdentity(name=name, model="test-model"),
                strategy=strategy,
                llm=object(),
                context_builder=_Context(),
                prompt_manager=_Prompts(),
                warden=_Warden(),
                agent_resolver=resolver,
            )

        registry: dict[str, Agent] = {"mason": _agent("mason", _Leaf())}
        coordinator = _agent(
            "coordinator",
            DelegateStrategy(routing_table={"code": "mason"}, default_agent="mason"),
            registry.get,
        )

        class _DelegatingConduit:
            def __init__(self) -> None:
                self.answer: Any = None

            async def route_request(
                self, messages: list[dict[str, Any]], **_kw: Any
            ) -> dict[str, Any]:
                auth = type("A", (), {"user_id": "u1", "org_id": "", "team_id": ""})()
                self.answer = await coordinator.handle(
                    messages=messages, auth=auth, classified_task_type="code"
                )
                return {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": self.answer.content},
                            "finish_reason": "stop",
                        }
                    ],
                    DISPATCHED_AGENT_KEY: self.answer.agent_name,
                }

        return _DelegatingConduit()

    @pytest.mark.ac("ADR-082426-6201/AC-1")
    async def test_a_delegated_turn_still_leaves_exactly_one_node_run(self) -> None:
        """The decision, stated as a count. A delegate is chosen by a strategy
        at runtime from data the Graph never saw, so it is not a Node in the
        Graph and gets no NodeRun — the Run's shape stays the Graph's shape
        however many agents the turn passed through.
        """
        container = await _container()
        conduit = self._delegating_conduit()
        container.conduit = conduit

        result = await container.route_request(MESSAGES)

        assert conduit.answer.delegation_chain == ("coordinator",), (
            "the turn must really have delegated, or this proves nothing"
        )
        node_run, attempts = await _spine(container, result["run_id"])
        assert node_run.status is RunStatus.COMPLETED
        assert len(attempts) == 1

    @pytest.mark.ac("ADR-082426-6201/AC-2")
    async def test_the_attempt_names_the_agent_that_answered(self) -> None:
        """The delegate, not the delegator: the Attempt records what ran. Who
        was *asked* is `delegation_chain`'s job (AC-3), which is the split the
        decision makes — one record each, neither guessing at the other's."""
        container = await _container()
        container.conduit = self._delegating_conduit()

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        assert attempts[0].result[ATTEMPT_AGENT_KEY] == "mason"
