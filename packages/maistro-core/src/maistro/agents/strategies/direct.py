"""Direct strategy: single LLM call, no tools.

Warden post-scan ensures the LLM response is checked for injected
instructions before being returned to the caller, matching the
defense-in-depth approach used by ReactStrategy for tool results.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategy.direct")


class DirectStrategy:
    """Single LLM call. No tools. Warden-scanned response."""

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
        if trace:
            with trace.span("llm_call_0") as ls:
                ls.set_input({"model": model, "message_count": len(messages)})
                response = await llm.complete(messages, model)
                usage = response.get("usage", {})
                ls.set_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=model,
                )
        else:
            response = await llm.complete(messages, model)
            usage = response.get("usage", {})

        total_input = usage.get("prompt_tokens", 0)
        total_output = usage.get("completion_tokens", 0)

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
        )
