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


def _pattern_search(pattern: regex.Pattern[str], text: str) -> bool:
    """One pattern, one window, bounded time. Exceptions propagate — a scanner
    that swallows its own failure and answers "no threat" is fail-open, and an
    earlier version of this helper did exactly that, making the ``regex_error:``
    handler below unreachable."""
    return bool(pattern.search(text, timeout=_PATTERN_TIMEOUT_S))


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

        # Fix #4: scan in overlapping windows — no unscanned tail.
        # Window: 50KB with 2KB overlap so patterns spanning a boundary are caught.
        window_size = 50 * 1024
        overlap = 2 * 1024
        # Full fold (NFKD + invisible stripping + homoglyph folding) so a
        # zero-width space inside "ignore", or a Cyrillic i in it, doesn't
        # walk past patterns written in ASCII. Applied here rather than in the
        # Gate so every caller gets it — the RSI quarantine gate calls scan()
        # directly and used to miss the Gate's sanitize pass entirely.
        content_norm = normalize_for_detection(content)

        if len(content_norm) <= window_size:
            flags.extend(_scan_reject_patterns(content_norm))
        else:
            offset = 0
            while offset < len(content_norm):
                chunk = content_norm[offset : offset + window_size]
                flags.extend(_scan_reject_patterns(chunk))
                if flags:
                    break  # Found something — no need to continue
                offset += window_size - overlap

        if flags:
            return WardenVerdict(
                clean=False,
                blocked=len(flags) >= 1,
                flags=tuple(flags),
                confidence=0.9,
            )

        suspicious, heuristic_flags = heuristic_scan(content_norm)
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
