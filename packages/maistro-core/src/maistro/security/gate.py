"""Gate: input processing -- sanitize, scan, strike, clarify.

The Gate is the first thing user input touches. Three execution modes:
- best_effort: sanitize + Warden scan. Block if malicious, pass through otherwise.
- persistent: + request sufficiency check. Returns clarifying questions if insufficient.
- supervised: always returns clarifying questions (human-in-the-loop).

Strike escalation (when Warden blocks):
- Strike 1: Warning; the account's scrutiny level is recorded as "elevated"
  and surfaced to callers in GateResult. (It does not change the scan path
  today — an earlier version of this docstring promised "L3 classifier
  enabled", but scan() takes no scrutiny input and the container wires no
  LLM into the Warden, so that line claimed a code path that did not exist.)
- Strike 2: 8-hour lockout (admin+ to unlock)
- Strike 3: Account disabled (admin+ to re-enable)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.observability.metrics import maistro_security_block_total
from maistro.security._types import ClarifyingQuestion, GateResult
from maistro.security.request_analyzer import analyze_request_sufficiency
from maistro.security.warden.sanitizer import sanitize

if TYPE_CHECKING:
    from maistro.protocols import StrikeTracker
    from maistro.security._types import AuthContext
    from maistro.security.warden.detector import Warden

logger = logging.getLogger("maistro.gate")


class Gate:
    """Processes user input before it reaches the agent pipeline.

    Takes Warden and StrikeTracker as constructor dependencies (DI).
    """

    def __init__(
        self,
        warden: Warden | None = None,
        strike_tracker: StrikeTracker | None = None,
    ) -> None:
        if warden is None:
            from maistro.security.warden.detector import Warden as WardenImpl

            warden = WardenImpl()
        self._warden = warden
        self._strike_tracker = strike_tracker

    async def process_input(
        self,
        content: str,
        *,
        execution_mode: str = "best_effort",
        task_type: str = "chat",
        conversation_context: list[dict[str, str]] | None = None,
        auth: AuthContext | None = None,
    ) -> GateResult:
        user_id = auth.user_id if auth else ""

        if self._strike_tracker and user_id:
            record = await self._strike_tracker.get(user_id)
            if record and record.is_locked:
                locked_str = record.locked_until.isoformat() if record.locked_until else ""
                if record.disabled:
                    maistro_security_block_total.inc(gate="strikes", reason="account_disabled")
                    return GateResult(
                        blocked=True,
                        block_reason=(
                            "Your account has been disabled due to repeated security violations. "
                            "An administrator must re-enable your account."
                        ),
                        strike_number=record.strike_count,
                        scrutiny_level=record.scrutiny_level,
                        locked_until=locked_str,
                        account_disabled=True,
                    )
                maistro_security_block_total.inc(gate="strikes", reason="account_locked")
                return GateResult(
                    blocked=True,
                    block_reason=(
                        "Your account is temporarily locked due to security violations. "
                        "An administrator must unlock your account, or the lockout "
                        f"expires at {locked_str}."
                    ),
                    strike_number=record.strike_count,
                    scrutiny_level=record.scrutiny_level,
                    locked_until=locked_str,
                )

        sanitized = sanitize(content)

        verdict = await self._warden.scan(sanitized, "user_input")

        if not verdict.clean:
            strike_number = 0
            scrutiny_level = "normal"
            locked_until = ""
            disabled = False

            if self._strike_tracker and user_id:
                record = await self._strike_tracker.record_violation(
                    user_id=user_id,
                    flags=verdict.flags,
                    boundary="user_input",
                    detail=f"Gate block: {', '.join(verdict.flags)}",
                )
                strike_number = record.strike_count
                scrutiny_level = record.scrutiny_level
                locked_until = record.locked_until.isoformat() if record.locked_until else ""
                disabled = record.disabled

            logger.warning(
                "GATE BLOCK: user=%s flags=%s strike=%d level=%s",
                user_id or "anonymous",
                verdict.flags,
                strike_number,
                scrutiny_level,
            )

            # Warden flags are a bounded detector taxonomy, so the primary
            # flag is a safe (low-cardinality) reason label.
            maistro_security_block_total.inc(
                gate="warden",
                reason=next(iter(verdict.flags), "unclean"),
            )

            return GateResult(
                sanitized_text=sanitized,
                warden_verdict=verdict,
                blocked=True,
                block_reason=f"Blocked by Warden: {', '.join(verdict.flags)}",
                strike_number=strike_number,
                scrutiny_level=scrutiny_level,
                locked_until=locked_until,
                account_disabled=disabled,
            )

        if execution_mode == "persistent":
            questions = _check_sufficiency(sanitized, task_type, conversation_context)
            if questions is not None:
                return GateResult(
                    sanitized_text=sanitized,
                    warden_verdict=verdict,
                    clarifying_questions=tuple(questions),
                )

        if execution_mode == "supervised":
            questions = _check_sufficiency(sanitized, task_type, conversation_context)
            if not questions:
                questions = [
                    ClarifyingQuestion(
                        question="I understood your request. Should I proceed?",
                        options=("Yes, go ahead", "No, let me clarify"),
                        allow_freetext=True,
                    )
                ]
            return GateResult(
                sanitized_text=sanitized,
                warden_verdict=verdict,
                clarifying_questions=tuple(questions),
            )

        return GateResult(
            sanitized_text=sanitized,
            warden_verdict=verdict,
        )


def _check_sufficiency(
    text: str,
    task_type: str,
    context: list[dict[str, str]] | None,
) -> list[ClarifyingQuestion] | None:
    """Request sufficiency check for persistent/supervised modes.

    Delegates to `analyze_request_sufficiency` for per-task-type WHAT/WHERE/
    HOW/CONTEXT signal scoring and conversation-aware confirmation-hijack
    guarding. Returns None if sufficient, list of ClarifyingQuestion if not.
    """
    if not text.strip():
        return [
            ClarifyingQuestion(
                question="Your request appears to be empty. What would you like me to do?",
                allow_freetext=True,
            )
        ]

    result = analyze_request_sufficiency(text, task_type, conversation_context=context)
    if result.sufficient:
        return None

    return [
        ClarifyingQuestion(question=detail.question, allow_freetext=True)
        for detail in result.missing
    ]
