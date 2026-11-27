"""The Sentinel output gate must not compress final answers as tool results."""

from __future__ import annotations

from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.sentinel.policy import Sentinel
from maistro.security.sentinel.token_optimizer import MAX_RESULT_LENGTH


class _StubWarden:
    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


def _auth() -> AuthContext:
    return AuthContext(user_id="u1", roles=frozenset({"user"}))


def _sentinel() -> Sentinel:
    return Sentinel(warden=_StubWarden(), permission_table={})


def _long_answer() -> str:
    return "word " * (MAX_RESULT_LENGTH // 2)


async def test_final_answer_boundary_preserves_full_sanitized_answer() -> None:
    """compress_tool_result=False skips token optimization: a long assistant
    answer reaches the client whole, with no truncation marker."""
    answer = _long_answer()

    outcome = await _sentinel().process_output(
        "assistant_response", answer, _auth(), compress_tool_result=False
    )

    assert not outcome.blocked
    assert outcome.sanitized_text == answer
    assert "[... truncated" not in outcome.sanitized_text


async def test_tool_results_are_still_compressed_by_default() -> None:
    """Default behavior is unchanged: tool results over the cap are compressed."""
    result = _long_answer()

    outcome = await _sentinel().process_output("search_tool", result, _auth())

    assert not outcome.blocked
    assert len(outcome.sanitized_text) <= MAX_RESULT_LENGTH
    assert outcome.sanitized_text.endswith("[... truncated, full result available in trace]")
