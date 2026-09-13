"""Skill & Tool optimizer — extends the DAG optimizer to skills and tools.

A Skill is a natural-language document (SKILL.md) that guides an agent.
A Tool is a function definition + description that an agent can call.
Both are "external state of a frozen agent" — optimizable with the same
SkillOpt pattern: rollout → reflect → bounded edit → validate → accept.

This module provides:
  - SkillDocument: versioned skill text with edit history
  - ToolDefinition: optimizable tool schema + description
  - optimize_skill(): run one SkillOpt pass on a skill
  - optimize_tool(): run one pass on a tool definition
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.skill_optimizer")

# SkillOpt controls
TEXTUAL_LEARNING_RATE = 4  # max add/delete/replace edits per pass
MAX_REJECTED_BUFFER = 20


@dataclass
class SkillDocument:
    """A versioned skill document — the optimizable artifact."""

    id: str
    name: str
    content: str  # The SKILL.md text
    version: int = 0
    score: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)
    rejected_edits: list[str] = field(default_factory=list)

    def apply_edit(self, new_content: str, score: float, rationale: str) -> None:
        """Accept an edit — bump version, record history."""
        self.history.append(
            {
                "version": self.version,
                "content": self.content,
                "score": self.score,
                "replaced_at": datetime.now(UTC).isoformat(),
            }
        )
        self.content = new_content
        self.score = score
        self.version += 1

    def reject_edit(self, proposed_content: str, reason: str) -> None:
        """Record a rejected edit so we don't re-propose it."""
        self.rejected_edits.append(proposed_content[:200])
        if len(self.rejected_edits) > MAX_REJECTED_BUFFER:
            self.rejected_edits.pop(0)


@dataclass
class ToolDefinition:
    """An optimizable tool definition."""

    id: str
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    version: int = 0
    score: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)


SKILL_OPT_PROMPT = """You are a skill optimizer. Given:
1. The current skill document
2. Scored rollout evidence (successes and failures)
3. Previously rejected edits (DO NOT re-propose these)

Propose bounded edits to improve the skill. You may:
- ADD a new rule/instruction (max {lr} additions per pass)
- DELETE a rule that causes failures
- REPLACE a rule with a better version

Rules:
- Each edit must be justified by evidence from the rollouts
- Total edits must not exceed {lr} (textual learning rate)
- Do not propose edits similar to previously rejected ones
- Preserve rules that correlate with successes

Return JSON:
{{
  "edits": [
    {{"type": "add"|"delete"|"replace", "target": "line or rule", "content": "new text", "evidence": "why"}}
  ],
  "new_skill_content": "the full updated skill document after edits",
  "expected_improvement": "what should get better and why"
}}"""


async def optimize_skill(
    skill: SkillDocument,
    successes: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run one SkillOpt pass. Returns proposed edits + new content."""
    base = os.environ.get("LITELLM_API_BASE", "")
    key = os.environ.get("LITELLM_API_KEY", "")
    if not base or not key:
        return {"error": "No LLM configured"}
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    messages = [
        {"role": "system", "content": SKILL_OPT_PROMPT.format(lr=TEXTUAL_LEARNING_RATE)},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_skill": skill.content,
                    "successes": successes[:5],
                    "failures": failures[:5],
                    "rejected_edits": skill.rejected_edits[-5:],
                }
            ),
        },
    ]

    try:
        async with shared_client(timeout=60.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gemini-3.5-flash",
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"error": str(e)}


async def optimize_tool(
    tool: ToolDefinition,
    call_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Optimize a tool's description and parameter schema based on usage."""
    base = os.environ.get("LITELLM_API_BASE", "")
    key = os.environ.get("LITELLM_API_KEY", "")
    if not base or not key:
        return {"error": "No LLM configured"}
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    messages = [
        {
            "role": "system",
            "content": (
                "You optimize tool definitions for AI agents. Given a tool's current description, "
                "parameter schema, and recent call results (successes/failures), propose improvements. "
                'Return JSON: {"new_description": "...", "new_parameters": {...}, "rationale": "..."}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "tool_name": tool.name,
                    "current_description": tool.description,
                    "current_parameters": tool.parameters,
                    "recent_calls": call_results[:10],
                }
            ),
        },
    ]

    try:
        async with shared_client(timeout=60.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gemini-3.5-flash",
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"error": str(e)}
