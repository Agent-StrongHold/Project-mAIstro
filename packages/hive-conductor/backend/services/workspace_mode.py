"""Per-request Workspace authorization over the canonical membership store.

Persona-specific capability checks remain Hive behavior; Workspace existence
and membership do not. They are resolved through `workspace_authority`, which
uses the Container's canonical `WorkspaceStore` (#37).
"""

from __future__ import annotations

from services.workspace_authority import is_member

_PM_FLEET_AGENT_NAMES = frozenset(
    {"intake", "program_manager", "research", "delivery", "risk_dependency", "reporting"}
)


async def is_workspace_member(user_id: str, workspace_id: str | None) -> bool:
    """True only when canonical membership authorizes this Workspace selection."""
    return await is_member(user_id, workspace_id)


async def is_workspace_request_authorized(user_id: str, workspace_id: str | None) -> bool:
    """Program-surface authorization, currently identical to membership."""
    return await is_workspace_member(user_id, workspace_id)


def workspace_has_pm_fleet_agents(workspace_id: str) -> bool:
    """Whether this Workspace's materialized roster supports PM work-item roles."""
    from services.agent_materialization import workspace_agents

    return any(
        a.name.rsplit(".", 1)[-1] in _PM_FLEET_AGENT_NAMES for a in workspace_agents(workspace_id)
    )
