"""SPEC-083026-14c3: repairing an Attempt emptied by the pre-#566 serialization.

Every case drives the `spine` fixture, so it runs against all three backends —
including the two a deployment actually uses. That is the point rather than
thoroughness for its own sake: the repair this replaces was withdrawn because it
ran over a store nothing writes, and a suite that exercised only an in-memory
double would not have caught that either.

The fixtures below build their Runs by *running the store the way production
runs it* — create, transition, accept — rather than by writing a hand-made row.
A hand-made NodeRun would let this suite agree with itself about what an emptied
Attempt looks like while disagreeing with the code that writes one.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.repair import Disposition, classify, repair, survey
from maistro.runs.store import RunIntegrityError, validate_accepted_outcome_against_attempt

pytestmark = [pytest.mark.contract("behavioral")]

#: What a node that returned a typed model persisted as, before #566: the
#: NodeResult round-trips, and its `output` is empty where the model went.
EMPTIED = {"status": "completed", "success": True, "output": {}}

#: What the executor dumped onto `NodeRun.result` in the same execution, which
#: is why the value is recoverable at all.
RECOVERED = {"title": "a typed model's own fields", "pages": 12}


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Durable graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _finished_attempt(store: Any, node_run: Any, result: Any) -> Any:
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    return await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result=result
    )


async def _accepted_emptied_attempt(spine: Any, *, node_result: Any = RECOVERED) -> Any:
    """A completed NodeRun whose Attempt holds an emptied output.

    `node_result` is the logical projection the executor wrote — the second
    copy. Passing the Attempt's own result instead reproduces the shape that
    carries no second copy at all.
    """
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id))
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await _finished_attempt(store, node_run, EMPTIED)
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result=node_result,
    )
    accepted = await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=node_result,
        accepted_outcome=outcome,
    )
    return run, accepted, attempt


class TestTheSurveyReadsTheStoreProductionWrites:
    """AC-1. The withdrawn repair opened a table nothing writes and reported a
    deployment full of emptied Attempts as clean. This is that regression."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-1")
    async def test_an_emptied_attempt_is_found(self, spine: Any) -> None:
        store, _workspace, _project_id = spine
        _run, _node_run, attempt = await _accepted_emptied_attempt(spine)

        found = await survey(store)

        assert [f.attempt_id for f in found.findings] == [attempt.attempt_id]
        assert found.runs_examined == 1

    @pytest.mark.ac("SPEC-083026-14c3/AC-1")
    async def test_a_store_with_nothing_wrong_reports_nothing(self, spine: Any) -> None:
        """The other half of AC-1: a clean answer has to be reachable too, or
        the survey is only ever right by accident."""
        store, workspace, project_id = spine
        run = await store.create_run(_graph(workspace, project_id))
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        await _finished_attempt(store, node_run, {"output": RECOVERED})

        found = await survey(store)

        assert found.findings == ()
        assert found.runs_examined == 1


