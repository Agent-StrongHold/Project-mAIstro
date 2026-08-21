"""Artificer strategy: plan -> architect -> phase loop (code -> check -> fix -> commit)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.artificer")

StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


_MAX_ARG_BYTES = 32_768
_MAX_RESULT_BYTES = 16_384


class ArtificerStrategy:
    """Multi-phase engineering workflow.

    1. Plan: decompose into phases
    2. For each phase:
       a. Write code (via write_file tool)
       b. Run quality checks (pytest, ruff, mypy, bandit)
       c. If fail: fix and recheck (max 2 retries)
       d. Commit when green
    3. Return summary of all phases
    """

    def __init__(
        self,
        max_phases: int = 5,
        max_retries_per_phase: int = 2,
    ) -> None:
        self.max_phases = max_phases
        self.max_retries = max_retries_per_phase

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        status_callback: StatusCallback | None = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        tool_history: list[dict[str, Any]] = []
        status = status_callback or _noop_status

        await status("Planning...")
        if trace:
            with trace.span("artificer.plan") as ps:
                ps.set_input({"model": model, "message_count": len(messages)})
                plan = await self._plan(messages, model, llm)
                ps.set_output({"plan_length": len(plan), "plan_lines": plan.count("\n")})
        else:
            plan = await self._plan(messages, model, llm)

        await status(f"Plan complete ({plan.count(chr(10))} lines)")
        logger.info("Artificer plan generated: %d chars", len(plan))

        await asyncio.sleep(2)

        results: list[str] = [f"## Plan\n{plan}"]
        current_messages = list(messages)
        current_messages.append({"role": "assistant", "content": plan})

        execute_prompt = (
            "Now execute the plan above. For each step:\n"
            "1. Use write_file to create/modify files\n"
            "2. Use run_pytest to verify tests pass\n"
            "3. Use run_ruff_check and run_mypy to verify code quality\n"
            "4. Use git_commit when a step is complete\n\n"
            "Execute step by step. Start with step 1."
        )
        current_messages.append({"role": "user", "content": execute_prompt})

        await status("Executing plan...")

        for round_num in range(self.max_phases * 3):
            response = await self._call_llm(llm, current_messages, model, tools, trace, round_num)

            choices = response.get("choices", [])
            choice = choices[0] if choices else {}
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            if not tool_calls:
                content = message.get("content", "")
                results.append(f"\n## Result\n{content}")
                await status("Complete")
                return ReasoningResult(
                    response="\n\n".join(results),
                    done=True,
                    tool_history=tool_history,
                )

            current_messages.append(message)

            for tc in tool_calls:
                tool_args, result_str = await self._handle_tool_call(
                    tc,
                    tool_executor=tool_executor,
                    trace=trace,
                    status=status,
                    sentinel=kwargs.get("sentinel"),
                    auth=kwargs.get("auth"),
                    warden=kwargs.get("warden"),
                )
                tool_history.append(
                    {
                        "tool_name": tc.get("function", {}).get("name", ""),
                        "arguments": tool_args,
                        "result": result_str,
                        "round": round_num,
                    }
                )
                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result_str,
                    }
                )

            await asyncio.sleep(1)

        await status("Max rounds reached")
        return ReasoningResult(
            response="\n\n".join(results) + "\n\nMax rounds reached.",
            done=True,
            tool_history=tool_history,
        )

    async def _call_llm(
        self,
        llm: LLMClient,
        current_messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        trace: Trace | None,
        round_num: int,
    ) -> dict[str, Any]:
        """Run one LLM completion (tool_choice='auto'), tracing when enabled."""
        if not trace:
            return await llm.complete(current_messages, model, tools=tools, tool_choice="auto")
        with trace.span(f"llm_call_{round_num}") as ls:
            ls.set_input({"model": model, "message_count": len(current_messages)})
            response = await llm.complete(current_messages, model, tools=tools, tool_choice="auto")
            usage = response.get("usage", {})
            ls.set_usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=model,
            )
        return response

    async def _run_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_executor: Any,
        trace: Trace | None,
    ) -> Any:
        """Invoke the tool executor, recording a trace span when tracing is on."""
        if not (tool_executor and callable(tool_executor)):
            return f"Tool '{tool_name}' not available"
        if not trace:
            return await tool_executor(tool_name, tool_args)
        with trace.span(f"tool.{tool_name}") as ts:
            ts.set_input(tool_args)
            tool_result = await tool_executor(tool_name, tool_args)
            result_preview = str(tool_result)[:300]
            tool_success = (
                '"passed": true' in result_preview
                or '"status": "ok"' in result_preview
                or (
                    not result_preview.startswith("Error")
                    and "error" not in result_preview[:50].lower()
                )
            )
            ts.set_output({"success": tool_success, "result_preview": result_preview})
        return tool_result

    async def _sanitize_result(
        self,
        tool_name: str,
        result_str: str,
        *,
        sentinel: Any,
        auth: Any,
        warden: Any,
    ) -> str:
        """Apply sentinel post-call, or warden scan, to a tool result string."""
        if sentinel is not None and auth is not None:
            sanitized: str = await sentinel.post_call(tool_name, result_str, auth)
            return sanitized
        if warden is not None:
            verdict = await warden.scan(result_str, "tool_result")
            if not verdict.clean:
                result_str = (
                    f"[BLOCKED: tool result contained suspicious content: "
                    f"{', '.join(verdict.flags)}]"
                )
        return result_str

    async def _emit_result_status(self, tool_name: str, result_str: str, status: Any) -> None:
        """Surface a coarse pass/fail/error status from the tool result preview."""
        result_preview = result_str[:200]
        if '"passed": true' in result_preview or '"status": "ok"' in result_preview:
            await status(f"{tool_name}: OK")
        elif '"passed": false' in result_preview:
            await status(f"{tool_name}: FAILED -- fixing...")
        elif '"error":' in result_preview and '"status": "failed"' in result_preview:
            await status(f"{tool_name}: error -- retrying...")

    async def _handle_tool_call(
        self,
        tc: dict[str, Any],
        *,
        tool_executor: Any,
        trace: Trace | None,
        status: Any,
        sentinel: Any,
        auth: Any,
        warden: Any,
    ) -> tuple[dict[str, Any], str]:
        """Process a single tool call end-to-end. Returns ``(tool_args, result_str)``."""
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        try:
            tool_args = json.loads(raw_args)
        except json.JSONDecodeError:
            logger.warning("Malformed tool arguments for %s: %s", tool_name, raw_args[:200])
            tool_args = {}

        if len(raw_args.encode("utf-8")) > _MAX_ARG_BYTES:
            logger.warning(
                "Tool %s arg size %d exceeds %d limit",
                tool_name,
                len(raw_args.encode("utf-8")),
                _MAX_ARG_BYTES,
            )
            return tool_args, f"Error: tool arguments exceed {_MAX_ARG_BYTES} byte limit"

        tool_blocked = False
        if sentinel is not None and auth is not None:
            sentinel_verdict = await sentinel.pre_call(tool_name, tool_args, auth, {})
            if not sentinel_verdict.allowed:
                tool_result: Any = f"Error: Permission denied for tool '{tool_name}'"
                tool_blocked = True
            elif sentinel_verdict.repaired_data:
                tool_args = sentinel_verdict.repaired_data

        await status(f"Running {tool_name}...")
        logger.info("Tool call: %s(%s)", tool_name, list(tool_args.keys()))

        if not tool_blocked:
            tool_result = await self._run_tool(tool_name, tool_args, tool_executor, trace)

        result_str = tool_result if isinstance(tool_result, str) else str(tool_result)
        if len(result_str) > _MAX_RESULT_BYTES:
            omitted = len(str(tool_result)) - _MAX_RESULT_BYTES
            result_str = (
                result_str[:_MAX_RESULT_BYTES] + f"\n[... truncated, {omitted} bytes omitted]"
            )

        result_str = await self._sanitize_result(
            tool_name, result_str, sentinel=sentinel, auth=auth, warden=warden
        )
        await self._emit_result_status(tool_name, result_str, status)
        return tool_args, result_str

    async def _plan(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
    ) -> str:
        plan_messages = list(messages)
        plan_messages.append(
            {
                "role": "user",
                "content": (
                    "Before writing any code, create a detailed plan. "
                    "Break the task into numbered phases. For each phase:\n"
                    "- What files to create/modify\n"
                    "- What tests to write\n"
                    "- What the acceptance criteria are\n\n"
                    "Output ONLY the plan, no code yet."
                ),
            }
        )

        response = await llm.complete(plan_messages, model)
        choices = response.get("choices", [])
        choice = choices[0] if choices else {}
        content: str = choice.get("message", {}).get("content", "No plan generated")
        return content
