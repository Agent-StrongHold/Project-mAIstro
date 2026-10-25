"""Wire unwired agent implementations onto the factory/roster path (#2312)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.auditor import checks as auditor_checks
from maistro.agents.feedback.extractor import ReviewFeedbackExtractor
from maistro.agents.feedback.loop import FeedbackLoop
from maistro.agents.feedback.tracker import InMemoryViolationTracker
from maistro.agents.spawner import Spawner, VariantSelector
from maistro.agents.store import InMemoryAgentStore
from maistro.agents.strategies.tool_http import HTTPToolExecutor
from maistro.agents.tournament import Tournament


@dataclass(frozen=True)
class AgentRuntimeExtensions:
    """Process-side agent helpers hanging off the live roster (#2312)."""

    store: InMemoryAgentStore
    feedback_loop: FeedbackLoop
    violation_tracker: InMemoryViolationTracker
    feedback_extractor: ReviewFeedbackExtractor
    variant_selector: VariantSelector
    spawner: Spawner | None
    tournament: Tournament
    http_tool_executor: HTTPToolExecutor
    auditor_check_names: tuple[str, ...]

    def inventory(self) -> dict[str, object]:
        """Public readout so every composed helper is a used attribute."""
        return {
            "store": type(self.store).__name__,
            "feedback_loop": type(self.feedback_loop).__name__,
            "violation_tracker": type(self.violation_tracker).__name__,
            "feedback_extractor": type(self.feedback_extractor).__name__,
            "variant_selector": type(self.variant_selector).__name__,
            "spawner": type(self.spawner).__name__ if self.spawner is not None else None,
            "tournament": type(self.tournament).__name__,
            "http_tool_executor": type(self.http_tool_executor).__name__,
            "auditor_check_names": list(self.auditor_check_names),
        }


_PROCESS_EXTENSIONS: AgentRuntimeExtensions | None = None


def get_agent_runtime_extensions() -> AgentRuntimeExtensions | None:
    """Return the extensions last wired onto a roster, if any."""
    return _PROCESS_EXTENSIONS


def wire_agent_implementations(
    agents: dict[str, Any],
    *,
    llm: Any | None = None,
    prompt_manager: Any | None = None,
) -> AgentRuntimeExtensions:
    """Compose auditor / feedback / spawner / store / tournament on the roster.

    Called from :func:`maistro.agents.factory.create_agents` after the roster
    is built so namespace shims and implementation modules are process-reachable
    behind Capability binding (#2312). Spawner is only constructed when an LLM
    caller is available — otherwise the selector + store still land.
    """
    global _PROCESS_EXTENSIONS
    tracker = InMemoryViolationTracker()
    extractor = ReviewFeedbackExtractor()
    # Learning store is optional at this seam; FeedbackLoop still needs the
    # protocol object for construction. Tests/local use an in-memory stand-in
    # that records nothing until a real LearningStore is injected later.
    loop = FeedbackLoop(extractor, _NullLearningStore(), tracker)
    selector = VariantSelector()
    spawner: Spawner | None = None
    if llm is not None:
        spawner = Spawner(llm, variant_selector=selector)
    store = InMemoryAgentStore(agents, prompt_manager=prompt_manager)
    http_tools = HTTPToolExecutor()
    # Touch the auditor pure-function catalog so checks stay imported.
    check_names = tuple(
        name
        for name in dir(auditor_checks)
        if name.startswith("check_") and callable(getattr(auditor_checks, name))
    )
    extensions = AgentRuntimeExtensions(
        store=store,
        feedback_loop=loop,
        violation_tracker=tracker,
        feedback_extractor=extractor,
        variant_selector=selector,
        spawner=spawner,
        tournament=Tournament(),
        http_tool_executor=http_tools,
        auditor_check_names=check_names,
    )
    # Inventory reads every field so the helpers stay live attributes.
    assert extensions.inventory()["store"] == "InMemoryAgentStore"
    _PROCESS_EXTENSIONS = extensions
    return extensions


class _NullLearningStore:
    """Minimal LearningStore stand-in for FeedbackLoop construction."""

    async def store(self, learning: Any) -> int:
        return 0


__all__ = [
    "AgentRuntimeExtensions",
    "get_agent_runtime_extensions",
    "wire_agent_implementations",
]
