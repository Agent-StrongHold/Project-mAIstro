"""The one competent-model policy all three benchmark arms share.

The benchmark compares *structures*, not model quality: ReAct
(``ReactStrategy``), explicit plan-and-execute (``PlanExecuteStrategy`` plus
one executor loop per planned subtask), and the canonical Graph role pipeline
(``GraphRun`` planner -> coder -> reviewer) are all driven by this same
deterministic policy. It executes each Goal's minimal program against the
shared world, retries an injected transient tool error exactly once, and
stops at a true dead end. Any difference the benchmark measures between arms
is therefore attributable to the planning/execution structure alone.

Two call surfaces, one policy:

- ``complete()`` -- OpenAI-shaped, for the strategy arms (tool loop turns and
  the plan-execute planner call);
- ``graph_llm_call()`` -- the ``llm_call(messages, model=..., temperature=...)``
  string-returning surface ``GraphRun``/``NodeRun`` drives, role-detected from
  the graph's system prompts.

Failure injection (``fail_on_call``) is keyed by 1-based call ordinal and is
how the recovery cells arm a transient provider failure for every arm alike.
"""

from __future__ import annotations

import json
from typing import Any

from ._world import (
    TRANSIENT_ERROR_PREFIX,
    UNKNOWN_KEY_PREFIX,
    GoalSpec,
    GoalWorld,
)

#: Graph system prompts (``maistro.graph.types.DEFAULT_SYSTEM_PROMPTS``).
_PLANNER_MARKER = "expert software planner"
_CODER_MARKER = "expert software developer"
_REVIEWER_MARKER = "senior code reviewer"

#: Plan-execute planner system prompt (``PlanExecuteStrategy.reason``).
_PLAN_EXEC_PLANNER_MARKER = "task planner"

_SUBTASK_DIRECTIVE = "Execute subtask: "


def _marker(messages: list[dict[str, Any]], needle: str) -> bool:
    for message in messages:
        if message.get("role") == "system" and needle in str(message.get("content", "")):
            return True
    return False


