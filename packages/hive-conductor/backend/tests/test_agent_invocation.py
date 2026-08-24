"""services/agent_invocation.py -- resolution against a workspace's own roster.

Replaces `test_pm_fleet.py`, which pinned `list_pm_agents()`'s four-agent
output and `invoke_pm_agent()`'s resolution against the hardcoded
`maistro.agents.pm_fleet.PM_FLEET` tuple. Both are gone with #129: a workspace
runs a persona, and what it can be asked to do is whatever that persona's
template declared, so the thing worth pinning is that resolution reads the
materialized roster and refuses everything outside it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import stores
from models.schemas import Agent
from services.agent_invocation import pulse_roster, resolve_agent, resolve_agent_task


@pytest.fixture(autouse=True)
def _clear_agents():
    for key in list(stores.agents.keys()):
        stores.agents.pop(key, None)
    yield
    for key in list(stores.agents.keys()):
        stores.agents.pop(key, None)


def _materialized(workspace_id: str, spawn: str, *, skills: list[str]) -> Agent:
    """An Agent shaped exactly as `materialize_workspace_agents` writes one.

    Built by hand rather than by expanding a real template so the test says
    which shape it depends on: the scoped `<workspace>.<spawn>` id, the dotted
    `<persona>.<spawn>` name, and capabilities landing in `skills` while
    `capabilities` (a spawn's `tools`) stays empty -- which is how
    `pm_fleet.yaml` and every template like it actually expand.
    """
    t = datetime.now(UTC)
    agent = Agent(
        id=f"{workspace_id}.{spawn}",
        workspace_id=workspace_id,
        name=f"pm_fleet.{spawn}",
        description="",
        model="x",
        status="idle",
        capabilities=[],
        skills=skills,
        created_at=t,
    )
    stores.agents[agent.id] = agent
    return agent


def _global(agent_id: str, *, skills: list[str]) -> Agent:
    t = datetime.now(UTC)
    agent = Agent(
        id=agent_id,
        workspace_id=None,
        name=agent_id,
        description="",
        model="x",
        status="idle",
        skills=skills,
        created_at=t,
    )
    stores.agents[agent_id] = agent
    return agent


class TestResolveAgent:
    def test_a_bare_spawn_name_finds_the_workspaces_own_agent(self) -> None:
        """The producers of an agent id -- `agent_for_work_item()`,
        `autonomous_pulse_candidates()` -- name a spawn, never a scoped id."""
        _materialized("ws-1", "delivery", skills=["poll_jira"])
        found = resolve_agent("delivery", workspace_id="ws-1")
        assert found is not None
        assert found.id == "ws-1.delivery"

    def test_the_workspaces_agent_wins_over_a_global_one_of_the_same_name(self) -> None:
        """Otherwise a global agent someone happened to name `delivery` would
        answer for every workspace that materialized its own."""
        _global("delivery", skills=["poll_jira"])
        _materialized("ws-1", "delivery", skills=["poll_jira"])
        found = resolve_agent("delivery", workspace_id="ws-1")
        assert found is not None
        assert found.workspace_id == "ws-1"

    def test_a_global_agent_still_resolves_when_no_workspace_holds_the_name(self) -> None:
        _global("scribe", skills=["draft"])
        found = resolve_agent("scribe", workspace_id="ws-1")
        assert found is not None
        assert found.workspace_id is None

    def test_an_agent_no_roster_holds_resolves_to_nothing(self) -> None:
        assert resolve_agent("delivery", workspace_id="ws-1") is None


class TestResolveAgentTask:
    def test_the_task_type_is_the_agents_own_name(self) -> None:
        """Not a separate label. `PmAgentDef.task_type` diverged from the agent
        name for two of six entries and nothing on the queue path read it."""
        _materialized("ws-1", "program_manager", skills=["fetch_program_state"])
        task_type, _, agent_id = resolve_agent_task(
            "program_manager", "fetch_program_state", {}, workspace_id="ws-1"
        )
        assert task_type == "program_manager"
        # The spawn name, not the store id. `maistro.agents.pm_runner`'s
        # `_resolve_role` is keyed by bare name, so a scoped id resolves to no
        # role and returns a synthetic `source="no_data"` result. The workspace
        # travels on `submit_task(workspace_id=...)` instead, which is where a
        # Run's scope belongs.
        assert agent_id == "program_manager"

    def test_the_description_keeps_the_shape_three_surfaces_display(self) -> None:
        _materialized("ws-1", "intake", skills=["create_initiative"])
        _, description, _ = resolve_agent_task(
            "intake", "create_initiative", {"title": "Q3 Platform"}, workspace_id="ws-1"
        )
        assert description == "[intake] create_initiative: Q3 Platform"

    def test_a_summary_and_a_reason_are_both_appended(self) -> None:
        _materialized("ws-1", "risk_dependency", skills=["scan_risks"])
        _, description, _ = resolve_agent_task(
            "risk_dependency",
            "scan_risks",
            {"title": "RAID", "summary": "weekly", "hyperagent_reason": "pulse"},
            workspace_id="ws-1",
        )
        assert description == "[risk_dependency] scan_risks: RAID — weekly (why: pulse)"

    def test_an_agent_this_workspace_does_not_have_is_refused(self) -> None:
        """The refusal POC mode could not make: with a global fleet synthesised
        per request, every caller had all six agents whatever workspace they
        were in."""
        _materialized("ws-1", "delivery", skills=["poll_jira"])
        with pytest.raises(ValueError, match="Unknown agent"):
            resolve_agent_task("reporting", "generate_exec_summary", {}, workspace_id="ws-1")

    def test_a_capability_the_agent_does_not_declare_is_refused(self) -> None:
        _materialized("ws-1", "delivery", skills=["poll_jira"])
        with pytest.raises(ValueError, match="not valid for"):
            resolve_agent_task("delivery", "generate_exec_summary", {}, workspace_id="ws-1")

    def test_a_capability_declared_as_a_tool_is_accepted_too(self) -> None:
        """`materialize_workspace_agents` maps a spawn's `tools` to
        `capabilities` and its `skills` to `skills`. A caller naming a
        capability does not know which side of that split it landed on."""
        t = datetime.now(UTC)
        stores.agents["ws-1.builder"] = Agent(
            id="ws-1.builder",
            workspace_id="ws-1",
            name="engineering.builder",
            description="",
            model="x",
            status="idle",
            capabilities=["run_build"],
            skills=[],
            created_at=t,
        )
        task_type, _, _ = resolve_agent_task("builder", "run_build", {}, workspace_id="ws-1")
        assert task_type == "builder"


class TestTheResolvedAgentIdIsTheExecutorsShape:
    """Codex P1 on #216: a scoped id resolves to no role at execution.

    `maistro.agents.pm_runner._resolve_role` looks the agent up in
    `_PM_AGENT_TO_ROLE`, keyed by bare spawn name. Handing it
    `ws-1.program_manager` misses, and its only fallback maps a *capability* to
    a role via `PM_PRIMARY_CAPABILITY` — which covers each role's primary and
    nothing else. So `create_epic`, `create_story`, `create_dev_task` and
    `fetch_program_state` would all resolve to no role and return a synthetic
    `source="no_data"` result instead of running the agent that was selected.
    """

    def test_the_executors_own_table_is_keyed_by_bare_name(self) -> None:
        """Pinned against the real table, so this test fails if the executor
        ever starts accepting scoped ids and this normalisation becomes
        unnecessary — rather than silently outliving its reason."""
        from maistro.agents.pm_runner import _PM_AGENT_TO_ROLE

        assert "program_manager" in _PM_AGENT_TO_ROLE
        assert not [key for key in _PM_AGENT_TO_ROLE if "." in key]

    async def test_a_materialized_agent_resolves_to_a_name_that_table_holds(self) -> None:
        from maistro.agents.pm_runner import _PM_AGENT_TO_ROLE

        _materialized("ws-1", "program_manager", skills=["fetch_program_state"])

        _task_type, _description, agent_id = resolve_agent_task(
            "program_manager", "fetch_program_state", {}, workspace_id="ws-1"
        )

        assert agent_id in _PM_AGENT_TO_ROLE


class TestPulseRoster:
    """What the autonomous pulse is allowed to propose (#221).

    Before this the pulse proposed PM Fleet's six names to every workspace,
    and a workspace running any other persona got a list of actions none of
    its agents could serve.
    """

    def test_a_non_pm_workspace_gets_its_own_agents(self) -> None:
        """The defect, stated positively. `content_creator` has no
        `program_manager`, and until now that was all the pulse could offer
        it."""
        _materialized("ws-1", "editor", skills=["scan_risks"])

        roster = pulse_roster("ws-1")

        assert [(a.name, sorted(a.capabilities)) for a in roster] == [
            ("editor", ["scan_risks"]),
        ]

    def test_the_name_is_the_spawn_name_the_next_layer_takes(self) -> None:
        """`resolve_agent_task` takes `delivery`, not `ws-1.delivery` and not
        `pm_fleet.delivery`. A proposed action carrying anything else would be
        a name the next layer has to undo."""
        _materialized("ws-1", "delivery", skills=["poll_jira"])

        assert [a.name for a in pulse_roster("ws-1")] == ["delivery"]

    def test_capabilities_come_from_both_fields(self) -> None:
        """The two rosters fill them differently, and a pulse candidate does
        not know which side of that split its capability landed on."""
        t = datetime.now(UTC)
        stores.agents["ws-1.mixed"] = Agent(
            id="ws-1.mixed",
            workspace_id="ws-1",
            name="persona.mixed",
            description="",
            model="x",
            status="idle",
            capabilities=["poll_jira"],
            skills=["scan_risks"],
            created_at=t,
        )

        roster = pulse_roster("ws-1")

        assert sorted(roster[0].capabilities) == ["poll_jira", "scan_risks"]

    def test_the_workspaces_own_agent_is_preferred_over_a_global_one(self) -> None:
        """The pulse takes the first declarer, so this ordering is what gives
        a workspace's own agent the same precedence `resolve_agent` gives it
        one step later."""
        _global("shared", skills=["scan_risks"])
        _materialized("ws-1", "own", skills=["scan_risks"])

        assert [a.name for a in pulse_roster("ws-1")] == ["own", "shared"]

    def test_another_workspaces_agents_are_not_in_this_roster(self) -> None:
        _materialized("ws-1", "mine", skills=["scan_risks"])
        _materialized("ws-2", "theirs", skills=["scan_risks"])

        assert [a.name for a in pulse_roster("ws-1")] == ["mine"]

    def test_no_workspace_sees_only_the_global_agents(self) -> None:
        """A pulse asked for without a workspace still has the workspace-less
        records `stores.agents` holds, which is what `resolve_agent` falls
        back to."""
        _global("shared", skills=["scan_risks"])
        _materialized("ws-1", "own", skills=["scan_risks"])

        assert [a.name for a in pulse_roster()] == ["shared"]

    def test_an_unknown_workspace_has_an_empty_roster(self) -> None:
        """And an empty roster proposes nothing, which is the honest answer
        rather than a list of actions that cannot run."""
        assert pulse_roster("ws-nobody") == []
