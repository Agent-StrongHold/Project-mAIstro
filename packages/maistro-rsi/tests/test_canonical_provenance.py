"""RSI cycles on the canonical Run -> NodeRun -> Attempt spine (#50 / epic #552).

Every test here answers the same question against the real canonical
substrate (the same ``InMemoryRunStore`` spine conformance holds to): when
an RSI campaign runs with provenance wired, which canonical Run did each
cycle execute under, and where is its evidence durable?
"""

from __future__ import annotations

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.runs.store import InMemoryRunStore
from maistro_rsi.canonical_provenance import (
    RSI_ADMISSION_SOURCE,
    RSI_BUDGET_KEY,
    RSI_CAMPAIGN_ID_KEY,
    RSI_CYCLE_ID_KEY,
    RSI_WORK_ITEM_ID_KEY,
    CanonicalCycleRecord,
    RsiCycleProvenance,
    RsiProvenanceError,
)

WORKSPACE = "rsi-provenance-test"


async def _provenance() -> tuple[RsiCycleProvenance, InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    runs = InMemoryRunStore(project_store=projects)
    return (
        RsiCycleProvenance(runs, workspace_id=WORKSPACE, project_id=root.project_id),
        runs,
        root.project_id,
    )


class TestAdmitCycle:
    async def test_admit_files_one_canonical_run_with_rsi_provenance(self):
        provenance, _, project_id = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="improve the router",
            actor_principal_id="human:op-1",
            budget={"max_cycles": 3},
            work_item_id="eng-001",
        )
        assert run.status is RunStatus.CREATED
        assert run.workspace_id == WORKSPACE
        assert run.project_id == project_id
        assert run.provenance[ADMISSION_SOURCE] == RSI_ADMISSION_SOURCE
        assert run.provenance[RSI_CAMPAIGN_ID_KEY] == "camp-1"
        assert run.provenance[RSI_CYCLE_ID_KEY] == "cycle-1"
        assert run.provenance[RSI_BUDGET_KEY] == {"max_cycles": 3}
        assert run.provenance[RSI_WORK_ITEM_ID_KEY] == "eng-001"
        # The immutable Graph snapshot alone states what the cycle was asked
        # to do: the objective rides the node definition, not a private log.
        node = run.graph.materialize().nodes[0]
        assert node.parameters["objective"] == "improve the router"

    async def test_admit_is_idempotent_per_cycle_id(self):
        provenance, runs, _ = await _provenance()
        first = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        again = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        assert first.run_id == again.run_id
        all_runs = [
            run
            for status in RunStatus
            for run in await runs.list_by_status(status, limit=100, project_id=first.project_id)
        ]
        assert len({r.run_id for r in all_runs}) == 1

    async def test_goal_binding_is_carried_through_and_both_or_neither(self):
        provenance, _, _ = await _provenance()
        bound = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-goal",
            objective="o",
            actor_principal_id="human:op-1",
            goal_id="goal-7",
            goal_revision=3,
        )
        assert bound.goal_id == "goal-7"
        assert bound.goal_revision == 3
        with pytest.raises(RsiProvenanceError, match="both-or-neither"):
            await provenance.admit_cycle(
                campaign_id="camp-1",
                cycle_id="cycle-half",
                objective="o",
                actor_principal_id="human:op-1",
                goal_id="goal-7",
            )

    async def test_admit_requires_attribution_and_non_empty_ids(self):
        provenance, _, _ = await _provenance()
        with pytest.raises(RsiProvenanceError, match="actor_principal_id"):
            await provenance.admit_cycle(
                campaign_id="c", cycle_id="cy", objective="o", actor_principal_id="  "
            )
        with pytest.raises(RsiProvenanceError, match="cycle_id"):
            await provenance.admit_cycle(
                campaign_id="c", cycle_id="", objective="o", actor_principal_id="a"
            )


