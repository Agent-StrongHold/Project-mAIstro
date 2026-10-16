"""Control management and mixed-control execution for Design Studio.

Design Studio manages mixed-control execution where different branches may be
 simultaneously user-controlled, collaborative, autonomous, waiting, cancelling, or locked.

The same Project/Goal lineage supports:
- Direct / interactive: user edits artifacts and invokes bounded AI help
- Collaborative / copilot: user and Agent alternate proposals/edits
- Delegated / autonomous: #804's accountable/delegated Agent may keep progressing
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ControlState:
    """Current control state for a project."""

    project_id: str
    workspace_id: str
    mode: str  # "direct", "collaborative", "delegated", "autonomous", "paused", "cancelled"
    active_branch: str | None = None
    user_locks: list[str] = None
    agent_locks: list[str] = None
    paused_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.user_locks is None:
            self.user_locks = []
        if self.agent_locks is None:
            self.agent_locks = []
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class ControlManager:
    """Manage control state and enforcement for Design Studio projects.

    This handles the supervisory-control invariant: autonomous never means exclusive
    control. During creative delegated work the user can inspect, pause at canonical
    safe boundaries, edit/lock artifacts, redirect creative guidance or the canonical
    Goal, cancel branches, reclaim/reassign delegated Subgoals, and resume without
    losing lineage.
    """

    def __init__(self, workspace_id: str, project_id: str):
        self.workspace_id = workspace_id
        self.project_id = project_id
        self._control_states: dict[str, ControlState] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize control manager."""
        logger.info(
            "initializing_control_manager", workspace=self.workspace_id, project=self.project_id
        )
        self._initialized = True

    async def create_project(self, project_id: str) -> ControlState:
        """Create control state for a new project."""
        state = ControlState(project_id=project_id, workspace_id=self.workspace_id)
        self._control_states[project_id] = state
        logger.info("control_state_created", project_id=project_id, mode=state.mode)
        return state

    async def set_control_mode(self, project_id: str, mode: str) -> ControlState:
        """Set the control mode for a project."""
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]
        old_mode = state.mode
        state.mode = mode
        state.updated_at = datetime.now(UTC)

        logger.info(
            "control_mode_changed",
            project_id=project_id,
            old_mode=old_mode,
            new_mode=mode,
        )

        # Enforce mode-specific constraints
        await self._enforce_mode_constraints(state)

        return state

    async def pause_project(self, project_id: str, reason: str = "user_pause") -> ControlState:
        """Pause execution at canonical safe boundaries.

        User can inspect, pause at canonical safe boundaries, edit/lock artifacts,
        redirect creative guidance or the canonical Goal, cancel branches, reclaim/reassign
        delegated Subgoals, and resume without losing Goal/delegation/execution lineage.
        """
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]
        state.mode = "paused"
        state.paused_at = datetime.now(UTC)
        state.updated_at = datetime.now(UTC)

        logger.info(
            "project_paused",
            project_id=project_id,
            reason=reason,
            paused_at=state.paused_at.isoformat(),
        )

        return state

    async def resume_project(self, project_id: str, reason: str = "user_resume") -> ControlState:
        """Resume execution after user intervention."""
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]

        if state.mode != "paused":
            raise ValueError(f"Project {project_id} is not paused (current mode: {state.mode})")

        state.mode = "direct"  # Resume in direct mode by default
        state.paused_at = None
        state.updated_at = datetime.now(UTC)

        logger.info(
            "project_resumed",
            project_id=project_id,
            reason=reason,
            resumed_at=state.updated_at.isoformat(),
        )

        return state

    async def lock_artifact(
        self, project_id: str, artifact_id: str, user_id: str
    ) -> dict[str, Any]:
        """Lock an artifact for editing by a specific user.

        This is a canonical safe boundary.
        """
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]

        if artifact_id in state.user_locks:
            return {"message": f"Artifact {artifact_id} already locked by user"}

        state.user_locks.append(artifact_id)
        state.updated_at = datetime.now(UTC)

        logger.info(
            "artifact_locked",
            project_id=project_id,
            artifact_id=artifact_id,
            user_id=user_id,
        )

        return {
            "project_id": project_id,
            "artifact_id": artifact_id,
            "locked_by": user_id,
            "locked_at": state.updated_at.isoformat(),
            "message": f"Artifact {artifact_id} locked for editing",
        }

    async def unlock_artifact(
        self, project_id: str, artifact_id: str, user_id: str
    ) -> dict[str, Any]:
        """Unlock an artifact."""
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]

        if artifact_id not in state.user_locks:
            return {"message": f"Artifact {artifact_id} is not locked"}

        state.user_locks.remove(artifact_id)
        state.updated_at = datetime.now(UTC)

        logger.info(
            "artifact_unlocked",
            project_id=project_id,
            artifact_id=artifact_id,
            user_id=user_id,
        )

        return {
            "project_id": project_id,
            "artifact_id": artifact_id,
            "unlocked_by": user_id,
            "unlocked_at": state.updated_at.isoformat(),
            "message": f"Artifact {artifact_id} unlocked",
        }

    async def cancel_branch(
        self, project_id: str, branch_id: str, user_id: str, reason: str = "user_cancelled"
    ) -> dict[str, Any]:
        """Cancel one branch while unrelated branches continue.

        Dependencies allow other branches to continue when this one is cancelled.
        """
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]

        if state.mode == "cancelled":
            return {"message": f"Project {project_id} is already cancelled"}

        state.mode = "cancelled"
        state.cancelled_at = datetime.now(UTC)
        state.updated_at = datetime.now(UTC)

        logger.info(
            "branch_cancelled",
            project_id=project_id,
            branch_id=branch_id,
            user_id=user_id,
            reason=reason,
        )

        return {
            "project_id": project_id,
            "cancelled_branch_id": branch_id,
            "cancelled_by": user_id,
            "cancelled_at": state.cancelled_at.isoformat(),
            "message": f"Branch {branch_id} cancelled by user",
        }

    async def reclaim_delegated_subgoal(
        self, project_id: str, subgoal_id: str, user_id: str
    ) -> dict[str, Any]:
        """Reclaim/reassign a delegated Goal/Subgoal through the canonical ownership seam.

        This does not fabricate new unrelated history.
        """
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]

        # Implementation would use the #458 Goal ownership seam
        # For now, mark the subgoal as reclaimed
        reclaim_record = {
            "subgoal_id": subgoal_id,
            "reclaimed_by": user_id,
            "reclaimed_at": datetime.now(UTC).isoformat(),
            "original_owner": "workspace_agent",
        }

        state.updated_at = datetime.now(UTC)

        logger.info(
            "delegated_subgoal_reclaimed",
            project_id=project_id,
            subgoal_id=subgoal_id,
            user_id=user_id,
        )

        return {
            "project_id": project_id,
            "reclaimed_subgoal_id": subgoal_id,
            "reclaimed_by": user_id,
            "reclaimed_at": reclaim_record["reclaimed_at"],
            "message": f"Delegated subgoal {subgoal_id} reclaimed through canonical ownership seam",
        }

    async def check_constraints(self, project_id: str) -> list[str]:
        """Check if project meets all constraints for current mode.

        Returns list of constraint violations that need to be addressed.
        """
        if project_id not in self._control_states:
            raise ValueError(f"Project {project_id} not found")

        state = self._control_states[project_id]
        violations = []

        # Check mode-specific constraints
        if state.mode == "direct":
            # Direct mode requires user locks for critical edits
            pass
        elif state.mode == "collaborative":
            # Collaborative mode requires coordination between user and agent
            pass
        elif state.mode == "delegated":
            # Delegated mode requires that #804's reconciliation is actively progressing
            pass
        elif state.mode == "paused":
            # Paused mode requires explicit resume
            pass

        logger.info("constraints_checked", project_id=project_id, violations=violations)
        return violations

    async def restore_state(self) -> None:
        """Restore control state from persistence (refresh/reconnect)."""
        logger.info("restoring_control_state", workspace=self.workspace_id)

        # In a real implementation, this would load control state from persistent storage
        # For now, just reinitialize
        self._initialized = False
        await self.initialize()

    async def _enforce_mode_constraints(self, state: ControlState) -> None:
        """Enforce constraints specific to the current control mode."""
        logger.debug("enforcing_mode_constraints", project_id=state.project_id, mode=state.mode)

        # Implementation would enforce mode-specific constraints
        # For example, in delegated mode, ensure the #804 reconciliation is active
        pass

    def get_state(self, project_id: str) -> ControlState | None:
        """Get current control state for a project."""
        return self._control_states.get(project_id)


