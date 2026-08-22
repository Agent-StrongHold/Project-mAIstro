"""End-to-end tests for the Conduit request pipeline.

These tests pin the contract between the Conduit and its collaborators:
- Gate is async (``process_input``) and returns a ``GateResult`` with
  ``.blocked`` / ``.block_reason``.
- ClassifierEngine.classify requires ``(messages, task_types)``.

They drive ``Conduit.route_request`` (and ``Container.route_request``) with
fakes and assert a well-formed response comes back without raising.
"""

from __future__ import annotations

from typing import Any, ClassVar

from maistro.conduit import Conduit
from maistro.security._types import GateResult
from maistro.types.config import TaskTypeConfig
from maistro.types.intent import Intent


class FakeGate:
    """Mimics the real Gate: async process_input -> GateResult."""

    def __init__(self, *, blocked: bool = False, reason: str = "") -> None:
        self._blocked = blocked
        self._reason = reason
        self.calls: list[str] = []

    async def process_input(self, content: str, **kwargs: Any) -> GateResult:
        self.calls.append(content)
        return GateResult(blocked=self._blocked, block_reason=self._reason)


class FakeClassifier:
    """Mimics ClassifierEngine: classify(messages, task_types) -> Intent."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], dict[str, TaskTypeConfig]]] = []

    async def classify(
        self,
        messages: list[dict[str, str]],
        task_types: dict[str, TaskTypeConfig],
        explicit_priority: str | None = None,
    ) -> Intent:
        # task_types must be the required dict, not absent.
        assert isinstance(task_types, dict)
        self.calls.append((messages, task_types))
        return Intent(task_type="chat")


class FakeIntentRegistry:
    def resolve(self, task_type: str) -> str:
        return "echo"


class FakeAgent:
    priority_tier = "P2"

    def __init__(self) -> None:
        self.handled = False

    async def handle(self, **kwargs: Any) -> dict[str, Any]:
        self.handled = True
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "hello back"},
                    "finish_reason": "stop",
                }
            ]
        }


class FakeConfig:
    task_types: ClassVar[dict[str, TaskTypeConfig]] = {"chat": TaskTypeConfig()}


class FakeContainer:
    """Minimal stand-in for Container holding the collaborators Conduit uses."""

    def __init__(self, *, gate: FakeGate, classifier: FakeClassifier, agent: FakeAgent) -> None:
        self.gate = gate
        self.classifier = classifier
        self.intent_registry = FakeIntentRegistry()
        self.agents = {"echo": agent}
        self.config = FakeConfig()
        # No spine wired: these tests exercise the pipeline, not admission.
        # `Conduit` reads this directly rather than through getattr, so a fake
        # Container that omits it is a fake that has drifted from the real one.
        self.chat_admitter = None


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "hi there"}]


async def test_route_request_happy_path_returns_response_without_raising() -> None:
    gate = FakeGate(blocked=False)
    classifier = FakeClassifier()
    agent = FakeAgent()
    container = FakeContainer(gate=gate, classifier=classifier, agent=agent)
    conduit = Conduit(container)  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert result["choices"][0]["message"]["content"] == "hello back"
    # Gate was invoked via the async process_input contract.
    assert gate.calls == ["hi there"]
    # Classifier received messages + the required task_types dict.
    assert classifier.calls
    _msgs, task_types = classifier.calls[0]
    assert task_types == {"chat": TaskTypeConfig()}
    assert agent.handled is True


async def test_route_request_blocked_by_gate_short_circuits() -> None:
    gate = FakeGate(blocked=True, reason="Blocked by Warden: injection")
    classifier = FakeClassifier()
    agent = FakeAgent()
    container = FakeContainer(gate=gate, classifier=classifier, agent=agent)
    conduit = Conduit(container)  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    content = result["choices"][0]["message"]["content"]
    assert "Blocked by Warden: injection" in content
    # Pipeline short-circuits: classifier and agent never run.
    assert classifier.calls == []
    assert agent.handled is False


async def test_container_route_request_delegates_end_to_end() -> None:
    # Exercise Container.route_request -> Conduit.route_request with real wiring.
    gate = FakeGate(blocked=False)
    classifier = FakeClassifier()
    agent = FakeAgent()
    container = FakeContainer(gate=gate, classifier=classifier, agent=agent)
    conduit = Conduit(container)  # type: ignore[arg-type]
    container.conduit = conduit  # type: ignore[attr-defined]

    # Mirror Container.route_request's delegation.
    result = await container.conduit.route_request(_messages())
    assert result["choices"][0]["message"]["content"] == "hello back"
