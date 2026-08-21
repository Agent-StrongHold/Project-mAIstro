"""Builders logging enhancement module.

Logs builder actions (Frank/Mason decisions, task decomposition),
tracks XP earned by builders, and logs learning promotions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("maistro.builders.logger")


@dataclass
class BuilderAction:
    """Builder action log entry."""

    timestamp: datetime
    builder_name: str
    action_type: str
    description: str
    xp_earned: int = 0
    metadata: dict[str, Any] | None = None


@dataclass
class LearningEvent:
    """Learning promotion event log entry."""

    timestamp: datetime
    learning_id: str
    source_agent: str
    promoted_by: str
    reason: str
    confidence: float


class BuildersLogger:
    """Logger for builder actions and learning events."""

    def __init__(self) -> None:
        self._actions: list[BuilderAction] = []
        self._learning_events: list[LearningEvent] = []
        self._xp_totals: dict[str, int] = {}

    def log_builder_action(
        self,
        builder_name: str,
        action_type: str,
        description: str,
        xp_earned: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        action = BuilderAction(
            timestamp=datetime.now(UTC),
            builder_name=builder_name,
            action_type=action_type,
            description=description,
            xp_earned=xp_earned,
            metadata=metadata,
        )
        self._actions.append(action)
        self._xp_totals[builder_name] = self._xp_totals.get(builder_name, 0) + xp_earned
        logger.info(
            "Builder action: %s %s +%d XP - %s",
            builder_name,
            action_type,
            xp_earned,
            description,
        )

    def log_learning_promotion(
        self,
        learning_id: str,
        source_agent: str,
        promoted_by: str,
        reason: str,
        confidence: float,
    ) -> None:
        event = LearningEvent(
            timestamp=datetime.now(UTC),
            learning_id=learning_id,
            source_agent=source_agent,
            promoted_by=promoted_by,
            reason=reason,
            confidence=confidence,
        )
        self._learning_events.append(event)
        logger.info(
            "Learning promoted: %s from %s by %s (confidence=%.2f) - %s",
            learning_id,
            source_agent,
            promoted_by,
            confidence,
            reason,
        )

    def get_actions(
        self,
        builder_name: str | None = None,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[BuilderAction]:
        filtered = self._actions
        if builder_name:
            filtered = [a for a in filtered if a.builder_name == builder_name]
        if since:
            filtered = [a for a in filtered if a.timestamp > since]
        return filtered[-limit:] if limit else filtered

    def get_xp_totals(self) -> dict[str, int]:
        return dict(self._xp_totals)

    def get_learning_events(
        self,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[LearningEvent]:
        filtered = self._learning_events
        if since:
            filtered = [e for e in filtered if e.timestamp > since]
        return filtered[-limit:] if limit else filtered

    def get_stats(self) -> dict[str, Any]:
        actions_by_builder: dict[str, list[Any]] = {}
        for action in self._actions:
            builder = action.builder_name
            if builder not in actions_by_builder:
                actions_by_builder[builder] = []
            actions_by_builder[builder].append(action)

        return {
            "total_actions": len(self._actions),
            "total_learning_events": len(self._learning_events),
            "actions_by_builder": actions_by_builder,
            "xp_totals": self._xp_totals,
        }

    def clear(self) -> None:
        self._actions.clear()
        self._learning_events.clear()
        self._xp_totals.clear()
