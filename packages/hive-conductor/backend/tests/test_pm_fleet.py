"""PM fleet service unit tests (no Hive auth/session deps)."""

from __future__ import annotations

from services.pm_fleet import invoke_pm_agent, is_pm_poc_mode, list_pm_agents

from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue


def test_list_pm_agents_returns_canonical_fleet() -> None:
    """PM fleet roster: program_manager, delivery, risk_dependency, reporting
    (4 agents — intake and research are filtered out because their primary
    capabilities are not in _WORKING_CAPABILITIES). Pinned so adding a 5th
    is a deliberate decision.

    The list also includes seeded store agents (agent-N); we check only the
    PM subset here.
    """
    agents = list_pm_agents([])
    ids = [a.id for a in agents]
    pm_ids = [i for i in ids if not i.startswith("agent-")]
    assert pm_ids == [
        "program_manager",
        "delivery",
        "risk_dependency",
        "reporting",
    ]
    pm_agents = [a for a in agents if not a.id.startswith("agent-")]
    assert pm_agents[0].tagline
    assert pm_agents[0].primary_capability


def test_invoke_pm_agent_builds_description() -> None:
    task_type, description, agent_id = invoke_pm_agent(
        "intake",
        "create_initiative",
        {"title": "Q3 Platform"},
    )
    assert task_type == "intake"
    assert agent_id == "intake"
    assert "Q3 Platform" in description


def test_pm_tasks_scoped_per_user_in_queue() -> None:
    import asyncio

    async def _run() -> None:
        queue = TaskQueue()
        task_type, desc, agent_id = invoke_pm_agent(
            "reporting",
            "generate_exec_summary",
            {"title": "Weekly"},
        )
        await queue.submit(
            TaskCreate(description=desc, task_type=task_type, agent_id=agent_id),
            user_id="alice",
        )
        alice_items, _ = queue.list_tasks(user_id="alice")
        bob_items, _ = queue.list_tasks(user_id="bob")
        assert len(alice_items) == 1
        assert len(bob_items) == 0

    asyncio.run(_run())


def test_is_pm_poc_mode_reads_env(monkeypatch) -> None:
    monkeypatch.delenv("MAISTRO_POC_MODE", raising=False)
    monkeypatch.delenv("HIVE_POC_MODE", raising=False)
    assert is_pm_poc_mode() is False
    monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
    assert is_pm_poc_mode() is True
