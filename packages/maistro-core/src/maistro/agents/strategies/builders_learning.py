"""Builders reasoning strategy without a second tool execution authority.

The Builders graph/runtime owns engineering work.  This strategy may add
prompt context and delegate model-selected tools to React, but it must not run
shell or GitHub operations itself through an arbitrary callback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.agents.strategies.react import ReactStrategy
from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace


class BuildersLearningStrategy:
    """Frank/Mason prompt specialization over the canonical ReAct boundary.

    Older versions performed repository reconnaissance and quality checks by
    calling ``tool_executor`` directly.  That made a strategy callback an
    execution authority and bypassed the Agent/Invocation envelope.  Those
    effects now belong to governed Builders graph nodes; this class only
    supplies role context and uses React for any explicitly exposed tools.
    """

    def __init__(
        self,
        max_rounds: int = 10,
        force_tool_first: bool = False,
        enable_learning: bool = True,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first
        self.enable_learning = enable_learning
        self._react = ReactStrategy(max_rounds=max_rounds, force_tool_first=force_tool_first)
        self.process = None
        self.build = None

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
        worker = kwargs.get("worker", "unknown")
        context: dict[str, Any] = {}
        if worker == "frank":
            context = {"coverage_expectation": "85% first pass, 95% final"}
        elif worker == "mason":
            context = {
                "coverage_expectation": "85% first pass, 95% final",
                "execution_mode": "fix"
                if kwargs.get("frank_diagnostic", {}).get("existing_code")
                else "implement",
            }

        return await self._react.reason(
            messages,
            model,
            llm,
            trace=trace,
            warden=warden,
            context=context,
            **kwargs,
        )