class TestClassification:
    """AC-2 and AC-3: what the second copy proves, and what nothing proves."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-2")
    async def test_an_accepted_attempt_beside_a_logical_record_is_repairable(
        self, spine: Any
    ) -> None:
        store, _workspace, _project_id = spine
        await _accepted_emptied_attempt(spine)

        (finding,) = (await survey(store)).findings

        assert finding.disposition is Disposition.REPAIRABLE
        assert finding.recovered == RECOVERED

    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    async def test_an_unaccepted_attempt_is_reported_not_guessed(self, spine: Any) -> None:
        """A superseded retry, a failure, or one still in flight: no accepted
        outcome names it, so there is no second copy anywhere."""
        store, workspace, project_id = spine
        run = await store.create_run(_graph(workspace, project_id))
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        await _finished_attempt(store, node_run, EMPTIED)

        (finding,) = (await survey(store)).findings

        assert finding.disposition is Disposition.NOT_ACCEPTED
        assert finding.recovered is None
        assert not finding.repairable

    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    async def test_an_accepted_attempt_with_no_second_copy_is_reported(self, spine: Any) -> None:
        """The reconciliation path records the whole Attempt result on the
        NodeRun, so the two are equal and nothing distinguishes an emptied
        output from one that was genuinely `{}`."""
        store, _workspace, _project_id = spine
        await _accepted_emptied_attempt(spine, node_result=EMPTIED)

        (finding,) = (await survey(store)).findings

        assert finding.disposition is Disposition.NO_SECOND_COPY
        assert not finding.repairable

    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    async def test_classify_needs_no_store(self, spine: Any) -> None:
        """The decision is a function of the two records, so it can be checked
        without one — and a caller cannot reach a different answer by holding a
        store the survey did not."""
        _run, node_run, attempt = await _accepted_emptied_attempt(spine)

        assert classify(attempt, node_run).disposition is Disposition.REPAIRABLE


class TestTheRepair:
    """AC-4, AC-5, AC-6: the write, its refusal, and the invariant."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-4")
    async def test_the_recovered_output_lands_on_the_attempt(self, spine: Any) -> None:
        store, _workspace, _project_id = spine
        _run, _node_run, attempt = await _accepted_emptied_attempt(spine)

        applied = await repair(store, (await survey(store)).findings)

        assert [f.attempt_id for f in applied] == [attempt.attempt_id]
        repaired = await store.get_attempt(attempt.attempt_id)
        assert repaired is not None
        assert repaired.result["output"] == RECOVERED
        assert repaired.result["success"] is True

    @pytest.mark.ac("SPEC-083026-14c3/AC-4")
    async def test_a_repaired_store_surveys_clean(self, spine: Any) -> None:
        """The end state, not just the write: running the survey again finds
        nothing, which is what an operator checks after applying."""
        store, _workspace, _project_id = spine
        await _accepted_emptied_attempt(spine)

        await repair(store, (await survey(store)).findings)

        assert (await survey(store)).findings == ()

    @pytest.mark.ac("SPEC-083026-14c3/AC-5")
    async def test_a_running_attempt_is_refused(self, spine: Any) -> None:
        store, workspace, project_id = spine
        run = await store.create_run(_graph(workspace, project_id))
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        attempt = await store.create_attempt(node_run.node_run_id)
        running = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

        with pytest.raises(RunIntegrityError, match="has not finished"):
            await store.repair_attempt_result(attempt.attempt_id, result={"output": RECOVERED})

        unchanged = await store.get_attempt(attempt.attempt_id)
        assert unchanged is not None
        assert unchanged.result == running.result

    @pytest.mark.ac("SPEC-083026-14c3/AC-6")
    async def test_the_accepted_outcome_moves_with_the_attempt(self, spine: Any) -> None:
        store, _workspace, _project_id = spine
        _run, node_run, attempt = await _accepted_emptied_attempt(spine)

        await repair(store, (await survey(store)).findings)

        reloaded = await store.get_node_run(node_run.node_run_id)
        repaired = await store.get_attempt(attempt.attempt_id)
        assert reloaded is not None and repaired is not None
        assert reloaded.accepted_outcome is not None
        # The invariant the store exists to hold: raising here is the record
        # holding two different physical results for one execution.
        validate_accepted_outcome_against_attempt(reloaded.accepted_outcome, repaired)

    @pytest.mark.ac("SPEC-083026-14c3/AC-6")
    async def test_the_logical_projection_is_left_alone(self, spine: Any) -> None:
        """Only the embedded physical copy is rebuilt. Rewriting the logical
        result would make the repair a second acceptance, and `NodeRun.result`
        was never the thing that was emptied."""
        store, _workspace, _project_id = spine
        _run, node_run, _attempt = await _accepted_emptied_attempt(spine)

        await repair(store, (await survey(store)).findings)

        reloaded = await store.get_node_run(node_run.node_run_id)
        assert reloaded is not None and reloaded.accepted_outcome is not None
        assert reloaded.result == RECOVERED
        assert reloaded.accepted_outcome.result == RECOVERED

    @pytest.mark.ac("SPEC-083026-14c3/AC-6")
    async def test_an_unaccepted_attempt_repairs_without_a_node_run_write(self, spine: Any) -> None:
        """The store must not require an accepted outcome to exist. A NodeRun
        that never accepted this Attempt is left exactly as it was."""
        store, workspace, project_id = spine
        run = await store.create_run(_graph(workspace, project_id))
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        attempt = await _finished_attempt(store, node_run, EMPTIED)

        repaired = await store.repair_attempt_result(
            attempt.attempt_id, result={"output": RECOVERED}
        )

        assert repaired.result["output"] == RECOVERED
        reloaded = await store.get_node_run(node_run.node_run_id)
        assert reloaded is not None
        assert reloaded.accepted_outcome is None


