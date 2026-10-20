"""CreativeBrief implementation for Design Studio.

CreativeBrief is Design Studio's versioned creative projection of one exact canonical Goal revision.
It supplies audience treatment, creative constraints, requested artifacts/channels, source truth,
and other creative context without becoming a second Goal.

This does not duplicate #458 Goal semantics; it's a Design Studio projection that can coexist
with the canonical Goal hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class CreativeBrief:
    """Design Studio's versioned creative projection of one exact canonical Goal revision.

    A CreativeBrief supplies audience treatment, creative constraints, requested artifacts/channels,
    source truth, and other creative context without becoming a second Goal.

    This is owned by Design Studio and is separate from the canonical Goal hierarchy
    established by #458.
    """

    id: str
    goal_id: str
    goal_revision: str
    persona_id: str
    design_system_id: str
    workspace_id: str
    script_id: str
    opening: str
    answers: dict[str, Any]
    sources: dict[str, str]
    options: dict[str, str]
    assumed: list[str]
    notes: list[str]
    turns: int
    created_at: datetime
    updated_at: datetime
    status: str = "active"  # "active", "committed", "dropped"

    @classmethod
    async def from_goal_revision(
        cls,
        goal_id: str,
        goal_revision: str,
        goal_state: dict[str, Any],
        persona_id: str,
        design_system_id: str,
        workspace_id: str,
    ) -> CreativeBrief:
        """Create a CreativeBrief from a canonical Goal revision.

        This creates the Design Studio projection without duplicating Goal semantics.
        """
        logger.info(
            "creating_creative_brief_from_goal",
            goal_id=goal_id,
            goal_revision=goal_revision,
            persona_id=persona_id,
            design_system_id=design_system_id,
        )

        # Extract creative context from Goal state
        audience = goal_state.get("audience", "Unknown audience")
        subject = goal_state.get("subject", "Unknown subject")
        outcome = goal_state.get("outcome", "Unknown outcome")
        channel = goal_state.get("channel", "Unknown channel")

        # Create opening statement based on Goal state
        opening = f"Create a {channel} about {subject} that {outcome} for {audience}."

        # Create structured answers from Goal state
        answers = {
            "subject": subject,
            "outcome": outcome,
            "channel": channel,
            "audience": audience,
        }

        # Add other fields as needed
        sources = {"goal": "canonical_goal_revision"}
        options = {}
        assumed = []
        notes = []
        turns = 1

        now = datetime.now(UTC)
        brief = cls(
            id=f"brief:{goal_id}:{goal_revision}",
            goal_id=goal_id,
            goal_revision=goal_revision,
            persona_id=persona_id,
            design_system_id=design_system_id,
            workspace_id=workspace_id,
            script_id="video_brief",  # This would come from Goal metadata
            opening=opening,
            answers=answers,
            sources=sources,
            options=options,
            assumed=assumed,
            notes=notes,
            turns=turns,
            created_at=now,
            updated_at=now,
            status="active",
        )

        logger.info("creative_brief_created", brief_id=brief.id)
        return brief

    def to_dict(self) -> dict[str, Any]:
        """Convert CreativeBrief to dictionary format."""
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "persona_id": self.persona_id,
            "design_system_id": self.design_system_id,
            "workspace_id": self.workspace_id,
            "script_id": self.script_id,
            "opening": self.opening,
            "answers": self.answers,
            "sources": self.sources,
            "options": self.options,
            "assumed": self.assumed,
            "notes": self.notes,
            "turns": self.turns,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
        }

    async def update_from_goal_revision(self, goal_state: dict[str, Any]) -> None:
        """Update CreativeBrief with new Goal revision state.

        This ensures the Agent consumes the newest committed Goal/CreativeBrief/user constraints
        before newly eligible work.
        """
        logger.info("updating_creative_brief_from_new_goal", brief_id=self.id)

        # Update fields based on new Goal state
        self.answers.update(
            subject=goal_state.get("subject", self.answers.get("subject", "Unknown")),
            outcome=goal_state.get("outcome", self.answers.get("outcome", "Unknown")),
            channel=goal_state.get("channel", self.answers.get("channel", "Unknown")),
            audience=goal_state.get("audience", self.answers.get("audience", "Unknown")),
        )

        self.updated_at = datetime.now(UTC)
        self.status = "active"

        logger.info("creative_brief_updated", brief_id=self.id)

    async def apply_user_constraints(self, constraints: dict[str, Any]) -> None:
        """Apply user edits, locks, guidance, or redirects as durable constraints.

        Changing only creative guidance records CreativeBrief/shared-decision state,
        not the canonical Goal state.
        """
        logger.info("applying_user_constraints", brief_id=self.id, constraints=constraints)

        # Apply user constraints to CreativeBrief
        for key, value in constraints.items():
            if key in self.answers:
                self.answers[key] = value
            else:
                self.notes.append(f"User constraint: {key}={value}")

        self.updated_at = datetime.now(UTC)

    async def commit_to_goal(self) -> dict[str, Any]:
        """Commit CreativeBrief changes to Goal state if desired outcome changed.

        Changing desired outcome records canonical Goal state; changing only creative
        guidance records CreativeBrief/shared-decision state.
        """
        logger.info("committing_creative_brief_to_goal", brief_id=self.id)

        # Determine if desired outcome changed
        outcome_changed = self._detect_outcome_change()

        if outcome_changed:
            # This would create a new Goal revision
            result = {
                "goal_id": self.goal_id,
                "new_revision": str(int(self.goal_revision) + 1),
                "outcome_changed": True,
                "creative_brief_state": self.to_dict(),
            }
            logger.info("goal_revision_committed", result=result)
            return result
        else:
            # Only creative guidance changed - update CreativeBrief state
            result = {
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "outcome_changed": False,
                "creative_brief_state": self.to_dict(),
            }
            logger.info("creative_brief_guidance_updated", result=result)
            return result

    def _detect_outcome_change(self) -> bool:
        """Detect if the desired outcome has changed from the Goal."""
        # Implementation would compare CreativeBrief answers with Goal requirements
        # For now, return False
        return False

    async def pause(self) -> dict[str, Any]:
        """Pause execution at canonical safe boundaries."""
        logger.info("pausing_creative_brief", brief_id=self.id)
        self.status = "paused"
        self.updated_at = datetime.now(UTC)
        return {"status": "paused", "brief_id": self.id}

    async def resume(self) -> dict[str, Any]:
        """Resume execution after user intervention."""
        logger.info("resuming_creative_brief", brief_id=self.id)
        self.status = "active"
        self.updated_at = datetime.now(UTC)
        return {"status": "active", "brief_id": self.id}

    async def cancel(self) -> dict[str, Any]:
        """Cancel the CreativeBrief (drop it)."""
        logger.info("cancelling_creative_brief", brief_id=self.id)
        self.status = "dropped"
        self.updated_at = datetime.now(UTC)
        return {"status": "dropped", "brief_id": self.id}
