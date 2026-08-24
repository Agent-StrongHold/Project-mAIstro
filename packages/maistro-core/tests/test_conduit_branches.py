"""Tests for Conduit branches not covered by the happy-path/blocked-gate suite
in test_conduit.py: tier overrides, intent hints, no-agent fallbacks, and
agent dispatch failure handling."""

from __future__ import annotations

from typing import Any, ClassVar

from maistro.conduit import Conduit, _apply_intent_hint, determine_execution_tier
from maistro.security._types import GateResult
from maistro.types.agent import AgentResponse
from maistro.types.config import TaskTypeConfig
from maistro.types.intent import Intent


class FakeGate:
    async def process_input(self, content: str, **kwargs: Any) -> GateResult:
        return GateResult(blocked=False, block_reason="")


class FakeClassifier:
    def __init__(self, intent: Intent | None = None) -> None:
        self._intent = intent or Intent(task_type="chat")

    async def classify(
        self,
        messages: list[dict[str, str]],
        task_types: dict[str, TaskTypeConfig],
        explicit_priority: str | None = None,
    ) -> Intent:
        return self._intent


class FakeIntentRegistry:
    def __init__(self, resolved_name: str = "unknown") -> None:
        self._resolved_name = resolved_name

    def resolve(self, task_type: str) -> str:
        return self._resolved_name


class FakeAgent:
    priority_tier = "P0"

    def __init__(self, *, response: Any = None, raises: Exception | None = None) -> None:
        self._response = response or {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        self._raises = raises
        self.handled_kwargs: dict[str, Any] | None = None

    async def handle(self, **kwargs: Any) -> Any:
        self.handled_kwargs = kwargs
        if self._raises:
            raise self._raises
        return self._response


class FakeConfig:
    task_types: ClassVar[dict[str, TaskTypeConfig]] = {
        "chat": TaskTypeConfig(),
        "code": TaskTypeConfig(),
    }


class FakeContainer:
    def __init__(
        self,
        *,
        agents: dict[str, Any] | None = None,
        resolved_name: str = "unknown",
        classifier: FakeClassifier | None = None,
    ) -> None:
        self.gate = FakeGate()
        self.classifier = classifier or FakeClassifier()
        self.intent_registry = FakeIntentRegistry(resolved_name)
        self.agents = agents or {}
        self.config = FakeConfig()


def _messages(content: str = "hi") -> list[dict[str, Any]]:
    return [{"role": "user", "content": content}]


class TestDetermineExecutionTier:
    async def test_no_agent_returns_unchanged_intent(self) -> None:
        intent = Intent(task_type="chat")
        result = await determine_execution_tier(intent, None)
        assert result is intent

    async def test_agent_without_priority_tier_attr_unchanged(self) -> None:
        intent = Intent(task_type="chat")
        result = await determine_execution_tier(intent, object())
        assert result is intent

    async def test_agent_with_same_tier_returns_same_intent(self) -> None:
        intent = Intent(task_type="chat", tier=Intent(task_type="chat").tier)

        class _Agent:
            priority_tier = intent.tier

        result = await determine_execution_tier(intent, _Agent())
        assert result is intent

    async def test_agent_with_different_tier_replaces(self) -> None:
        intent = Intent(task_type="chat")

        class _Agent:
            priority_tier = "P0" if intent.tier != "P0" else "P5"

        result = await determine_execution_tier(intent, _Agent())
        assert result.tier == _Agent.priority_tier
        assert result is not intent


class TestApplyIntentHint:
    def test_empty_hint_returns_same_intent(self) -> None:
        intent = Intent(task_type="chat")
        assert _apply_intent_hint(intent, "") is intent

    def test_matching_hint_overrides_task_type(self) -> None:
        """A hint naming a configured task type must be honoured.

        This test previously drew its target from `TIER_ORDER` and asserted a
        model-size tier ("small") landed in `task_type` — it encoded the H5
        defect rather than the intent. `task_type`'s domain is
        `config.task_types`, which is what the classifier is handed and what
        `IntentRegistry.resolve` looks up.
        """
        intent = Intent(task_type="chat")
        result = _apply_intent_hint(intent, "CODE", FakeConfig.task_types)
        assert result.task_type == "code"

    def test_unmatched_hint_returns_same_intent(self) -> None:
        intent = Intent(task_type="chat")
        result = _apply_intent_hint(intent, "totally-not-a-real-type", FakeConfig.task_types)
        assert result is intent

    def test_tier_name_is_no_longer_accepted_as_a_task_type(self) -> None:
        """The regression guard for H5.

        `"large"` is a model-size tier, not a task type. Writing it into
        `task_type` resolved to no agent and silently fell through to whichever
        agent happened to be first — a routing corruption with no error.
        """
        from maistro.types.intent import TIER_ORDER

        intent = Intent(task_type="chat")
        for tier in TIER_ORDER:
            if tier in FakeConfig.task_types:
                continue
            assert _apply_intent_hint(intent, tier, FakeConfig.task_types) is intent

    def test_no_task_types_configured_is_not_a_crash(self) -> None:
        intent = Intent(task_type="chat")
        assert _apply_intent_hint(intent, "code", {}) is intent
        assert _apply_intent_hint(intent, "code", None) is intent


class TestRouteRequestEdgeCases:
    async def test_no_user_message_returns_stop_response(self) -> None:
        container = FakeContainer()
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request([{"role": "assistant", "content": "hi"}])

        assert result["choices"][0]["message"]["content"] == "No message provided."

    async def test_empty_messages_returns_stop_response(self) -> None:
        container = FakeContainer()
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request([])

        assert result["choices"][0]["message"]["content"] == "No message provided."

    async def test_unresolved_agent_falls_back_to_first_available(self) -> None:
        agent = FakeAgent()
        container = FakeContainer(agents={"only-one": agent}, resolved_name="missing-name")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        assert result["choices"][0]["message"]["content"] == "ok"
        assert agent.handled_kwargs is not None

    async def test_no_agents_at_all_returns_stop_response(self) -> None:
        container = FakeContainer(agents={})
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        assert result["choices"][0]["message"]["content"] == "No agents available."

    async def test_agent_handle_raises_returns_error_response(self) -> None:
        agent = FakeAgent(raises=RuntimeError("kaboom"))
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        content = result["choices"][0]["message"]["content"]
        assert "Agent error: kaboom" in content

    async def test_non_dict_result_wrapped_in_stop_response(self) -> None:
        agent = FakeAgent(response="plain string result")
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        assert result["choices"][0]["message"]["content"] == "plain string result"

    async def test_intent_hint_threads_through_to_agent(self) -> None:
        agent = FakeAgent()
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        await conduit.route_request(_messages(), intent_hint="code")

        assert agent.handled_kwargs is not None
        assert agent.handled_kwargs["intent"].task_type == "code"

    async def test_classified_task_type_reaches_the_agent(self) -> None:
        """The regression guard for H4.

        `handle()` accepted `classified_task_type` and the conduit never passed
        it, so strategy construction, RCA tagging and learning scope all ran
        with "" on every live request while the classifier's result was thrown
        away one line short of its destination.
        """
        agent = FakeAgent()
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        await conduit.route_request(_messages(), intent_hint="code")

        assert agent.handled_kwargs is not None
        assert agent.handled_kwargs["classified_task_type"] == "code"

    async def test_session_id_and_auth_threaded_to_agent(self) -> None:
        agent = FakeAgent()
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]
        auth = object()

        await conduit.route_request(_messages(), auth=auth, session_id="sess-1")

        assert agent.handled_kwargs is not None
        assert agent.handled_kwargs["auth"] is auth
        assert agent.handled_kwargs["session_id"] == "sess-1"


