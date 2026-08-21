"""Tournament: head-to-head agent scoring + auto-promotion via Elo ratings."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("maistro.tournament")

_DEFAULT_ELO = 1200.0
_K_FACTOR = 32.0
_PROMOTION_THRESHOLD = 50
_MIN_BATTLES = 10


@dataclass
class BattleRecord:
    """Result of a head-to-head agent comparison."""

    id: int = 0
    intent: str = ""
    agent_a: str = ""
    agent_b: str = ""
    winner: str = ""
    score_a: float = 0.0
    score_b: float = 0.0
    judge_model: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentRating:
    """Elo rating for an agent on a specific intent."""

    agent: str
    intent: str
    elo: float = _DEFAULT_ELO
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def total_battles(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        if self.total_battles == 0:
            return 0.0
        return (self.wins + 0.5 * self.draws) / self.total_battles


class Tournament:
    """In-memory tournament system with Elo ratings."""

    def __init__(self) -> None:
        self._ratings: dict[tuple[str, str], AgentRating] = {}
        self._battles: list[BattleRecord] = []
        self._next_id: int = 1
        self._max_battles: int = 10000

    def _get_rating(self, agent: str, intent: str) -> AgentRating:
        key = (agent, intent)
        if key not in self._ratings:
            self._ratings[key] = AgentRating(agent=agent, intent=intent)
        return self._ratings[key]

    def record_battle(
        self,
        intent: str,
        agent_a: str,
        agent_b: str,
        score_a: float,
        score_b: float,
        judge_model: str = "",
    ) -> BattleRecord:
        if score_a > score_b:
            winner = agent_a
        elif score_b > score_a:
            winner = agent_b
        else:
            winner = "draw"

        record = BattleRecord(
            id=self._next_id,
            intent=intent,
            agent_a=agent_a,
            agent_b=agent_b,
            winner=winner,
            score_a=score_a,
            score_b=score_b,
            judge_model=judge_model,
        )
        self._next_id += 1
        self._battles.append(record)

        if len(self._battles) > self._max_battles:
            self._battles.pop(0)

        ra = self._get_rating(agent_a, intent)
        rb = self._get_rating(agent_b, intent)

        expected_a = 1 / (1 + math.pow(10, (rb.elo - ra.elo) / 400))
        expected_b = 1 - expected_a

        if winner == agent_a:
            actual_a, actual_b = 1.0, 0.0
            ra.wins += 1
            rb.losses += 1
        elif winner == agent_b:
            actual_a, actual_b = 0.0, 1.0
            ra.losses += 1
            rb.wins += 1
        else:
            actual_a, actual_b = 0.5, 0.5
            ra.draws += 1
            rb.draws += 1

        ra.elo += _K_FACTOR * (actual_a - expected_a)
        rb.elo += _K_FACTOR * (actual_b - expected_b)

        logger.debug(
            "Battle %s vs %s on %s: winner=%s (elo: %.0f vs %.0f)",
            agent_a,
            agent_b,
            intent,
            winner,
            ra.elo,
            rb.elo,
        )
        return record

    def get_leaderboard(self, intent: str) -> list[dict[str, Any]]:
        ratings = [r for r in self._ratings.values() if r.intent == intent]
        ratings.sort(key=lambda r: r.elo, reverse=True)
        return [
            {
                "agent": r.agent,
                "elo": round(r.elo, 1),
                "wins": r.wins,
                "losses": r.losses,
                "draws": r.draws,
                "total": r.total_battles,
                "win_rate": round(r.win_rate, 3),
            }
            for r in ratings
        ]

    def check_promotions(self, intent: str, incumbent: str) -> str | None:
        """Check if any challenger should replace the incumbent."""
        inc_rating = self._get_rating(incumbent, intent)
        best_challenger: str | None = None
        best_margin: float = 0.0

        for _key, rating in self._ratings.items():
            if rating.intent != intent:
                continue
            if rating.agent == incumbent:
                continue
            if rating.total_battles < _MIN_BATTLES:
                continue

            margin = rating.elo - inc_rating.elo
            if margin >= _PROMOTION_THRESHOLD and margin > best_margin:
                best_challenger = rating.agent
                best_margin = margin

        if best_challenger:
            logger.info(
                "Promotion candidate: %s -> %s on intent=%s (margin=%.0f Elo)",
                incumbent,
                best_challenger,
                intent,
                best_margin,
            )
        return best_challenger

    def get_battle_history(
        self,
        agent: str | None = None,
        intent: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        filtered = self._battles
        if agent:
            filtered = [b for b in filtered if b.agent_a == agent or b.agent_b == agent]
        if intent:
            filtered = [b for b in filtered if b.intent == intent]

        return [
            {
                "id": b.id,
                "intent": b.intent,
                "agent_a": b.agent_a,
                "agent_b": b.agent_b,
                "winner": b.winner,
                "score_a": b.score_a,
                "score_b": b.score_b,
                "judge_model": b.judge_model,
                "timestamp": b.timestamp,
            }
            for b in filtered[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_battles": len(self._battles),
            "total_ratings": len(self._ratings),
            "intents_tracked": len({r.intent for r in self._ratings.values()}),
        }
