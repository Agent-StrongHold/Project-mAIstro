"""Scout fallback ordering: monotonic skill accrual, strict tier ordering
(no hysteresis needed — scores never move backward), and round-robin fairness
within a tied tier. The whole point is stopping a single chronically-benched
scout model from silently zeroing the scout every cycle (the real failure
mode observed in the 150-cycle run: `code` got stuck benched from cycle ~20
onward and the scout produced nothing for the rest of the run)."""

from __future__ import annotations

from pathlib import Path

from maistro_rsi.scout_fallback import (
    ScoutFallbackState,
    load_state,
    next_order,
    record_success,
    save_state,
)


def test_record_success_increments_the_scout_models_score() -> None:
    state = ScoutFallbackState()
    state = record_success(state, "devstral-medium")
    state = record_success(state, "devstral-medium")
    state = record_success(state, "codestral")
    assert state.scores == {"devstral-medium": 2, "codestral": 1}


def test_record_success_empty_model_is_a_noop() -> None:
    state = ScoutFallbackState()
    assert record_success(state, "") is state


def test_unscored_models_share_the_zero_tier_in_catalog_order() -> None:
    state = ScoutFallbackState()
    order, _ = next_order(state, ["a", "b", "c"])
    assert order == ["a", "b", "c"]


def test_higher_score_always_leads_regardless_of_catalog_order() -> None:
    state = ScoutFallbackState(scores={"a": 1, "b": 5, "c": 3})
    order, _ = next_order(state, ["a", "b", "c"])
    assert order == ["b", "c", "a"]


def test_a_single_point_lead_reorders_immediately_no_hysteresis() -> None:
    # Unlike the old design, ANY score difference separates tiers strictly —
    # there is no deadband, because scores only ever increase.
    state = ScoutFallbackState(scores={"a": 5, "b": 6})
    order, _ = next_order(state, ["a", "b"])
    assert order == ["b", "a"]


def test_tied_models_round_robin_across_successive_calls() -> None:
    state = ScoutFallbackState(scores={"a": 1, "b": 1, "c": 1})
    order1, state = next_order(state, ["a", "b", "c"])
    order2, state = next_order(state, ["a", "b", "c"])
    order3, _ = next_order(state, ["a", "b", "c"])
    assert order1 == ["a", "b", "c"]
    assert order2 == ["b", "c", "a"]
    assert order3 == ["c", "a", "b"]


def test_round_robin_only_applies_within_a_tier_not_across_tiers() -> None:
    # b/c are tied (tier 1); a is alone in a higher tier (tier 5) and must
    # always lead regardless of rotation.
    state = ScoutFallbackState(scores={"a": 5, "b": 1, "c": 1})
    order1, state = next_order(state, ["a", "b", "c"])
    order2, _ = next_order(state, ["a", "b", "c"])
    assert order1 == ["a", "b", "c"]
    assert order2 == ["a", "c", "b"]


def test_climbing_into_a_new_tier_leads_outright_next_call() -> None:
    state = ScoutFallbackState(scores={"a": 5, "b": 5})
    state = record_success(state, "b")  # b now leads outright: 6 vs 5
    order, _ = next_order(state, ["a", "b"])
    assert order == ["b", "a"]


def test_state_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "scout_fallback.json"
    state = ScoutFallbackState(scores={"devstral-medium": 3}, rotation=7)
    save_state(path, state)
    reloaded = load_state(path)
    assert reloaded == state


def test_load_missing_file_returns_empty_state(tmp_path: Path) -> None:
    assert load_state(tmp_path / "nope.json") == ScoutFallbackState()


def test_load_corrupt_file_returns_empty_state(tmp_path: Path) -> None:
    path = tmp_path / "scout_fallback.json"
    path.write_text("not json", encoding="utf-8")
    assert load_state(path) == ScoutFallbackState()
