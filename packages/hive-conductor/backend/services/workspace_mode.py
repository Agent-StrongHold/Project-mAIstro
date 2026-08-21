"""Per-request workspace authorization -- Persona/Workspace system, Phase H.

Recon for the originally-scoped "full migration" (re-point all ~26
`is_pm_poc_mode()`/`HIVE_POC_MODE` call sites, then delete the env var)
found that framing was too broad: several of those call sites are
legitimately global, process-level defaults resolved once at boot --
`services/engine.py`'s executor selection, `settings_defaults.py`'s default
log level/temperature, `logging_setup.py`'s default verbosity -- with no
per-request "active workspace" to resolve against even in principle. Those
are deliberately left alone; deleting `is_pm_poc_mode()`/`HIVE_POC_MODE`
entirely would break them, not just rename something.

No persona is special-cased here. `pm_fleet` is one premade
`PersonaTemplate` among any number of others (`content_creator`,
wizard-authored ones) -- `is_workspace_request_authorized()` only checks
real membership, never a workspace's `persona_template_id` string.
`workspace_has_pm_fleet_agents()` is the one place that still gates on a
capability genuinely specific to a particular set of agents (Jira
epic/story drafting, `routes/work_items.py`) -- and even that checks
whether the workspace's own *materialized* agent roster
(`services/agent_materialization.py`) happens to include agents shaped
like PM Fleet's dispatch table expects, not an identity string. Any
persona whose spawns declare agents named `intake`/`program_manager`/etc.
would qualify the same way `pm_fleet.yaml` does today.
"""

from __future__ import annotations

import stores

from services.pm_fleet import is_pm_poc_mode

# routes/work_items.py's maistro.agents.pm_capabilities.agent_for_work_item()
# dispatches to these agent names regardless of which workspace's persona is
# asking -- a workspace only genuinely has Jira/work-item capability if its
# own materialized roster includes at least one of them.
_PM_FLEET_AGENT_NAMES = frozenset(
    {"intake", "program_manager", "research", "delivery", "risk_dependency", "reporting"}
)


def is_workspace_request_authorized(user_id: str, workspace_id: str | None) -> bool:
    """True if `workspace_id` names a real workspace `user_id` is a member
    of -- regardless of which persona it runs. Falls back to the legacy
    global `is_pm_poc_mode()` flag for no workspace_id, an unresolvable
    one, or one the caller isn't a member of (so a caller can never probe
    another user's private workspace_id to flip gated behavior for
    themselves)."""
    if workspace_id is not None:
        workspace = stores.workspaces.get(workspace_id)
        if workspace is not None and any(m.user_id == user_id for m in workspace.members):
            return True
    return is_pm_poc_mode()


def workspace_has_pm_fleet_agents(workspace_id: str) -> bool:
    """True if this workspace's own materialized agents
    (`services/agent_materialization.py`) include at least one shaped like
    PM Fleet's Jira-dispatch table expects. Data-driven: it reflects what
    this specific workspace's persona actually spawned, not a hardcoded
    `persona_template_id == "pm_fleet"` identity check."""
    from services.agent_materialization import workspace_agents

    return any(
        a.name.rsplit(".", 1)[-1] in _PM_FLEET_AGENT_NAMES for a in workspace_agents(workspace_id)
    )