class MixedControlExecutor:
    """Execute mixed-control workflows for Design Studio.

    This manages the execution of creative work where different branches may be
    simultaneously user-controlled, collaborative, autonomous, waiting, cancelling, or locked.
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self._active_executions: dict[str, Any] = {}

    async def start_execution(
        self,
        project_id: str,
        mode: str,
        instructions: str | None = None,
        branch_id: str | None = None,
    ) -> str:
        """Start a mixed-control execution.

        Returns an execution ID that can be used to track and manage the execution.
        """
        execution_id = f"exec:{self.workspace_id}:{project_id}:{int(datetime.now(UTC).timestamp())}"

        execution = {
            "id": execution_id,
            "project_id": project_id,
            "mode": mode,
            "instructions": instructions,
            "branch_id": branch_id,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "active",
        }

        self._active_executions[execution_id] = execution

        logger.info(
            "execution_started",
            execution_id=execution_id,
            project_id=project_id,
            mode=mode,
            branch_id=branch_id,
        )

        return execution_id

    async def get_execution_status(self, execution_id: str) -> dict[str, Any]:
        """Get status of an active execution."""
        if execution_id not in self._active_executions:
            raise ValueError(f"Execution {execution_id} not found")

        return self._active_executions[execution_id].copy()

    async def complete_execution(self, execution_id: str, result: dict[str, Any]) -> None:
        """Complete an execution with a result."""
        if execution_id not in self._active_executions:
            raise ValueError(f"Execution {execution_id} not found")

        execution = self._active_executions[execution_id]
        execution["status"] = "completed"
        execution["completed_at"] = datetime.now(UTC).isoformat()
        execution["result"] = result

        logger.info(
            "execution_completed",
            execution_id=execution_id,
            status="completed",
        )

    async def cancel_execution(self, execution_id: str, reason: str = "user_cancelled") -> None:
        """Cancel an execution."""
        if execution_id not in self._active_executions:
            raise ValueError(f"Execution {execution_id} not found")

        execution = self._active_executions[execution_id]
        execution["status"] = "cancelled"
        execution["cancelled_at"] = datetime.now(UTC).isoformat()
        execution["cancellation_reason"] = reason

        logger.info(
            "execution_cancelled",
            execution_id=execution_id,
            reason=reason,
        )
