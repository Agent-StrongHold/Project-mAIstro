"""The chat pipeline admits, closes and reports a canonical Run (#131).

`test_chat_admission` proves the admitter. This proves the seam: that the
conduit actually uses it, that the Run it closes says what really happened, and
— the half that is easy to lose — that a chat caller who does not care about any
of it sees exactly the response it saw before.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from maistro.conduit import CONDUIT_OUTCOME, Conduit
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE, SESSION_ID_KEY
from maistro.runs.chat import CHAT_TURN_SOURCE, ChatRunAdmitter
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.security._types import GateResult
from maistro.types.config import TaskTypeConfig
from maistro.types.intent import Intent

WORKSPACE = "conduit-workspace"


class FakeGate:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked

    async def process_input(self, content: str, **kwargs: Any) -> GateResult:
        return GateResult(blocked=self.blocked, block_reason="policy" if self.blocked else "")


class FakeClassifier:
    async def classify(self, messages: Any, task_types: Any, explicit_priority: Any = None):
        return Intent(task_type="chat")


class FakeIntentRegistry:
    def resolve(self, task_type: str) -> str:
        return "echo"


class FakeIdentity:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeAgent:
    def __init__(self, *, response: Any = None, raises: Exception | None = None) -> None:
        self.identity = FakeIdentity("echo")
        self._response = response or {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        self._raises = raises

    async def handle(self, **kwargs: Any) -> Any:
        if self._raises:
            raise self._raises
        return self._response


class FakeConfig:
    task_types: ClassVar[dict[str, TaskTypeConfig]] = {"chat": TaskTypeConfig()}


class FakeContainer:
    def __init__(self, *, agent: Any, chat_admitter: Any, blocked: bool = False) -> None:
        self.gate = FakeGate(blocked=blocked)
        self.classifier = FakeClassifier()
        self.intent_registry = FakeIntentRegistry()
        self.agents = {"echo": agent} if agent is not None else {}
        self.config = FakeConfig()
        self.chat_admitter = chat_admitter


@pytest.fixture
async def seam():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    admitter = ChatRunAdmitter(store, workspace_id=WORKSPACE, project_id=root.project_id)
    return admitter, store


def _messages(content: str = "hi") -> list[dict[str, Any]]:
    return [{"role": "user", "content": content}]


# ── the run_id is real ────────────────────────────────────────────


async def test_a_chat_turn_returns_a_resolvable_run_id(seam) -> None:
    admitter, store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert result["run_id"]
    assert await store.get_run(result["run_id"]) is not None


async def test_the_run_correlates_back_to_its_session(seam) -> None:
    admitter, store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages(), session_id="sess-42")

    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.provenance[SESSION_ID_KEY] == "sess-42"
    assert run.provenance[ADMISSION_SOURCE] == CHAT_TURN_SOURCE


async def test_the_request_id_reaches_the_run(seam) -> None:
    admitter, store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages(), request_id="req-9")

    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.provenance["request_id"] == "req-9"


async def test_the_run_names_the_agent_that_actually_ran(seam) -> None:
    """`agent_name` is the *resolved* name, and the pipeline falls back to an
    arbitrary registered agent when that one is missing. The Run must name the
    one that ran, or the canonical record disagrees with the execution."""
    admitter, store = seam
    agent = FakeAgent()
    agent.identity = FakeIdentity("actually-this-one")
    conduit = Conduit(FakeContainer(agent=agent, chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.graph.materialize().nodes[0].parameters["to_agent"] == "actually-this-one"


# ── the Run says what really happened ─────────────────────────────


async def test_a_successful_turn_closes_its_run_completed(seam) -> None:
    admitter, store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_an_agent_failure_closes_its_run_failed(seam) -> None:
    """The pipeline turns an agent exception into an ordinary assistant message
    so an OpenAI client keeps working. Without an explicit outcome the Run would
    read COMPLETED — canonical in shape only, which is the defect this seam
    exists to remove."""
    admitter, store = seam
    agent = FakeAgent(raises=RuntimeError("provider exploded"))
    conduit = Conduit(FakeContainer(agent=agent, chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert result[CONDUIT_OUTCOME] == "failed"
    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert "provider exploded" in run.error


async def test_a_non_dict_agent_result_still_closes_its_run(seam) -> None:
    admitter, store = seam
    conduit = Conduit(
        FakeContainer(agent=FakeAgent(response="plain string"), chat_admitter=admitter)  # type: ignore[arg-type]
    )

    result = await conduit.route_request(_messages())

    assert result["choices"][0]["message"]["content"] == "plain string"
    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_the_conversation_content_is_not_copied_onto_the_run(seam) -> None:
    """Deliberate: the session store already holds this, with its own TTL.
    Two copies would mean two retentions and two places to honour a deletion."""
    admitter, store = seam
    agent = FakeAgent(
        response={"choices": [{"message": {"role": "assistant", "content": "my SSN is 1"}}]}
    )
    conduit = Conduit(FakeContainer(agent=agent, chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages("my SSN is 1"))

    run = await store.get_run(result["run_id"])
    assert run is not None
    assert run.result is None


# ── refusals happen before there is work to admit ─────────────────


async def test_a_blocked_request_admits_no_run(seam) -> None:
    """A Gate block is a refusal at the trust boundary, not work. Its audit
    record is the Gate's; admitting a Run for it would put a Graph naming the
    fallback agent into the spine for every rejected probe."""
    admitter, _store = seam
    conduit = Conduit(
        FakeContainer(agent=FakeAgent(), chat_admitter=admitter, blocked=True)  # type: ignore[arg-type]
    )

    result = await conduit.route_request(_messages())

    assert "run_id" not in result
    assert result[CONDUIT_OUTCOME] == "refused"


async def test_an_empty_request_admits_no_run(seam) -> None:
    admitter, _store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request([{"role": "assistant", "content": "hi"}])

    assert "run_id" not in result
    assert result[CONDUIT_OUTCOME] == "refused"


async def test_no_agents_admits_no_run(seam) -> None:
    admitter, _store = seam
    conduit = Conduit(FakeContainer(agent=None, chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert "run_id" not in result
    assert result[CONDUIT_OUTCOME] == "failed"


# ── parity: nothing above changes what a chat caller already saw ──


async def test_the_openai_shape_is_unchanged(seam) -> None:
    admitter, _store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert result["choices"][0]["message"] == {"role": "assistant", "content": "ok"}


async def test_without_a_spine_the_pipeline_is_exactly_as_it_was() -> None:
    """A Container built directly, without `create_container`, still routes.
    A chat path that started refusing requests because housekeeping was unwired
    would be a worse failure than an absent run_id."""
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=None))  # type: ignore[arg-type]

    result = await conduit.route_request(_messages())

    assert result["choices"][0]["message"]["content"] == "ok"
    assert "run_id" not in result


async def test_a_bookkeeping_failure_does_not_lose_the_answer(seam) -> None:
    """The user's answer is already computed by the time the Run is closed.
    Losing it to a failed transition would be the worse trade."""
    admitter, _store = seam
    conduit = Conduit(FakeContainer(agent=FakeAgent(), chat_admitter=admitter))  # type: ignore[arg-type]

    async def refuse(*_args: Any, **_kwargs: Any) -> bool:
        return False

    admitter.record_outcome = refuse  # type: ignore[method-assign]

    result = await conduit.route_request(_messages())

    assert result["choices"][0]["message"]["content"] == "ok"
    assert result["run_id"]
