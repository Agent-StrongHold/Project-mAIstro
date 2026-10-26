"""Frank/Mason ReAct wrapper with strategy-authored effects retired (#847).

The former implementation invoked a raw ``tool_executor`` callback itself with
``shell``/``github`` commands (``find ... | head -50``, ``ruff ... 2>&1 | tail``,
GitHub issue searches) before any allowlist or contract admission, and the
gathered context was never consumed by the downstream ReAct loop -- pure effect
risk for no behavioral benefit. Strategy code cannot widen authority beyond the
canonical Agent/Principal envelope even for internally chosen calls (#847), so
the recon/diagnostic effects are retired rather than routed: this wrapper now
performs no tool effects of its own. All tool traffic is model-selected and
flows through the Agent's governed executor with the same admission as any
other tool call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.agents.strategies.react import ReactStrategy
from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategy.builders_learning")


class BuildersLearningStrategy:
    """Frank/Mason wrapper around the ReAct loop.

    The Frank (recon/diagnose) and Mason (build/self-check) variants shared one
    ReAct core with strategy-authored shell/GitHub side calls. Those side calls
    are gone; every worker now reasons through the same governed ReAct loop,
    and the ``worker`` selection only remains part of the call signature so
    existing roster wiring keeps working.
    """

    def __init__(
        self,
        max_rounds: int = 10,
        force_tool_first: bool = False,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first
        self._react = ReactStrategy(max_rounds=max_rounds, force_tool_first=force_tool_first)

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        # A supplied tool_executor is deliberately NOT consumed here: the
        # Agent pipeline hands strategies the governed executor for
        # model-selected calls, and strategy-authored effects were the #847
        # bypass. Standalone callers that pass a raw executor get no effects
        # from this strategy at all.
        worker = kwargs.get("worker", "unknown")
        logger.debug("BuildersLearning worker '%s' delegating to governed ReAct", worker)
        return await self._react.reason(messages, model, llm, trace=trace, warden=warden, **kwargs)
