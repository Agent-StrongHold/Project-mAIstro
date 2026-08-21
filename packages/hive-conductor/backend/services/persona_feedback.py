"""Persona-scoped feedback aggregation — Persona/Workspace system, Phase I.

Aggregates PersonaFeedback rows (models/persona_feedback.py) for one persona
across every workspace that instantiates it. Deliberately just aggregation
for now: ADR-060's Tier 2 preference-residual calibration (scikit-learn +
Bradley-Terry) and hill-climber-driven refinement proposals are their own
follow-up, not built here -- this module is the plain data surface they'll
eventually read from.
"""

from __future__ import annotations

from models.persona_feedback import PersonaFeedback
from pydantic import BaseModel, ConfigDict


class PersonaFeedbackSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persona_template_id: str
    thumbs_up: int
    thumbs_down: int
    recent: list[PersonaFeedback]


def summarize(
    persona_template_id: str,
    entries: list[PersonaFeedback],
    *,
    recent_limit: int = 20,
) -> PersonaFeedbackSummary:
    """Aggregate every entry for one persona, most-recent-first."""
    matching = [e for e in entries if e.persona_template_id == persona_template_id]
    recent = sorted(matching, key=lambda e: e.created_at, reverse=True)[:recent_limit]
    return PersonaFeedbackSummary(
        persona_template_id=persona_template_id,
        thumbs_up=sum(1 for e in matching if e.thumb == "up"),
        thumbs_down=sum(1 for e in matching if e.thumb == "down"),
        recent=recent,
    )
