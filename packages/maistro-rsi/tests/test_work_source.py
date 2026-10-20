"""RSI's consumption of the generic Workspace work source (#50 / #98 / #100 / #101).

Every test pins one half of the acceptance: RSI draws objectives from (and
files receipts back into) the *generic* backlog through the authorized
surface — it never touches the store for claims, never widens a claimed
item's scope, and never closes an item without evidence.
"""

from __future__ import annotations

import pytest

from maistro.backlog.agent_surface import AgentBacklogSurface
from maistro.backlog.model import BacklogItemStatus
from maistro.backlog.store import InMemoryBacklogStore
from maistro.workspaces.backlog_history import (
    BacklogHistoryEventKind,
    InMemoryBacklogHistoryStore,
)
from maistro_rsi.work_source import (
    RSI_WORK_SOURCE,
    RsiWorkSource,
    RsiWorkSourceError,
    objective_instruction,
)

WS = "ws-rsi-work-source"
PROJECT = "proj-1"


def _roles(roles: dict[str, str]):
    async def authorize(actor: str, workspace_id: str, action: str):
        if workspace_id != WS:
            return None
        return roles.get(actor)

    return authorize


async def _seed(
    store: InMemoryBacklogStore,
    item_id: str,
    title: str,
    *,
    details: str = "",
    priority: int = 3,
) -> None:
    await store.create_item(
        workspace_id=WS,
        title=title,
        actor="human:owner",
        details=details,
        priority=priority,
        item_id=item_id,
    )


def _source(
    store: InMemoryBacklogStore,
    *,
    history: InMemoryBacklogHistoryStore | None = None,
) -> RsiWorkSource:
    surface = AgentBacklogSurface(store, _roles({"rsi-campaign": "editor"}))
    return RsiWorkSource(
        surface,
        history=history,
        backlog_store=store,
        project_id=PROJECT,
    )


class TestNextObjective:
    async def test_claims_highest_priority_item_through_the_authorized_surface(self):
        store = InMemoryBacklogStore()
        await _seed(store, "eng-low", "Low priority work")
        await _seed(store, "eng-high", "High priority work", priority=1, details="do the thing")
        source = _source(store)

        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)

        assert sourced is not None
        assert sourced.item_id == "eng-high"
        assert sourced.claimed_by == "rsi-campaign"
        # The objective is derived deterministically from the item's fields.
        assert sourced.instruction == "High priority work\n\ndo the thing"
        # The item is now claimed: the next claimant gets the other one.
        second = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert second is not None and second.item_id == "eng-low"

    async def test_none_when_no_claimable_work(self):
        source = _source(InMemoryBacklogStore())
        assert await source.next_objective(actor="rsi-campaign", workspace_id=WS) is None


class TestClaimAndEvidenceReceipts:
    async def test_claim_evidence_and_closure_are_journaled_with_run_references(self):
        store = InMemoryBacklogStore()
        history = InMemoryBacklogHistoryStore()
        await _seed(store, "eng-001", "Improve the thing")
        source = _source(store, history=history)

        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert sourced is not None
        await source.record_claim(sourced, actor_principal_id="human:op-1")
        await source.record_cycle_evidence(
            sourced,
            run_id="run-1",
            node_run_id="nr-1",
            attempt_id="att-1",
            summary="campaign cycle executed",
        )
        await source.close(
            sourced,
            actor="rsi-campaign",
            evidence_refs=("run:run-1",),
            run_id="run-1",
            closure_summary="improved and merged",
        )

        events = await history.history_for_item(WS, "eng-001")
        kinds = [event.kind for event in events]
        assert BacklogHistoryEventKind.CLAIM_RECORDED in kinds
        assert BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED in kinds
        assert BacklogHistoryEventKind.CLOSURE_RECORDED in kinds
        evidence_event = next(
            e for e in events if e.kind is BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED
        )
        # The journal carries references to canonical Run identity, not copies.
        assert evidence_event.run_refs[0].run_id == "run-1"
        assert evidence_event.run_refs[0].node_run_id == "nr-1"
        # And the store-side terminal move happened through close_item.
        item = await store.get_item("eng-001")
        assert item is not None and item.status == BacklogItemStatus.DONE

    async def test_close_refuses_to_close_without_evidence(self):
        store = InMemoryBacklogStore()
        await _seed(store, "eng-001", "Improve the thing")
        source = _source(store)
        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert sourced is not None
        with pytest.raises(RsiWorkSourceError, match="evidence_refs"):
            await source.close(sourced, actor="rsi-campaign", evidence_refs=(), run_id="run-1")
        # The item stays open: a completed Run alone is not closure evidence.
        item = await store.get_item("eng-001")
        assert item is not None and item.status != BacklogItemStatus.DONE

    async def test_release_leaves_the_item_open_for_the_next_claimant(self):
        store = InMemoryBacklogStore()
        history = InMemoryBacklogHistoryStore()
        await _seed(store, "eng-001", "Improve the thing")
        source = _source(store, history=history)
        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert sourced is not None

        await source.release(sourced, actor="rsi-campaign", reason="no improvement")

        item = await store.get_item("eng-001")
        assert item is not None and item.status != BacklogItemStatus.DONE
        again = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert again is not None and again.item_id == "eng-001"


