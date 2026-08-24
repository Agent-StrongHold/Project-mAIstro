"""Warden: threat detection at two ingress points.

Scans user input and tool results for hostile content.
Four layers (cheap to expensive, short-circuit on detection):
1. Regex patterns (zero cost, sub-millisecond)
2. Heuristic scoring (lightweight statistical check)
2.5. Semantic tool-poisoning (action+object+prescriptive, sub-millisecond)
3. LLM classification (few-shot, ~100ms, costs tokens -- optional)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from maistro.security._types import WardenVerdict
from maistro.security.normalize import normalize_for_detection
from maistro.security.warden.heuristics import heuristic_scan
from maistro.security.warden.patterns import REJECT_PATTERNS
from maistro.security.warden.semantic import semantic_tool_poisoning_scan

if TYPE_CHECKING:
    import regex

    from maistro.security._types import LLMClient

logger = logging.getLogger("maistro.warden")

# Per-search ceiling. A reject pattern that cannot finish in half a second on a
# 50KB window is catastrophically backtracking; `regex` raises TimeoutError,
# which the loop below records as a fail-closed flag.
_PATTERN_TIMEOUT_S = 0.5

# One window size for both scan phases (#74). They used to differ: the reject
# phase windowed at 50KB with a 2KB overlap while the heuristic phase received
# the whole document, so the two halves of one scan disagreed about how much
# text a single pass may see.
#
# That asymmetry matters because the phases are bounded differently. The reject
# phase runs `regex` with a per-search timeout, so a catastrophic pattern is cut
# off (`test_catastrophic_pattern_times_out_and_fails_closed`). The heuristic
# phase runs `_regex`, whose stdlib fallback has **no timeout at all** — so a
# pattern there is bounded only by the text it is handed. Handing it the whole
# document removed the one bound it had.
#
# The overlap exists so a pattern straddling a boundary is still seen whole. 2KB
# is far more than the widest construct either phase matches — the density
# window is 40 words and the base64 run needs 40 characters.
_SCAN_WINDOW_CHARS = 50 * 1024
_SCAN_OVERLAP_CHARS = 2 * 1024


def _windows(text: str) -> Iterator[str]:
    """`text` in overlapping windows — the same slicing for both scan phases.

    A generator rather than a list so a 1MB body is not copied in full before
    the first window is examined; both callers stop at the first flagged
    window, so the tail is usually never materialised.
    """
    if len(text) <= _SCAN_WINDOW_CHARS:
        yield text
        return
    offset = 0
    while offset < len(text):
        yield text[offset : offset + _SCAN_WINDOW_CHARS]
        offset += _SCAN_WINDOW_CHARS - _SCAN_OVERLAP_CHARS


def _pattern_search(pattern: regex.Pattern[str], text: str) -> bool:
    """One pattern, one window, bounded time. Exceptions propagate — a scanner
    that swallows its own failure and answers "no threat" is fail-open, and an
    earlier version of this helper did exactly that, making the ``regex_error:``
    handler below unreachable."""
    return bool(pattern.search(text, timeout=_PATTERN_TIMEOUT_S))


def _scan_heuristics_windowed(content: str) -> tuple[bool, list[str]]:
    """`heuristic_scan` over the same windows the reject phase uses (#74).

    Windowed for the reason stated on `_SCAN_WINDOW_CHARS`: this phase runs
    `_regex`, whose stdlib fallback has no timeout, so the text handed to one
    call is its only bound.

    The verdict is unchanged by the split. Density is already a max over
    40-word sub-windows and the base64 run needs 40 characters — both far
    inside the 2KB overlap — so the maximum over windows equals the maximum
    over the whole text. `test_windowing_does_not_change_the_verdict` pins that
    rather than leaving it as an argument, and it fails if this stops looking
    past the first window.
    """
    for window in _windows(content):
        suspicious, flags = heuristic_scan(window)
        if suspicious:
            return True, flags
    return False, []


def _scan_reject_patterns(scan_content: str) -> list[str]:
    """Run every reject pattern against ``scan_content``, collecting flag
    descriptions — and ``regex_error:`` markers for patterns that raise or time
    out, so an engine failure surfaces as a non-clean verdict instead of
    passing silently."""
    flags: list[str] = []
    for pattern, description in REJECT_PATTERNS:
        try:
            if _pattern_search(pattern, scan_content):
                flags.append(description)
        except Exception:
            logger.warning("Regex error on pattern: %s", description)
            flags.append(f"regex_error:{description}")
    return flags


class Warden:
    """Threat detector. Runs at user_input and tool_result boundaries only.

    Layers 1-2.5 are always active (free, instant).
    Layer 3 (LLM) is optional -- requires an LLM client and model to be configured.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        classifier_model: str = "auto",
    ) -> None:
        self._llm = llm
        self._classifier_model = classifier_model

    async def scan(
        self,
        content: str,
        boundary: str,
    ) -> WardenVerdict:
        flags: list[str] = []

        # Fix #4: scan in overlapping windows — no unscanned tail. See
        # `_windows`; both phases below share it so they cannot drift apart.
        #
        # Full fold (NFKD + invisible stripping + homoglyph folding) so a
        # zero-width space inside "ignore", or a Cyrillic i in it, doesn't
        # walk past patterns written in ASCII. Applied here rather than in the
        # Gate so every caller gets it — the RSI quarantine gate calls scan()
        # directly and used to miss the Gate's sanitize pass entirely.
        content_norm = normalize_for_detection(content)

        for window in _windows(content_norm):
            flags.extend(_scan_reject_patterns(window))
            if flags:
                break  # Found something — no need to continue

        if flags:
            return WardenVerdict(
                clean=False,
                blocked=len(flags) >= 1,
                flags=tuple(flags),
                confidence=0.9,
            )

        suspicious, heuristic_flags = _scan_heuristics_windowed(content_norm)
        if suspicious:
            flags.extend(heuristic_flags)
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=tuple(flags),
                confidence=0.6,
            )

        poisoned, semantic_flags = semantic_tool_poisoning_scan(content_norm)
        if poisoned:
            flags.extend(semantic_flags)
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=tuple(flags),
                confidence=0.7,
            )

        if boundary == "tool_result" and self._llm is not None:
            llm_verdict = await self._scan_llm_classification(content, flags)
            if llm_verdict is not None:
                return llm_verdict

        return WardenVerdict(clean=True)

    async def _scan_llm_classification(
        self, content: str, flags: list[str]
    ) -> WardenVerdict | None:
        """L3 LLM tool-result classification. Returns a verdict if the content is
        classified suspicious, otherwise ``None``. Only called when ``self._llm``
        is set."""
        assert self._llm is not None
        try:
            from maistro.security.warden.llm_classifier import classify_tool_result

            result = await classify_tool_result(
                content,
                self._llm,
                self._classifier_model,
            )

            if result.get("label") == "suspicious":
                model = result.get("model", "?")
                flags.append(f"llm_classification:suspicious (model={model}, mode=binary)")
                return WardenVerdict(
                    clean=False,
                    blocked=False,
                    flags=tuple(flags),
                    confidence=0.8,
                    reasoning_trace=result.get("reasoning_trace"),
                )
        except Exception:
            # `classify_tool_result` already fails closed on everything it can
            # see, so reaching here means the judge could not be consulted at
            # all — an import failure, a shape this function does not expect.
            # `self._llm` is set, so L3 *was* configured; treating its absence
            # as clean would put the fail-open path back one frame further out,
            # which is the defect this whole check exists to remove.
            logger.warning("L3 LLM classification unavailable; failing closed", exc_info=True)
            flags.append(
                f"llm_classification:suspicious (model={self._classifier_model}, mode=unavailable)"
            )
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=tuple(flags),
                confidence=0.8,
                reasoning_trace="llm_judge_inconclusive:classifier_unavailable",
            )
        return None
