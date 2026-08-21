"""Second-opinion LLM regression check — a safety net for changes no
deterministic gate would catch: a data-shape conversion narrowed for an
untested input, a new branch riding on an unrelated test's coverage credit, an
exception handler that discards the original error type, a guard clause that
silently rejects previously-valid input. These are subtle-semantics bugs a
careful reader catches by inspection, not by running the existing suite —
that suite, by definition, doesn't yet know to look for the regression.

Deliberately narrow and conservative (see ADR-070126-6386 v3's W2S posture):
the objective gates (tests, coverage, syntax, collectability) stay the primary,
dumb, reliable defense; this judge only supplements them, is only consulted
when a candidate has already cleared every other gate (so a doomed candidate
never burns an LLM call), and defaults to a passing score on any judge
failure — it must never become the thing that blocks promotion when the
gateway hiccups.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

LlmCall = Callable[..., dict[str, Any]]

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


def judge_regression(
    diff_text: str, target: str, llm_call: LlmCall, *, fallback_score: float = 0.7
) -> tuple[float, str]:
    """Single-candidate LLM judge of regression risk for an already-passing diff.

    Never raises: an unavailable/erroring/unparsable judge reply returns
    ``fallback_score`` (a passing-leaning default) rather than blocking
    promotion on an infra hiccup — the deterministic gates remain the primary
    defense; this is only ever a supplement.
    """
    if not diff_text.strip():
        return 1.0, "empty diff"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Target: {target}\n\nDiff:\n{diff_text[:8000]}"},
    ]
    try:
        result = llm_call(messages, max_tokens=400)
    except Exception:
        return fallback_score, "judge unavailable"
    content = result.get("content", "") if isinstance(result, dict) else result
    text = content if isinstance(content, str) else str(content)
    return _parse_verdict(text, fallback_score)


def _parse_verdict(text: str, fallback_score: float) -> tuple[float, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return fallback_score, "judge reply unparsable"
    try:
        data = json.loads(match.group(0))
        score = max(0.0, min(1.0, float(data.get("score", fallback_score))))
        rationale = str(data.get("rationale", "")).strip()[:500]
        return score, rationale or "no rationale given"
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback_score, "judge reply unparsable"
