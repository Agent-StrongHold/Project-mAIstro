"""Direct strategy: single LLM call, no tools.

Warden post-scan ensures the LLM response is checked for injected
instructions before being returned to the caller, matching the
defense-in-depth approach used by ReactStrategy for tool results.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.quota.usage_report import reported_usage
from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategy.direct")


def _counted(reported: tuple[int, int] | None) -> tuple[int, int, int]:
    """`(input, output, reporting calls)` for one provider call.

    The trailing count is what separates a call that reported zero tokens from
    one that reported nothing: both give `(0, 0)`, and only one of them was
    measured (#717).
    """
    if reported is None:
        return 0, 0, 0
    return reported[0], reported[1], 1


class DirectStrategy:
    """Single LLM call. No tools. Warden-scanned response."""

    async def _complete(
        self,
        llm: LLMClient,
        messages: list[dict[str, Any]],
        model: str,
        trace: Trace | None,
    ) -> tuple[dict[str, Any], int, int, int]:
        """One completion, recording a span when tracing is on.

        Returns the response and the turn's usage as `(input, output, reporting
        calls)`. A direct turn is one provider call, so the count is 1 or 0 --
        but it is a count either way, because `(0, 0, 0)` and `(0, 0, 1)` are
        the two facts `usage.get(..., 0)` used to store identically (#717). The
        span still takes the zero: `set_usage` counts tokens and has nowhere to
        put an absence, the same trade `extract_usage` makes for the quota log.

        Split out of `reason` for the reason `ReactStrategy._call_llm` was: the
        trace-or-not branch doubles every statement inside it, and resolving the
        usage in `reason` took it past the complexity ceiling.
        """
        if not trace:
            response = await llm.complete(messages, model)
            return response, *_counted(reported_usage(response))
        with trace.span("llm_call_0") as ls:
            ls.set_input({"model": model, "message_count": len(messages)})
            response = await llm.complete(messages, model)
            usage = _counted(reported_usage(response))
            ls.set_usage(input_tokens=usage[0], output_tokens=usage[1], model=model)
        return response, *usage

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
        response, total_input, total_output, reported_calls = await self._complete(
            llm, messages, model, trace
        )

        choices = response.get("choices", [])
        choice = choices[0] if choices else {}
        content = choice.get("message", {}).get("content", "")

        if warden is not None and content:
            verdict = await warden.scan(content, "tool_result")
            if not verdict.clean:
                flags_str = ", ".join(verdict.flags)
                logger.warning("Warden blocked DirectStrategy response: %s", flags_str)
                return ReasoningResult(
                    response=(
                        f"[Response blocked by Warden: {flags_str}. "
                        "The response contained content that matched security "
                        "patterns. Please rephrase your request.]"
                    ),
                    done=True,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    usage_reported_calls=reported_calls,
                )

        if content:
            try:
                from maistro.security.sentinel.pii_filter import scan_and_redact

                content, pii_matches = scan_and_redact(content)
                if pii_matches:
                    logger.info(
                        "DirectStrategy PII redacted: %d pattern(s): %s",
                        len(pii_matches),
                        ", ".join(m.pii_type for m in pii_matches),
                    )
            except ImportError:
                pass

        return ReasoningResult(
            response=content,
            done=True,
            input_tokens=total_input,
            output_tokens=total_output,
            usage_reported_calls=reported_calls,
        )
