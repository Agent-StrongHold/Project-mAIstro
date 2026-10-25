"""RSI cycles on the canonical Run -> NodeRun -> Attempt spine (#50 / epic #552).

Every test here answers the same question against the real canonical
substrate (the same ``InMemoryRunStore`` spine conformance holds to): when
an RSI campaign runs with provenance wired, which canonical Run did each
cycle execute under, and where is its evidence durable?
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
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
from maistro_rsi.coordinator import ExecutionReport
from maistro_rsi.htr import HypothesisEvidence

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
    async def test_sqlite_backend_returns_the_executor_report_object(self, tmp_path):
        """The durable Attempt is JSON, the caller's report is not (#552).

        SqliteRunStore (and PgRunStore) round-trip the Attempt result through
        `evidence_json`, so a read-back is a plain dict — `HtrCoordinator.run`
        would then trip on `report.evidence` after the first executed cycle.
        The wrap must return the executor's own report object while the spine
        still persists the payload.
        """
        aiosqlite = pytest.importorskip("aiosqlite")
        from maistro.runs.sqlite_store import SqliteRunStore

        projects = InMemoryProjectScopeStore()
        root = await projects.create_root(WORKSPACE)
        conn = await aiosqlite.connect(tmp_path / "runs.db")
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        try:
            provenance = RsiCycleProvenance(
                runs, workspace_id=WORKSPACE, project_id=root.project_id
            )
            report = ExecutionReport(
                evidence=HypothesisEvidence(
                    tests_passed=True, benchmarks_won=1, battles=2, improved=True
                ),
                diff="diff --git a/x b/x",
            )

            async def executor(context):
                return report

            wrapped = provenance.wrap_executor(
                executor,
                campaign_id="camp-1",
                actor_principal_id="human:op-1",
            )
            from maistro_rsi.coordinator import HtrContext
            from maistro_rsi.htr import HypothesisTree

            tree = HypothesisTree("root idea")
            returned = await wrapped(
                HtrContext(node=tree.nodes[tree.root_id], insights=[], tree=tree)
            )
            # The executor's own object, attribute access intact: exactly what
            # `HtrCoordinator.run` consumes (`report.evidence`, `report.diff`).
            assert returned is report
            assert returned.evidence.improved is True
            assert returned.diff == "diff --git a/x b/x"
            # The durable Attempt still carries the payload (dict after the
            # JSON round-trip), so provenance loses nothing.
            run = await provenance.find_cycle("camp-1", tree.root_id)
            assert run is not None
            node_runs = await runs.list_node_runs(run.run_id)
            attempt = (await runs.list_attempts(node_runs[0].node_run_id))[-1]
            payload = attempt.result
            assert isinstance(payload, dict)
            assert payload["evidence"]["improved"] is True
            assert payload["diff"] == "diff --git a/x b/x"
        finally:
            await conn.close()

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


class _VanishingRunStore:
    """An ``InMemoryRunStore`` whose point lookups can be made to lose a record.

    The seam's defensive branches answer one question: what happens when a run
    or NodeRun that admission just filed disappears from the store before the
    seam reads it back. Rather than reconstruct every store failure mode, the
    tests flip a flag and the lookup returns ``None`` — the same answer a
    concurrent purge or a retention sweep would produce.
    """

    def __init__(self, inner: InMemoryRunStore) -> None:
        self._inner = inner
        self.drop_get_run = False
        self.drop_get_node_run = False

    async def get_run(self, run_id: str, **kwargs: object):
        if self.drop_get_run:
            return None
        return await self._inner.get_run(run_id)  # type: ignore[arg-type]

    async def get_node_run(self, node_run_id: str, **kwargs: object):
        if self.drop_get_node_run:
            return None
        return await self._inner.get_node_run(node_run_id)  # type: ignore[arg-type]

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class TestDegenerateCanonicalPaths:
    """White-box pins for the seam's defensive branches.

    These branches are the seam's answer to a store that changes under it —
    a run that went terminal between two reads, a NodeRun a reconciliation
    sweep removed, an Attempt that never landed. Each one must fail loudly
    (or settle quietly, where settling is the correct disposition) instead of
    inventing canonical evidence (#552).
    """

    async def test_fail_run_settles_quietly_when_the_run_is_already_terminal(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        for status in transition_path(run.status, RunStatus.FAILED):
            run = await runs.transition_run(run.run_id, status)
        # Already FAILED: the projection must not walk it again (a terminal
        # status has no legal outgoing transition, so doing so would raise).
        await provenance._fail_run(run.run_id, error="late failure")
        settled = await runs.get_run(run.run_id)
        assert settled is not None and settled.status is RunStatus.FAILED

    async def test_fail_run_skips_terminal_node_runs_and_fails_the_rest(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        node_id = run.graph.materialize().nodes[0].node_id
        for status in transition_path(run.status, RunStatus.RUNNING):
            run = await runs.transition_run(run.run_id, status)
        settled = await runs.create_node_run(run.run_id, node_id=node_id)
        # A NodeRun only reaches COMPLETED through a completed Attempt's
        # accepted outcome — walk the spine's own sequence, exactly as
        # execute_node does, so the terminal state is a legal one.
        for status in transition_path(settled.status, RunStatus.RUNNING):
            settled = await runs.transition_node_run(settled.node_run_id, status)
        attempt = await runs.create_attempt(settled.node_run_id, executor_id="rsi-cycle")
        token = (
            attempt.execution_lease.fencing_token if attempt.execution_lease is not None else None
        )
        await runs.transition_attempt(
            attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token
        )
        attempt = await runs.transition_attempt(
            attempt.attempt_id, AttemptStatus.COMPLETED, result={"ok": True}, fencing_token=token
        )
        settled = await runs.transition_node_run(
            settled.node_run_id,
            RunStatus.COMPLETED,
            result={"ok": True},
            accepted_outcome=AcceptedNodeOutcome(
                node_run_id=settled.node_run_id,
                attempt_result=AttemptResult(
                    attempt_id=attempt.attempt_id,
                    node_run_id=settled.node_run_id,
                    ordinal=attempt.ordinal,
                    status=AttemptStatus.COMPLETED,
                    result={"ok": True},
                    finished_at=attempt.finished_at,
                ),
                logical_status=RunStatus.COMPLETED,
                result={"ok": True},
            ),
        )
        pending = await runs.create_node_run(run.run_id, node_id=node_id)
        await provenance._fail_run(run.run_id, error="boom")
        still = await runs.get_node_run(settled.node_run_id)
        assert still is not None and still.status is RunStatus.COMPLETED
        failed = await runs.get_node_run(pending.node_run_id)
        assert failed is not None and failed.status is RunStatus.FAILED

    async def test_resume_refuses_a_run_that_lost_its_record(self):
        projects = InMemoryProjectScopeStore()
        inner = InMemoryRunStore(project_store=projects)
        root = await projects.create_root(WORKSPACE)
        store = _VanishingRunStore(inner)
        provenance = RsiCycleProvenance(store, workspace_id=WORKSPACE, project_id=root.project_id)
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        store.drop_get_run = True
        with pytest.raises(RsiProvenanceError, match="disappeared"):
            await provenance.run_cycle(run, lambda: _return_value(None))

    async def test_resume_accepts_a_run_already_queued(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        for status in transition_path(run.status, RunStatus.QUEUED):
            run = await runs.transition_run(run.run_id, status)
        record = await provenance.run_cycle(run, lambda: _return_value({"ok": True}))
        assert record.completed

    async def test_resume_accepts_a_run_already_running(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        for status in transition_path(run.status, RunStatus.RUNNING):
            run = await runs.transition_run(run.run_id, status)
        record = await provenance.run_cycle(run, lambda: _return_value({"ok": True}))
        assert record.completed

    async def test_close_refuses_a_run_that_lost_its_record(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        record = await provenance.run_cycle(run, lambda: _return_value({"ok": True}))
        store = _VanishingRunStore(runs)
        store.drop_get_run = True
        provenance2 = RsiCycleProvenance(store, workspace_id=WORKSPACE, project_id=run.project_id)
        with pytest.raises(RsiProvenanceError, match="disappeared"):
            await provenance2._close_run_from_node(run.run_id, record.node_run_id)

    async def test_close_refuses_a_node_run_that_lost_its_record(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        record = await provenance.run_cycle(run, lambda: _return_value({"ok": True}))
        store = _VanishingRunStore(runs)
        store.drop_get_node_run = True
        provenance2 = RsiCycleProvenance(store, workspace_id=WORKSPACE, project_id=run.project_id)
        with pytest.raises(RsiProvenanceError, match="disappeared"):
            await provenance2._close_run_from_node(run.run_id, record.node_run_id)

    async def test_close_refuses_a_node_run_without_an_attempt(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        node_id = run.graph.materialize().nodes[0].node_id
        for status in transition_path(run.status, RunStatus.RUNNING):
            run = await runs.transition_run(run.run_id, status)
        node_run = await runs.create_node_run(run.run_id, node_id=node_id)
        with pytest.raises(RsiProvenanceError, match="no Attempt"):
            await provenance._close_run_from_node(run.run_id, node_run.node_run_id)

    async def test_close_is_quiet_when_the_run_is_already_terminal(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        record = await provenance.run_cycle(run, lambda: _return_value({"ok": True}))
        # The run settled COMPLETED on the first close; reading the same
        # NodeRun again must return the same record, not re-transition it.
        again = await provenance._close_run_from_node(run.run_id, record.node_run_id)
        assert again.run_id == record.run_id
        assert again.attempt_id == record.attempt_id
        settled = await runs.get_run(run.run_id)
        assert settled is not None and settled.status is RunStatus.COMPLETED

    async def test_close_leaves_a_nonterminal_run_open_while_its_node_is_running(self):
        provenance, runs, _ = await _provenance()
        run = await provenance.admit_cycle(
            campaign_id="camp-1",
            cycle_id="cycle-1",
            objective="o",
            actor_principal_id="human:op-1",
        )
        node_id = run.graph.materialize().nodes[0].node_id
        for status in transition_path(run.status, RunStatus.RUNNING):
            run = await runs.transition_run(run.run_id, status)
        node_run = await runs.create_node_run(run.run_id, node_id=node_id)
        for status in transition_path(node_run.status, RunStatus.RUNNING):
            node_run = await runs.transition_node_run(node_run.node_run_id, status)
        await runs.create_attempt(node_run.node_run_id, executor_id="rsi-cycle")
        # The NodeRun has physical evidence but no observed disposition yet:
        # closing now would invent an outcome, so the Run stays RUNNING.
        record = await provenance._close_run_from_node(run.run_id, node_run.node_run_id)
        assert record.run_status == RunStatus.RUNNING.value
        assert record.node_run_status == RunStatus.RUNNING.value
        live = await runs.get_run(run.run_id)
        assert live is not None and live.status is RunStatus.RUNNING

    async def test_cycle_objective_falls_back_when_the_hypothesis_is_not_usable(self):
        provenance, _, _ = await _provenance()

        async def executor(context):
            return {"seen": context.node.id}

        wrapped = provenance.wrap_executor(
            executor,
            campaign_id="camp-1",
            actor_principal_id="human:op-1",
        )
        # A context whose node carries no usable hypothesis (not a string):
        # the cycle still runs, and the objective degrades to the neutral
        # "RSI cycle" instead of failing admission.
        report = await wrapped(SimpleNamespace(node=SimpleNamespace(id="anon-node", hypothesis=42)))
        assert report == {"seen": "anon-node"}
        run = await provenance.find_cycle("camp-1", "anon-node")
        assert run is not None
        objective = run.graph.materialize().nodes[0].parameters["objective"]
        assert objective == "RSI cycle"
