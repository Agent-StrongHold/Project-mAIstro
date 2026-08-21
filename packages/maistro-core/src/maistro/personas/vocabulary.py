"""Declarative check vocabulary for rubric criteria (ADR-060 §1).

The vocabulary is code, audited once, in one place. Domains are data
(one YAML file per domain). Every op returns a bool: True = criterion passed.

Ops
---
keywords_any   any(word in output.lower() for word in words)
keywords_none  not any(word in output.lower() for word in words)
regex          bool(re.search(pattern, output, flags))
regex_absent   not bool(re.search(pattern, output, flags))
regex_count    len(re.findall(...)) satisfies min/max constraint
word_count     word count satisfies min/max constraint
metric         named scalar compared with lt/lte/gt/gte/eq
any            short-circuit OR over a list of sub-checks
all            short-circuit AND over a list of sub-checks
registered     named predicate from PREDICATES registry (escape hatch)

Text-matching ops (keywords_any, keywords_none, regex, regex_absent) accept an
optional ``slice_start`` / ``slice_end`` to restrict the region checked:
  {op: keywords_any, words: [...], slice_end: 200}    # first 200 chars
  {op: keywords_any, words: [...], slice_start: -300} # last 300 chars

The ``registered`` registry is the *only* place new eval primitives are added.
A criterion using it requires a comment justifying why the vocabulary is
insufficient (ADR-060).

This module is the core-canonical port of ``hive-conductor/eval/vocabulary.py``;
op semantics are identical so department YAML files load unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Named metrics (for the `metric` op)
# ---------------------------------------------------------------------------


def _avg_sentence_words(output: str) -> float:
    sentences = [s for s in output.split(".") if s.strip()]
    if not sentences:
        return 0.0
    return sum(len(s.split()) for s in sentences) / len(sentences)


def _long_word_ratio(output: str) -> float:
    words = output.split()
    if not words:
        return 0.0
    return sum(1 for w in words if len(w) > 10) / len(words)


def _unique_word_ratio(output: str) -> float:
    words = output.split()
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _paragraph_count(output: str) -> float:
    return float(len([p for p in output.split("\n\n") if p.strip()]))


def _hashtag_count(output: str) -> float:
    return float(len(re.findall(r"#\w+", output)))


def _sentence_length_variety(output: str) -> float:
    """Number of distinct sentence-word-counts (proxy for rhythmic variety)."""
    sentences = [s for s in output.split(".") if s.strip()]
    return float(len({len(s.split()) for s in sentences}))


def _list_density(output: str) -> float:
    """Ratio of list-item lines to total non-empty lines."""
    lines = [ln for ln in output.split("\n") if ln.strip()]
    if not lines:
        return 0.0
    list_lines = sum(1 for ln in lines if ln.strip().startswith(("- ", "* ", "• ")))
    return list_lines / len(lines)


def _max_line_length(output: str) -> float:
    """Max character length among non-empty lines."""
    lines = [ln for ln in output.split("\n") if ln.strip()]
    return float(max((len(ln) for ln in lines), default=0))


METRICS: dict[str, Callable[[str], float]] = {
    "avg_sentence_words": _avg_sentence_words,
    "long_word_ratio": _long_word_ratio,
    "unique_word_ratio": _unique_word_ratio,
    "paragraph_count": _paragraph_count,
    "hashtag_count": _hashtag_count,
    "sentence_length_variety": _sentence_length_variety,
    "list_density": _list_density,
    "max_line_length": _max_line_length,
}

# ---------------------------------------------------------------------------
# Registered predicates (escape hatch — add here with a justification comment)
# ---------------------------------------------------------------------------


# rhyme_density: ratio of line-ending word pairs that share a suffix >= 3 chars.
# Needed because rhyme cannot be expressed as a simple keyword or regex count.
def _rhyme_density(output: str, *, min: float = 0.3, **_: Any) -> bool:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    last_words = [ln.split()[-1].lower().rstrip(".,!?;:") for ln in lines]
    pairs = [(last_words[i], last_words[i + 1]) for i in range(len(last_words) - 1)]
    rhyming = sum(1 for a, b in pairs if a[-3:] == b[-3:] and a != b)
    return (rhyming / max(len(pairs), 1)) >= min


# active_voice_ratio: "will" count must exceed "shall be" count.
# Needed because it compares two substring counts — not expressible as a single op.
def _active_voice_ratio(output: str, **_: Any) -> bool:
    lo = output.lower()
    return lo.count("shall be") < lo.count("will") + 1


# latin_phrase_count: number of Latin legalisms present must be below max.
# Needed because it counts phrases (not tokens) across a fixed list.
def _latin_phrase_count(output: str, *, max: int = 1, **_: Any) -> bool:
    phrases = ["inter alia", "mutatis mutandis", "ipso facto", "prima facie"]
    return sum(1 for p in phrases if p in output.lower()) <= max


# keyword_count_max: count of distinct keywords (from list) found must be <= max.
# Needed for "at most N of these CTAs appear" — a bounded distinct-count.
def _keyword_count_max(output: str, *, words: list[str], max: int, **_: Any) -> bool:
    lo = output.lower()
    return sum(1 for w in words if w.lower() in lo) <= max


PREDICATES: dict[str, Callable[..., bool]] = {
    "rhyme_density": _rhyme_density,
    "active_voice_ratio": _active_voice_ratio,
    "latin_phrase_count": _latin_phrase_count,
    "keyword_count_max": _keyword_count_max,
}

# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------

_FLAG_MAP: dict[str, re.RegexFlag] = {
    "i": re.IGNORECASE,
    "s": re.DOTALL,
    "m": re.MULTILINE,
    "is": re.IGNORECASE | re.DOTALL,
    "si": re.IGNORECASE | re.DOTALL,
    "im": re.IGNORECASE | re.MULTILINE,
    "mi": re.IGNORECASE | re.MULTILINE,
}


def _parse_flags(flags: str | None) -> re.RegexFlag:
    if not flags:
        return re.RegexFlag(0)
    return _FLAG_MAP.get(flags.lower(), re.RegexFlag(0))


# ---------------------------------------------------------------------------
# Comparators for `metric` op
# ---------------------------------------------------------------------------

_CMP: dict[str, Callable[[float, float], bool]] = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
}

# ---------------------------------------------------------------------------
# Core: evaluate one check-spec against (output, context)
# ---------------------------------------------------------------------------


def _apply_slice(text: str, check: dict[str, Any]) -> str:
    """Apply optional slice_start / slice_end to text before matching."""
    start = check.get("slice_start")
    end = check.get("slice_end")
    if start is None and end is None:
        return text
    return text[start:end]


def _eval_keywords(check: dict[str, Any], output: str, *, negate: bool) -> bool:
    words: list[str] = check["words"]
    region = _apply_slice(output, check)
    hit = any(w.lower() in region.lower() for w in words)
    return not hit if negate else hit


def _eval_regex(check: dict[str, Any], output: str, *, negate: bool) -> bool:
    region = _apply_slice(output, check)
    flags = _parse_flags(check.get("flags"))
    hit = bool(re.search(check["pattern"], region, flags))
    return not hit if negate else hit


def _eval_bounds(count: int, check: dict[str, Any]) -> bool:
    mn: int | None = check.get("min")
    mx: int | None = check.get("max")
    return (mn is None or count >= mn) and (mx is None or count <= mx)


def _eval_regex_count(check: dict[str, Any], output: str) -> bool:
    flags = _parse_flags(check.get("flags"))
    count = len(re.findall(check["pattern"], output, flags))
    return _eval_bounds(count, check)


def _eval_metric(check: dict[str, Any], output: str) -> bool:
    name: str = check["name"]
    fn = METRICS.get(name)
    if fn is None:
        raise ValueError(f"Unknown metric: {name!r}")
    cmp_fn = _CMP.get(check["cmp"])
    if cmp_fn is None:
        raise ValueError(f"Unknown comparator: {check['cmp']!r}")
    return cmp_fn(fn(output), float(check["value"]))


def _eval_registered(check: dict[str, Any], output: str) -> bool:
    name: str = check["name"]
    fn = PREDICATES.get(name)
    if fn is None:
        raise ValueError(f"Unknown registered predicate: {name!r}")
    return fn(output, **dict(check.get("args", {})))


def _eval_simple(op: str | None, check: dict[str, Any], output: str) -> bool | None:
    """Handle text-matching and counting ops; return None if op is not handled here."""
    if op == "keywords_any":
        return _eval_keywords(check, output, negate=False)
    if op == "keywords_none":
        return _eval_keywords(check, output, negate=True)
    if op == "regex":
        return _eval_regex(check, output, negate=False)
    if op == "regex_absent":
        return _eval_regex(check, output, negate=True)
    if op == "regex_count":
        return _eval_regex_count(check, output)
    if op == "word_count":
        return _eval_bounds(len(output.split()), check)
    return None


def evaluate(check: dict[str, Any], output: str, context: dict[str, Any]) -> bool:
    """Evaluate one check-spec dict against output text and context."""
    op = check.get("op")
    simple = _eval_simple(op, check, output)
    if simple is not None:
        return simple
    if op == "metric":
        return _eval_metric(check, output)
    if op == "any":
        return any(evaluate(sub, output, context) for sub in check["of"])
    if op == "all":
        return all(evaluate(sub, output, context) for sub in check["of"])
    if op == "registered":
        return _eval_registered(check, output)
    raise ValueError(f"Unknown check op: {op!r}")
