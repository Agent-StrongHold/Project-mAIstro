"""VariantSelector — Thompson sampling over prompt variants (ADR-007)."""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SUCCESS_THRESHOLD = 7.0


class VariantStats(BaseModel):
    variant: str
    runs: int = 0
    successes: int = 0
    failures: int = 0
    mean_score: float = 0.0
    success_rate: float = 0.0
    last_updated: datetime = datetime.now(UTC)


class VariantSelector:
    def __init__(
        self,
        langfuse_client: object | None = None,
        cache_ttl: int = 300,
        success_threshold: float = _SUCCESS_THRESHOLD,
    ) -> None:
        self._lf = langfuse_client
        self._cache: dict[str, dict[str, VariantStats]] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl = cache_ttl
        self._success_threshold = success_threshold
        self._rr_counters: dict[str, int] = {}

    def select(self, recipe: object) -> str:
        """Return the prompt variant label to use for this spawn."""
        variants: list[str] = getattr(recipe, "prompt_variants", [])
        if not variants:
            return "production"
        if len(variants) == 1:
            return variants[0]

        prompt_name: str = getattr(recipe, "prompt_name", "")
        min_samples: int = getattr(recipe, "min_samples_before_selection", 20)
        exploration_rate: float = getattr(recipe, "exploration_rate", 0.1)

        stats = self._get_stats(prompt_name)
        total_runs = sum(s.runs for s in stats.values())

        # Phase 1: round-robin to gather data
        if total_runs < min_samples:
            idx = self._rr_counters.get(prompt_name, 0)
            self._rr_counters[prompt_name] = (idx + 1) % len(variants)
            return variants[idx % len(variants)]

        # Phase 2: random exploration
        if random.random() < exploration_rate:  # nosec B311 — exploration rate, not crypto
            return random.choice(variants)  # nosec B311 — variant pick, not crypto

        # Phase 3: Thompson sampling
        best_sample = -1.0
        best_variant = variants[0]
        for variant in variants:
            vs = stats.get(variant)
            if vs is None or vs.runs == 0:
                sample = random.random()  # nosec B311 — Thompson sampling cold-start, not crypto
            else:
                sample = random.betavariate(vs.successes + 1, vs.failures + 1)
            if sample > best_sample:
                best_sample = sample
                best_variant = variant

        return best_variant

    def record_outcome(
        self,
        prompt_name: str,
        variant: str,
        score: float,
        *,
        trace_id: str | None = None,
    ) -> None:
        stats = self._cache.setdefault(prompt_name, {})
        vs = stats.get(variant)
        if vs is None:
            vs = VariantStats(variant=variant)
            stats[variant] = vs

        vs.runs += 1
        is_success = score >= self._success_threshold
        if is_success:
            vs.successes += 1
        else:
            vs.failures += 1
        vs.mean_score = vs.mean_score + (score - vs.mean_score) / vs.runs
        vs.success_rate = vs.successes / vs.runs
        vs.last_updated = datetime.now(UTC)

        if self._lf and trace_id:
            try:
                self._lf.score(  # type: ignore[attr-defined]
                    trace_id=trace_id,
                    name="variant_score",
                    value=score,
                    comment=f"variant={variant}",
                )
            except Exception as exc:
                logger.debug("Failed to record variant score in Langfuse: %s", exc)

    def get_stats(self, prompt_name: str) -> dict[str, VariantStats]:
        return dict(self._get_stats(prompt_name))

    def _get_stats(self, prompt_name: str) -> dict[str, VariantStats]:
        now = time.monotonic()
        cache_ts = self._cache_timestamps.get(prompt_name, 0.0)
        if prompt_name in self._cache and (now - cache_ts) < self._cache_ttl:
            return self._cache[prompt_name]
        if self._lf:
            try:
                self._refresh_from_langfuse(prompt_name)
                self._cache_timestamps[prompt_name] = now
            except Exception as exc:
                logger.debug("Failed to refresh stats from Langfuse: %s", exc)
        return self._cache.get(prompt_name, {})

    def _refresh_from_langfuse(self, prompt_name: str) -> None:
        if not self._lf:
            return
        try:
            scores = self._lf.client.score.list(name="variant_score", page=1, limit=500)  # type: ignore[attr-defined]
            stats: dict[str, VariantStats] = {}
            for score in scores.data:
                comment = score.comment or ""
                if not comment.startswith("variant="):
                    continue
                variant = comment.split("=", 1)[1]
                vs = stats.setdefault(variant, VariantStats(variant=variant))
                vs.runs += 1
                if score.value >= self._success_threshold:
                    vs.successes += 1
                else:
                    vs.failures += 1
            for vs in stats.values():
                if vs.runs > 0:
                    vs.success_rate = vs.successes / vs.runs
                vs.last_updated = datetime.now(UTC)
            self._cache[prompt_name] = stats
        except Exception as exc:
            logger.debug("Langfuse score fetch failed: %s", exc)