class BlockingGate:
    """A Gate that refuses, so the refusal's own shape can be checked."""

    async def process_input(self, content: str, **kwargs: Any) -> GateResult:
        return GateResult(blocked=True, block_reason="prompt injection")


class TestAgentResponseReachesTheCaller:
    """The shape every `BaseAgent.handle` returns, which had no test.

    The non-dict branch was covered only by a plain string, so it looked
    exercised while `AgentResponse` — the type that actually travels it — was
    never tried. A dataclass with no `__str__` stringifies to its repr, so what
    a caller read back as the assistant's message was the whole dataclass with
    the answer buried inside it.
    """

    async def test_the_answer_is_the_content_not_the_dataclass_repr(self) -> None:
        agent = FakeAgent(response=AgentResponse(content="the real answer"))
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        message = result["choices"][0]["message"]["content"]
        assert message == "the real answer"
        assert "AgentResponse(" not in message

    async def test_an_agent_refusal_is_a_content_filter_finish(self) -> None:
        """A refusal an agent decided on — Sentinel, a policy — reads the same
        as one the Gate decided on. A client branching on `finish_reason`
        should not have to know which layer said no."""
        agent = FakeAgent(response=AgentResponse.blocked_response("sentinel said no"))
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        choice = result["choices"][0]
        assert choice["finish_reason"] == "content_filter"
        assert choice["message"]["content"] == "Request blocked: sentinel said no"

    async def test_a_failed_response_still_carries_its_message(self) -> None:
        """`error_response` puts the message in `content`, so the failure is
        already the answer. OpenAI has no finish_reason for it, and inventing
        one would be a shape no client parses."""
        agent = FakeAgent(response=AgentResponse.error_response("upstream is down"))
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        choice = result["choices"][0]
        assert choice["message"]["content"] == "upstream is down"
        assert choice["finish_reason"] == "stop"

    async def test_a_dict_returning_agent_is_still_passed_through(self) -> None:
        """The pass-through this change must not break: an agent already
        speaking the wire shape owns it, `finish_reason` included."""
        wire = {"choices": [{"message": {"role": "assistant", "content": "mine"}, "id": "x"}]}
        agent = FakeAgent(response=wire)
        container = FakeContainer(agents={"unknown": agent}, resolved_name="unknown")
        conduit = Conduit(container)  # type: ignore[arg-type]

        assert await conduit.route_request(_messages()) is wire


class TestGateRefusalShape:
    async def test_a_gate_block_finishes_as_content_filter(self) -> None:
        """OpenAI's own spelling for a refusal, so a client that already
        handles moderation needs no Maistro-specific case."""
        container = FakeContainer(agents={"unknown": FakeAgent()}, resolved_name="unknown")
        container.gate = BlockingGate()  # type: ignore[assignment]
        conduit = Conduit(container)  # type: ignore[arg-type]

        result = await conduit.route_request(_messages())

        choice = result["choices"][0]
        assert choice["finish_reason"] == "content_filter"
        assert choice["message"]["content"] == "Request blocked: prompt injection"
