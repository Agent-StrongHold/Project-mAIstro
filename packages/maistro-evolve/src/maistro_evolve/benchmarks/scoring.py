from __future__ import annotations

import json
import re
from typing import Any

# Sentinel for ``json_field_match``: no explicit expected value was supplied,
# so the rule asserts presence-and-non-null rather than a specific value.
# (Using ``None`` as the sentinel is what made a missing field score 1.0.)
_FIELD_EXPECTED_ABSENT = object()


def exact_match(response: str, expected: str) -> float:
    return 1.0 if response.strip().lower() == expected.strip().lower() else 0.0


def contains_any(response: str, keywords: list[str]) -> float:
    lower = response.lower()
    return 1.0 if any(kw.lower() in lower for kw in keywords) else 0.0


def contains_all(response: str, keywords: list[str]) -> float:
    lower = response.lower()
    return 1.0 if all(kw.lower() in lower for kw in keywords) else 0.0


def not_contains(response: str, forbidden: list[str]) -> float:
    lower = response.lower()
    return 1.0 if all(f.lower() not in lower for f in forbidden) else 0.0


def starts_with(response: str, prefix: str) -> float:
    return 1.0 if response.strip().lower().startswith(prefix.strip().lower()) else 0.0


def ends_with(response: str, suffix: str) -> float:
    return 1.0 if response.strip().lower().endswith(suffix.strip().lower()) else 0.0


def is_valid_json(response: str) -> float:
    try:
        json.loads(response.strip())
        return 1.0
    except (json.JSONDecodeError, ValueError):
        return 0.0


def json_field_match(response: str, field: str, expected: Any = _FIELD_EXPECTED_ABSENT) -> float:
    """Score a required JSON field, bidirectionally (issue #852).

    A missing field always scores 0.0 — the historical hardcoded ``None``
    expectation rewarded the field being absent (``data.get(field)`` is
    ``None`` for both a missing key and an explicit ``null``, so an empty
    object scored 1.0). When ``expected`` is provided the observed value must
    equal it; when it is not, the field must be present and non-null.
    """
    try:
        data = json.loads(response.strip())
        if isinstance(data, dict):
            if field not in data:
                return 0.0
            if expected is _FIELD_EXPECTED_ABSENT:
                return 1.0 if data[field] is not None else 0.0
            return 1.0 if data[field] == expected else 0.0
        return 0.0
    except (json.JSONDecodeError, ValueError):
        return 0.0


def _try_parse_json(text: str) -> dict[str, Any] | list[Any] | None:
    try:
        loaded: Any = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return loaded if isinstance(loaded, (dict, list)) else None


def _extract_balanced_json(text: str) -> str | None:
    """Find the first balanced {...} or [...] substring, honoring nesting.

    Whichever bracket opens first in the text wins, so an unfenced JSON
    array of multiple objects is captured whole (not just its first
    element) and a nested object's outer braces aren't cut short.
    """
    brace_idx = text.find("{")
    bracket_idx = text.find("[")
    if brace_idx == -1 and bracket_idx == -1:
        return None
    if bracket_idx == -1 or (brace_idx != -1 and brace_idx < bracket_idx):
        start, open_ch, close_ch = brace_idx, "{", "}"
    else:
        start, open_ch, close_ch = bracket_idx, "[", "]"

    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_from_response(
    response: str,
) -> dict[str, Any] | list[Any] | None:
    for pat in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        match = re.search(pat, response, re.DOTALL)
        if match:
            parsed = _try_parse_json(match.group(1))
            if parsed is not None:
                return parsed

    balanced = _extract_balanced_json(response)
    if balanced is not None:
        parsed = _try_parse_json(balanced)
        if parsed is not None:
            return parsed

    return _try_parse_json(response.strip())


def function_call_match(
    response: str, expected_name: str, expected_params: dict[str, Any] | None = None
) -> float:
    data = extract_json_from_response(response)
    if data is None:
        return 0.0

    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    if not isinstance(data, dict):
        return 0.0

    name = data.get("name") or data.get("function") or data.get("action") or ""
    if name.lower() != expected_name.lower():
        return 0.0

    if expected_params is None:
        return 1.0

    actual_params = data.get("parameters") or data.get("arguments") or data.get("args") or {}
    if not isinstance(actual_params, dict):
        return 0.5

    total = len(expected_params)
    if total == 0:
        return 1.0

    score = sum(
        _param_value_score(actual_params.get(key), expected_val)
        for key, expected_val in expected_params.items()
    )
    return score / total


