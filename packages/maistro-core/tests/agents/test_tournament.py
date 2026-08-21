"""Coverage for maistro.agents.tournament.Tournament (was 0%)."""

from __future__ import annotations

import math

from maistro.agents.tournament import (
    _DEFAULT_ELO,
    _K_FACTOR,
    _MIN_BATTLES,
    _PROMOTION_THRESHOLD,
    AgentRating,
    BattleRecord,
    Tournament,
)


def _expected(ra: float, rb: float) -> float:
    return 1 / (1 + math.pow(10, (rb - ra) / 400))


# --- AgentRating -----------------------------------------------------------


def test_agent_rating_defaults() -> None:
    rating = AgentRating(agent="a", intent="chat")
    assert rating.elo == _DEFAULT_ELO
    assert rating.wins == 0
    assert rating.losses == 0
    assert rating.draws == 0
    assert rating.total_battles == 0
    assert rating.win_rate == 0.0


def test_agent_rating_win_rate_counts_draws_as_half() -> None:
    rating = AgentRating(agent="a", intent="chat", wins=3, losses=1, draws=2)
    assert rating.total_battles == 6
    assert rating.win_rate == (3 + 0.5 * 2) / 6


def test_agent_rating_win_rate_zero_battles_is_zero_not_division_error() -> None:
    rating = AgentRating(agent="a", intent="chat", wins=0, losses=0, draws=0)
    assert rating.win_rate == 0.0


# --- record_battle: winner determination -----------------------------------


def test_record_battle_agent_a_wins_when_score_a_higher() -> None:
    t = Tournament()
    record = t.record_battle("chat", "alpha", "beta", score_a=0.9, score_b=0.4)
    assert record.winner == "alpha"
    assert record.score_a == 0.9
    assert record.score_b == 0.4
    assert record.id == 1
    assert record.intent == "chat"
    assert record.agent_a == "alpha"
    assert record.agent_b == "beta"


def test_record_battle_agent_b_wins_when_score_b_higher() -> None:
    t = Tournament()
    record = t.record_battle("chat", "alpha", "beta", score_a=0.2, score_b=0.7)
    assert record.winner == "beta"


def test_record_battle_draw_when_scores_equal() -> None:
    t = Tournament()
    record = t.record_battle("chat", "alpha", "beta", score_a=0.5, score_b=0.5)
    assert record.winner == "draw"


def test_record_battle_ids_increment_across_calls() -> None:
    t = Tournament()
    r1 = t.record_battle("chat", "a", "b", 1.0, 0.0)
    r2 = t.record_battle("chat", "a", "b", 1.0, 0.0)
    r3 = t.record_battle("chat", "a", "b", 1.0, 0.0)
    assert (r1.id, r2.id, r3.id) == (1, 2, 3)


def test_record_battle_judge_model_default_is_empty_string() -> None:
    t = Tournament()
    record = t.record_battle("chat", "a", "b", 1.0, 0.0)
    assert record.judge_model == ""


def test_record_battle_judge_model_recorded_when_provided() -> None:
    t = Tournament()
    record = t.record_battle("chat", "a", "b", 1.0, 0.0, judge_model="gpt-judge")
    assert record.judge_model == "gpt-judge"


# --- record_battle: exact Elo math ------------------------------------------


def test_record_battle_equal_elo_win_moves_rating_by_half_k() -> None:
    # Both start at default Elo 1200, so expected_a = expected_b = 0.5.
    # Winner gets +K*(1-0.5) = +16, loser gets +K*(0-0.5) = -16.
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)

    ra = t._get_rating("alpha", "chat")
    rb = t._get_rating("beta", "chat")

    assert ra.elo == _DEFAULT_ELO + _K_FACTOR * 0.5
    assert rb.elo == _DEFAULT_ELO - _K_FACTOR * 0.5
    assert ra.elo == 1216.0
    assert rb.elo == 1184.0
    assert ra.wins == 1
    assert ra.losses == 0
    assert rb.wins == 0
    assert rb.losses == 1


def test_record_battle_draw_at_equal_elo_leaves_elo_unchanged() -> None:
    # expected_a = expected_b = 0.5, actual_a = actual_b = 0.5 -> delta is 0.
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=0.5, score_b=0.5)

    ra = t._get_rating("alpha", "chat")
    rb = t._get_rating("beta", "chat")

    assert ra.elo == _DEFAULT_ELO
    assert rb.elo == _DEFAULT_ELO
    assert ra.draws == 1
    assert rb.draws == 1


