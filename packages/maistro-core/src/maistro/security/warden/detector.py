"""Warden: threat detection at two ingress points.

Scans user input and tool results for hostile content.
Four layers (cheap to expensive, short-circuit on detection):
1. Regex patterns (zero cost, sub-millisecond)
2. Heuristic scoring (lightweight statistical check)
2.5. Semantic tool-poisoning (action+object+prescriptive, sub-millisecond)
3. LLM classification (few-shot, ~100ms, costs tokens -- optional)
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

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

# The detector mechanism is the canonical policy version consumed by boundary
# audit records. Turing must not create a second policy identifier.
WARDEN_POLICY_VERSION = "warden-code-v1"

# Context is an analysis aid, not a second session store. Only recent
# untrusted entries are retained for one scan, and the byte budget is shared by
# those entries. Trusted system/developer messages are labelled and excluded,
# never concatenated with attacker-controlled text.
_CONTEXT_MAX_TURNS = 8
_CONTEXT_MAX_BYTES = 16 * 1024
# Do not walk an attacker-supplied sequence forever while looking for recent
# turns. This is deliberately larger than the retained turn count so trusted
# labels and empty entries cannot crowd out a normal short context.
_CONTEXT_MAX_INPUT_ITEMS = 64


@dataclass(frozen=True)
class WardenContext:
    """One ordered context item with an explicit authority provenance label."""

    content: str
    provenance: Literal["trusted", "untrusted"] = "untrusted"
    boundary: str = "conversation"


def _bounded_json_text(value: object, budget: int) -> str:
    """Serialize only a bounded prefix of structured message metadata."""
    if budget <= 0:
        return ""
    try:
        chunks: list[str] = []
        used = 0
        for chunk in json.JSONEncoder(sort_keys=True, default=str).iterencode(value):
            chunk_bytes = len(chunk.encode("utf-8"))
            if used + chunk_bytes > budget:
                chunks.append(_prefix_within_utf8_budget(chunk, budget - used))
                break
            chunks.append(chunk)
            used += chunk_bytes
        return "".join(chunks)
    except (TypeError, ValueError):
        return _prefix_within_utf8_budget(str(value), budget)


def message_to_scan_text(message: Mapping[str, object], *, max_bytes: int | None = None) -> str:
    """Serialize fields reaching a downstream harness, optionally bounded."""
    content = message.get("content", "")
    content_text = (
        content
        if isinstance(content, str)
        else (str(content) if max_bytes is None else _bounded_json_text(content, max_bytes))
    )
    extra_fields = {k: v for k, v in message.items() if k not in ("content", "role")}
    if max_bytes is None:
        if not extra_fields:
            return content_text
        try:
            serialized = json.dumps(extra_fields, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(extra_fields)
        return f"{content_text}\n{serialized}" if content_text else serialized

    content_text = _prefix_within_utf8_budget(content_text, max_bytes)
    used = len(content_text.encode("utf-8"))
    if not extra_fields or used >= max_bytes:
        return content_text
    separator = "\n" if content_text else ""
    remaining = max_bytes - used - len(separator.encode("utf-8"))
    return f"{content_text}{separator}{_bounded_json_text(extra_fields, remaining)}"


def context_from_messages(messages: Sequence[Mapping[str, object]]) -> list[WardenContext]:
    """Label a bounded message tail without changing authority semantics.

    System/developer messages are trusted metadata and Warden excludes them from
    aggregation. All other message roles, including assistant/tool output, are
    untrusted because they may carry indirect instructions. The tail and each
    serialized item are bounded before structured metadata is materialized.
    """
    result: list[WardenContext] = []
    start = max(0, len(messages) - _CONTEXT_MAX_INPUT_ITEMS)
    for index in range(start, len(messages)):
        message = messages[index]
        role = str(message.get("role", ""))
        provenance: Literal["trusted", "untrusted"] = (
            "trusted" if role in {"system", "developer"} else "untrusted"
        )
        result.append(
            WardenContext(
                content=message_to_scan_text(message, max_bytes=_CONTEXT_MAX_BYTES),
                provenance=provenance,
                boundary=f"conversation:{role or 'unknown'}",
            )
        )
    return result


def prior_message_context(messages: Sequence[Mapping[str, object]]) -> list[WardenContext]:
    """Return messages before the latest user turn in their original order."""
    latest_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].get("role") == "user"
        ),
        len(messages),
    )
    return context_from_messages(messages[:latest_user])


def _coerce_context_item(item: WardenContext | str | Mapping[str, object]) -> WardenContext:
    if isinstance(item, WardenContext):
        return item
    if isinstance(item, str):
        return WardenContext(item)
    role = str(item.get("role", ""))
    provenance = item.get("provenance")
    if provenance is None:
        provenance = "trusted" if role in {"system", "developer"} else "untrusted"
    if provenance not in {"trusted", "untrusted"}:
        raise ValueError("Warden context provenance must be 'trusted' or 'untrusted'")
    boundary = item.get("boundary")
    if boundary is None:
        boundary = f"conversation:{role or 'unknown'}"
    return WardenContext(
        content=str(item.get("content", "")),
        provenance=provenance,
        boundary=str(boundary),
    )


def _prefix_within_utf8_budget(text: str, budget: int) -> str:
    """Return a prefix whose encoded size is at most ``budget`` bytes."""
    if budget <= 0:
        return ""
    prefix: list[str] = []
    used = 0
    # At most ``budget`` code points are visited, so an oversized context item
    # cannot turn the bounded copy into a scan proportional to its full size.
    for char in text:
        char_bytes = len(char.encode("utf-8"))
        if used + char_bytes > budget:
            break
        prefix.append(char)
        used += char_bytes
    return "".join(prefix)


def _bounded_untrusted_context(
    context: Sequence[WardenContext | str | Mapping[str, object]] | None,
) -> list[str]:
    if not context:
        return []
    selected: list[str] = []
    remaining = _CONTEXT_MAX_BYTES
    start = max(0, len(context) - _CONTEXT_MAX_INPUT_ITEMS)
    for index in range(len(context) - 1, start - 1, -1):
        item = _coerce_context_item(context[index])
        if item.provenance == "trusted" or remaining <= 0:
            continue
        # A context item's own prefix is retained; the total byte budget is
        # what prevents a caller from turning one scan into an unbounded copy.
        text = _prefix_within_utf8_budget(item.content, remaining)
        if text:
            selected.append(text)
            remaining -= len(text.encode("utf-8"))
        if len(selected) >= _CONTEXT_MAX_TURNS:
            break
    selected.reverse()
    return selected


# Separators an attacker can place between the characters or the words of
# an instruction override. Curated, not open-ended: whitespace plus the
# punctuation that renders as nothing between letters in common fonts (dot,
# hyphen, underscore, comma, semicolon, colon, pipe, slash). Digits and the
# leetspeak symbols stay out -- they are payload, not separators.
_SEPARATOR_RUN = re.compile(r"[\s._,\-;:/|]+")

_SINGLE_CHARACTER_RUN = re.compile(
    r"(?<!\w)(?:[A-Za-z0-9@$](?:[\s._,\-;:/|]+[A-Za-z0-9@$]){2,})(?!\w)"
)


def _collapse_single_character_runs(text: str) -> str:
    """Remove separators only from long single-character runs.

    Requiring at least three characters and a non-word boundary prevents normal
    prose such as "a cat" from being globally compacted. Digits and the two
    symbol substitutions supported by the bounded leetspeak fold are included
    so a payload such as ``1 g n o r e 4 l l`` is compacted before that fold
    runs again. Compact phrase rules then recognize the override without
    altering the primary view.
    """
    return _SINGLE_CHARACTER_RUN.sub(lambda match: _SEPARATOR_RUN.sub("", match.group()), text)


def _literal_views(text: str) -> tuple[str, str]:
    """Separator-free readings of ``text`` for the reject patterns alone.

    An override does not need single-character runs at all. Between words:
    ``ignore_all_previous_instructions`` and ``you-are-now-a-pirate`` hide a
    phrase the primary view never sees, because every reject pattern anchors
    on whitespace. Inside words: ``ig-nore all previous instructions`` and a
    payload split mid-word across turns (the turn join inserts a newline
    inside ``instruc|tions``) leave no intact phrase for those anchors
    either. Two bounded readings close both shapes:

    - removal: every separator deleted. Word-internal splits reunite and
      collide with the whitespace-free compact override pattern.
    - replacement: every separator run becomes one space. All the
      whitespace-anchored phrase patterns then see canonical spacing, so
      the same defect class cannot survive on the other families by
      substituting punctuation for spaces.

    Ordinary prose already separates words with spaces, which replacement
    preserves -- the false-positive surface this adds is text that
    deliberately uses non-space separators, which is the attack. Both views
    destroy the whitespace statistics the heuristic layer measures, and
    removal destroys word structure outright, so neither is ever handed to
    the heuristics or the semantic layer.
    """
    return (
        normalize_for_detection(_SEPARATOR_RUN.sub("", text)),
        normalize_for_detection(_SEPARATOR_RUN.sub(" ", text)),
    )


class _DetectionViews(NamedTuple):
    """Canonical detection views: structure-preserving first, then literal.

    ``structural`` views keep word boundaries (the compact one only compacts
    bounded single-character runs) and are the sole input to the heuristic
    and semantic layers. ``literal`` holds the separator-free readings used
    by the reject patterns alone.
    """

    structural: tuple[str, ...]
    literal: tuple[str, ...]


def _detection_views(text: str) -> _DetectionViews:
    compact = _collapse_single_character_runs(text)
    if compact != text:
        # The first normalization pass cannot fold a digit that is a token by
        # itself. Compacting first turns spaced leetspeak into mixed tokens,
        # so one bounded second pass handles both obfuscation layers.
        compact = normalize_for_detection(compact)
    structural = (text,) if compact == text else (text, compact)
    removed, spaced = _literal_views(structural[-1])
    literal: list[str] = []
    for view in (removed, spaced):
        if view not in structural and view not in literal:
            literal.append(view)
    return _DetectionViews(structural, tuple(literal))


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


def _scan_reject_views(content_views: Sequence[str]) -> list[str]:
    """Run reject patterns over each canonical view and stop on first hit."""
    flags: list[str] = []
    for content in content_views:
        for window in _windows(content):
            for flag in _scan_reject_patterns(window):
                if flag not in flags:
                    flags.append(flag)
            if flags:
                return flags
    return flags


def _scan_heuristic_views(content_views: Sequence[str]) -> list[str]:
    """Return the first heuristic finding from the canonical views."""
    for content in content_views:
        suspicious, flags = _scan_heuristics_windowed(content)
        if suspicious:
            return flags
    return []


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
            logger.warning("Warden pattern scan failed closed")
            flags.append(f"regex_error:{description}")
    return flags


class Warden:
    """Threat detector. Runs at user_input and tool_result boundaries only.

    ``policy_version`` identifies this canonical detector mechanism for audit
    correlation; consumers must not replace it with a product-local policy.

    Layers 1-2.5 are always active (free, instant).
    Layer 3 (LLM) is optional -- requires an LLM client and model to be configured.
    """

    policy_version = WARDEN_POLICY_VERSION

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
        *,
        context: Sequence[WardenContext | str | Mapping[str, object]] | None = None,
    ) -> WardenVerdict:
        """Scan untrusted content and a bounded ordered analysis context.

        ``content`` is always untrusted. ``context`` is optional for legacy
        single-turn callers; entries labelled ``trusted`` are deliberately not
        joined to the attacker-controlled analysis text. The context window is
        capped by turns and bytes before normalization or pattern matching.
        """
        flags: list[str] = []
        prior_context = _bounded_untrusted_context(context)
        scan_input = "\n".join((*prior_context, content))

        # Full fold (Unicode, zero-width, homoglyph, and bounded leetspeak)
        # runs before every detector. The compact structural view handles
        # single-character runs while the primary view preserves ordinary
        # prose; the literal views catch separators placed inside words or
        # substituted for the spaces between them, including a mid-word turn
        # boundary.
        content_views = _detection_views(normalize_for_detection(scan_input))

        reject_flags = _scan_reject_views((*content_views.structural, *content_views.literal))
        if reject_flags:
            return WardenVerdict(
                clean=False,
                blocked=True,
                flags=tuple(reject_flags),
                confidence=0.9,
            )

        heuristic_flags = _scan_heuristic_views(content_views.structural)
        if heuristic_flags:
            flags.extend(flag for flag in heuristic_flags if flag not in flags)
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=tuple(flags),
                confidence=0.6,
            )

        # Semantic analysis operates on the canonical primary view. It sees
        # untrusted context but never trusted system/developer instructions.
        content_norm = content_views.structural[0]
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
            logger.warning("L3 LLM classification unavailable; failing closed")
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
