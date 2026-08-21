"""Scout model fallback: an ordered list of every usable model, ranked by
demonstrated skill, so a single benched/exhausted model can never silently
zero out the scout for a cycle.

The scout previously used one static model (``scout_model or model``) — when
that model got chronically benched (a real, observed failure mode: a shared
gateway alias becoming a single point of failure once a provider's quota
exhausted), ``scout_shortlist`` silently returned ``[]`` and every cycle fell
back to the generic single-slot objective for the rest of the run.

Skill is earned, never spent: every cycle whose promotion succeeds credits
the model that served as scout THAT cycle with one point
(``record_success``). There is deliberately no penalty for a later denied
RLPHD review — a denial is a verdict on the CODE a (possibly different)
competitor model wrote, not on the scout's proposal, so subtracting points
here would punish the wrong model for someone else's problem. Because scores
only ever go up, ordering between tiers needs no hysteresis: a model is
grouped into a "tier" with every other model sharing its exact score, tiers
sort strictly by score (a model that earns enough points to climb into a
higher tier leads outright, immediately — there's no noise to guard
against), and only WITHIN a tied tier does fairness matter: those models
round-robin who goes first, so ties don't calcify around whichever one
happened to score first. Persistence is one human-readable JSON file,
matching the existing ``RlphdStateStore``/``PendingReview`` convention.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class ScoutFallbackState:
    """``scores``: accumulated per-model success points (increment-only).
    ``rotation``: advances once per computed order, driving round-robin
    rotation within any tier of tied models — not itself meaningful outside
    that role."""

    scores: dict[str, int] = field(default_factory=dict)
    rotation: int = 0


def record_success(state: ScoutFallbackState, model: str) -> ScoutFallbackState:
    """One accepted patch => one point for the model that served as scout.
    Increment-only by design — see module docstring for why a denial must
    never subtract here."""
    if not model:
        return state
    new_scores = dict(state.scores)
    new_scores[model] = new_scores.get(model, 0) + 1
    return replace(state, scores=new_scores)


def next_order(
    state: ScoutFallbackState, all_models: list[str]
) -> tuple[list[str], ScoutFallbackState]:
    """The ordered list to try THIS call, plus the state to persist for next
    time (rotation advanced by one).

    Groups ``all_models`` into tiers by exact score (unscored models share
    the 0 tier), sorts tiers highest-score-first — a model that earns enough
    points to climb into a higher tier leads outright, immediately, no
    hysteresis needed since scores never move backward. Within any tier with
    more than one model, rotates the starting point by ``state.rotation`` so
    ties get fair exposure over time rather than the same model always
    leading.
    """
    by_score: dict[int, list[str]] = {}
    for m in all_models:
        by_score.setdefault(state.scores.get(m, 0), []).append(m)
    order: list[str] = []
    for tier_score in sorted(by_score.keys(), reverse=True):
        members = by_score[tier_score]
        if len(members) > 1:
            offset = state.rotation % len(members)
            members = members[offset:] + members[:offset]
        order.extend(members)
    return order, replace(state, rotation=state.rotation + 1)


def load_state(path: Path) -> ScoutFallbackState:
    if not path.is_file():
        return ScoutFallbackState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ScoutFallbackState()
    return ScoutFallbackState(scores=data.get("scores", {}), rotation=data.get("rotation", 0))


def save_state(path: Path, state: ScoutFallbackState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
