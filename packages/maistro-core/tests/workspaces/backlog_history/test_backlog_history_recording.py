"""The recording semantics (#101): what each fact is, and what may never happen."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from maistro.workspaces.backlog_history import (
    BacklogHistoryError,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    BacklogHistoryStore,
    BacklogSubject,
    ClosureEvidenceMissing,
    InMemoryBacklogHistoryStore,
    RunReference,
    recording,
)


@pytest.fixture
async def store() -> AsyncIterator[BacklogHistoryStore]:
    yield InMemoryBacklogHistoryStore()


def _subject(item_id: str = "item-1") -> BacklogSubject:
    return BacklogSubject(workspace_id="ws-a", project_id="p-1", item_id=item_id)


def test_subject_validator_is_registered_with_pydantic() -> None:
    """The scope check runs because pydantic calls it; pin the registration."""
    assert BacklogSubject._non_empty.__name__ in set(
        BacklogSubject.__pydantic_decorators__.model_validators
    )


async def test_item_recorded_carries_its_provenance(store: BacklogHistoryStore) -> None:
    event = await recording.item_recorded(
        store,
        _subject(),
        source_ref="spec:SPEC-177",
        actor_agent_id="workspace-agent",
        summary="imported from the workspace campaign",
    )
    assert event.kind is BacklogHistoryEventKind.ITEM_RECORDED
    assert event.source_ref == "spec:SPEC-177"
    assert event.actor_agent_id == "workspace-agent"


async def test_fields_changed_records_pairs_and_refuses_noops(
    store: BacklogHistoryStore,
) -> None:
    event = await recording.fields_changed(
        store,
        _subject(),
        before={"priority": "P1", "rank": 2.0, "acceptance_refs": ["AC-1"]},
        after={"priority": "P0", "rank": 2.0, "acceptance_refs": ["AC-1", "AC-2"]},
        actor_principal_id="owner-1",
    )
    assert event.kind is BacklogHistoryEventKind.FIELDS_CHANGED
    assert [(change.field, change.before, change.after) for change in event.changed_fields] == [
        ("acceptance_refs", ["AC-1"], ["AC-1", "AC-2"]),
        ("priority", "P1", "P0"),
    ]

    with pytest.raises(BacklogHistoryError, match="no difference"):
        await recording.fields_changed(
            store,
            _subject(),
            before={"priority": "P0"},
            after={"priority": "P0"},
        )


async def test_status_move_records_both_ends(store: BacklogHistoryStore) -> None:
    event = await recording.status_moved(
        store,
        _subject(),
        from_status="accepted",
        to_status="implemented",
        reason="the acceptance checks passed",
    )
    assert (event.from_status, event.to_status) == ("accepted", "implemented")


async def test_claim_lifecycle_records_what_was_taken_and_cleared(
    store: BacklogHistoryStore,
) -> None:
    claimed = await recording.claim_recorded(
        store,
        _subject(),
        claimant_agent_id="workspace-agent",
        claim_run_id="run-12",
        fence_token=4,
    )
    assert claimed.kind is BacklogHistoryEventKind.CLAIM_RECORDED
    assert {(change.field, change.after) for change in claimed.changed_fields} == {
        ("claimant_agent_id", "workspace-agent"),
        ("claim_run_id", "run-12"),
        ("fence_token", 4),
    }

    released = await recording.claim_released(
        store,
        _subject(),
        previous={"claimant_agent_id": "workspace-agent"},
    )
    assert released.changed_fields[0].before == "workspace-agent"
    assert released.changed_fields[0].after is None

    with pytest.raises(BacklogHistoryError, match="without a claim"):
        await recording.claim_recorded(store, _subject())
    with pytest.raises(BacklogHistoryError, match="without a previous claim"):
        await recording.claim_released(store, _subject(), previous={})


async def test_blockers_are_recorded_and_cleared(store: BacklogHistoryStore) -> None:
    blocked = await recording.blocker_recorded(
        store,
        _subject(),
        blocker_reason="waiting for the credential slice",
        waiting_on="human",
    )
    assert (blocked.blocker_reason, blocked.waiting_on) == (
        "waiting for the credential slice",
        "human",
    )
    cleared = await recording.blocker_cleared(store, _subject(), summary="credentials landed")
    assert cleared.kind is BacklogHistoryEventKind.BLOCKER_CLEARED


async def test_partial_progress_implies_no_status(store: BacklogHistoryStore) -> None:
    """Progress is recorded without closing the parent: the entry carries no
    status at all, so it can never read as a completion."""
    event = await recording.progress_noted(
        store,
        _subject(),
        note="2 of 5 acceptance checks pass",
        evidence_refs=("run:12#node:3",),
        actor_agent_id="workspace-agent",
    )
    assert event.kind is BacklogHistoryEventKind.PROGRESS_NOTED
    assert event.from_status is None
    assert event.to_status is None
    assert event.evidence_refs == ("run:12#node:3",)


async def test_decomposition_snapshots_parent_acceptance_without_rewriting_it(
    store: BacklogHistoryStore,
) -> None:
    """The receipt carries the parent's acceptance criteria as they were; a
    later rewrite is a separate, visible fields_changed entry — never part of
    the decomposition."""
    decomposed = await recording.decomposition_recorded(
        store,
        _subject(),
        child_item_ids=("child-1", "child-2"),
        parent_acceptance_refs=["AC-1", "AC-2"],
        actor_agent_id="workspace-agent",
    )
    assert decomposed.child_item_ids == ("child-1", "child-2")
    snapshot = decomposed.changed_fields[0]
    assert (snapshot.field, snapshot.before, snapshot.after) == (
        "acceptance_refs",
        ["AC-1", "AC-2"],
        ["AC-1", "AC-2"],
    )

    await recording.fields_changed(
        store,
        _subject(),
        before={"acceptance_refs": ["AC-1", "AC-2"]},
        after={"acceptance_refs": ["AC-1", "AC-2", "AC-3"]},
        summary="scope change is visible in history",
    )
    history = await store.history_for_item("ws-a", "item-1")
    assert [event.kind for event in history] == [
        BacklogHistoryEventKind.DECOMPOSITION_RECORDED,
        BacklogHistoryEventKind.FIELDS_CHANGED,
    ]


async def test_discovered_work_is_pinned_to_proposed(store: BacklogHistoryStore) -> None:
    event = await recording.discovered_work_recorded(
        store,
        _subject(),
        child_item_ids=("prereq-1",),
        discovered_by_run_id="run-77",
        actor_agent_id="workspace-agent",
        summary="the migration needs a lock budget first",
    )
    assert event.child_initial_status == "proposed"
    assert event.run_refs == (RunReference(run_id="run-77"),)

    # A refusal that comes from the model, so a caller cannot bypass the pin
    # by constructing the event itself.
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="proposed"):
        BacklogHistoryEvent(
            workspace_id="ws-a",
            project_id="p-1",
            item_id="item-1",
            kind=BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
            child_item_ids=("prereq-1",),
            child_initial_status="accepted",
        )


async def test_goal_binding_references_the_canonical_goal(
    store: BacklogHistoryStore,
) -> None:
    event = await recording.goal_bound(
        store,
        _subject(),
        goal_id="g-1",
        goal_revision="r7",
        actor_agent_id="workspace-agent",
    )
    assert event.goal_link is not None
    assert (event.goal_link.goal_id, event.goal_link.goal_revision) == ("g-1", "r7")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await recording.goal_bound(store, _subject(), goal_id="  ", goal_revision="r7")


async def test_reconciliation_records_the_pointer_not_the_decision(
    store: BacklogHistoryStore,
) -> None:
    event = await recording.reconciliation_recorded(
        store,
        _subject(),
        decision_ref="reconciliation:rec-42",
        outcome="keep_goal_replan_item",
        reason="the Goal moved to revision r8; the item needed a replan",
        goal_id="g-1",
        goal_revision="r8",
        run_refs=(RunReference(run_id="run-9"),),
    )
    assert event.reconciliation is not None
    assert event.reconciliation.decision_ref == "reconciliation:rec-42"
    assert event.goal_link is not None and event.goal_link.goal_revision == "r8"


async def test_run_evidence_records_why_a_replan_was_needed(
    store: BacklogHistoryStore,
) -> None:
    event = await recording.run_evidence_recorded(
        store,
        _subject(),
        run_refs=(RunReference(run_id="run-5", node_run_id="nr-1"),),
        evaluation_refs=("eval-run-5",),
        reason="the first Attempt failed node nr-1; a replan Run was required",
        actor_agent_id="workspace-agent",
    )
    assert event.run_refs[0].node_run_id == "nr-1"
    assert event.evaluation_refs == ("eval-run-5",)
    assert event.reason is not None and "replan" in event.reason


async def test_closure_requires_evidence_and_a_run_alone_never_suffices(
    store: BacklogHistoryStore,
) -> None:
    """`latest_run == completed` is not closure: a Run reference with no
    evidence refs is refused exactly like an empty hand."""
    with pytest.raises(ClosureEvidenceMissing, match="evidence_refs"):
        await recording.closure_recorded(store, _subject(), evidence_refs=())
    with pytest.raises(ClosureEvidenceMissing):
        await recording.closure_recorded(
            store,
            _subject(),
            evidence_refs=(),
            run_refs=(RunReference(run_id="run-5"),),
        )

    closed = await recording.closure_recorded(
        store,
        _subject(),
        evidence_refs=("spec:SPEC-177#AC-2", "artifact:report-1"),
        run_refs=(RunReference(run_id="run-5"),),
        evaluation_refs=("eval-run-5",),
        to_status="implemented",
        actor_agent_id="workspace-agent",
    )
    assert closed.evidence_refs == ("spec:SPEC-177#AC-2", "artifact:report-1")
    assert closed.to_status == "implemented"


async def test_reopen_requires_a_reason(store: BacklogHistoryStore) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="reason"):
        await recording.reopened(store, _subject(), reason="")
    event = await recording.reopened(store, _subject(), reason="a check regressed")
    assert event.kind is BacklogHistoryEventKind.REOPENED


async def test_a_whole_item_life_reads_back_in_order(store: BacklogHistoryStore) -> None:
    """The acceptance story, end to end, in one journal."""
    subject = _subject("epic-1")
    await recording.item_recorded(store, subject, source_ref="scenario:auth-flow")
    await recording.goal_bound(store, subject, goal_id="g-1", goal_revision="r1")
    await recording.claim_recorded(store, subject, claimant_agent_id="workspace-agent")
    await recording.progress_noted(store, subject, note="first check passes")
    await recording.discovered_work_recorded(
        store, subject, child_item_ids=("prereq-1",), discovered_by_run_id="run-2"
    )
    await recording.decomposition_recorded(
        store,
        subject,
        child_item_ids=("child-1", "child-2"),
        parent_acceptance_refs=["AC-1"],
    )
    await recording.run_evidence_recorded(
        store,
        subject,
        run_refs=(RunReference(run_id="run-3"),),
        reason="replan after the migration node failed",
    )
    await recording.closure_recorded(
        store,
        subject,
        evidence_refs=("spec:SPEC-177#AC-1",),
        run_refs=(RunReference(run_id="run-3"),),
        to_status="implemented",
    )
    await recording.reopened(store, subject, reason="AC-1 regressed")

    history = await store.history_for_item("ws-a", "epic-1")
    assert [event.kind for event in history] == [
        BacklogHistoryEventKind.ITEM_RECORDED,
        BacklogHistoryEventKind.GOAL_BOUND,
        BacklogHistoryEventKind.CLAIM_RECORDED,
        BacklogHistoryEventKind.PROGRESS_NOTED,
        BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
        BacklogHistoryEventKind.DECOMPOSITION_RECORDED,
        BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED,
        BacklogHistoryEventKind.CLOSURE_RECORDED,
        BacklogHistoryEventKind.REOPENED,
    ]
    assert [event.sequence for event in history] == list(range(1, 10))
