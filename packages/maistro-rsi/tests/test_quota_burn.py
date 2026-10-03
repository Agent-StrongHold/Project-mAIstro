"""Tests tied to SPEC.md §3 (quota-burn scheduling) acceptance criteria quota-1..5."""

from __future__ import annotations

import pytest

from maistro.quota.tracker import InMemoryQuotaTracker
from maistro_rsi.quota_burn import QuotaBurnScheduler, discover_models, rank_models_by_headroom

CYCLE = "2026-06"
FREE_TOKENS = {"openai": 1_000_000, "anthropic": 500_000}


class TestRankModelsByHeadroom:
    @pytest.mark.asyncio
    async def test_orders_by_descending_remaining_headroom(self):
        """quota-1: most-idle model (highest remaining headroom) ranks first."""
        tracker = InMemoryQuotaTracker()
        # openai/heavy: 90% used of 1,000,000 -> ~100k headroom
        await tracker.record_usage("openai", CYCLE, 800_000, 100_000)
        # anthropic/light: 10% used of 500,000 -> ~450k headroom
        await tracker.record_usage("anthropic", CYCLE, 30_000, 20_000)

        ranked = await rank_models_by_headroom(
            ["openai/heavy", "anthropic/light"],
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
        )

        assert [m.model for m in ranked] == ["anthropic/light", "openai/heavy"]
        assert ranked[0].headroom_tokens > ranked[1].headroom_tokens

    @pytest.mark.asyncio
    async def test_overused_model_clamps_to_zero_headroom_and_ranks_last(self):
        """quota-2: usage above the configured free-tier budget clamps headroom to zero, never negative."""
        tracker = InMemoryQuotaTracker()
        # openai/over: used 1.2M of a 1,000,000 budget
        await tracker.record_usage("openai", CYCLE, 1_000_000, 200_000)
        # anthropic/fresh: untouched
        ranked = await rank_models_by_headroom(
            ["openai/over", "anthropic/fresh"],
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
        )

        over = next(m for m in ranked if m.model == "openai/over")
        assert over.headroom_tokens == 0
        assert ranked[-1].model == "openai/over"

    @pytest.mark.asyncio
    async def test_unlisted_provider_falls_back_to_default_free_tokens(self):
        """A provider absent from free_tokens_per_provider is scheduled against
        default_free_tokens rather than skipped or treated as zero budget."""
        tracker = InMemoryQuotaTracker()
        # "mistral" is not in FREE_TOKENS, so it must fall back to the default
        # budget of 1,000,000; record exactly half of it as used.
        await tracker.record_usage("mistral", CYCLE, 400_000, 100_000)

        ranked = await rank_models_by_headroom(
            ["mistral/large"],
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
            default_free_tokens=1_000_000,
        )

        mq = ranked[0]
        assert mq.provider == "mistral"
        assert mq.free_tokens == 1_000_000
        assert mq.used_pct == pytest.approx(0.5)
        assert mq.headroom_tokens == 500_000


class TestQuotaBurnScheduler:
    @pytest.mark.asyncio
    async def test_next_model_returns_none_for_empty_list(self):
        """quota-3: an empty model list yields None, not an error."""
        scheduler = QuotaBurnScheduler(InMemoryQuotaTracker(), billing_cycle=CYCLE)
        assert await scheduler.next_model([]) is None

    @pytest.mark.asyncio
    async def test_next_model_matches_top_of_headroom_ranking(self):
        """quota-4: next_model returns the same model rank_models_by_headroom puts first."""
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("openai", CYCLE, 900_000, 50_000)

        scheduler = QuotaBurnScheduler(
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
        )
        models = ["openai/busy", "anthropic/idle"]

        chosen = await scheduler.next_model(models)
        ranked = await rank_models_by_headroom(
            models,
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
        )

        assert chosen == ranked[0].model == "anthropic/idle"

    @pytest.mark.asyncio
    async def test_record_attempt_attributes_usage_to_models_provider(self):
        """quota-5: record_attempt files usage under the model's provider prefix, affecting future ranking."""
        tracker = InMemoryQuotaTracker()
        scheduler = QuotaBurnScheduler(
            tracker,
            billing_cycle=CYCLE,
            free_tokens_per_provider=FREE_TOKENS,
        )

        await scheduler.record_attempt("openai/gpt-5", input_tokens=400_000, output_tokens=400_000)

        usage_pct = await tracker.get_usage_pct("openai", CYCLE, FREE_TOKENS["openai"])
        assert usage_pct == pytest.approx(0.8)

        # a model from a provider that was never recorded against stays untouched
        other_pct = await tracker.get_usage_pct("anthropic", CYCLE, FREE_TOKENS["anthropic"])
        assert other_pct == 0.0


class TestDiscoverModels:
    """Tests for discover_models function — currently has no tests."""

    @pytest.mark.asyncio
    async def test_extracts_model_ids_from_v1_models_response(self):
        """Verify discover_models correctly parses the /v1/models response."""
        # Simulate the LiteLLM /v1/models endpoint response
        payload = {
            "object": "list",
            "data": [
                {"id": "openai/gpt-4", "object": "model"},
                {"id": "anthropic/claude-3-opus", "object": "model"},
                {"id": "openai/gpt-3.5-turbo", "object": "model"},
            ],
        }

        # A MockTransport rather than a stand-in client: the shared client is
        # real, so this exercises the actual request-building path.
        import httpx

        from maistro.http import override_transport

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        with override_transport(httpx.MockTransport(handler)):
            models = await discover_models(base_url="http://fake.example", api_key="fake-key")

        # Should extract all "id" fields from the "data" array
        assert models == ["openai/gpt-4", "anthropic/claude-3-opus", "openai/gpt-3.5-turbo"]