class TestASurveyWritesNothing:
    """AC-7. The first thing an operator wants is to know what would happen."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    async def test_surveying_leaves_every_attempt_as_it_was(self, spine: Any) -> None:
        store, _workspace, _project_id = spine
        _run, node_run, attempt = await _accepted_emptied_attempt(spine)

        await survey(store)
        await survey(store)

        unchanged = await store.get_attempt(attempt.attempt_id)
        reloaded = await store.get_node_run(node_run.node_run_id)
        assert unchanged is not None and reloaded is not None
        assert unchanged.result == EMPTIED
        assert reloaded.accepted_outcome is not None
        assert reloaded.accepted_outcome.attempt_result.result == EMPTIED

    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    async def test_repair_skips_what_it_cannot_recover(self, spine: Any) -> None:
        """Handed every finding, `repair` writes only the repairable ones — the
        guard against a caller that filters wrongly, or not at all."""
        store, _workspace, _project_id = spine
        _run, _node_run, attempt = await _accepted_emptied_attempt(spine, node_result=EMPTIED)

        applied = await repair(store, (await survey(store)).findings)

        assert applied == ()
        unchanged = await store.get_attempt(attempt.attempt_id)
        assert unchanged is not None
        assert unchanged.result == EMPTIED


class TestACappedSweepSaysSo:
    """AC-8. Presenting a partial sweep as complete is the withdrawn repair's
    defect one level up: answering more confidently than the evidence allows."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-8")
    async def test_a_full_page_is_reported_as_truncated(self, spine: Any) -> None:
        store, workspace, project_id = spine
        for _ in range(2):
            await store.create_run(_graph(workspace, project_id))

        found = await survey(store, limit=2)

        assert RunStatus.CREATED in found.truncated_statuses
        assert not found.complete

    @pytest.mark.ac("SPEC-083026-14c3/AC-8")
    async def test_a_sweep_that_saw_everything_reports_complete(self, spine: Any) -> None:
        store, workspace, project_id = spine
        await store.create_run(_graph(workspace, project_id))

        found = await survey(store, limit=50)

        assert found.truncated_statuses == ()
        assert found.complete
        assert found.runs_examined == 1


class TestAnEmptyLogicalRecordIsNotASecondCopy:
    """Codex, #690. A node that genuinely returned `{}` leaves
    `NodeRun.result == {}` beside the Attempt's `{"output": {}}`. Those compare
    *unequal* — one is a projection, the other an envelope — so equality alone
    called the record repairable, wrote `{}` back unchanged, and reported the
    same Attempt on every sweep after that: a finding no operator could clear.
    """

    @pytest.mark.parametrize("empty", [{}, None])
    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    async def test_an_empty_node_result_carries_no_evidence(self, spine: Any, empty: Any) -> None:
        _run, node_run, attempt = await _accepted_emptied_attempt(spine, node_result=empty)

        assert classify(attempt, node_run).disposition is Disposition.NO_SECOND_COPY

    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    async def test_the_sweep_does_not_offer_to_repair_it(self, spine: Any) -> None:
        """The property that matters to an operator: it is reported with its
        reason, and `--apply` writes nothing, so the next sweep says the same."""
        store, _workspace, _project_id = spine
        await _accepted_emptied_attempt(spine, node_result={})

        found = await survey(store)
        assert found.repairable == ()
        assert await repair(store, found.findings) == ()


