"""`discovery.scout` — the cheap scout tier's deterministic filter (#1051).

Broad, high-recall, zero-model work: fingerprint dedupe (within the cycle and
against the Workspace's durable seen-ledger carried by the discovery context
authority), watch-topic overlap scoring, category down-weighting from prior
negative feedback, and a floor cut. No frontier model, no network, no cost —
"slow cheap/local CPU work for candidate generation", exactly the tier the
issue asks to exist before any stronger model sees a candidate.

Scoring is deliberately simple and inspectable: every candidate carries the
topics it matched, so the curator (and the surfaced item's `explain`) can
name the evidence instead of a bare number.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext, ReplaySemantics
from .discovery_context import (
    DiscoveryContextProvider,
    DiscoveryCycleContext,
    default_discovery_context,
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'+.-]*", re.IGNORECASE)


class DiscoveryScoutIn(BaseModel):
    entries: list[dict[str, str]] = Field(default_factory=list)
    watch_topics: list[str] = Field(default_factory=list)
    #: 0..1 topic-overlap floor; candidates below it never reach the curator.
    min_score: float = Field(default=0.1, ge=0.0, le=1.0)
    max_candidates: int = Field(default=24, ge=1, le=100)


class ScoutedCandidate(BaseModel):
    fingerprint: str
    entry_id: str
    url: str = ""
    title: str = ""
    summary: str = ""
    category: str = ""
    source_url: str = ""
    published_at: str = ""
    #: Explicit source-carried deadline (e.g. a sale window); never invented.
    expires_at: str = ""
    score: float
    matched_topics: list[str] = Field(default_factory=list)


class DiscoveryScoutOut(BaseModel):
    candidates: list[ScoutedCandidate] = Field(default_factory=list)
    #: Honest cycle telemetry. These counts are read by the pipeline tests and
    #: by the host's lift path (outside the shipped-src tree this scan roots
    #: at), so inside ``packages/*/src`` they are serialization-only surface —
    #: the same declarative-schema class the vulture ledger banks as
    #: ``pydantic-declarative-field``. The inline acknowledgment is the
    #: analyzer's documented mechanism, used because this lane cannot land the
    #: ledger grant a floor raise would need (two-merge ratchet).
    seen_suppressed: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests
    below_floor: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests


def fingerprint_for(*, entry_id: str, url: str, title: str) -> str:
    """The candidate's stable identity for dedupe across cycles.

    URL first (the canonical identity of a web item); id and title back it up
    for feeds that omit one. The ledger stores fingerprints, never full
    content.
    """
    basis = url.strip() or entry_id.strip() or title.strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]  # nosec: B324 - identity hash


def _topics_of(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _overlap(entry_text: str, topics: list[str]) -> tuple[float, list[str]]:
    """Fraction of watch topics the entry's text mentions, with which ones."""
    if not topics:
        return 0.0, []
    tokens = _topics_of(entry_text)
    matched = [topic for topic in topics if topic.strip().lower() in tokens]
    if not matched:
        return 0.0, []
    return len(matched) / len(topics), matched


def _cycle_floor(min_score: float, cycle: DiscoveryCycleContext) -> float:
    """The effective floor: the Workspace's config may tighten, never loosen."""
    if cycle.min_scout_score >= 0:
        return max(min_score, cycle.min_scout_score)
    return min_score


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    return fingerprint_for(
        entry_id=str(entry.get("id") or ""),
        url=str(entry.get("url") or ""),
        title=str(entry.get("title") or ""),
    )


def _scored(
    entry: dict[str, Any], topics: list[str], downweights: dict[str, float]
) -> tuple[float, list[str], str]:
    """Topic-overlap score with feedback down-weights applied, plus category."""
    text = " ".join(str(entry.get(key) or "") for key in ("title", "summary", "category"))
    score, matched = _overlap(text, topics)
    category = str(entry.get("category") or "")
    weight = downweights.get(category)
    if weight is not None and matched:
        score = round(score * weight, 4)
    return score, matched, category


def _candidate(
    entry: dict[str, Any], fingerprint: str, score: float, matched: list[str], category: str
) -> ScoutedCandidate:
    return ScoutedCandidate(
        fingerprint=fingerprint,
        entry_id=str(entry.get("id") or ""),
        url=str(entry.get("url") or ""),
        title=str(entry.get("title") or ""),
        summary=str(entry.get("summary") or ""),
        category=category,
        source_url=str(entry.get("source_url") or ""),
        published_at=str(entry.get("published_at") or ""),
        expires_at=str(entry.get("expires_at") or ""),
        score=score,
        matched_topics=matched,
    )


def _capped(
    scored: list[ScoutedCandidate], max_candidates: int, cycle: DiscoveryCycleContext
) -> list[ScoutedCandidate]:
    """Highest-score first; the Workspace's budget may narrow, never widen."""
    scored.sort(key=lambda c: (-c.score, c.fingerprint))
    cap = max_candidates
    if cycle.max_candidates > 0:
        cap = min(cap, cycle.max_candidates)
    return scored[:cap]


@register_node
class DiscoveryScoutNode(BaseNode[DiscoveryScoutIn, DiscoveryScoutOut]):
    kind: ClassVar[str] = "discovery.scout"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = DiscoveryScoutIn
    output_schema: ClassVar[type[BaseModel]] = DiscoveryScoutOut
    cost_hint: ClassVar[float] = 0.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.IDEMPOTENT
    external_io: ClassVar[bool] = False
    optional_authorities: ClassVar = {"discovery_context": "discovery_context"}
    display_name: ClassVar[str] = "Discovery: scout candidates"
    description: ClassVar[str] = (
        "Deterministic candidate generation over fetched entries: dedupe "
        "against the seen ledger, score watch-topic overlap, apply category "
        "down-weights from prior feedback, cut at the floor. No model call."
    )

    def __init__(self, *, discovery_context: DiscoveryContextProvider | None = None) -> None:
        self._cycle = discovery_context or default_discovery_context()

    async def _execute(self, inputs: DiscoveryScoutIn, ctx: NodeContext) -> DiscoveryScoutOut:
        cycle = await self._cycle.context_for(
            str(ctx.workspace_id or ""),
            str(ctx.project_id or ""),
            str(ctx.user_id or ""),
            cycle_key=ctx.run_id,
        )
        topics = list(dict.fromkeys([*inputs.watch_topics, *cycle.watch_topics]))
        downweights = dict(cycle.category_downweights)
        floor = _cycle_floor(inputs.min_score, cycle)

        seen_in_cycle: set[str] = set()
        scored: list[ScoutedCandidate] = []
        seen_suppressed = 0
        below_floor = 0
        for entry in inputs.entries:
            if not isinstance(entry, dict):
                continue
            fingerprint = _entry_fingerprint(entry)
            if fingerprint in cycle.seen_fingerprints or fingerprint in seen_in_cycle:
                seen_suppressed += 1
                continue
            seen_in_cycle.add(fingerprint)
            score, matched, category = _scored(entry, topics, downweights)
            if score < floor:
                below_floor += 1
                continue
            scored.append(_candidate(entry, fingerprint, score, matched, category))
        return DiscoveryScoutOut(
            candidates=_capped(scored, inputs.max_candidates, cycle),
            seen_suppressed=seen_suppressed,
            below_floor=below_floor,
        )


__all__ = ["DiscoveryScoutNode", "ScoutedCandidate", "fingerprint_for"]