def test_record_battle_underdog_upset_gains_more_than_half_k() -> None:
    # Pre-seed unequal ratings: alpha=1400, beta=1000 (400 elo gap).
    t = Tournament()
    t._ratings[("alpha", "chat")] = AgentRating(agent="alpha", intent="chat", elo=1400.0)
    t._ratings[("beta", "chat")] = AgentRating(agent="beta", intent="chat", elo=1000.0)

    expected_alpha = _expected(1400.0, 1000.0)
    expected_beta = 1 - expected_alpha

    # Underdog beta wins.
    t.record_battle("chat", "alpha", "beta", score_a=0.1, score_b=0.9)

    ra = t._get_rating("alpha", "chat")
    rb = t._get_rating("beta", "chat")

    assert ra.elo == 1400.0 + _K_FACTOR * (0.0 - expected_alpha)
    assert rb.elo == 1000.0 + _K_FACTOR * (1.0 - expected_beta)
    # Favorite losing to a 400-point underdog should drop more than half of K.
    assert _DEFAULT_ELO < 1400.0  # sanity: default unused here, just documents baseline
    assert (1400.0 - ra.elo) > _K_FACTOR / 2


def test_record_battle_favorite_win_gains_less_than_half_k() -> None:
    t = Tournament()
    t._ratings[("alpha", "chat")] = AgentRating(agent="alpha", intent="chat", elo=1400.0)
    t._ratings[("beta", "chat")] = AgentRating(agent="beta", intent="chat", elo=1000.0)

    expected_alpha = _expected(1400.0, 1000.0)

    t.record_battle("chat", "alpha", "beta", score_a=0.9, score_b=0.1)

    ra = t._get_rating("alpha", "chat")
    assert ra.elo == 1400.0 + _K_FACTOR * (1.0 - expected_alpha)
    # A heavy favorite winning the expected result should gain less than half K.
    assert (ra.elo - 1400.0) < _K_FACTOR / 2


def test_record_battle_separate_intents_get_independent_ratings() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    t.record_battle("code", "alpha", "beta", score_a=0.0, score_b=1.0)

    chat_alpha = t._get_rating("alpha", "chat")
    code_alpha = t._get_rating("alpha", "code")
    assert chat_alpha.elo == 1216.0
    assert code_alpha.elo == 1184.0
    assert chat_alpha.wins == 1
    assert code_alpha.losses == 1


def test_record_battle_evicts_oldest_when_exceeding_max_battles() -> None:
    t = Tournament()
    t._max_battles = 3
    for _i in range(4):
        t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    assert len(t._battles) == 3
    # The first battle (id=1) should have been evicted.
    assert [b.id for b in t._battles] == [2, 3, 4]


# --- get_leaderboard ---------------------------------------------------------


def test_get_leaderboard_sorted_descending_by_elo() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    board = t.get_leaderboard("chat")
    assert [row["agent"] for row in board] == ["alpha", "beta"]
    assert board[0]["elo"] == 1216.0
    assert board[1]["elo"] == 1184.0
    assert board[0]["wins"] == 1
    assert board[0]["losses"] == 0
    assert board[0]["total"] == 1
    assert board[0]["win_rate"] == 1.0
    assert board[1]["win_rate"] == 0.0


def test_get_leaderboard_filters_by_intent() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    t.record_battle("code", "gamma", "delta", score_a=1.0, score_b=0.0)
    board = t.get_leaderboard("chat")
    assert {row["agent"] for row in board} == {"alpha", "beta"}


def test_get_leaderboard_empty_intent_returns_empty_list() -> None:
    t = Tournament()
    assert t.get_leaderboard("nonexistent") == []


def test_get_leaderboard_rounds_elo_and_win_rate() -> None:
    t = Tournament()
    t._ratings[("alpha", "chat")] = AgentRating(
        agent="alpha", intent="chat", elo=1234.567, wins=1, losses=2
    )
    board = t.get_leaderboard("chat")
    assert board[0]["elo"] == 1234.6
    assert board[0]["win_rate"] == round(1 / 3, 3)


# --- check_promotions ---------------------------------------------------------


def test_check_promotions_returns_none_when_no_challengers() -> None:
    t = Tournament()
    assert t.check_promotions("chat", "incumbent") is None


def test_check_promotions_returns_none_when_below_min_battles() -> None:
    t = Tournament()
    challenger = AgentRating(agent="challenger", intent="chat", elo=1300.0, wins=_MIN_BATTLES - 1)
    t._ratings[("challenger", "chat")] = challenger
    t._ratings[("incumbent", "chat")] = AgentRating(agent="incumbent", intent="chat", elo=1200.0)
    assert t.check_promotions("chat", "incumbent") is None


def test_check_promotions_returns_none_when_margin_below_threshold() -> None:
    t = Tournament()
    # Margin of exactly threshold-1 should not promote.
    challenger = AgentRating(
        agent="challenger",
        intent="chat",
        elo=1200.0 + _PROMOTION_THRESHOLD - 1,
        wins=_MIN_BATTLES,
    )
    t._ratings[("challenger", "chat")] = challenger
    t._ratings[("incumbent", "chat")] = AgentRating(agent="incumbent", intent="chat", elo=1200.0)
    assert t.check_promotions("chat", "incumbent") is None