class TestTheSweepStaysInsideItsWorkspace:
    """Codex, #690. `--workspace-id` only chose which store to wire; the sweep
    itself listed globally, so naming one Workspace surveyed — and with
    `--apply` repaired — every other tenant's records in the same database.

    Built on one in-memory store with two real Workspaces rather than through
    the `spine` fixture: the store refuses a Project that belongs to another
    Workspace, which is the invariant that makes two genuine Workspaces the
    only honest way to pose the question. The filter itself is in `survey`, so
    it is backend-independent and one store is the right scope for it.
    """

    @staticmethod
    async def _emptied_run_in(store: Any, workspace: str, project_id: str) -> Any:
        run = await store.create_run(_graph(workspace, project_id))
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        attempt = await _finished_attempt(store, node_run, EMPTIED)
        await store.transition_node_run(
            node_run.node_run_id,
            RunStatus.COMPLETED,
            result=RECOVERED,
            accepted_outcome=AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=AttemptResult.from_attempt(attempt),
                logical_status=RunStatus.COMPLETED,
                result=RECOVERED,
            ),
        )
        return run

    @pytest.mark.ac("SPEC-083026-14c3/AC-9")
    async def test_another_workspace_is_neither_surveyed_nor_repaired(self) -> None:
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        projects = InMemoryProjectScopeStore()
        store = InMemoryRunStore(project_store=projects)
        runs = {}
        for name in ("tenant-a", "tenant-b"):
            root = await projects.create_root(name)
            project = await projects.create(
                workspace_id=name, parent_project_id=root.project_id, name="Durable"
            )
            runs[name] = await self._emptied_run_in(store, name, project.project_id)

        confined = await survey(store, workspace_id="tenant-a")

        assert confined.workspace_id == "tenant-a"
        assert confined.runs_examined == 1
        assert {f.run_id for f in confined.repairable} == {runs["tenant-a"].run_id}
        # Both are damaged; only one is in scope. An unscoped sweep sees two.
        assert len((await survey(store)).repairable) == 2

    @pytest.mark.ac("SPEC-083026-14c3/AC-9")
    async def test_applying_in_one_workspace_leaves_the_other_untouched(self) -> None:
        """The half that makes it a data-safety property rather than a display
        one: `--apply` on tenant-a must not rewrite tenant-b's Attempt."""
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        projects = InMemoryProjectScopeStore()
        store = InMemoryRunStore(project_store=projects)
        for name in ("tenant-a", "tenant-b"):
            root = await projects.create_root(name)
            project = await projects.create(
                workspace_id=name, parent_project_id=root.project_id, name="Durable"
            )
            await self._emptied_run_in(store, name, project.project_id)

        applied = await repair(store, (await survey(store, workspace_id="tenant-a")).findings)

        assert len(applied) == 1
        # tenant-b's Attempt is still emptied, so an unscoped sweep still finds it.
        assert len((await survey(store)).repairable) == 1
        assert (await survey(store, workspace_id="tenant-a")).repairable == ()


class TestTheSqliteRepairCommitsBothCopiesTogether:
    """Codex, #690. `_update_payload` commits as it goes, so writing the
    Attempt and its NodeRun through it was two transactions. Stopping between
    them leaves `Attempt.result` disagreeing with
    `accepted_outcome.attempt_result` — the state
    `validate_accepted_outcome_against_attempt` refuses, and the one this
    method exists to prevent. The write lock does not close it: it serializes
    writers, and readers do not take it.
    """

    @pytest.mark.ac("SPEC-083026-14c3/AC-6")
    async def test_one_flush_carries_both_payloads(self) -> None:
        import aiosqlite

        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.sqlite_store import SqliteRunStore

        projects = InMemoryProjectScopeStore()
        root = await projects.create_root("tenant")
        project = await projects.create(
            workspace_id="tenant", parent_project_id=root.project_id, name="Durable"
        )
        conn = await aiosqlite.connect(":memory:")
        try:
            store = SqliteRunStore(conn, project_store=projects)
            await store.ensure_schema()
            spine = (store, "tenant", project.project_id)
            _run, node_run, attempt = await _accepted_emptied_attempt(spine)

            flushes = 0
            staged_at_flush: list[int] = []
            original = store._flush

            async def _counting_flush() -> None:
                nonlocal flushes
                flushes += 1
                staged_at_flush.append(len(store._pending))
                await original()

            store._flush = _counting_flush  # type: ignore[method-assign]
            repaired = await store.repair_attempt_result(
                attempt.attempt_id, result={**EMPTIED, "output": RECOVERED}
            )

            # One commit, carrying both rows — not one commit each.
            assert flushes == 1
            assert staged_at_flush == [2]
            # And the spine agrees with itself afterwards, which is the point.
            validate_accepted_outcome_against_attempt(
                (await store.get_node_run(node_run.node_run_id)).accepted_outcome, repaired
            )
        finally:
            await conn.close()