class TestDiscoveredWork:
    async def test_discovered_work_is_filed_as_new_rsi_sourced_items(self):
        store = InMemoryBacklogStore()
        history = InMemoryBacklogHistoryStore()
        await _seed(store, "eng-001", "Root work")
        source = _source(store, history=history)
        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert sourced is not None

        child_id = await source.propose_discovered_work(
            actor="rsi-campaign",
            workspace_id=WS,
            title="Defect found while working eng-001",
            parent_id="eng-001",
        )
        child = await store.get_item(child_id)
        assert child is not None
        assert child.source == RSI_WORK_SOURCE
        assert child.parent_id == "eng-001"
        # The parent is untouched: discovered work never widens the claimed
        # item's own scope.
        parent = await store.get_item("eng-001")
        assert parent is not None and parent.details == ""

        await source.record_discovered_work(
            sourced, child_item_ids=[child_id], discovered_by_run_id="run-1"
        )
        events = await history.history_for_item(WS, "eng-001")
        assert any(e.kind is BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED for e in events)

    async def test_discovered_work_needs_the_store_and_a_title(self):
        surface_store = InMemoryBacklogStore()
        surface = AgentBacklogSurface(surface_store, _roles({"rsi-campaign": "editor"}))
        bare = RsiWorkSource(surface, project_id=PROJECT)
        with pytest.raises(RsiWorkSourceError, match="BacklogStore"):
            await bare.propose_discovered_work(actor="rsi-campaign", workspace_id=WS, title="x")
        source = _source(surface_store)
        with pytest.raises(RsiWorkSourceError, match="title"):
            await source.propose_discovered_work(actor="rsi-campaign", workspace_id=WS, title="   ")


class TestUnwiredHistory:
    async def test_store_side_changes_survive_a_missing_history_store(self):
        store = InMemoryBacklogStore()
        await _seed(store, "eng-001", "Work")
        source = _source(store)  # no history wired
        sourced = await source.next_objective(actor="rsi-campaign", workspace_id=WS)
        assert sourced is not None
        # Release still releases; the campaign is not punished for running
        # without a journal.
        await source.release(sourced, actor="rsi-campaign", reason="done for now")
        item = await store.get_item("eng-001")
        assert item is not None and item.status != BacklogItemStatus.DONE


def test_objective_instruction_is_deterministic():
    from maistro.backlog.model import BacklogItem

    def item(title: str, details: str) -> BacklogItem:
        return BacklogItem(
            item_id="x",
            workspace_id=WS,
            title=title,
            details=details,
            created_by="human:owner",
            version=1,
            priority=3,
        )

    assert objective_instruction(item("T", "D")) == "T\n\nD"
    assert objective_instruction(item("T", "  ")) == "T"
    assert objective_instruction(item("T", "D")) == objective_instruction(item("T", "D"))
