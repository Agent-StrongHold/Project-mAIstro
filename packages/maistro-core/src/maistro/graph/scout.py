from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

from maistro.graph.types import (
    DEFAULT_SYSTEM_PROMPTS,
    JSON_OUTPUT_SCHEMAS,
    AgentRole,
    GraphBlackboard,
    GraphTask,
    ScoutContext,
    ScoutOutput,
)

logger = logging.getLogger(__name__)


def _strip_json_block(text: str) -> str:
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _scout_prompt(task: GraphTask, blackboard: GraphBlackboard) -> str:
    history_summary = ""
    if blackboard.optimization_history:
        last = blackboard.optimization_history[-1]
        weakest = getattr(last, "weakest_node", None)
        avg_score = getattr(last, "avg_review_score", None)
        if weakest:
            score_str = f", avg review {avg_score:.1f}/10" if avg_score else ""
            history_summary = (
                f"\nOptimization history: iteration {blackboard.iteration}, "
                f"weakest node was {weakest}{score_str}. "
                f"Focus especially on context relevant to {weakest}."
            )

    return (
        f"Task: {task.description}\n\n"
        f"Workspace: {blackboard.workspace}\n"
        f"Iteration: {blackboard.iteration}{history_summary}\n\n"
        "Survey the workspace and provide a briefing for the engineering team."
    )


async def run_scout(
    task: GraphTask,
    blackboard: GraphBlackboard,
    llm_call: Callable[..., Awaitable[str]],
    *,
    model: str = "default",
    temperature: float | None = None,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> GraphBlackboard:
    logger.info(
        "scout_start",
        extra={"workspace": blackboard.workspace, "iteration": blackboard.iteration},
    )

    try:
        system = DEFAULT_SYSTEM_PROMPTS[AgentRole.SCOUT] + JSON_OUTPUT_SCHEMAS.get(
            AgentRole.SCOUT, ""
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _scout_prompt(task, blackboard)},
        ]

        raw = await asyncio.wait_for(
            llm_call(messages, model=model, temperature=temperature),
            timeout=timeout,
        )

        cleaned = _strip_json_block(raw)
        scout_out = ScoutOutput.model_validate(json.loads(cleaned))

        scout_context = ScoutContext(
            relevant_files=scout_out.relevant_files,
            patterns=scout_out.patterns,
            dependency_map=scout_out.dependency_map,
            similar_implementations=scout_out.similar_implementations,
            raw_findings=scout_out.summary,
        )

        logger.info(
            "scout_complete",
            extra={"relevant_files": len(scout_context.relevant_files)},
        )

        return blackboard.model_copy(update={"scout_context": scout_context})

    except Exception as exc:
        logger.warning("scout_failed", extra={"error": str(exc)})
        return blackboard