class PolicyModel:
    """Deterministic competent model implementing the shared Goal policy."""

    def __init__(
        self,
        spec: GoalSpec,
        world: GoalWorld,
        *,
        prompt_tokens_per_call: int = 40,
        completion_tokens_per_call: int = 30,
    ) -> None:
        self.spec = spec
        self.world = world
        self.prompt_tokens_per_call = prompt_tokens_per_call
        self.completion_tokens_per_call = completion_tokens_per_call
        self.calls_made = 0
        self.call_log: list[str] = []
        #: 1-based call ordinal -> exception to raise instead of answering.
        self.fail_on_call: dict[int, Exception] = {}

    # ------------------------------------------------------------------
    # accounting

    @property
    def llm_calls(self) -> int:
        return self.calls_made

    def _bump(self, surface: str) -> None:
        self.calls_made += 1
        self.call_log.append(f"{self.calls_made}:{surface}")
        exc = self.fail_on_call.get(self.calls_made)
        if exc is not None:
            raise exc

    def _usage(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens_per_call,
            "completion_tokens": self.completion_tokens_per_call,
            "total_tokens": self.prompt_tokens_per_call + self.completion_tokens_per_call,
        }

    # ------------------------------------------------------------------
    # program-state derivation (stateless across calls: read from the ledger)

    def _step_done(self, index: int) -> bool:
        return any(r.ok for r in self.world.ledger.calls_for(self.spec.steps[index]))

    def _first_incomplete_step(self) -> int | None:
        for index in range(len(self.spec.steps)):
            if not self._step_done(index):
                return index
        return None

    def _transient_error(self, records: list[Any]) -> bool:
        return bool(records) and all(r.result.startswith(TRANSIENT_ERROR_PREFIX) for r in records)

    def _dead_end(self, records: list[Any]) -> bool:
        return bool(records) and all(r.result.startswith(UNKNOWN_KEY_PREFIX) for r in records)

    # ------------------------------------------------------------------
    # surfaces

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str = "bench-model",
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        """OpenAI-shaped surface: plan-execute planner + every tool-loop turn."""
        self._bump("complete")
        if tools is None and _marker(messages, _PLAN_EXEC_PLANNER_MARKER):
            content = self._plan_text()
            return self._content_response(content)

        # Tool-loop turn (ReactStrategy rounds and plan-execute executor loops).
        restriction = self._subtask_restriction(messages)
        return self._next_action_response(restriction)

    async def graph_llm_call(
        self,
        messages: list[dict[str, Any]],
        model: str = "bench-model",
        temperature: float | None = None,
        **_extra: Any,
    ) -> tuple[str, dict[str, int]]:
        """``GraphRun`` surface: role-detected from the graph's system prompt."""
        self._bump("graph")
        if _marker(messages, _PLANNER_MARKER):
            return self._with_usage(json.dumps(self._plan_output()))
        if _marker(messages, _CODER_MARKER):
            description = await self._execute_remaining_program()
            code = {
                "files_changed": [],
                "description": description,
                "tests_added": False,
            }
            return self._with_usage(json.dumps(code))
        if _marker(messages, _REVIEWER_MARKER):
            review = self._review_output()
            return self._with_usage(json.dumps(review))
        raise AssertionError(f"policy could not detect a graph role in: {messages!r}")

    # ------------------------------------------------------------------
    # strategy-arm actions

    def _plan_text(self) -> str:
        lines = [f"{i + 1}. {step.describe()}" for i, step in enumerate(self.spec.steps)]
        return "\n".join(lines)

    def _subtask_restriction(self, messages: list[dict[str, Any]]) -> int | None:
        """Index into ``spec.steps`` a plan-execute executor loop is scoped to."""
        for message in reversed(messages):
            content = str(message.get("content", ""))
            if message.get("role") == "user" and content.startswith(_SUBTASK_DIRECTIVE):
                line = content[len(_SUBTASK_DIRECTIVE) :]
                number = line.split(".", 1)[0].strip()
                if number.isdigit():
                    return int(number) - 1
        return None

    def _next_action_response(self, restriction: int | None) -> dict[str, Any]:
        if restriction is not None:
            step = self.spec.steps[restriction]
            records = self.world.ledger.calls_for(step)
            if any(r.ok for r in records):
                return self._content_response(f"subtask done: {step.describe()}")
            if self._dead_end(records) or (self._transient_error(records) and len(records) >= 2):
                return self._content_response(f"answer: {self.spec.expected_answer}")
            return self._tool_call_response(step)

        index = self._first_incomplete_step()
        if index is None:
            return self._content_response(f"answer: {self.spec.expected_answer}")
        step = self.spec.steps[index]
        records = self.world.ledger.calls_for(step)
        if self._dead_end(records) or (self._transient_error(records) and len(records) >= 2):
            return self._content_response(f"answer: {self.spec.expected_answer}")
        return self._tool_call_response(step)

    def _tool_call_response(self, step: Any) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{self.calls_made}",
                    "type": "function",
                    "function": {
                        "name": step.tool,
                        "arguments": json.dumps(step.args),
                    },
                }
            ],
        }
        return {
            "id": "bench-response",
            "object": "chat.completion",
            "created": 0,
            "model": "bench-model",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
            "usage": self._usage(),
        }

    def _content_response(self, content: str) -> dict[str, Any]:
        message = {"role": "assistant", "content": content}
        return {
            "id": "bench-response",
            "object": "chat.completion",
            "created": 0,
            "model": "bench-model",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": self._usage(),
        }

    # ------------------------------------------------------------------
    # graph-arm roles

    def _plan_output(self) -> dict[str, Any]:
        return {
            "summary": self.spec.question,
            "subtasks": [
                {"title": f"step {i + 1}", "description": step.describe(), "file_paths": []}
                for i, step in enumerate(self.spec.steps)
            ],
            "estimated_files": [],
        }

    async def _execute_remaining_program(self) -> str:
        """The coder turn: run every not-yet-done step against the shared world.

        Same policy rules as the tool loops: retry an injected transient error
        once, stop at a true dead end, report the answer when the program
        completes. All executions land in the shared ledger like any other arm.
        """
        for index in range(len(self.spec.steps)):
            step = self.spec.steps[index]
            records = self.world.ledger.calls_for(step)
            if any(r.ok for r in records):
                continue
            if self._dead_end(records) or (self._transient_error(records) and len(records) >= 2):
                return f"answer: {self.spec.expected_answer}"
            outcome = await self.world.execute(step.tool, step.args)
            if outcome.startswith(TRANSIENT_ERROR_PREFIX):
                # The competent policy retries a transient error once, inside
                # the same turn, exactly like the tool loops do across turns.
                outcome = await self.world.execute(step.tool, step.args)
            if outcome.startswith(UNKNOWN_KEY_PREFIX) or outcome.startswith(TRANSIENT_ERROR_PREFIX):
                return f"answer: {self.spec.expected_answer}"
        return f"answer: {self.spec.expected_answer}"

    def _review_output(self) -> dict[str, Any]:
        approved = self._program_complete_or_dead_end()
        score = 10.0 if approved else 4.0
        return {
            "approved": approved,
            "score": score,
            "issues": [] if approved else ["coder output does not answer the goal"],
            "suggestions": [],
        }

    def _program_complete_or_dead_end(self) -> bool:
        for step in self.spec.steps:
            records = self.world.ledger.calls_for(step)
            if any(r.ok for r in records):
                continue
            if self._dead_end(records):
                continue
            return False
        return True

    def _with_usage(self, text: str) -> tuple[str, dict[str, int]]:
        return text, {
            "prompt_tokens": self.prompt_tokens_per_call,
            "completion_tokens": self.completion_tokens_per_call,
        }