def _param_value_score(actual_val: Any, expected_val: Any) -> float:
    if actual_val is None:
        return 0.0
    if isinstance(expected_val, str) and isinstance(actual_val, str):
        if expected_val.lower() == actual_val.lower():
            return 1.0
        if expected_val.lower() in actual_val.lower():
            return 0.5
        return 0.0
    if actual_val == expected_val:
        return 1.0
    return 0.0


def sentence_count(response: str) -> int:
    text = re.sub(r"[.!?]+", ".", response.strip())
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    return len(sentences)


def word_count(response: str) -> int:
    return len(response.split())


def count_section(response: str) -> float:
    headers = re.findall(r"^#{1,3}\s+.+", response, re.MULTILINE)
    return max(0.0, min(1.0, len(headers) / 3.0))


_JUDGE_LABELED_RE = re.compile(r"(?:score|rating)\s*[::]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_JUDGE_BARE_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _normalize_judge_value(value: float) -> float:
    """Clamp a judge's number to [0, 1]; values above 1 are read as 0-10."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return min(value / 10.0, 1.0)
    return value


def _judge_word_verdict(lowered: str) -> float | None:
    """Whole-word verdict terms; ``None`` when no verdict word is present.

    Negations are anchored too and always win over their positive
    counterparts, regardless of order in the text.
    """
    if re.search(r"\bnot\s+correct\b", lowered) or re.search(r"\bincorrect\b", lowered):
        return 0.0
    if re.search(r"\bpartially\b", lowered):
        return 0.5
    if re.search(r"\bcorrect\b", lowered):
        return 1.0
    return None


def judge_score(judge_response: str) -> float:
    """Parse an LLM judge's verdict under a fail-closed, anchored policy.

    Issue #852 contract:

    - **The demanded format is parseable.** Every in-repo judge prompt (GAIA,
      RAGAS, SWE-bench-pro cross-file review) says "Respond with ONLY a
      number 0-10", so a bare numeric response is parsed as such.
    - **Anchored, negation-safe word matching.** Positive/negative words are
      matched whole-word only and negatives are checked first, so
      ``"incorrect"`` can never match the ``"correct"`` pattern (the old
      substring scan scored ``'incorrect'`` as 0.8).
    - **Malformed output is failure.** Unparseable/empty responses return
      0.0 — never a positive floor the candidate could use to satisfy a
      hard gate (the old default of 0.3 exactly met GAIA's 0.30 gate).

    Accepted formats, in priority order: a whole-response JSON object with a
    numeric ``"score"``; the last ``score:``/``rating:`` label; a bare
    number; whole-word ``incorrect``/``not correct``/``correct``/
    ``partially``; a whole-word yes/no vote (majority; ties fail).
    """
    text = judge_response.strip()
    if not text:
        return 0.0

    # 1. JSON object responses are schema-or-failure: a numeric ``score``
    #    field is honored, and anything else inside a JSON object (e.g. a
    #    prose verdict embedded in structured output) is malformed rather
    #    than eligible for word voting below.
    if text.startswith("{"):
        try:
            loaded: Any = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return 0.0
        if isinstance(loaded, dict) and isinstance(loaded.get("score"), int | float):
            return _normalize_judge_value(float(loaded["score"]))
        return 0.0

    # 2. Labeled score/rating (last mention wins).
    labeled = _JUDGE_LABELED_RE.findall(text.lower())
    if labeled:
        return _normalize_judge_value(float(labeled[-1]))

    # 3. Bare number — the format every judge prompt actually demands.
    if _JUDGE_BARE_NUMBER_RE.match(text):
        return _normalize_judge_value(float(text))

    # 4. Whole-word verdicts (see _judge_word_verdict).
    lowered = text.lower()
    word_verdict = _judge_word_verdict(lowered)
    if word_verdict is not None:
        return word_verdict

    # 5. Whole-word yes/no vote. Word boundaries keep substrings like "eyes"
    #    or "knowledge" from voting; a majority is required and ties fail.
    yes_count = len(re.findall(r"\byes\b", lowered))
    no_count = len(re.findall(r"\bno\b", lowered))
    if yes_count > no_count:
        return 1.0
    return 0.0