class TestRunCycle:
    async def test_cycle_executes_as_one_attempt_with_durable_result(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="objective text",
            actor_principal_id="human:op-1",
        )
        record = await provenance.run_cycle(run, lambda: _return_value({"score": 0.9}))

        assert isinstance(record, CanonicalCycleRecord)
        assert record.run_id == run.run_id
        assert record.run_status == RunStatus.COMPLETED.value
        assert record.node_run_status == RunStatus.COMPLETED.value
        assert record.attempt_status == AttemptStatus.COMPLETED.value
        # The Attempt is the record: the report is durable in the RunStore.
        attempt = (await runs.list_attempts(record.node_run_id))[-1]
        assert attempt.result == {"score": 0.9}

    async def test_cycle_failure_is_durable_and_propagates(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-fail",
            objective="objective",
            actor_principal_id="human:op-1",
        )

        async def _boom() -> None:
            raise RuntimeError("cycle exploded")

        with pytest.raises(RuntimeError, match="cycle exploded"):
            await provenance.run_cycle(run, _boom)
        stored = await runs.get_run(run.run_id)
        assert stored is not None and stored.status is RunStatus.FAILED
        node_runs = await runs.list_node_runs(run.run_id)
        assert node_runs[0].status is RunStatus.FAILED

    async def test_run_cycle_refuses_a_terminal_run(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)
        with pytest.raises(RsiProvenanceError, match="already terminal"):
            await provenance.run_cycle(run, lambda: _return_value(None))


async def _return_value(value: object) -> object:
    return value


class TestRecordCompletedCycle:
    async def test_observed_outcome_becomes_canonical_evidence(self):
        provenance, runs, _ = await _provenance()
        record = await provenance.record_completed_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-observed",
            objective="observed objective",
            actor_principal_id="human:op-1",
            outcome={"index": 1, "changed": True, "tests_passed": True},
        )
        assert record.completed
        attempt = (await runs.list_attempts(record.node_run_id))[-1]
        assert attempt.result == {"index": 1, "changed": True, "tests_passed": True}

    async def test_failed_cycle_records_failure_never_success(self):
        provenance, _, _ = await _provenance()
        record = await provenance.record_completed_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-bad",
            objective="o",
            actor_principal_id="human:op-1",
            outcome={},
            failed=True,
            error="tests failed",
        )
        assert not record.completed
        assert record.run_status == RunStatus.FAILED.value
        assert record.attempt_status == AttemptStatus.FAILED.value

    async def test_sync_facade_refuses_a_live_event_loop(self):
        provenance, _, _ = await _provenance()
        with pytest.raises(RsiProvenanceError, match="live event loop"):
            provenance.record_completed_cycle_sync(
                campaign_id="c",
                cycle_id="cy",
                objective="o",
                actor_principal_id="a",
                outcome={},
            )


class TestWrapExecutor:
    async def test_every_executor_call_is_one_canonical_cycle(self):
        provenance, runs, _ = await _provenance()
        records: list[CanonicalCycleRecord] = []
        calls: list[str] = []

        async def executor(context):
            calls.append(context.node.hypothesis)
            return {"report": context.node.id}

        wrapped = provenance.wrap_executor(
            executor,
            campaign_id="camp-1",
            actor_principal_id="human:op-1",
            records=records,
        )
        # Two contexts = two cycles, each its own Run.
        from maistro_rsi.coordinator import HtrContext
        from maistro_rsi.htr import HypothesisTree

        tree = HypothesisTree("root idea")
        node_a = tree.expand(tree.root_id, "refine alpha")
        report_a = await wrapped(HtrContext(node=tree.nodes[tree.root_id], insights=[], tree=tree))
        node_b_id = node_a.id
        report_b = await wrapped(HtrContext(node=tree.nodes[node_b_id], insights=[], tree=tree))

        assert report_a == {"report": tree.root_id}
        assert report_b == {"report": node_b_id}
        assert calls == ["root idea", "refine alpha"]
        assert len(records) == 2
        assert {r.cycle_id for r in records} == {tree.root_id, node_b_id}
        assert all(r.completed for r in records)
        # Distinct canonical Runs, one per cycle.
        assert len({r.run_id for r in records}) == 2
        # The report is read back from the durable Attempt, not a side channel.
        attempt = (await runs.list_attempts(records[0].node_run_id))[-1]
        assert attempt.result == {"report": tree.root_id}


class TestFindCycle:
    async def test_find_cycle_resolves_only_the_named_cycle(self):
        provenance, _, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-2",
            objective="o",
            actor_principal_id="human:op-1",
        )
        found = await provenance.find_cycle("camp-1", "cycle-1")
        assert found is not None and found.run_id == run.run_id
        assert await provenance.find_cycle("camp-1", "cycle-missing") is None
        assert await provenance.find_cycle("other-campaign", "cycle-1") is None
