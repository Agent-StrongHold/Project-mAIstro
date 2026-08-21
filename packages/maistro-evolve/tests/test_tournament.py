from __future__ import annotations

import pytest

from maistro_evolve.tournament import _DEFAULT_ELO, _K_FACTOR, EloTournament


class TestEloTournament:
    def test_new_tournament_has_no_battles(self):
        t = EloTournament()
        assert t.get_stats()["total_battles"] == 0

    def test_record_battle_winner_a(self):
        t = EloTournament()
        battle = t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        assert battle.winner_id == "g1"
        assert battle.score_a == 0.8
        assert battle.score_b == 0.4

    def test_record_battle_winner_b(self):
        t = EloTournament()
        battle = t.record_battle("proxy_ifeval", "g1", "g2", 0.3, 0.9)
        assert battle.winner_id == "g2"

    def test_record_battle_draw(self):
        t = EloTournament()
        battle = t.record_battle("proxy_ifeval", "g1", "g2", 0.5, 0.5)
        assert battle.winner_id == "draw"

    def test_elo_updates_on_win(self):
        t = EloTournament()
        t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        elo_a = t.get_elo("g1", "proxy_ifeval")
        elo_b = t.get_elo("g2", "proxy_ifeval")
        assert elo_a > _DEFAULT_ELO
        assert elo_b < _DEFAULT_ELO
        delta = elo_a - _DEFAULT_ELO
        assert abs(delta - _K_FACTOR * (1.0 - 0.5)) < 0.01

    def test_elo_converges_over_many_battles(self):
        t = EloTournament()
        for _ in range(50):
            t.record_battle("proxy_ifeval", "strong", "weak", 0.8, 0.2)
        elo_strong = t.get_elo("strong", "proxy_ifeval")
        elo_weak = t.get_elo("weak", "proxy_ifeval")
        assert elo_strong > elo_weak
        assert elo_strong > 1400

    def test_get_avg_elo(self):
        t = EloTournament()
        t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        t.record_battle("proxy_bfcl", "g1", "g2", 0.3, 0.7)
        avg = t.get_avg_elo("g1")
        assert 1100 < avg < 1300

    def test_get_avg_elo_unknown(self):
        t = EloTournament()
        assert t.get_avg_elo("unknown") == _DEFAULT_ELO

    def test_leaderboard_sorted_by_elo(self):
        t = EloTournament()
        for _ in range(20):
            t.record_battle("proxy_ifeval", "g1", "g2", 0.9, 0.1)
            t.record_battle("proxy_ifeval", "g2", "g3", 0.8, 0.2)
        lb = t.get_leaderboard()
        assert lb[0]["genome_id"] == "g1"
        assert lb[0]["avg_elo"] > lb[1]["avg_elo"]

    def test_leaderboard_filtered_by_benchmark(self):
        t = EloTournament()
        t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        t.record_battle("proxy_bfcl", "g1", "g2", 0.3, 0.7)
        lb = t.get_leaderboard(benchmark="proxy_ifeval")
        assert all(isinstance(e, dict) for e in lb)
        assert [e["total_battles"] for e in lb] == [1, 1]

    def test_unfiltered_leaderboard_sums_battles_across_benchmarks(self):
        """No battle is recorded against the name "overall", so looking one up
        reported total_battles=0 for every genome — a perfect record reading as
        unproven. This is user-facing via GET /v1/tournament/leaderboard."""
        t = EloTournament()
        t.record_battle("ifeval", "g1", "g2", 0.9, 0.1)
        t.record_battle("bfcl", "g1", "g2", 0.9, 0.1)
        t.record_battle("swebench", "g1", "g2", 0.5, 0.5)  # draw

        board = {e["genome_id"]: e for e in t.get_leaderboard()}
        assert board["g1"]["total_battles"] == 3
        assert board["g2"]["total_battles"] == 3
        assert board["g1"]["win_rate"] == pytest.approx((2 + 0.5) / 3)
        assert board["g2"]["win_rate"] == pytest.approx(0.5 / 3)

    def test_reading_the_leaderboard_does_not_mutate_ratings(self):
        """_get_rating creates on miss, so the "overall" lookup inserted a
        phantom default-elo rating per genome. get_avg_elo averages over every
        rating for a genome, so merely reading the leaderboard moved the number
        that feeds compute_fitness's elo component."""
        t = EloTournament()
        t.record_battle("ifeval", "g1", "g2", 0.9, 0.1)
        t.record_battle("bfcl", "g1", "g2", 0.9, 0.1)

        before = t.get_avg_elo("g1")
        t.get_leaderboard()
        assert t.get_avg_elo("g1") == before
        assert t.get_leaderboard() == t.get_leaderboard()  # idempotent
        assert all(bench != "overall" for _gid, bench in t._ratings)

    def test_empty_leaderboard(self):
        assert EloTournament().get_leaderboard() == []
        assert EloTournament().get_leaderboard(benchmark="ifeval") == []

    def test_tournament_select(self):
        t = EloTournament()
        for _ in range(20):
            t.record_battle("proxy_ifeval", "strong", "weak", 0.9, 0.1)
        import random

        random.seed(42)
        selected = t.tournament_select(["strong", "weak", "medium"], tournament_size=3)
        assert selected is not None
        assert selected in ["strong", "weak", "medium"]

    def test_tournament_select_empty(self):
        t = EloTournament()
        assert t.tournament_select([]) is None

    def test_battle_history_filter(self):
        t = EloTournament()
        t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        t.record_battle("proxy_bfcl", "g1", "g3", 0.5, 0.6)
        history = t.get_battle_history(genome_id="g1")
        assert len(history) == 2
        ife_history = t.get_battle_history(benchmark="proxy_ifeval")
        assert len(ife_history) == 1

    def test_stats(self):
        t = EloTournament()
        t.record_battle("proxy_ifeval", "g1", "g2", 0.8, 0.4)
        t.record_battle("proxy_bfcl", "g1", "g2", 0.5, 0.6)
        stats = t.get_stats()
        assert stats["total_battles"] == 2
        assert stats["total_genomes_rated"] == 2
        assert stats["benchmarks_tracked"] == 2
