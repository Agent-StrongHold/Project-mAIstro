"""Tests for pure cost computation from registry metadata."""

from __future__ import annotations

import pytest

from maistro.providers import compute_cost_cents, compute_embedding_cost_cents

from .fixtures_models import ADA, GPT35, LOCAL, OPUS


class TestComputeCostCents:
    def test_matches_metadata_pricing(self) -> None:
        # 2000 input @ 0.15/1k + 1000 output @ 0.75/1k
        assert compute_cost_cents(OPUS, 2000, 1000) == pytest.approx(0.3 + 0.75)

    def test_zero_tokens_is_free(self) -> None:
        assert compute_cost_cents(GPT35, 0, 0) == 0.0

    def test_local_model_is_free(self) -> None:
        assert compute_cost_cents(LOCAL, 10_000, 10_000) == 0.0

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            compute_cost_cents(OPUS, -1, 0)
        with pytest.raises(ValueError, match="non-negative"):
            compute_cost_cents(OPUS, 0, -1)

    def test_no_hardcoded_pricing(self) -> None:
        custom = OPUS.__class__(
            name="x",
            provider="p",
            cost_per_1k_input=1.0,
            cost_per_1k_output=2.0,
            latency_p50_ms=1,
        )
        assert compute_cost_cents(custom, 1500, 500) == pytest.approx(1.5 + 1.0)


class TestComputeEmbeddingCostCents:
    def test_matches_metadata_pricing(self) -> None:
        assert compute_embedding_cost_cents(ADA, 10_000) == pytest.approx(10 * 0.0001)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            compute_embedding_cost_cents(ADA, -5)
