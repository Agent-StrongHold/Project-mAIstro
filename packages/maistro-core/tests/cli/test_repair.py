"""Tests for `maistro repair attempt-outputs` (maistro.cli._repair).

The command's whole reason for existing is that its predecessor reached the
wrong store, so what these check is which store it opens and what it says about
what it saw — not the formatting of the table.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.cli._repair import _open_store, _report, attempt_outputs
from maistro.graph import Graph, Node
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.repair import Disposition, Finding, Survey

pytestmark = [pytest.mark.contract("behavioral")]


class TestTheStoreItOpens:
    """AC-1's other half, at the seam the operator actually invokes. The
    withdrawn command opened `durable_graph_runs`; this one has to reach the
    canonical spine, and on a `sqlite:` URL that is checkable directly."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-1")
    async def test_a_sqlite_url_opens_the_canonical_spine(self, tmp_path: Path) -> None:
        db = tmp_path / "spine.db"
        store, closer = await _open_store(f"sqlite:///{db}", "workspace-1")
        try:
            # The canonical tables, not the document-shaped one the withdrawn
            # command created.
            async with aiosqlite.connect(db) as conn:
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in await cursor.fetchall()}
            assert "canonical_attempts" in tables
            assert "durable_graph_runs" not in tables
            assert await store.list_by_status(RunStatus.CREATED) == []
        finally:
            await closer()

    @pytest.mark.ac("SPEC-083026-14c3/AC-1")
    async def test_the_store_it_opens_can_see_a_run_written_through_it(
        self, tmp_path: Path
    ) -> None:
        """Opening the right tables is not the same as reading them. A Run
        written through the store the command opens has to come back."""
        db = tmp_path / "spine.db"
        store, closer = await _open_store(f"sqlite:///{db}", "workspace-1")
        try:
            projects = store._project_store  # type: ignore[attr-defined]
            root = await projects.create_root("workspace-1")
            project = await projects.create(
                workspace_id="workspace-1", parent_project_id=root.project_id, name="P"
            )
            await store.create_run(
                Graph(
                    workspace_id="workspace-1",
                    project_id=project.project_id,
                    name="G",
                    nodes=[Node(node_id="node-1", node_type="agent")],
                )
            )
            assert len(await store.list_by_status(RunStatus.CREATED)) == 1
        finally:
            await closer()


