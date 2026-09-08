"""Second-opinion LLM regression check — a safety net for changes no
deterministic gate would catch: a data-shape conversion narrowed for an
untested input, a new branch riding on an unrelated test's coverage credit, an
exception handler that discards the original error type, a guard clause that
silently rejects previously-valid input. These are subtle-semantics bugs a
careful reader catches by inspection, not by running the existing suite —
that suite, by definition, doesn't yet know to look for the regression.

Deliberately narrow (see ADR-070126-6386 v3's W2S posture) and FAIL-CLOSED
(#307, superseding this module's original "must never become the thing that
blocks promotion" rationale): the objective gates (tests, coverage, syntax,
collectability) stay the primary, dumb, reliable defense and this judge only
supplements them, but when the judge is ENABLED it is REQUIRED — a gateway
error, timeout, unparsable reply, or oversized diff yields an *unavailable*
verdict (``score=None``) that fails the ``no_flagged_regression`` gate rather
than masquerading as a passing 0.7. An unavailable judge saying "promote"
is indistinguishable from no judge at all, and a silent fail-open is exactly
the posture #307 removes. Operators who prefer the old lenient behavior
disable the judge entirely (``regression_judge=false``) instead of relying
on an unobserved failure mode.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

LlmCall = Callable[..., dict[str, Any]]

# A parsed score below this is a flagged regression: the verdict becomes
# "reject" and the promotion gate vetoes. Single-sourced here so the judge's
# status mapping and the gate in candidate_fitness can never drift apart
# (the system prompt below tells the model the same threshold).
REJECT_BELOW = 0.4

# The judge only ever sees this many leading characters of the diff — enough
# context to rule, bounded prompt cost.
_MAX_DIFF_CHARS = 8000
# But slicing below half the real diff means the judge would rule on a
# partial view that hides most of the change — unavailable instead (#307).
_MIN_RETAINED_FRACTION = 0.5

_SYSTEM = (
    "You are reviewing a code diff for regressions the automated test suite "
    "would not catch. The diff already passes tests, coverage, and lint — "
    "look specifically for:\n"
    "1. A type/shape conversion narrowed or widened in a way existing tests "
    "don't exercise (e.g. str() applied to a list/dict instead of its "
    "elements, a Sequence type narrowed to list).\n"
    "2. A new branch or method added with no test exercising it, riding on "
    "an unrelated test's credit in the same diff.\n"
    "3. An exception handler that discards, re-types, or misrepresents the "
    "original exception.\n"
    "4. A guard clause or validation that would now reject previously-valid "
    "input.\n"
    'Reply with ONLY a JSON object: {"score": 0.0-1.0, "rationale": '
    '"..."}. score=1.0 means no regression risk found. score below 0.4 '
    "means you found a concrete, plausible regression — name the exact line "
    "and the failing scenario in the rationale. Do not flag style/naming "
    "preferences or vague concerns without a concrete failure scenario."
)


@dataclass(frozen=True)
class JudgeVerdict:
    """One regression-judge consultation, availability kept separate from score.

    ``status`` is "pass"/"reject" only when the judge actually RULED — "reject"
    means a parsed score below :data:`REJECT_BELOW` (a flagged regression).
    Any judge failure is "unavailable" with ``score=None`` and a ``cause``
    naming the failure class ("gateway_error", "timeout", "unparsable_reply",
    "oversized_diff"). The score of an unavailable verdict must never be
    coerced to a number — that is the fail-open posture #307 removes.
    """

    status: Literal["pass", "reject", "unavailable"]
    score: float | None  # None iff status == "unavailable"
    rationale: str
    cause: str | None = None  # failure class; None whenever the judge ruled


def judge_regression_verdict(diff_text: str, target: str, llm_call: LlmCall) -> JudgeVerdict:
    """Single-candidate LLM judge of regression risk for an already-passing diff.

    Never raises: every judge failure returns a ``JudgeVerdict`` with
    status "unavailable" and ``score=None`` — the promotion gate then fails
    the candidate (fail closed, #307). An empty diff needs no second opinion:
    "pass" with score 1.0, no LLM call.
    """
    if not diff_text.strip():
        return JudgeVerdict("pass", 1.0, "empty diff")
    sliced = diff_text[:_MAX_DIFF_CHARS]
    if len(sliced) < _MIN_RETAINED_FRACTION * len(diff_text):
        return JudgeVerdict(
            "unavailable",
            None,
            f"diff too large to judge whole ({len(diff_text)} chars, cap {_MAX_DIFF_CHARS}) "
            "— refusing to rule on a partial view",
            "oversized_diff",
        )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Target: {target}\n\nDiff:\n{sliced}"},
    ]
    try:
        result = llm_call(messages, max_tokens=400)
    except TimeoutError:
        return JudgeVerdict("unavailable", None, "judge timed out", "timeout")
    except Exception:
        return JudgeVerdict("unavailable", None, "judge gateway error", "gateway_error")
    content = result.get("content", "") if isinstance(result, dict) else result
    text = content if isinstance(content, str) else str(content)
    return _parse_verdict(text)


def _parse_verdict(text: str) -> JudgeVerdict:
    """Parse the model's reply into a ruling; anything short of a usable
    ``{"score": <number>, ...}`` object is unavailable/unparsable_reply."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return _unparsable("no JSON object found in reply")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _unparsable("reply was not valid JSON")
    if not isinstance(data, dict):
        return _unparsable("reply JSON was not an object")
    if "score" not in data:
        return _unparsable("reply JSON has no 'score' key")
    try:
        score = max(0.0, min(1.0, float(data["score"])))
    except (TypeError, ValueError):
        return _unparsable("'score' was not numeric")
    rationale = str(data.get("rationale", "")).strip()[:500]
    status: Literal["pass", "reject"] = "reject" if score < REJECT_BELOW else "pass"
    return JudgeVerdict(status, score, rationale or "no rationale given")


def _unparsable(why: str) -> JudgeVerdict:
    return JudgeVerdict("unavailable", None, f"judge reply unusable: {why}", "unparsable_reply")
