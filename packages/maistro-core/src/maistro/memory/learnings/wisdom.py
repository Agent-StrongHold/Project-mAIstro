"""CoinSwarm wisdom JSON -> Learning import (M4-B3).

CoinSwarm's wisdom payloads carry exactly the shape this issue asks learnings
to keep: `lessons` (the claim text), `excels_in` / `avoid_in` (structured
applicability) and `confidence` (evidence strength from the swarm's own
tracking). The importer is a pure mapping — no I/O, no LLM — and every imported
record lands as `EpistemicType.REPORTED`: the swarm asserts it, nothing here
has validated it, and REPORTED is the epistemic type that says so. Imported
wisdom may carry `works_when`/`avoid_in` and a measured confidence, and still
cannot be promoted until a source Run/evaluation id backs it
(`evidence.promotion_blockers` is the one verdict).
"""

from __future__ import annotations

from typing import Any

from maistro.memory.types import MemoryScope
from maistro.types.memory import EpistemicType, Learning


def _strings(value: Any) -> list[str]:
    """Coerce a payload field to a list of non-blank strings, tolerating junk."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _text(payload: dict[str, Any]) -> str:
    for key in ("lesson", "text", "learning"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _confidence(payload: dict[str, Any]) -> float | None:
    value = payload.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(0.0, min(1.0, float(value)))


def learning_from_wisdom(payload: dict[str, Any], *, org_id: str = "") -> Learning:
    """Map one CoinSwarm wisdom object onto the Learning record.

    `excels_in` -> `works_when`, `avoid_in` -> `avoid_in`, `confidence` ->
    `confidence` (clamped to [0, 1]), optional `evidence_run_ids` /
    `evaluation_ids` threaded through when the swarm exports them. The swarm's
    lesson id, when present, is kept in `source_query` as `coinswarm:<id>` so
    the import stays traceable without inventing a new column for it.
    """
    wisdom_id = payload.get("id")
    source = f"coinswarm:{wisdom_id}" if wisdom_id else "coinswarm"
    return Learning(
        category="wisdom",
        trigger_keys=_text(payload).lower().split()[:5],
        learning=_text(payload),
        source_query=source,
        org_id=org_id,
        scope=MemoryScope.AGENT,
        epistemic_type=EpistemicType.REPORTED,
        works_when=_strings(payload.get("excels_in")),
        avoid_in=_strings(payload.get("avoid_in")),
        confidence=_confidence(payload),
        evidence_run_ids=_strings(payload.get("evidence_run_ids")),
        evaluation_ids=_strings(payload.get("evaluation_ids")),
    )