class TestWhatItReports:
    @pytest.mark.ac("SPEC-083026-14c3/AC-8")
    def test_a_truncated_sweep_is_announced(self, capsys: pytest.CaptureFixture[str]) -> None:
        _report(Survey(runs_examined=2, truncated_statuses=(RunStatus.CREATED,)))

        printed = capsys.readouterr().out
        assert "stopped at its limit" in printed
        assert "created" in printed

    @pytest.mark.ac("SPEC-083026-14c3/AC-8")
    def test_a_complete_sweep_claims_no_limit(self, capsys: pytest.CaptureFixture[str]) -> None:
        _report(Survey(runs_examined=2))

        printed = capsys.readouterr().out
        assert "stopped at its limit" not in printed
        assert "No Attempt holds an emptied output" in printed

    @pytest.mark.ac("SPEC-083026-14c3/AC-3")
    def test_an_unrepairable_finding_is_shown_with_its_reason(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _report(
            Survey(
                findings=(
                    Finding(
                        run_id="run-1",
                        node_run_id="nr-1",
                        attempt_id="at-1",
                        disposition=Disposition.NO_SECOND_COPY,
                    ),
                ),
                runs_examined=1,
            )
        )

        printed = capsys.readouterr().out
        assert "no_second_copy" in printed
        assert "No Attempt holds an emptied output" not in printed


class TestSurveyIsTheDefault:
    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    def test_running_without_apply_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "spine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("DB_HOST", raising=False)

        attempt_outputs(workspace_id="workspace-1")

        printed = capsys.readouterr().out
        assert "No Attempt holds an emptied output" in printed
        assert "Repaired" not in printed


class TestApplyIsTheOnlyThingThatWrites:
    """AC-4 and AC-7 at the operator's own seam. The survey path is checked
    above; these are the two lines the operator reaches only by asking."""

    @staticmethod
    async def _emptied_turn(db: Path) -> None:
        """One accepted Attempt holding an emptied output, written through the
        store the command will open — not into a hand-made row."""
        store, closer = await _open_store(f"sqlite:///{db}", "workspace-1")
        try:
            projects = store._project_store  # type: ignore[attr-defined]
            root = await projects.create_root("workspace-1")
            project = await projects.create(
                workspace_id="workspace-1", parent_project_id=root.project_id, name="P"
            )
            run = await store.create_run(
                Graph(
                    workspace_id="workspace-1",
                    project_id=project.project_id,
                    name="G",
                    nodes=[Node(node_id="node-1", node_type="agent")],
                )
            )
            node_run = await store.create_node_run(run.run_id, node_id="node-1")
            await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
            await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
            attempt = await store.create_attempt(node_run.node_run_id)
            await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
            terminal = await store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.COMPLETED,
                result={"status": "completed", "success": True, "output": {}},
            )
            await store.transition_node_run(
                node_run.node_run_id,
                RunStatus.COMPLETED,
                result={"recovered": True},
                accepted_outcome=AcceptedNodeOutcome(
                    node_run_id=node_run.node_run_id,
                    attempt_result=AttemptResult.from_attempt(terminal),
                    logical_status=RunStatus.COMPLETED,
                    result={"recovered": True},
                ),
            )
        finally:
            await closer()

    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    def test_a_survey_names_what_it_would_repair_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "spine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("DB_HOST", raising=False)
        asyncio.run(self._emptied_turn(db))

        attempt_outputs(workspace_id="workspace-1")

        printed = capsys.readouterr().out
        assert "1 repairable" in printed
        assert "Re-run with --apply" in printed
        assert "Repaired" not in printed

        # And nothing was written: the same survey still finds it.
        attempt_outputs(workspace_id="workspace-1")
        assert "1 repairable" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-083026-14c3/AC-4")
    def test_apply_writes_the_repair_and_says_how_many(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "spine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("DB_HOST", raising=False)
        asyncio.run(self._emptied_turn(db))

        attempt_outputs(apply=True, workspace_id="workspace-1")
        assert "Repaired 1 Attempt(s)." in capsys.readouterr().out

        # The end state an operator checks: the survey now finds nothing.
        attempt_outputs(workspace_id="workspace-1")
        assert "No Attempt holds an emptied output" in capsys.readouterr().out


class TestThePostgresBranchOpensAPool:
    """The reason this command exists rather than the withdrawn one: a
    PostgreSQL deployment has to be reachable. Checked by routing the branch,
    since a real server is not guaranteed wherever this suite runs."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-1")
    def test_a_postgresql_url_goes_through_get_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import maistro.persistence as persistence
        import maistro.runs.wiring as wiring

        seen: dict[str, Any] = {}

        async def _fake_get_pool(dsn: str) -> Any:
            seen["dsn"] = dsn

            class _Pool:
                async def close(self) -> None:
                    seen["closed"] = True

            return _Pool()

        async def _fake_release_pool(pool: Any) -> bool:
            seen["released"] = pool
            return True

        async def _fake_wire(conn: Any, **kwargs: Any) -> tuple[Any, ...]:
            seen["conn"] = conn
            seen["pool"] = kwargs.get("pg_pool")
            seen["prime"] = kwargs.get("prime")
            return (object(), object(), object(), object(), object(), object())

        monkeypatch.setattr(persistence, "get_pool", _fake_get_pool)
        monkeypatch.setattr(persistence, "release_pool", _fake_release_pool)
        monkeypatch.setattr(wiring, "wire_execution_spine", _fake_wire)

        _store, closer = asyncio.run(
            _open_store("postgresql://u:p@localhost:5432/maistro", "workspace-1")
        )
        asyncio.run(closer())

        # The spine is wired on the pool, with no SQLite connection in sight.
        assert seen["conn"] is None
        assert seen["pool"] is not None
        assert seen["dsn"].startswith("postgres")
        # Released, never closed. `get_pool` hands back a registry-shared pool
        # and counts its users, so closing it outright would drop the
        # connections under any other user in the process and leave a dead pool
        # registered for the next caller (Codex, #690).
        assert seen["released"] is seen["pool"]
        assert "closed" not in seen

        # And the survey never primes: priming writes.
        assert seen["prime"] is False


class TestTheSweepStatesWhatItCouldNotRead:
    """Codex, #690. Two bounds, and only one of them a re-run can lift.

    An archived Run's payload is offloaded and `PgRunStore.list_by_status`
    selects `payload IS NOT NULL`, so a cold record holding the very loss this
    command repairs is invisible to the sweep and no `--limit` reveals it.
    Reporting a clean pass over records it could not read is the false clean
    bill of health the withdrawn repair gave — the defect this command exists
    to not repeat — so the bound is printed every time, beside the count.
    """

    @pytest.mark.ac("SPEC-083026-14c3/AC-10")
    def test_the_archive_bound_is_printed_beside_the_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "spine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("DB_HOST", raising=False)

        attempt_outputs(workspace_id="workspace-1")

        printed = capsys.readouterr().out
        assert "Archived runs are not examined" in printed
        # Stated even on a clean sweep — that is the case it exists for.
        assert "No Attempt holds an emptied output" in printed

    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    def test_the_survey_names_the_workspace_it_confined_itself_to(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "spine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("DB_HOST", raising=False)

        attempt_outputs(workspace_id="tenant-a")

        assert "in workspace 'tenant-a'" in capsys.readouterr().out


class TestASurveyDoesNotPrimeTheSpine:
    """Codex, #690. `wire_execution_spine` creates the Root Project eagerly, so
    a command promising "Without this, nothing is written" wrote to the
    database it was only asked to read. Repair never creates work — it rewrites
    records that already exist — so it wires with `prime=False` on both
    backends."""

    @pytest.mark.ac("SPEC-083026-14c3/AC-7")
    def test_the_sqlite_branch_wires_without_priming(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import maistro.runs.wiring as wiring

        seen: dict[str, Any] = {}

        async def _fake_wire(conn: Any, **kwargs: Any) -> tuple[Any, ...]:
            seen["prime"] = kwargs.get("prime")
            return (object(), object(), object(), object(), object(), object())

        monkeypatch.setattr(wiring, "wire_execution_spine", _fake_wire)

        _store, closer = asyncio.run(
            _open_store(f"sqlite:///{tmp_path / 'spine.db'}", "workspace-1")
        )
        asyncio.run(closer())

        assert seen["prime"] is False