def test_check_promotions_promotes_at_exact_threshold_margin() -> None:
    t = Tournament()
    challenger = AgentRating(
        agent="challenger",
        intent="chat",
        elo=1200.0 + _PROMOTION_THRESHOLD,
        wins=_MIN_BATTLES,
    )
    t._ratings[("challenger", "chat")] = challenger
    t._ratings[("incumbent", "chat")] = AgentRating(agent="incumbent", intent="chat", elo=1200.0)
    assert t.check_promotions("chat", "incumbent") == "challenger"


def test_check_promotions_picks_largest_margin_among_multiple_challengers() -> None:
    t = Tournament()
    t._ratings[("incumbent", "chat")] = AgentRating(agent="incumbent", intent="chat", elo=1200.0)
    t._ratings[("small_margin", "chat")] = AgentRating(
        agent="small_margin", intent="chat", elo=1260.0, wins=_MIN_BATTLES
    )
    t._ratings[("big_margin", "chat")] = AgentRating(
        agent="big_margin", intent="chat", elo=1400.0, wins=_MIN_BATTLES
    )
    assert t.check_promotions("chat", "incumbent") == "big_margin"


def test_check_promotions_ignores_incumbent_itself() -> None:
    t = Tournament()
    t._ratings[("incumbent", "chat")] = AgentRating(
        agent="incumbent", intent="chat", elo=1400.0, wins=_MIN_BATTLES
    )
    assert t.check_promotions("chat", "incumbent") is None


def test_check_promotions_ignores_other_intents() -> None:
    t = Tournament()
    t._ratings[("incumbent", "chat")] = AgentRating(agent="incumbent", intent="chat", elo=1200.0)
    t._ratings[("challenger", "code")] = AgentRating(
        agent="challenger", intent="code", elo=1400.0, wins=_MIN_BATTLES
    )
    assert t.check_promotions("chat", "incumbent") is None


# --- get_battle_history -------------------------------------------------------


def test_get_battle_history_returns_all_fields() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0, judge_model="judge1")
    history = t.get_battle_history()
    assert len(history) == 1
    entry = history[0]
    assert entry["id"] == 1
    assert entry["intent"] == "chat"
    assert entry["agent_a"] == "alpha"
    assert entry["agent_b"] == "beta"
    assert entry["winner"] == "alpha"
    assert entry["score_a"] == 1.0
    assert entry["score_b"] == 0.0
    assert entry["judge_model"] == "judge1"
    assert "timestamp" in entry


def test_get_battle_history_filters_by_agent_either_side() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    t.record_battle("chat", "gamma", "alpha", score_a=0.0, score_b=1.0)
    t.record_battle("chat", "gamma", "delta", score_a=1.0, score_b=0.0)

    history = t.get_battle_history(agent="alpha")
    assert len(history) == 2
    assert all("alpha" in (h["agent_a"], h["agent_b"]) for h in history)


def test_get_battle_history_filters_by_intent() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    t.record_battle("code", "alpha", "beta", score_a=1.0, score_b=0.0)
    history = t.get_battle_history(intent="code")
    assert len(history) == 1
    assert history[0]["intent"] == "code"


def test_get_battle_history_respects_limit_and_returns_most_recent() -> None:
    t = Tournament()
    for _ in range(5):
        t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    history = t.get_battle_history(limit=2)
    assert len(history) == 2
    assert [h["id"] for h in history] == [4, 5]


def test_get_battle_history_no_filters_returns_everything_up_to_default_limit() -> None:
    t = Tournament()
    for _ in range(3):
        t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    history = t.get_battle_history()
    assert len(history) == 3


# --- get_stats -----------------------------------------------------------------


def test_get_stats_empty_tournament() -> None:
    t = Tournament()
    stats = t.get_stats()
    assert stats == {"total_battles": 0, "total_ratings": 0, "intents_tracked": 0}


def test_get_stats_counts_battles_ratings_and_distinct_intents() -> None:
    t = Tournament()
    t.record_battle("chat", "alpha", "beta", score_a=1.0, score_b=0.0)
    t.record_battle("chat", "alpha", "beta", score_a=0.0, score_b=1.0)
    t.record_battle("code", "gamma", "delta", score_a=1.0, score_b=0.0)

    stats = t.get_stats()
    assert stats["total_battles"] == 3
    assert stats["total_ratings"] == 4
    assert stats["intents_tracked"] == 2


# --- BattleRecord dataclass defaults ------------------------------------------


def test_battle_record_defaults() -> None:
    record = BattleRecord()
    assert record.id == 0
    assert record.intent == ""
    assert record.agent_a == ""
    assert record.agent_b == ""
    assert record.winner == ""
    assert record.score_a == 0.0
    assert record.score_b == 0.0
    assert record.judge_model == ""
    assert isinstance(record.timestamp, float)
