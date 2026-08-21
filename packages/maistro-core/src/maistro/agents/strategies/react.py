"""React strategy: LLM -> tool calls -> execute -> feed back -> repeat.

This is the core tool loop, ported from Conductor main.py:486-609.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategies.react")


def _find_tool_schema(
    tools: list[dict[str, Any]] | None,
    tool_name: str,
) -> dict[str, Any]:
    if not tools:
        return {}
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") == tool_name:
            params: dict[str, Any] = fn.get("parameters", {})
            return params
    return {}


class ReactStrategy:
    """ReAct loop: LLM call -> tool dispatch -> feed back -> repeat."""

    def __init__(
        self,
        max_rounds: int = 3,
        force_tool_first: bool = False,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        current_messages = list(messages)
        tool_history: list[dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0

        tool_choice = "required" if self.force_tool_first else "auto"

        for round_num in range(self.max_rounds + 1):
            if round_num > 0:
                tool_choice = "auto"

            response = await self._call_llm(
                llm, current_messages, model, tools, tool_choice, trace, round_num
            )

            usage = response.get("usage", {})
            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)

            choices = response.get("choices", [])
            choice = choices[0] if choices else {}
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            if not tool_calls or round_num >= self.max_rounds:
                content = message.get("content", "")
                return ReasoningResult(
                    response=content,
                    done=True,
                    tool_history=tool_history,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            current_messages.append(message)

            for tc in tool_calls:
                tool_args, tool_result_str = await self._execute_one_tool_call(
                    tc,
                    tools=tools,
                    tool_executor=tool_executor,
                    trace=trace,
                    warden=warden,
                    sentinel=kwargs.get("sentinel"),
                    auth=kwargs.get("auth"),
                )

                tool_history.append(
                    {
                        "tool_name": tc.get("function", {}).get("name", ""),
                        "arguments": tool_args,
                        "result": tool_result_str,
                        "round": round_num,
                    }
                )

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_str,
                    }
                )

        # Unreachable: line 84 always early-returns once round_num >= self.max_rounds,
        # which the last iteration of `range(self.max_rounds + 1)` always satisfies.
        return ReasoningResult(  # pragma: no cover
            response="Max tool rounds reached",
            done=True,
            tool_history=tool_history,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    async def _call_llm(
        self,
        llm: LLMClient,
        current_messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        tool_choice: str,
        trace: Trace | None,
        round_num: int,
    ) -> dict[str, Any]:
        """Run one LLM completion, recording a trace span when tracing is on."""
        if not trace:
            return await llm.complete(
                current_messages,
                model,
                tools=tools,
                tool_choice=tool_choice if tools else None,
            )
        with trace.span(f"llm_call_{round_num}") as ls:
            ls.set_input({"model": model, "message_count": len(current_messages)})
            response = await llm.complete(
                current_messages,
                model,
                tools=tools,
                tool_choice=tool_choice if tools else None,
            )
            usage = response.get("usage", {})
            ls.set_usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=model,
            )
        return response

    def _parse_tool_args(self, tool_name: str, raw_args: str) -> tuple[dict[str, Any], str | None]:
        """Parse tool-call arguments. Returns ``(args, error_result)`` where
        ``error_result`` is a pre-built error string if the args were unusable."""
        if len(raw_args) > 32768:
            logger.warning("Tool args too large for %s: %d bytes", tool_name, len(raw_args))
            return {}, f"Error: Tool arguments too large ({len(raw_args)} bytes)"
        try:
            return json.loads(raw_args), None
        except json.JSONDecodeError:
            logger.warning("Malformed tool arguments for %s: %s", tool_name, raw_args[:200])
            return {}, None

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
            preview = str(tool_result)[:300]
            tool_success = not preview.startswith("Error") and "error" not in preview[:50].lower()
            ts.set_output({"success": tool_success, "result_preview": preview})
        return tool_result

    async def _sanitize_tool_result(
        self,
        tool_name: str,
        tool_result_str: str,
        *,
        sentinel: Any,
        auth: Any,
        warden: Any,
    ) -> str:
        """Apply sentinel post-call (or warden scan + PII redaction) to a result."""
        if sentinel is not None and auth is not None:
            sanitized: str = await sentinel.post_call(tool_name, tool_result_str, auth)
            return sanitized

        if warden is not None:
            verdict = await warden.scan(tool_result_str, "tool_result")
            if not verdict.clean:
                tool_result_str = (
                    f"[BLOCKED: tool result contained suspicious content: "
                    f"{', '.join(verdict.flags)}]"
                )
        try:
            from maistro.security.sentinel.pii_filter import scan_and_redact

            tool_result_str, _ = scan_and_redact(tool_result_str)
        except ImportError:
            pass
        return tool_result_str

    async def _execute_one_tool_call(
        self,
        tc: dict[str, Any],
        *,
        tools: list[dict[str, Any]] | None,
        tool_executor: Any,
        trace: Trace | None,
        warden: Any,
        sentinel: Any,
        auth: Any,
    ) -> tuple[dict[str, Any], str]:
        """Process a single tool call end-to-end: parse args, sentinel pre-call,
        execute, truncate, sanitize. Returns ``(tool_args, tool_result_str)``."""
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        tool_args, error_result = self._parse_tool_args(tool_name, fn.get("arguments", "{}"))

        # NOTE: a parse error sets a placeholder result but does NOT block — the
        # original behavior falls through to execution with the (possibly empty)
        # parsed args. Only a sentinel denial blocks execution.
        tool_result: Any = error_result
        tool_blocked = False

        if sentinel is not None and auth is not None:
            tool_schema = _find_tool_schema(tools, tool_name)
            sentinel_verdict = await sentinel.pre_call(tool_name, tool_args, auth, tool_schema)
            if not sentinel_verdict.allowed:
                tool_result = f"Error: Permission denied for tool '{tool_name}'"
                tool_blocked = True
            elif sentinel_verdict.repaired_data:
                tool_args = sentinel_verdict.repaired_data

        if not tool_blocked:
            tool_result = await self._run_tool(tool_name, tool_args, tool_executor, trace)

        tool_result_str = str(tool_result)
        if len(tool_result_str) > 16384:
            tool_result_str = (
                tool_result_str[:16384]
                + f"\n[... truncated, {len(str(tool_result)) - 16384} bytes omitted]"
            )

        tool_result_str = await self._sanitize_tool_result(
            tool_name,
            tool_result_str,
            sentinel=sentinel,
            auth=auth,
            warden=warden,
        )
        return tool_args, tool_result_str
