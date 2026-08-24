"""Per-request workspace authorization -- Persona/Workspace system, Phase H.

Recon for the originally-scoped "full migration" (re-point all ~26
`is_pm_poc_mode()`/`HIVE_POC_MODE` call sites, then delete the env var)
found that framing was too broad: several of those call sites are
legitimately global, process-level defaults resolved once at boot, with no
per-request "active workspace" to resolve against even in principle.

**#129 drew the line those two kinds of call site fall on, and it turned out
to already exist in the code.** There were two byte-identical
`is_pm_poc_mode()` functions, and they had disjoint callers: the copy in
`settings_defaults.py` served every boot-time default (`logging_setup.py`'s
verbosity, `stores.py`'s seeding, its own log level and temperature), and the
copy in the PM-named `services/pm_fleet.py` served only per-request gates --
this module, `routes/agents.py`, `routes/work_items.py`,
`services/program_hyperagent.py`. So retiring POC mode as a *routing and
authorization* concept meant deleting one function and none of the defaults.
`settings_defaults.is_pm_poc_mode` stays, is still the answer to "what should
this deployment default to", and is no longer reachable from any request.

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

# routes/work_items.py's maistro.agents.pm_capabilities.agent_for_work_item()
# dispatches to these agent names regardless of which workspace's persona is
# asking -- a workspace only genuinely has Jira/work-item capability if its
# own materialized roster includes at least one of them.
_PM_FLEET_AGENT_NAMES = frozenset(
    {"intake", "program_manager", "research", "delivery", "risk_dependency", "reporting"}
)


def is_workspace_member(user_id: str, workspace_id: str | None) -> bool:
    """True only if `workspace_id` names a real workspace `user_id` belongs to.

    Strict where `is_workspace_request_authorized()` is permissive: no fallback
    to the legacy global flag. Submitting work *into* a workspace has to be an
    unambiguous yes -- there is no sensible legacy reading of "file this Run in
    a workspace the caller is not in" (#158), where there is one for "is this
    caller allowed to see gated UI at all".
    """
    if not workspace_id:
        return False
    workspace = stores.workspaces.get(workspace_id)
    return workspace is not None and any(m.user_id == user_id for m in workspace.members)


def is_workspace_request_authorized(user_id: str, workspace_id: str | None) -> bool:
    """True if `workspace_id` names a real workspace `user_id` is a member of.

    Membership is now the whole answer (#129). This used to fall back to the
    global `is_pm_poc_mode()` flag for no workspace_id, an unresolvable one, or
    one the caller was not a member of -- which meant a deployment with
    `HIVE_POC_MODE=pm` set authorized *every* caller for gated program surfaces
    whether or not they were in any workspace at all. A persona's membership is
    the thing the gate was always trying to approximate, so it is what the gate
    asks now, and the answer no longer depends on an environment variable.

    Still identical to `is_workspace_member` in behaviour, and still spelled
    separately: this one answers "may this caller see gated program UI", and
    that one answers "may this caller file work into this workspace" (#158).
    They agree today; the reason to keep them apart is that the second may
    legitimately tighten without the first following it.
    """
    return is_workspace_member(user_id, workspace_id)


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
