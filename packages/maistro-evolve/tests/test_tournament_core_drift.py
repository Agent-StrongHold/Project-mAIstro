"""Phase 16.5 item 4: cross-package fitness/tournament semantic drift check.

Confirms `maistro.agents.tournament.Tournament` (core) and
`maistro_evolve.tournament.EloTournament` (evolve) compute identical Elo
math for identical battle sequences, so the two packages don't silently
diverge in selection semantics. Not adversarial/formal — a plain
comparative unit test, per the Phase 16.5 plan.
"""

from __future__ import annotations

import pytest

from maistro.agents.tournament import Tournament
from maistro_evolve.tournament import EloTournament


def test_both_packages_share_the_same_default_elo_and_k_factor():
    from maistro.agents.tournament import _DEFAULT_ELO as core_default_elo
    from maistro.agents.tournament import _K_FACTOR as core_k_factor
    from maistro_evolve.tournament import _DEFAULT_ELO as evolve_default_elo
    from maistro_evolve.tournament import _K_FACTOR as evolve_k_factor

    assert core_default_elo == evolve_default_elo
    assert core_k_factor == evolve_k_factor


@pytest.mark.parametrize(
    "score_a,score_b",
    [
        (1.0, 0.0),
        (0.0, 1.0),
        (0.5, 0.5),
        (0.9, 0.3),
        (0.2, 0.8),
    ],
)
def test_single_battle_elo_update_matches_between_packages(score_a, score_b):
    core_t = Tournament()
    evolve_t = EloTournament()

    core_t.record_battle("intent_x", "agent_a", "agent_b", score_a, score_b)
    evolve_t.record_battle("bench_x", "agent_a", "agent_b", score_a, score_b)

    core_elo_a = core_t._get_rating("agent_a", "intent_x").elo
    core_elo_b = core_t._get_rating("agent_b", "intent_x").elo
    evolve_elo_a = evolve_t.get_elo("agent_a", "bench_x")
    evolve_elo_b = evolve_t.get_elo("agent_b", "bench_x")

    assert core_elo_a == pytest.approx(evolve_elo_a)
    assert core_elo_b == pytest.approx(evolve_elo_b)


def test_multi_battle_sequence_elo_trajectory_matches_between_packages():
    core_t = Tournament()
    evolve_t = EloTournament()

    sequence = [
        ("agent_a", "agent_b", 0.8, 0.2),
        ("agent_b", "agent_c", 0.4, 0.6),
        ("agent_a", "agent_c", 0.5, 0.5),
        ("agent_c", "agent_a", 0.9, 0.1),
        ("agent_b", "agent_a", 0.3, 0.7),
    ]

    for a, b, score_a, score_b in sequence:
        core_t.record_battle("shared_intent", a, b, score_a, score_b)
        evolve_t.record_battle("shared_intent", a, b, score_a, score_b)

    for agent in ("agent_a", "agent_b", "agent_c"):
        core_elo = core_t._get_rating(agent, "shared_intent").elo
        evolve_elo = evolve_t.get_elo(agent, "shared_intent")
        assert core_elo == pytest.approx(evolve_elo), f"Elo drift detected for {agent}"


def test_win_loss_draw_bookkeeping_matches_between_packages():
    core_t = Tournament()
    evolve_t = EloTournament()

    core_t.record_battle("intent_y", "agent_a", "agent_b", 1.0, 0.0)
    evolve_t.record_battle("bench_y", "agent_a", "agent_b", 1.0, 0.0)
    core_t.record_battle("intent_y", "agent_a", "agent_b", 0.0, 1.0)
    evolve_t.record_battle("bench_y", "agent_a", "agent_b", 0.0, 1.0)
    core_t.record_battle("intent_y", "agent_a", "agent_b", 0.5, 0.5)
    evolve_t.record_battle("bench_y", "agent_a", "agent_b", 0.5, 0.5)

    core_rating = core_t._get_rating("agent_a", "intent_y")
    evolve_rating = evolve_t._get_rating("agent_a", "bench_y")

    assert core_rating.wins == evolve_rating.wins == 1
    assert core_rating.losses == evolve_rating.losses == 1
    assert core_rating.draws == evolve_rating.draws == 1
    assert core_rating.win_rate == pytest.approx(evolve_rating.win_rate)
