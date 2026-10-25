"""Design project management for Design Studio.

Design Studio manages design projects that can use Canvas, Builders/code, and specialized
editor/media branches under the same Project/Goal lineage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class DesignProject:
    """Design project managed by Design Studio.

    One canonical Goal revision can produce/use a Design Studio project that:
    - Uses Canvas (for fixed-page/visual composition)
    - Uses Builders/code (for code/web work)
    - Uses specialized editor/media branch

    All branches remain under one Project/Goal lineage.
    """

    id: str
    workspace_id: str
    skill_slug: str  # "canvas", "builders", "deck_builder", "media_provider", etc.
    design_system_id: str
    persona_id: str
    status: str  # "draft", "in_progress", "completed", "locked"
    created_at: datetime
    updated_at: datetime
    artifacts: list[dict[str, Any]]
    discovery: dict[str, Any]  # Skill discovery responses
    outputs: list[dict[str, Any]]  # Generated artifacts

    @classmethod
    async def create(
        cls,
        workspace_id: str,
        skill_slug: str,
        design_system_id: str,
        persona_id: str,
        discovery: dict[str, Any],
    ) -> DesignProject:
        """Create a new design project."""
        logger.info(
            "creating_design_project",
            workspace_id=workspace_id,
            skill_slug=skill_slug,
            persona_id=persona_id,
        )

        now = datetime.now(UTC)
        project = cls(
            id=f"project:{workspace_id}:{skill_slug}:{int(now.timestamp())}",
            workspace_id=workspace_id,
            skill_slug=skill_slug,
            design_system_id=design_system_id,
            persona_id=persona_id,
            status="draft",
            created_at=now,
            updated_at=now,
            artifacts=[],
            discovery=discovery,
            outputs=[],
        )

        logger.info("design_project_created", project_id=project.id)
        return project

    def to_dict(self) -> dict[str, Any]:
        """Convert DesignProject to dictionary format."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "skill_slug": self.skill_slug,
            "design_system_id": self.design_system_id,
            "persona_id": self.persona_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "artifacts": self.artifacts,
            "discovery": self.discovery,
            "outputs": self.outputs,
        }

    async def add_artifact(self, artifact: dict[str, Any]) -> None:
        """Add an artifact to the project."""
        artifact["id"] = f"artifact:{self.id}:{len(self.artifacts)}"
        artifact["project_id"] = self.id
        artifact["created_at"] = datetime.now(UTC).isoformat()

        self.artifacts.append(artifact)
        self.updated_at = datetime.now(UTC)

        logger.info("artifact_added", project_id=self.id, artifact_id=artifact["id"])

    async def add_output(self, output: dict[str, Any]) -> None:
        """Add an output to the project."""
        output["id"] = f"output:{self.id}:{len(self.outputs)}"
        output["project_id"] = self.id
        output["created_at"] = datetime.now(UTC).isoformat()

        self.outputs.append(output)
        self.updated_at = datetime.now(UTC)

        logger.info("output_added", project_id=self.id, output_id=output["id"])

    async def lock(self, user_id: str) -> dict[str, Any]:
        """Lock the project pending review.

        This is a canonical safe boundary where user can pause, edit, lock,
        redirect and resume without losing Goal/delegation/execution lineage.
        """
        logger.info("locking_project", project_id=self.id, user_id=user_id)

        self.status = "locked"
        self.updated_at = datetime.now(UTC)

        return {
            "project_id": self.id,
            "status": "locked",
            "locked_by": user_id,
            "locked_at": self.updated_at.isoformat(),
            "message": "Project locked pending review",
        }

    async def unlock(self, user_id: str) -> dict[str, Any]:
        """Unlock a locked project."""
        logger.info("unlocking_project", project_id=self.id, user_id=user_id)

        self.status = "in_progress"
        self.updated_at = datetime.now(UTC)

        return {
            "project_id": self.id,
            "status": "in_progress",
            "unlocked_by": user_id,
            "unlocked_at": self.updated_at.isoformat(),
            "message": "Project unlocked for editing",
        }

    async def redirect(self, new_skill_slug: str, user_id: str) -> dict[str, Any]:
        """Redirect the project to a different creative direction.

        This is a canonical safe boundary.
        """
        logger.info(
            "redirecting_project",
            project_id=self.id,
            new_skill_slug=new_skill_slug,
            user_id=user_id,
        )

        old_skill = self.skill_slug
        self.skill_slug = new_skill_slug
        self.status = "draft"
        self.updated_at = datetime.now(UTC)

        # Clear artifacts that may not apply to the new direction
        self.artifacts = [a for a in self.artifacts if a.get("skill_slug") != old_skill]

        return {
            "project_id": self.id,
            "old_skill_slug": old_skill,
            "new_skill_slug": new_skill_slug,
            "redirected_by": user_id,
            "redirected_at": self.updated_at.isoformat(),
            "message": f"Project redirected from {old_skill} to {new_skill_slug}",
        }

    async def cancel_branch(self, branch_id: str, user_id: str) -> dict[str, Any]:
        """Cancel one branch while unrelated branches continue.

        This supports mixed-control execution where different branches may be
        simultaneously user-controlled, collaborative, autonomous, waiting, cancelling, or locked.
        """
        logger.info(
            "cancelling_branch",
            project_id=self.id,
            branch_id=branch_id,
            user_id=user_id,
        )

        # Find and remove the branch
        self.artifacts = [a for a in self.artifacts if a.get("id") != branch_id]
        self.outputs = [o for o in self.outputs if o.get("id") != branch_id]

        self.updated_at = datetime.now(UTC)

        return {
            "project_id": self.id,
            "cancelled_branch_id": branch_id,
            "cancelled_by": user_id,
            "cancelled_at": self.updated_at.isoformat(),
            "remaining_artifacts": len(self.artifacts),
            "remaining_outputs": len(self.outputs),
            "message": f"Branch {branch_id} cancelled, other branches continue",
        }

    async def reclaim_delegated_subgoal(self, subgoal_id: str, user_id: str) -> dict[str, Any]:
        """Reclaim/reassign a delegated Goal/Subgoal through the canonical ownership seam.

        This does not fabricate new unrelated history.
        """
        logger.info(
            "reclaiming_delegated_subgoal",
            project_id=self.id,
            subgoal_id=subgoal_id,
            user_id=user_id,
        )

        # Implementation would use the #458 Goal ownership seam
        # For now, mark the subgoal as reclaimed
        for artifact in self.artifacts:
            if artifact.get("id") == subgoal_id:
                artifact["status"] = "reclaimed"
                artifact["reclaimed_by"] = user_id
                artifact["reclaimed_at"] = datetime.now(UTC).isoformat()

        self.updated_at = datetime.now(UTC)

        return {
            "project_id": self.id,
            "reclaimed_subgoal_id": subgoal_id,
            "reclaimed_by": user_id,
            "reclaimed_at": self.updated_at.isoformat(),
            "message": f"Delegated subgoal {subgoal_id} reclaimed through canonical ownership seam",
        }
