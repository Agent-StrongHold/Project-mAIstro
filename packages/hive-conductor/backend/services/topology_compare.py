"""Phase 7 — Topology comparison.

Retrospective comparison: bucket recent runs of a DAG by some grouping
field (model_used, node_kind, edge weight band, etc.) and rank the
buckets by composite score so the optimizer can ask "which variant
won the last K runs?"

Composite score = 0.5 * success_rate
                 + 0.3 * (1 - normalized_p95_latency)
                 + 0.2 * (1 - normalized_thumb_down_rate)

  success_rate  ∈ [0, 1]   (completed / total)
  p95 latency   normalized to [0, 1] over the comparison set
  thumb_down    normalized to [0, 1] across observed feedback

Higher composite_score is better. Returned ranking is descending.

Live A/B exec lands in v2 — this v1 only reads from
services.node_metrics_store + outcome_store.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from services.feedback_service import get_outcome_store
from services.node_metrics_store import (
    NodeObservation,
)
from services.node_metrics_store import (
    get_store as _metrics_store,
)

logger = logging.getLogger(__name__)


W_SUCCESS = 0.4  # quality (benchmark pass rate, eval-judge score)
W_LATENCY = 0.25  # speed (lower is better)
W_THUMB = 0.2  # user satisfaction
W_COST = 0.15  # cost efficiency (lower is better)

ALLOWED_GROUP_FIELDS = ("model_used", "node_kind", "node_id")


@dataclass
class VariantBucket:
    """One bucket of observations grouped by the chosen field."""

    label: str
    observations: list[NodeObservation] = field(default_factory=list)
    thumb_up: int = 0
    thumb_down: int = 0

    @property
    def count(self) -> int:
        return len(self.observations)

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.observations if o.phase == "COMPLETED")

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.count if self.count else 0.0

    @property
    def p95_latency(self) -> int:
        if not self.observations:
            return 0
        # Through the store's own summarizer rather than the module-private
        # `_aggregate` this used to import (#698).
        agg = _metrics_store().summarize(self.observations)
        return int(agg["latency_ms_p95"])

    @property
    def thumb_down_rate(self) -> float:
        total = self.thumb_up + self.thumb_down
        return self.thumb_down / total if total else 0.0


def _resolve_label(obs: NodeObservation, group_by: str) -> str:
    """Pull the grouping label from an observation. Empty values are
    bucketed under '(unset)' so we never lose data."""
    raw = getattr(obs, group_by, "") or ""
    return raw if raw else "(unset)"


def _bucket_observations(
    obs_list: list[NodeObservation],
    group_by: str,
) -> dict[str, VariantBucket]:
    buckets: dict[str, VariantBucket] = {}
    for o in obs_list:
        label = _resolve_label(o, group_by)
        buckets.setdefault(label, VariantBucket(label=label)).observations.append(o)
    return buckets


def _fold_in_thumbs(
    buckets: dict[str, VariantBucket],
    *,
    dag_id: str,
    group_by: str,
) -> None:
    """For each Outcome with a thumb in scope of this DAG, attribute to
    the bucket whose label matches the outcome's `node_id` (only valid
    when group_by='node_id' — otherwise thumbs aren't bucket-scoped)."""
    if group_by != "node_id":
        return
    store = get_outcome_store()
    for o in getattr(store, "_outcomes", []):
        if dag_id and getattr(o, "dag_id", "") and o.dag_id != dag_id:
            continue
        if not getattr(o, "thumb", ""):
            continue
        label = o.node_id or "(unset)"
        if label not in buckets:
            buckets[label] = VariantBucket(label=label)
        if o.thumb == "up":
            buckets[label].thumb_up += 1
        elif o.thumb == "down":
            buckets[label].thumb_down += 1


def _normalize(values: list[float], invert: bool = True) -> list[float]:
    """Return a 0..1 normalization of `values`. invert=True means
    'smaller is better' (latency, thumb-down rate)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        # No variation → all variants equal on this dimension
        return [0.5 for _ in values]
    out = []
    for v in values:
        n = (v - lo) / (hi - lo)
        out.append(1.0 - n if invert else n)
    return out


def _composite(
    success_rates: list[float],
    norm_latency: list[float],
    norm_thumb_down: list[float],
    norm_cost: list[float] | None = None,
) -> list[float]:
    costs = norm_cost or [0.0] * len(success_rates)
    return [
        round(W_SUCCESS * s + W_LATENCY * lat + W_THUMB * t + W_COST * c, 4)
        for s, lat, t, c in zip(success_rates, norm_latency, norm_thumb_down, costs, strict=False)
    ]


def compare_variants(
    dag_id: str,
    *,
    group_by: str = "model_used",
    window_seconds: int = 24 * 3600,
    now: Any = None,
) -> dict[str, Any]:
    """Compare recent runs grouped by the chosen field. Returns a
    ranked variant table.

    Parameters
    ----------
    dag_id : DAG to scope the observations
    group_by : "model_used" | "node_kind" | "node_id"
    window_seconds : sliding window for observations
    now : test seam for the filter cutoff

    Returns
    -------
    {
      "dag_id": <id>,
      "group_by": <field>,
      "variants": [
        {"label", "count", "succeeded", "success_rate",
         "p95_latency_ms", "thumb_down_rate", "composite_score",
         "rank"},
        ...  # sorted by composite_score desc
      ],
      "winner": <best label> | "",
    }
    """
    if not dag_id:
        raise ValueError("dag_id is required")
    if group_by not in ALLOWED_GROUP_FIELDS:
        raise ValueError(f"group_by must be one of {ALLOWED_GROUP_FIELDS!r}, got {group_by!r}")

    obs = _metrics_store().observations(
        dag_id=dag_id,
        window_seconds=window_seconds,
        now=now,
    )
    buckets = _bucket_observations(obs, group_by)
    _fold_in_thumbs(buckets, dag_id=dag_id, group_by=group_by)

    if not buckets:
        return {"dag_id": dag_id, "group_by": group_by, "variants": [], "winner": ""}

    labels = list(buckets.keys())
    success_rates = [buckets[label].success_rate for label in labels]
    p95s = [float(buckets[label].p95_latency) for label in labels]
    thumbs_down = [buckets[label].thumb_down_rate for label in labels]

    norm_lat = _normalize(p95s, invert=True)
    norm_thumb = _normalize(thumbs_down, invert=True)
    composite = _composite(success_rates, norm_lat, norm_thumb)

    rows = []
    for i, lbl in enumerate(labels):
        b = buckets[lbl]
        rows.append(
            {
                "label": lbl,
                "count": b.count,
                "succeeded": b.succeeded,
                "success_rate": round(success_rates[i], 4),
                "p95_latency_ms": int(p95s[i]),
                "thumb_up": b.thumb_up,
                "thumb_down": b.thumb_down,
                "thumb_down_rate": round(thumbs_down[i], 4),
                "composite_score": composite[i],
            }
        )

    rows.sort(key=lambda r: r["composite_score"], reverse=True)
    for r, row in enumerate(rows, 1):
        row["rank"] = r

    return {
        "dag_id": dag_id,
        "group_by": group_by,
        "variants": rows,
        "winner": rows[0]["label"] if rows else "",
    }
