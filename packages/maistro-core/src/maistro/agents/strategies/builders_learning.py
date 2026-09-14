"""Builders reasoning strategy without a second tool execution authority.

The Builders graph/runtime owns engineering work.  This strategy may add
prompt context and delegate model-selected tools to React, but it must not run
shell or GitHub operations itself through an arbitrary callback.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.agents.strategies.react import ReactStrategy
from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategy.builders_learning")


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

    async def _check_repository_state(self, **_kwargs: Any) -> dict[str, Any]:
        """Compatibility projection; repository reads belong to a governed node."""
        return {"code": [], "tests": [], "failed_prs": []}

    async def _analyze_failure_patterns(self, **_kwargs: Any) -> dict[str, Any]:
        """Compatibility projection; GitHub reads belong to a governed node."""
        return {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

    async def _run_pr_diagnostics(self, **_kwargs: Any) -> dict[str, Any]:
        """Compatibility projection; command execution is not strategy-owned."""
        return {
            "all_passed": False,
            "issues": [],
            "has_critical_issues": False,
            "not_run": True,
        }

    async def _store_frank_learning(
        self,
        repo_state: dict[str, Any],
        failure_patterns: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        logger.info(
            "Frank learning: %d code files, %d test files, %d failures found",
            len(repo_state.get("code", [])),
            len(repo_state.get("tests", [])),
            len(failure_patterns.get("failures", [])),
        )

    async def _store_mason_learning(
        self,
        diagnostics: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        logger.info(
            "Mason learning: gates_passed=%s, issues=%d, tools_used=%d",
            diagnostics.get("all_passed"),
            len(diagnostics.get("issues", [])),
            len(getattr(result, "tool_history", [])),
        )

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)
