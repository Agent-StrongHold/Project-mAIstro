"""Tests for Agent.handle()'s pipeline: warden -> session history -> context ->
strategy -> delegation -> RCA/learning extraction -> persistence -> tracing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from maistro.agents.base import Agent, _build_tool_schema, _extract_user_text
from maistro.sessions.store import InMemorySessionStore
from maistro.types.agent import AgentIdentity, AgentResponse, ReasoningResult


@dataclass
class _Verdict:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _FakeWarden:
    def __init__(self, *, clean: bool = True, flags: tuple[str, ...] = ()) -> None:
        self._clean = clean
        self._flags = flags
        self.scanned: list[str] = []

    async def scan(self, text: str, _surface: str) -> _Verdict:
        self.scanned.append(text)
        return _Verdict(clean=self._clean, flags=self._flags)


class _FakeContextBuilder:
    def __init__(self, learning_ids: list[int] | None = None) -> None:
        self._learning_ids = learning_ids or []
        self.calls: list[dict[str, Any]] = []

    async def build(
        self, messages: list[dict[str, Any]], _identity: Any, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        self.calls.append(kwargs)
        return messages, self._learning_ids


class _FakePromptManager:
    async def get(self, _name: str) -> str:
        return ""


class _RecordingStrategy:
    def __init__(
        self, result: ReasoningResult | None = None, *, raises: Exception | None = None
    ) -> None:
        self._result = result or ReasoningResult(response="ok", done=True)
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        self.calls.append({"messages": messages, "model": model, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self._result


class _FakeSessionStore:
    def __init__(self, history: list[dict[str, str]] | None = None) -> None:
        self._history = history or []
        self.appended: list[tuple[str, list[dict[str, str]]]] = []
        self.turn_ids: list[str | None] = []

    async def get_history(self, _session_id: str) -> list[dict[str, str]]:
        return self._history

    async def append_messages(
        self, session_id: str, messages: list[dict[str, str]], turn_id: str | None = None
    ) -> None:
        self.appended.append((session_id, messages))
        self.turn_ids.append(turn_id)


class _FakeOutcomeStore:
    def __init__(self) -> None:
        self.recorded: list[Any] = []

    async def record(self, outcome: Any) -> None:
        self.recorded.append(outcome)


@dataclass
class _LearningRecord:
    learning: str = "x"
    agent_id: str = ""
    org_id: str = ""
    team_id: str = ""


class _FakeLearningStore:
    def __init__(self) -> None:
        self.stored: list[Any] = []
        self.marked: list[tuple[list[int], bool, str]] = []

    async def store(self, learning: Any) -> None:
        self.stored.append(learning)

    async def mark_outcome(self, ids: list[int], *, success: bool, org_id: str) -> None:
        self.marked.append((ids, success, org_id))


class _FakeLearningExtractor:
    def __init__(
        self,
        corrections: list[Any] | None = None,
        positives: list[Any] | None = None,
    ) -> None:
        self._corrections = corrections or []
        self._positives = positives or []

    def extract_corrections(self, _user_text: str, _tool_history: Any) -> list[Any]:
        return list(self._corrections)

    def extract_positive_patterns(self, _user_text: str, _tool_history: Any) -> list[Any]:
        return list(self._positives)


class _FakeRcaExtractor:
    def __init__(self, rca: Any = None) -> None:
        self._rca = rca

    async def extract_rca(self, _user_text: str, _tool_history: Any) -> Any:
        return self._rca


class _FakeLearningPromoter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def check_and_promote(self, *, org_id: str) -> None:
        self.calls.append(org_id)


class _FakeCoinLedger:
    def __init__(self, charge_info: dict[str, Any] | None = None) -> None:
        self._charge_info = charge_info or {"charged_microchips": 5, "pricing_version": "v1"}
        self.calls: list[dict[str, Any]] = []

    async def charge_usage(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self._charge_info


@dataclass
class _FakeSpan:
    inputs: list[Any] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)

    def __enter__(self) -> _FakeSpan:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_input(self, data: Any) -> _FakeSpan:
        self.inputs.append(data)
        return self

    def set_output(self, data: Any) -> _FakeSpan:
        self.outputs.append(data)
        return self


class _FakeTrace:
    def __init__(self) -> None:
        self.spans: dict[str, _FakeSpan] = {}
        self.scored: list[tuple[str, float, str]] = []
        self.updates: list[dict[str, Any]] = []
        self.ended = False

    def span(self, name: str) -> _FakeSpan:
        span = _FakeSpan()
        self.spans[name] = span
        return span

    def score(self, name: str, value: float, comment: str = "") -> None:
        self.scored.append((name, value, comment))

    def update(self, data: dict[str, Any]) -> None:
        self.updates.append(data)

    def end(self) -> None:
        self.ended = True


class _FakeTracer:
    def __init__(self) -> None:
        self.traces: list[_FakeTrace] = []

    def create_trace(self, **_kwargs: Any) -> _FakeTrace:
        trace = _FakeTrace()
        self.traces.append(trace)
        return trace


class _Auth:
    user_id = "u1"
    org_id = "org-1"
    team_id = "team-1"


def _identity(**overrides: Any) -> AgentIdentity:
    return AgentIdentity(name="tester", model="test-model", **overrides)


def _make_agent(
    strategy: Any,
    *,
    identity: AgentIdentity | None = None,
    warden: Any = None,
    context_builder: Any = None,
    session_store: Any = None,
    outcome_store: Any = None,
    learning_store: Any = None,
    learning_extractor: Any = None,
    rca_extractor: Any = None,
    learning_promoter: Any = None,
    coin_ledger: Any = None,
    tracer: Any = None,
    tool_registry: Any = None,
    agent_resolver: Any = None,
) -> Agent:
    return Agent(
        identity=identity or _identity(),
        strategy=strategy,
        llm=object(),
        context_builder=context_builder or _FakeContextBuilder(),
        prompt_manager=_FakePromptManager(),
        warden=warden or _FakeWarden(),
        session_store=session_store,
        outcome_store=outcome_store,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        rca_extractor=rca_extractor,
        learning_promoter=learning_promoter,
        coin_ledger=coin_ledger,
        tracer=tracer,
        tool_registry=tool_registry,
        agent_resolver=agent_resolver,
    )


class TestExtractUserText:
    def test_string_content(self) -> None:
        assert _extract_user_text([{"role": "user", "content": "hello"}]) == "hello"

    def test_content_block_list(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part one"},
                    {"type": "image", "url": "x"},
                    {"type": "text", "text": "part two"},
                ],
            }
        ]
        assert _extract_user_text(messages) == "part one part two"

    def test_no_user_message_returns_empty(self) -> None:
        assert _extract_user_text([{"role": "assistant", "content": "hi"}]) == ""

    def test_unrecognized_content_type_returns_empty(self) -> None:
        assert _extract_user_text([{"role": "user", "content": 42}]) == ""

    def test_picks_latest_user_message(self) -> None:
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert _extract_user_text(messages) == "second"


class TestBuildToolSchema:
    def test_known_builtin_tool(self) -> None:
        schema = _build_tool_schema("read_file")
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"

    def test_unknown_tool_gets_generic_schema(self) -> None:
        schema = _build_tool_schema("mystery_tool")
        assert schema["function"]["description"] == "Run mystery_tool"
        assert schema["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_registry_takes_precedence(self) -> None:
        @dataclass
        class _Defn:
            name: str
            description: str
            parameters: dict[str, Any]

        class _Registry:
            def get(self, name: str) -> Any:
                return _Defn(name=name, description="custom", parameters={"type": "object"})

        schema = _build_tool_schema("read_file", registry=_Registry())
        assert schema["function"]["description"] == "custom"

    def test_registry_miss_falls_back_to_builtin(self) -> None:
        class _EmptyRegistry:
            def get(self, _name: str) -> Any:
                return None

        schema = _build_tool_schema("read_file", registry=_EmptyRegistry())
        assert schema["function"]["description"].startswith("Read the contents")


class TestHandleWardenGate:
    async def test_warden_blocks_returns_blocked_response_without_running_strategy(self) -> None:
        strategy = _RecordingStrategy()
        warden = _FakeWarden(clean=False, flags=("prompt_injection",))
        agent = _make_agent(strategy, warden=warden)

        result = await agent.handle(
            messages=[{"role": "user", "content": "bad input"}],
            auth=_Auth(),
        )

        assert result.blocked is True
        assert "prompt_injection" in result.block_reason
        assert strategy.calls == []

    async def test_warden_blocks_ends_trace_with_score(self) -> None:
        tracer = _FakeTracer()
        warden = _FakeWarden(clean=False, flags=("exfil",))
        agent = _make_agent(_RecordingStrategy(), warden=warden, tracer=tracer)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        trace = tracer.traces[0]
        assert trace.ended is True
        assert trace.scored[0][0] == "blocked"

    async def test_warden_clean_proceeds_to_strategy(self) -> None:
        strategy = _RecordingStrategy(ReasoningResult(response="hi", done=True))
        agent = _make_agent(strategy)

        result = await agent.handle(messages=[{"role": "user", "content": "ok"}], auth=_Auth())

        assert result.content == "hi"
        assert len(strategy.calls) == 1


class TestHandleSessionHistory:
    async def test_no_session_id_skips_history_injection(self) -> None:
        strategy = _RecordingStrategy()
        session_store = _FakeSessionStore(history=[{"role": "user", "content": "old"}])
        agent = _make_agent(strategy, session_store=session_store)

        await agent.handle(messages=[{"role": "user", "content": "new"}], auth=_Auth())

        assert strategy.calls[0]["messages"] == [{"role": "user", "content": "new"}]

    async def test_history_prepended_after_leading_system_message(self) -> None:
        strategy = _RecordingStrategy()
        session_store = _FakeSessionStore(history=[{"role": "user", "content": "old"}])
        agent = _make_agent(strategy, session_store=session_store)

        await agent.handle(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "new"},
            ],
            auth=_Auth(),
            session_id="s1",
        )

        assert strategy.calls[0]["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "user", "content": "new"},
        ]

    async def test_history_prepended_without_system_message(self) -> None:
        strategy = _RecordingStrategy()
        session_store = _FakeSessionStore(history=[{"role": "user", "content": "old"}])
        agent = _make_agent(strategy, session_store=session_store)

        await agent.handle(
            messages=[{"role": "user", "content": "new"}],
            auth=_Auth(),
            session_id="s1",
        )

        assert strategy.calls[0]["messages"] == [
            {"role": "user", "content": "old"},
            {"role": "user", "content": "new"},
        ]

    async def test_empty_history_returns_messages_unchanged(self) -> None:
        strategy = _RecordingStrategy()
        session_store = _FakeSessionStore(history=[])
        agent = _make_agent(strategy, session_store=session_store)

        await agent.handle(
            messages=[{"role": "user", "content": "new"}], auth=_Auth(), session_id="s1"
        )

        assert strategy.calls[0]["messages"] == [{"role": "user", "content": "new"}]


class TestHandleTracingSpans:
    async def test_traced_run_sets_spans_for_warden_context_and_strategy(self) -> None:
        tracer = _FakeTracer()
        agent = _make_agent(_RecordingStrategy(ReasoningResult(response="hi")), tracer=tracer)

        await agent.handle(messages=[{"role": "user", "content": "hi"}], auth=_Auth())

        trace = tracer.traces[0]
        assert "warden.user_input" in trace.spans
        assert "prompt.build" in trace.spans
        assert "strategy.reason" in trace.spans
        assert trace.ended is True

    async def test_traced_run_finalizes_with_tool_call_counts(self) -> None:
        tracer = _FakeTracer()
        result = ReasoningResult(
            response="done",
            tool_history=[
                {"tool_name": "read_file", "result": "ok"},
                {"tool_name": "write_file", "result": "Error: failed"},
            ],
        )
        agent = _make_agent(_RecordingStrategy(result), tracer=tracer)

        await agent.handle(messages=[{"role": "user", "content": "hi"}], auth=_Auth())

        trace = tracer.traces[0]
        update = trace.updates[-1]
        assert update["tool_calls_total"] == "2"
        assert update["tool_calls_success"] == "1"
        assert update["tool_calls_failed"] == "1"
        assert update["tools_used"] == "read_file,write_file"


class TestBuildStrategyKwargs:
    async def test_sentinel_status_callback_and_task_type_all_threaded(self) -> None:
        strategy = _RecordingStrategy()

        class _FakeSentinel:
            pass

        sentinel = _FakeSentinel()
        agent = Agent(
            identity=_identity(),
            strategy=strategy,
            llm=object(),
            context_builder=_FakeContextBuilder(),
            prompt_manager=_FakePromptManager(),
            warden=_FakeWarden(),
            sentinel=sentinel,
        )

        def status_callback(_msg: str) -> None:
            return None

        await agent.handle(
            messages=[{"role": "user", "content": "x"}],
            auth=_Auth(),
            status_callback=status_callback,
            classified_task_type="code",
        )

        call = strategy.calls[0]
        assert call["sentinel"] is sentinel
        assert call["status_callback"] is status_callback
        assert call["classified_task_type"] == "code"


class TestHandleToolDefs:
    async def test_tools_attached_when_identity_declares_them(self) -> None:
        strategy = _RecordingStrategy()
        identity = _identity(tools=("read_file",))
        agent = _make_agent(strategy, identity=identity)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert strategy.calls[0]["tools"][0]["function"]["name"] == "read_file"

    async def test_no_tools_declared_means_tools_kwarg_is_none(self) -> None:
        strategy = _RecordingStrategy()
        agent = _make_agent(strategy)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert strategy.calls[0]["tools"] is None


class TestHandleStrategyFailure:
    async def test_value_error_in_strategy_returns_generic_error_response(self) -> None:
        strategy = _RecordingStrategy(raises=ValueError("boom"))
        agent = _make_agent(strategy)

        result = await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert "internal error" in result.content

    async def test_strategy_failure_with_trace_scores_and_ends(self) -> None:
        tracer = _FakeTracer()
        strategy = _RecordingStrategy(raises=RuntimeError("boom"))
        agent = _make_agent(strategy, tracer=tracer)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        trace = tracer.traces[0]
        assert trace.scored[-1][0] == "strategy_error"
        assert trace.ended is True


class TestHandleDelegation:
    async def test_delegation_depth_limit_returns_abort_message(self) -> None:
        result = ReasoningResult(response=None, done=False, delegate_to="loopback")
        strategy = _RecordingStrategy(result)
        registry: dict[str, Agent] = {}
        agent = _make_agent(strategy, agent_resolver=registry.get)
        registry["coordinator"] = agent

        response = await agent.handle(
            messages=[{"role": "user", "content": "x"}],
            auth=_Auth(),
            _delegation_depth=5,
        )

        assert "too deep" in response.content

    async def test_delegation_depth_limit_with_trace_scores_and_ends(self) -> None:
        tracer = _FakeTracer()
        result = ReasoningResult(response=None, done=False, delegate_to="loopback")
        strategy = _RecordingStrategy(result)
        agent = _make_agent(strategy, tracer=tracer, agent_resolver={}.get)

        await agent.handle(
            messages=[{"role": "user", "content": "x"}],
            auth=_Auth(),
            _delegation_depth=5,
        )

        trace = tracer.traces[0]
        assert trace.scored[-1][0] == "delegation_depth_exceeded"
        assert trace.ended is True

    async def test_unresolvable_target_falls_through_to_normal_response(self) -> None:
        result = ReasoningResult(response=None, done=False, delegate_to="ghost")
        strategy = _RecordingStrategy(result)
        agent = _make_agent(strategy, agent_resolver={}.get)

        response = await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert response.content == ""

    async def test_resolved_target_returns_its_response_with_trace_update(self) -> None:
        tracer = _FakeTracer()
        registry: dict[str, Agent] = {}
        sub_agent = _make_agent(_RecordingStrategy(ReasoningResult(response="sub says hi")))
        registry["sub"] = sub_agent
        coordinator_result = ReasoningResult(response=None, done=False, delegate_to="sub")
        coordinator = _make_agent(
            _RecordingStrategy(coordinator_result),
            agent_resolver=registry.get,
            tracer=tracer,
        )

        response = await coordinator.handle(
            messages=[{"role": "user", "content": "x"}], auth=_Auth()
        )

        assert response.content == "sub says hi"
        assert tracer.traces[0].updates[0] == {"delegated_to": "sub"}

    async def test_resolver_as_mapping_without_call(self) -> None:
        registry: dict[str, Agent] = {}
        sub_agent = _make_agent(_RecordingStrategy(ReasoningResult(response="mapped")))
        registry["sub"] = sub_agent

        class _MappingResolver:
            def get(self, name: str) -> Agent | None:
                return registry.get(name)

        coordinator_result = ReasoningResult(response=None, done=False, delegate_to="sub")
        coordinator = _make_agent(
            _RecordingStrategy(coordinator_result), agent_resolver=_MappingResolver()
        )

        response = await coordinator.handle(
            messages=[{"role": "user", "content": "x"}], auth=_Auth()
        )

        assert response.content == "mapped"

    async def test_no_resolver_configured_falls_through_to_normal_response(self) -> None:
        coordinator_result = ReasoningResult(response=None, done=False, delegate_to="sub")
        coordinator = _make_agent(_RecordingStrategy(coordinator_result))

        response = await coordinator.handle(
            messages=[{"role": "user", "content": "x"}], auth=_Auth()
        )

        assert response.content == ""

    async def test_resolver_returning_non_agent_is_ignored(self) -> None:
        coordinator_result = ReasoningResult(response=None, done=False, delegate_to="sub")
        coordinator = _make_agent(
            _RecordingStrategy(coordinator_result),
            agent_resolver=lambda _name: "not an agent",
        )

        response = await coordinator.handle(
            messages=[{"role": "user", "content": "x"}], auth=_Auth()
        )

        assert response.content == ""


class TestHandleRcaAndLearningExtraction:
    async def test_tool_failure_triggers_rca_extraction(self) -> None:
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=_LearningRecord(learning="root cause"))
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: failed"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored[0].learning == "root cause"

    async def test_tool_failure_with_no_rca_found_skips_store(self) -> None:
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=None)
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: failed"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored == []

    async def test_tool_failure_rca_traced(self) -> None:
        tracer = _FakeTracer()
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=_LearningRecord(learning="traced rca"))
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "error happened"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
            tracer=tracer,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        trace = tracer.traces[0]
        assert "rca.extraction" in trace.spans
        assert learning_store.stored[0].learning == "traced rca"

    async def test_tool_failure_rca_found_without_trace_stores_learning(self) -> None:
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=_LearningRecord(learning="untraced rca"))
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: failed"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored[0].learning == "untraced rca"
        assert learning_store.stored[0].agent_id == "tester"
        # The untraced branch set only `agent_id`, so the RCA was stored at its
        # default `org_id=""`. That is not a cosmetic gap: an unowned learning
        # was readable by every org, so an analysis derived from this org's tool
        # failures reached other orgs' system prompts. Tracing is an
        # observability toggle and must not change what is persisted.
        assert learning_store.stored[0].org_id == "org-1", (
            "RCA stored without its org when tracing is disabled — it lands in "
            "the unowned scope instead of this caller's"
        )
        assert learning_store.stored[0].team_id == "team-1"

    async def test_rca_scope_does_not_depend_on_tracing(self) -> None:
        """The traced and untraced branches must persist identical scope.

        Pinning them against each other rather than against literals is what
        keeps the two from drifting again — the defect was that one branch
        acquired scope fields the other never did.
        """
        stored = []
        for tracer in (_FakeTracer(), None):
            learning_store = _FakeLearningStore()
            agent = _make_agent(
                _RecordingStrategy(
                    ReasoningResult(
                        response="done",
                        tool_history=[{"tool_name": "x", "result": "Error: failed"}],
                    )
                ),
                learning_store=learning_store,
                rca_extractor=_FakeRcaExtractor(rca=_LearningRecord(learning="rca")),
                tracer=tracer,
            )
            await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())
            rca = learning_store.stored[0]
            stored.append((rca.agent_id, rca.org_id, rca.team_id))

        assert stored[0] == stored[1], (
            f"tracing changed the persisted scope: traced={stored[0]} untraced={stored[1]}"
        )

    async def test_tool_failure_rca_traced_with_no_rca_found(self) -> None:
        tracer = _FakeTracer()
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=None)
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: failed"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
            tracer=tracer,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored == []
        assert tracer.traces[0].spans["rca.extraction"].outputs == [{"rca": "none"}]

    async def test_no_tool_history_skips_rca(self) -> None:
        learning_store = _FakeLearningStore()
        rca_extractor = _FakeRcaExtractor(rca=_LearningRecord())
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="done")),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored == []

    async def test_learning_extraction_stores_corrections_and_positives_when_traced(self) -> None:
        tracer = _FakeTracer()
        learning_store = _FakeLearningStore()
        extractor = _FakeLearningExtractor(
            corrections=[_LearningRecord(learning="fix it")],
            positives=[_LearningRecord(learning="good job")],
        )
        result = ReasoningResult(response="done", tool_history=[{"tool_name": "x", "result": "ok"}])
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            learning_extractor=extractor,
            tracer=tracer,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        learnings = [rec.learning for rec in learning_store.stored]
        assert "fix it" in learnings
        assert "good job" in learnings
        assert "learning.extraction" in tracer.traces[0].spans

    async def test_learning_extraction_without_trace_stores_only_corrections(self) -> None:
        learning_store = _FakeLearningStore()
        extractor = _FakeLearningExtractor(
            corrections=[_LearningRecord(learning="fix it")],
            positives=[_LearningRecord(learning="should not appear")],
        )
        result = ReasoningResult(response="done", tool_history=[{"tool_name": "x", "result": "ok"}])
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            learning_extractor=extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        learnings = [rec.learning for rec in learning_store.stored]
        assert learnings == ["fix it"]

    async def test_no_tool_history_skips_learning_extraction(self) -> None:
        learning_store = _FakeLearningStore()
        extractor = _FakeLearningExtractor(corrections=[_LearningRecord()])
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="done")),
            learning_store=learning_store,
            learning_extractor=extractor,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.stored == []

    async def test_learning_promoter_invoked_when_learnings_were_injected(self) -> None:
        promoter = _FakeLearningPromoter()
        context_builder = _FakeContextBuilder(learning_ids=[1, 2])
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="done")),
            context_builder=context_builder,
            learning_promoter=promoter,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert promoter.calls == ["org-1"]

    async def test_learning_promoter_skipped_when_no_learnings_injected(self) -> None:
        promoter = _FakeLearningPromoter()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="done")),
            learning_promoter=promoter,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert promoter.calls == []


class TestHandlePersistence:
    async def test_session_history_appended_with_user_and_assistant_turns(self) -> None:
        session_store = _FakeSessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="assistant reply")),
            session_store=session_store,
        )

        await agent.handle(
            messages=[{"role": "user", "content": "hello"}], auth=_Auth(), session_id="s1"
        )

        session_id, saved = session_store.appended[0]
        assert session_id == "s1"
        assert saved == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "assistant reply"},
        ]

    async def test_a_turn_identity_reaches_the_store(self) -> None:
        session_store = _FakeSessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="assistant reply")),
            session_store=session_store,
        )

        await agent.handle(
            messages=[{"role": "user", "content": "hello"}],
            auth=_Auth(),
            session_id="s1",
            turn_id="run-1",
        )

        assert session_store.turn_ids == ["run-1"]

    async def test_no_turn_identity_is_passed_as_none(self) -> None:
        session_store = _FakeSessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="assistant reply")),
            session_store=session_store,
        )

        await agent.handle(
            messages=[{"role": "user", "content": "hello"}], auth=_Auth(), session_id="s1"
        )

        assert session_store.turn_ids == [None]

    @pytest.mark.ac("SPEC-083026-5fab/AC-9")
    async def test_a_retried_turn_appends_its_messages_once(self) -> None:
        """The agent half of AC-9, against a store that actually enforces the
        identity. A fake that records `turn_id` proves it was passed and not
        that passing it changes anything, which is the claim."""
        session_store = InMemorySessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="assistant reply")),
            session_store=session_store,
        )

        for _ in range(2):
            await agent.handle(
                messages=[{"role": "user", "content": "hello"}],
                auth=_Auth(),
                session_id="s1",
                turn_id="run-1",
            )

        assert await session_store.get_history("s1") == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "assistant reply"},
        ]

    async def test_two_turns_of_one_session_both_land(self) -> None:
        """The mutation guard on the test above: a store that dropped every
        append after the first would satisfy it. Two identities, two turns."""
        session_store = InMemorySessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="assistant reply")),
            session_store=session_store,
        )

        for turn in ("run-1", "run-2"):
            await agent.handle(
                messages=[{"role": "user", "content": "hello"}],
                auth=_Auth(),
                session_id="s1",
                turn_id=turn,
            )

        assert len(await session_store.get_history("s1")) == 4

    async def test_no_response_skips_session_persistence(self) -> None:
        session_store = _FakeSessionStore()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="")),
            session_store=session_store,
        )

        await agent.handle(
            messages=[{"role": "user", "content": "hello"}], auth=_Auth(), session_id="s1"
        )

        assert session_store.appended == []

    async def test_outcome_recorded_with_coin_ledger_charge(self) -> None:
        outcome_store = _FakeOutcomeStore()
        coin_ledger = _FakeCoinLedger()
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "ok"}],
            input_tokens=10,
            output_tokens=20,
        )
        agent = _make_agent(
            _RecordingStrategy(result), outcome_store=outcome_store, coin_ledger=coin_ledger
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        outcome = outcome_store.recorded[0]
        assert outcome.charged_microchips == 5
        assert outcome.pricing_version == "v1"
        assert outcome.success is True
        assert outcome.tool_calls == [{"name": "x", "success": True}]
        assert len(coin_ledger.calls) == 1

    async def test_outcome_recorded_without_coin_ledger_uses_zero_charge(self) -> None:
        outcome_store = _FakeOutcomeStore()
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: nope"}],
        )
        agent = _make_agent(_RecordingStrategy(result), outcome_store=outcome_store)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        outcome = outcome_store.recorded[0]
        assert outcome.charged_microchips == 0
        assert outcome.success is False
        assert outcome.error_type == "tool_error"

    async def test_learning_outcome_marked_when_learnings_injected(self) -> None:
        learning_store = _FakeLearningStore()
        context_builder = _FakeContextBuilder(learning_ids=[7, 8])
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="done")),
            learning_store=learning_store,
            context_builder=context_builder,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.marked == [([7, 8], True, "org-1")]

    async def test_learning_outcome_marked_unsuccessful_on_tool_failure(self) -> None:
        learning_store = _FakeLearningStore()
        context_builder = _FakeContextBuilder(learning_ids=[7])
        result = ReasoningResult(
            response="done",
            tool_history=[{"tool_name": "x", "result": "Error: bad"}],
        )
        agent = _make_agent(
            _RecordingStrategy(result),
            learning_store=learning_store,
            context_builder=context_builder,
        )

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert learning_store.marked == [([7], False, "org-1")]


class TestHandleFinalResponse:
    async def test_none_response_becomes_empty_string(self) -> None:
        agent = _make_agent(_RecordingStrategy(ReasoningResult(response=None)))

        result = await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert isinstance(result, AgentResponse)
        assert result.content == ""
        assert result.agent_name == "tester"


class TestProviderFailureHandling:
    """Review finding H9: unhandled provider exceptions skipped cleanup.

    `_run_strategy` caught only (ValueError, RuntimeError, TimeoutError,
    OSError), and `handle()` had no try/finally at all. The shipped LLM client
    raises bare `httpx` errors via `raise_for_status()`, and
    `httpx.HTTPStatusError`, `AgentError`, `LLMProviderError` and
    `CircuitOpenError` all derive from `Exception` directly — so the single most
    likely real failure, a provider outage, was the one case that bypassed
    `trace.end()` and `_persist_run` entirely.
    """

    async def test_arbitrary_provider_exception_is_handled(self) -> None:
        """Fails without the fix: the exception propagated out of handle()."""

        class _ProviderDown(Exception):
            """Stands in for httpx.HTTPStatusError — derives from Exception."""

        strategy = _RecordingStrategy(raises=_ProviderDown("503 from upstream"))
        agent = _make_agent(strategy)

        result = await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert isinstance(result, AgentResponse)
        assert "internal error" in result.content.lower()

    async def test_provider_exception_still_ends_the_trace(self) -> None:
        """The trace must be closed on the failure path too.

        A trace left open is not merely untidy: it is a span that never
        reports, so the outage is invisible in telemetry precisely when it
        matters most.
        """

        class _ProviderDown(Exception):
            pass

        tracer = _FakeTracer()
        agent = _make_agent(_RecordingStrategy(raises=_ProviderDown("boom")), tracer=tracer)

        await agent.handle(messages=[{"role": "user", "content": "x"}], auth=_Auth())

        assert tracer.traces[0].ended is True

    async def test_trace_is_ended_exactly_once_on_the_happy_path(self) -> None:
        """Guard against the finally double-ending what _finalize_trace ended.

        `_finalize_trace` used to call `trace.end()` itself; ownership moved to
        `handle()`'s finally, and this pins that there is exactly one owner.
        """

        class _CountingTrace(_FakeTrace):
            def __init__(self) -> None:
                super().__init__()
                self.end_calls = 0

            def end(self) -> None:
                self.end_calls += 1
                super().end()

        class _CountingTracer(_FakeTracer):
            def create_trace(self, **_kwargs: Any) -> _CountingTrace:
                trace = _CountingTrace()
                self.traces.append(trace)
                return trace

        tracer = _CountingTracer()
        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="hi", done=True)), tracer=tracer
        )

        await agent.handle(messages=[{"role": "user", "content": "ok"}], auth=_Auth())

        assert tracer.traces[0].end_calls == 1

    async def test_trace_end_failure_does_not_mask_the_response(self) -> None:
        """Telemetry must never turn a successful run into an error."""

        class _ExplodingTrace(_FakeTrace):
            def end(self) -> None:
                raise RuntimeError("langfuse unreachable")

        class _ExplodingTracer(_FakeTracer):
            def create_trace(self, **_kwargs: Any) -> _ExplodingTrace:
                trace = _ExplodingTrace()
                self.traces.append(trace)
                return trace

        agent = _make_agent(
            _RecordingStrategy(ReasoningResult(response="hi", done=True)),
            tracer=_ExplodingTracer(),
        )

        result = await agent.handle(messages=[{"role": "user", "content": "ok"}], auth=_Auth())

        assert result.content == "hi"


class TestClassifiedTaskTypeFromIntent:
    """Review finding H4: `intent` was declared and never read."""

    async def test_intent_supplies_the_task_type(self) -> None:
        from dataclasses import dataclass as _dc

        @_dc
        class _Intent:
            task_type: str

        strategy = _RecordingStrategy(ReasoningResult(response="ok", done=True))
        agent = _make_agent(strategy)

        await agent.handle(
            messages=[{"role": "user", "content": "x"}],
            auth=_Auth(),
            intent=_Intent(task_type="code"),
        )

        assert strategy.calls[0].get("classified_task_type") == "code"

    async def test_explicit_classified_task_type_wins_over_intent(self) -> None:
        """The delegation path passes it explicitly and has no Intent."""
        from dataclasses import dataclass as _dc

        @_dc
        class _Intent:
            task_type: str

        strategy = _RecordingStrategy(ReasoningResult(response="ok", done=True))
        agent = _make_agent(strategy)

        await agent.handle(
            messages=[{"role": "user", "content": "x"}],
            auth=_Auth(),
            intent=_Intent(task_type="code"),
            classified_task_type="chat",
        )

        assert strategy.calls[0].get("classified_task_type") == "chat"
