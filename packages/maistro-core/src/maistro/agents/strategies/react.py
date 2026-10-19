"""React strategy: LLM -> tool calls -> execute -> feed back -> repeat.

This is the core tool loop, ported from Conductor main.py:486-609.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from maistro.agents.tool_dispatch import dispatch_tool_call
from maistro.quota.usage_report import reported_usage
from maistro.security.sentinel.audit import log_scoped_tool_denial
from maistro.security.warden.detector import WardenContext
from maistro.tools.contracts import ToolArgumentError, validate_tool_arguments
from maistro.types.agent import ReasoningResult
from maistro.types.tool import ToolCall

_TOOL_CONTEXT_MAX_TURNS = 8

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategies.react")


def _raw_arguments_error(raw_args: str, tool_name: str) -> str | None:
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        return f"Error: malformed arguments for tool '{tool_name}'"
    if not isinstance(parsed, dict):
        return f"Error: arguments for tool '{tool_name}' must be an object"
    return None


def _validate_model_tool_call(
    tools: list[dict[str, Any]] | None,
    tool_name: str,
    tool_args: dict[str, Any],
    allowed_tools: frozenset[str] | None,
    raw_error: str | None,
) -> tuple[bool, str | None, dict[str, Any], str]:
    """Return a refusal, if any, before Sentinel/provider dispatch.

    The fourth element is the host-owned denial reason for the scoped audit
    record (#847); it is empty when the call is admitted.
    """
    schema = _find_tool_schema(tools, tool_name)
    if allowed_tools is None:
        return False, None, schema, ""
    if raw_error is not None:
        return True, raw_error, schema, "malformed tool arguments"
    if tool_name not in allowed_tools:
        return (
            True,
            f"Error: tool '{tool_name}' is not in the Agent allowlist",
            schema,
            "tool not in agent allowlist",
        )
    if not schema:
        return (
            True,
            f"Error: no schema is registered for tool '{tool_name}'",
            schema,
            "no schema registered for requested tool",
        )
    try:
        validate_tool_arguments(schema, tool_args)
    except ToolArgumentError as exc:
        return (
            True,
            f"Error: invalid arguments for tool '{tool_name}': {exc}",
            schema,
            "invalid tool arguments",
        )
    return False, None, schema, ""


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


def _model_message(response: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    """Extract the assistant message and its tool calls from one completion."""
    choices = response.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return message, []
    return message, tool_calls


def _truncate_tool_result(tool_result: Any) -> str:
    tool_result_str = str(tool_result)
    if len(tool_result_str) <= 16384:
        return tool_result_str
    return (
        tool_result_str[:16384]
        + f"\n[... truncated, {len(str(tool_result)) - 16384} bytes omitted]"
    )


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
        # How many of this loop's provider calls reported usage. A ReAct turn
        # stores one summed pair, so without the count a turn whose providers
        # reported nothing is stored as one that cost nothing (#717).
        reported_calls = 0
        security_pipeline = bool(kwargs.get("security_pipeline", False))
        # Keep the analysis context separate from the model message list. Tool
        # output is untrusted; assistant/system messages must not become part of
        # the detector's authority-labelled input.
        tool_context: deque[WardenContext] = deque(maxlen=_TOOL_CONTEXT_MAX_TURNS)

        tool_choice = "required" if self.force_tool_first else "auto"
        # #847: the Agent wires its audit log so a refusal here leaves scoped
        # authorization-denied evidence, not only a returned error string.
        audit_log = kwargs.get("audit_log")
        identity = kwargs.get("identity")
        agent_name = getattr(identity, "name", "") if identity is not None else ""

        for round_num in range(self.max_rounds + 1):
            if round_num > 0:
                tool_choice = "auto"

            response = await self._call_llm(
                llm, current_messages, model, tools, tool_choice, trace, round_num
            )

            reported = reported_usage(response)
            if reported is not None:
                total_input_tokens += reported[0]
                total_output_tokens += reported[1]
                reported_calls += 1

            message, tool_calls = _model_message(response)

            if not tool_calls or round_num >= self.max_rounds:
                content = message.get("content", "")
                return ReasoningResult(
                    response=content,
                    done=True,
                    tool_history=tool_history,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    usage_reported_calls=reported_calls,
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
                    allowed_tools=(
                        frozenset(kwargs["allowed_tools"]) if "allowed_tools" in kwargs else None
                    ),
                    context=list(tool_context),
                    security_pipeline=security_pipeline,
                    tool_round=round_num,
                    audit_log=audit_log,
                    agent_name=agent_name,
                )
                tool_context.append(WardenContext(tool_result_str))

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
            usage_reported_calls=reported_calls,
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
            # The span records tokens and has nowhere to put an absence. One
            # parser decides what "reported" means, here and at the two seams
            # that store the total (#717).
            reported = reported_usage(response) or (0, 0)
            ls.set_usage(
                input_tokens=reported[0],
                output_tokens=reported[1],
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
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            logger.warning("Malformed tool arguments for %s: %s", tool_name, raw_args[:200])
            return {}, None
        if not isinstance(parsed, dict):
            return {}, f"Error: arguments for tool '{tool_name}' must be an object"
        return parsed, None

    async def _run_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_executor: Any,
        trace: Trace | None,
        *,
        tool_call_id: str = "",
        tool_round: int = 0,
    ) -> Any:
        """Invoke the tool executor, recording a trace span when tracing is on."""
        if not (tool_executor and callable(tool_executor)):
            return f"Tool '{tool_name}' not available"
        call = ToolCall(id=tool_call_id, name=tool_name, arguments=tool_args)
        if not trace:
            return await dispatch_tool_call(tool_executor, call, tool_round=tool_round)
        with trace.span(f"tool.{tool_name}") as ts:
            ts.set_input(tool_args)
            tool_result = await dispatch_tool_call(tool_executor, call, tool_round=tool_round)
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
        context: list[WardenContext] | None = None,
        security_pipeline: bool = False,
    ) -> str:
        """Apply the shared output gate with bounded prior tool context.

        Inside the Agent security pipeline the governed executor has already
        scanned the result with its own bounded context and redacted it, so
        this gate only serves standalone strategy callers.
        """
        if security_pipeline:
            return tool_result_str
        scan_kwargs: dict[str, Any] = {"context": context} if context else {}
        if sentinel is not None and auth is not None:
            sanitized: str = await sentinel.post_call(
                tool_name, tool_result_str, auth, **scan_kwargs
            )
            return sanitized

        if warden is not None:
            verdict = await warden.scan(tool_result_str, "tool_result", **scan_kwargs)
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

    async def _sentinel_admission(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_schema: dict[str, Any],
        *,
        sentinel: Any,
        auth: Any,
    ) -> tuple[dict[str, Any], str | None]:
        """Run Sentinel pre-call admission; returns ``(args, refusal_or_None)``."""
        sentinel_verdict = await sentinel.pre_call(tool_name, tool_args, auth, tool_schema)
        if not sentinel_verdict.allowed:
            return tool_args, f"Error: Permission denied for tool '{tool_name}'"
        if not sentinel_verdict.repaired_data:
            return tool_args, None
        repaired = sentinel_verdict.repaired_data
        if tool_schema:
            try:
                validate_tool_arguments(tool_schema, repaired)
            except ToolArgumentError as exc:
                return tool_args, f"Error: repaired arguments are invalid: {exc}"
        return repaired, None

    async def _admit_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        raw_args: str,
        error_result: str | None,
        *,
        tools: list[dict[str, Any]] | None,
        sentinel: Any,
        auth: Any,
        allowed_tools: frozenset[str] | None,
        security_pipeline: bool,
    ) -> tuple[bool, str | None, dict[str, Any], str]:
        """Admission gate before Sentinel/provider dispatch (#57/#847).

        Returns ``(blocked, refusal, schema, denial_reason, tool_args)`` where
        ``tool_args`` carries Sentinel's repaired arguments when admission
        repaired them. The refusal and the host-owned denial reason travel
        together so the caller can audit the decision at the same boundary
        that made it.
        """
        # The model can return a name outside the Agent declaration or a name
        # absent from the host schema even when the provider accepts it. Both
        # cases are hard refusals before Sentinel/provider dispatch (#57).
        raw_error = _raw_arguments_error(raw_args, tool_name)
        blocked, refusal, schema, denial_reason = _validate_model_tool_call(
            tools, tool_name, tool_args, allowed_tools, raw_error
        )
        blocked = blocked or error_result is not None
        if error_result is not None and not denial_reason:
            denial_reason = "malformed tool arguments"
        if blocked or security_pipeline:
            return blocked, refusal, schema, denial_reason, tool_args

        if sentinel is None or auth is None:
            logger.warning(
                "Denied tool '%s': no Sentinel or caller auth to authorize it", tool_name
            )
            return (
                True,
                f"Error: Permission denied for tool '{tool_name}'",
                schema,
                "no sentinel or caller auth to authorize tool",
                tool_args,
            )
        tool_args, refusal = await self._sentinel_admission(
            tool_name, tool_args, schema, sentinel=sentinel, auth=auth
        )
        return blocked or refusal is not None, refusal, schema, denial_reason, tool_args

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
        allowed_tools: frozenset[str] | None = None,
        context: list[WardenContext] | None = None,
        security_pipeline: bool = False,
        tool_round: int = 0,
        audit_log: Any = None,
        agent_name: str = "",
    ) -> tuple[dict[str, Any], str]:
        """Process a single tool call end-to-end: parse args, sentinel pre-call,
        execute, truncate, sanitize. Returns ``(tool_args, tool_result_str)``."""
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        tool_args, error_result = self._parse_tool_args(tool_name, raw_args)

        tool_blocked, refusal, tool_schema, denial_reason, tool_args = await self._admit_tool_call(
            tool_name,
            tool_args,
            raw_args,
            error_result,
            tools=tools,
            sentinel=sentinel,
            auth=auth,
            allowed_tools=allowed_tools,
            security_pipeline=security_pipeline,
        )
        tool_result: Any = refusal or error_result

        if tool_blocked and refusal is not None and audit_log is not None:
            await log_scoped_tool_denial(
                audit_log,
                tool_name=tool_name,
                reason=denial_reason or "refused before sentinel dispatch",
                auth=auth,
                agent_name=agent_name,
            )

        if not tool_blocked:
            tool_result = await self._run_tool(
                tool_name,
                tool_args,
                tool_executor,
                trace,
                tool_call_id=tc.get("id", ""),
                tool_round=tool_round,
            )
        elif refusal is not None:
            tool_result = refusal

        tool_result_str = _truncate_tool_result(tool_result)

        tool_result_str = await self._sanitize_tool_result(
            tool_name,
            tool_result_str,
            sentinel=sentinel,
            auth=auth,
            warden=warden,
            context=context,
            security_pipeline=security_pipeline,
        )
        return tool_args, tool_result_str
