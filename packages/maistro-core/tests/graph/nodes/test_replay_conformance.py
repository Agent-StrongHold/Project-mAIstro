"""Idempotent node kinds reconcile one side effect when executed again (#1194).

The catalog bool is derived from ``replay`` inside ``catalog_json``. A node
declared idempotent has to mean it: running it twice against the same logical
state leaves one penalty, or one dashboard section, not a second copy.
"""

from __future__ import annotations

from maistro.graph.nodes import catalog_idempotent, catalog_json, get_node
from maistro.graph.nodes.base import NodeContext
from maistro.graph.types import GraphBlackboard


def test_catalog_idempotent_is_derived_from_replay() -> None:
    """The palette bool is not a second source beside the executable contract."""
    for entry in catalog_json():
        cls = get_node(entry["kind"])
        assert "idempotent" not in cls.__dict__
        assert entry["replay"] == cls.replay
        assert entry["idempotent"] is catalog_idempotent(cls.replay)


async def test_idempotent_kinds_replay_to_one_side_effect() -> None:
    """compliance.block and dashboard.append_section are the required cases."""
    bb = GraphBlackboard(task_objective="x", workspace="")
    ctx = NodeContext(run_id="r1", dag_id="d1", node_id="block-1", blackboard=bb)
    block = get_node("compliance.block")
    assert block.replay == "idempotent"
    payload = {
        "rule_id": "pii.email_in_summary",
        "severity": 3.0,
        "reason": "first",
        "evidence": {"matched": "alice@example.com"},
    }
    await block().run(payload, ctx)
    await block().run({**payload, "severity": 4.0, "reason": "replay"}, ctx)
    penalties = bb.metadata["penalties"]
    assert len(penalties) == 1
    assert penalties[0]["id"] == "penalty:r1:block-1:pii.email_in_summary"
    assert penalties[0]["severity"] == 4.0
    assert penalties[0]["reason"] == "replay"

    section = get_node("dashboard.append_section")
    assert section.replay == "idempotent"
    section_ctx = NodeContext(run_id="r1", dag_id="d1", node_id="dash-1", blackboard=bb)
    body = {"dashboard_id": "daily", "section_title": "Jira", "markdown": "first", "order_hint": 1}
    await section().run(body, section_ctx)
    await section().run({**body, "markdown": "replayed"}, section_ctx)
    sections = bb.metadata["dashboard:daily"]["sections"]
    assert len(sections) == 1
    assert sections[0]["id"] == "daily/Jira"
    assert sections[0]["markdown"] == "replayed"
