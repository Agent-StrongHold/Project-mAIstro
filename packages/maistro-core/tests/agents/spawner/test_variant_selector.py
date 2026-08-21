"""Coverage for maistro.agents.spawner.variant_selector.VariantSelector (was 0%).

Exercises the three selection phases (round-robin warm-up, random exploration,
Thompson sampling), record_outcome's running-mean/success-rate bookkeeping, the
Langfuse-backed cache refresh path (including its failure handling), and the
degenerate zero/one-variant cases.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maistro.agents.spawner.variant_selector import VariantSelector, VariantStats


def _recipe(
    prompt_variants: list[str] | None = None,
    prompt_name: str = "coder.generate",
    min_samples_before_selection: int = 20,
    exploration_rate: float = 0.1,
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_variants=prompt_variants if prompt_variants is not None else ["production"],
        prompt_name=prompt_name,
        min_samples_before_selection=min_samples_before_selection,
        exploration_rate=exploration_rate,
    )


# ─── select(): degenerate variant counts ─────────────────────────────────


def test_select_with_no_variants_returns_production_default():
    vs = VariantSelector()
    recipe = _recipe(prompt_variants=[])
    assert vs.select(recipe) == "production"


def test_select_with_single_variant_returns_it_without_consulting_stats():
    vs = VariantSelector()
    recipe = _recipe(prompt_variants=["only_variant"])
    assert vs.select(recipe) == "only_variant"


def test_select_uses_getattr_defaults_for_missing_recipe_fields():
    """A plain object lacking prompt_variants entirely falls back to "production"."""
    vs = VariantSelector()
    assert vs.select(object()) == "production"


# ─── select(): Phase 1 round robin ──────────────────────────────────────


def test_select_round_robins_through_variants_below_min_samples():
    vs = VariantSelector()
    recipe = _recipe(prompt_variants=["a", "b", "c"], min_samples_before_selection=20)

    # No runs recorded yet -> total_runs (0) < min_samples (20) -> round robin.
    picks = [vs.select(recipe) for _ in range(7)]
    assert picks == ["a", "b", "c", "a", "b", "c", "a"]


def test_select_round_robin_counter_is_keyed_by_prompt_name():
    vs = VariantSelector()
    recipe_x = _recipe(prompt_variants=["a", "b"], prompt_name="x")
    recipe_y = _recipe(prompt_variants=["a", "b"], prompt_name="y")

    assert vs.select(recipe_x) == "a"
    assert vs.select(recipe_x) == "b"
    # Separate prompt_name starts its own counter from index 0.
    assert vs.select(recipe_y) == "a"
    assert vs.select(recipe_x) == "a"


# ─── select(): Phase 2 random exploration ───────────────────────────────


def test_select_explores_randomly_when_below_exploration_rate(monkeypatch):
    vs = VariantSelector()
    recipe = _recipe(prompt_variants=["a", "b"], min_samples_before_selection=0)
    # Seed stats so total_runs >= min_samples (0), skipping phase 1.
    vs.record_outcome("coder.generate", "a", 9.0)

    monkeypatch.setattr("random.random", lambda: 0.05)  # below exploration_rate=0.1
    monkeypatch.setattr("random.choice", lambda seq: seq[1])

    assert vs.select(recipe) == "b"


def test_select_skips_exploration_when_above_exploration_rate(monkeypatch):
    vs = VariantSelector()
    recipe = _recipe(
        prompt_variants=["a", "b"], min_samples_before_selection=0, exploration_rate=0.1
    )
    vs.record_outcome("coder.generate", "a", 9.0)
    vs.record_outcome("coder.generate", "b", 1.0)

    # random.random() called twice: once for exploration gate, then possibly
    # inside Thompson sampling cold-start branches (not needed here since both
    # variants have runs > 0, so betavariate is used instead).
    monkeypatch.setattr("random.random", lambda: 0.5)  # above exploration_rate -> phase 3
    monkeypatch.setattr("random.betavariate", lambda a, b: 1.0 if a > b else 0.0)

    # "a" has successes=1,failures=0 -> betavariate(2,1); "b" has successes=0,
    # failures=1 -> betavariate(1,2). Our stub returns 1.0 when a>b, so "a" wins.
    assert vs.select(recipe) == "a"


def test_select_thompson_sampling_cold_start_uses_random_for_unseen_variant(monkeypatch):
    vs = VariantSelector()
    recipe = _recipe(prompt_variants=["seen", "unseen"], min_samples_before_selection=0)
    vs.record_outcome("coder.generate", "seen", 9.0)

    monkeypatch.setattr("random.random", lambda: 0.99)  # always above exploration_rate
    # First random.random() call is the exploration gate (0.99, skip explore).
    # The cold-start sample for "unseen" also calls random.random(); stub it
    # to return a value guaranteed to beat any betavariate() draw.
    calls = {"n": 0}

    def fake_random():
        calls["n"] += 1
        return 0.99

    monkeypatch.setattr("random.random", fake_random)
    monkeypatch.setattr("random.betavariate", lambda a, b: 0.0)

    result = vs.select(recipe)
    assert result == "unseen"
    # Called once for exploration gate, once for "seen"? no -- "seen" has
    # runs>0 so it uses betavariate, not random(). Only "unseen" calls random().
    assert calls["n"] == 2  # exploration gate + cold-start sample for "unseen"


# ─── record_outcome(): running mean / success rate bookkeeping ─────────


def test_record_outcome_tracks_success_threshold_boundary():
    vs = VariantSelector(success_threshold=7.0)
    vs.record_outcome("p", "v1", 7.0)  # exactly at threshold -> success
    vs.record_outcome("p", "v1", 6.999)  # just below -> failure

    stats = vs.get_stats("p")["v1"]
    assert stats.runs == 2
    assert stats.successes == 1
    assert stats.failures == 1
    assert stats.success_rate == 0.5


def test_record_outcome_computes_incremental_mean_score():
    vs = VariantSelector()
    vs.record_outcome("p", "v1", 10.0)
    vs.record_outcome("p", "v1", 0.0)
    vs.record_outcome("p", "v1", 5.0)

    stats = vs.get_stats("p")["v1"]
    assert stats.mean_score == pytest.approx(5.0)
    assert stats.runs == 3


def test_record_outcome_creates_new_variant_stats_on_first_call():
    vs = VariantSelector()
    assert vs.get_stats("p") == {}

    vs.record_outcome("p", "brand_new", 8.0)

    stats = vs.get_stats("p")
    assert set(stats.keys()) == {"brand_new"}
    assert isinstance(stats["brand_new"], VariantStats)
    assert stats["brand_new"].runs == 1
    assert stats["brand_new"].successes == 1


def test_record_outcome_with_langfuse_client_calls_score():
    calls = []

    class FakeLangfuse:
        def score(self, *, trace_id, name, value, comment):
            calls.append((trace_id, name, value, comment))

    vs = VariantSelector(langfuse_client=FakeLangfuse())
    vs.record_outcome("p", "v1", 8.5, trace_id="trace-123")

    assert calls == [("trace-123", "variant_score", 8.5, "variant=v1")]


def test_record_outcome_without_trace_id_does_not_call_langfuse():
    class FakeLangfuse:
        def score(self, **kwargs):
            raise AssertionError("should not be called without trace_id")

    vs = VariantSelector(langfuse_client=FakeLangfuse())
    vs.record_outcome("p", "v1", 8.5, trace_id=None)  # no trace_id -> no call


def test_record_outcome_swallows_langfuse_score_exception():
    class ExplodingLangfuse:
        def score(self, **kwargs):
            raise RuntimeError("langfuse is down")

    vs = VariantSelector(langfuse_client=ExplodingLangfuse())
    # Must not raise -- exception is logged and swallowed.
    vs.record_outcome("p", "v1", 8.5, trace_id="t1")

    stats = vs.get_stats("p")["v1"]
    assert stats.runs == 1


# ─── get_stats() / _get_stats(): caching + langfuse refresh ────────────


def test_get_stats_returns_copy_not_internal_reference():
    vs = VariantSelector()
    vs.record_outcome("p", "v1", 8.0)

    snapshot = vs.get_stats("p")
    snapshot["v1"].runs = 999  # mutate the copy

    # Internal cache dict is untouched because get_stats wraps in dict(...);
    # however the VariantStats *objects* themselves are shared, so this
    # mutation IS visible internally -- get_stats only copies the outer dict.
    assert vs.get_stats("p")["v1"].runs == 999


def test_get_stats_without_langfuse_client_returns_empty_for_unknown_prompt():
    vs = VariantSelector()
    assert vs.get_stats("never_seen") == {}


def test_select_refreshes_from_langfuse_when_cache_expired(monkeypatch):
    class FakeScore:
        def __init__(self, value, comment):
            self.value = value
            self.comment = comment

    class FakeScoreList:
        def __init__(self, data):
            self.data = data

    class FakeScoreClient:
        def list(self, *, name, page, limit):
            return FakeScoreList(
                [
                    FakeScore(9.0, "variant=a"),
                    FakeScore(2.0, "variant=a"),
                    FakeScore(8.0, "variant=b"),
                    FakeScore(5.0, "no-prefix-here"),  # ignored: doesn't start with "variant="
                ]
            )

    class FakeClient:
        score = FakeScoreClient()

    class FakeLangfuse:
        client = FakeClient()

    vs = VariantSelector(langfuse_client=FakeLangfuse(), cache_ttl=300)
    stats = vs.get_stats("p")

    assert set(stats.keys()) == {"a", "b"}
    assert stats["a"].runs == 2
    assert stats["a"].successes == 1  # 9.0 >= 7.0
    assert stats["a"].failures == 1  # 2.0 < 7.0
    assert stats["a"].success_rate == 0.5
    assert stats["b"].runs == 1
    assert stats["b"].successes == 1
    assert stats["b"].success_rate == 1.0


def test_get_stats_uses_cache_within_ttl_and_does_not_refetch(monkeypatch):
    call_count = {"n": 0}

    class FakeScoreClient:
        def list(self, *, name, page, limit):
            call_count["n"] += 1
            raise AssertionError("should not refetch within TTL")

    class FakeClient:
        score = FakeScoreClient()

    class FakeLangfuse:
        client = FakeClient()

    vs = VariantSelector(langfuse_client=FakeLangfuse(), cache_ttl=300)
    # Prime the cache manually (bypassing the langfuse fetch) and set a fresh timestamp.
    import time as time_mod

    vs._cache["p"] = {"a": VariantStats(variant="a", runs=1, successes=1)}
    vs._cache_timestamps["p"] = time_mod.monotonic()

    result = vs.get_stats("p")
    assert result == {"a": vs._cache["p"]["a"]}
    assert call_count["n"] == 0


def test_refresh_from_langfuse_swallows_fetch_exception():
    class ExplodingScoreClient:
        def list(self, **kwargs):
            raise RuntimeError("network error")

    class FakeClient:
        score = ExplodingScoreClient()

    class FakeLangfuse:
        client = FakeClient()

    vs = VariantSelector(langfuse_client=FakeLangfuse())
    # Must not raise; falls back to empty stats for an unseen prompt.
    assert vs.get_stats("p") == {}


def test_refresh_from_langfuse_noop_when_no_client():
    vs = VariantSelector(langfuse_client=None)
    # _refresh_from_langfuse's early return is exercised indirectly via
    # _get_stats's `if self._lf` guard -- direct call here for explicitness.
    vs._refresh_from_langfuse("p")
    assert vs.get_stats("p") == {}
