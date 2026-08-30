"""Tests for `maistro repair attempt-outputs` (maistro.cli._repair).

The command's whole reason for existing is that its predecessor reached the
wrong store, so what these check is which store it opens and what it says about
what it saw — not the formatting of the table.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from maistro.cli._repair import _open_store, _report, attempt_outputs
from maistro.graph import Graph, Node
from maistro.runs.model import RunStatus
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

        attempt_outputs()

        printed = capsys.readouterr().out
        assert "No Attempt holds an emptied output" in printed
        assert "Repaired" not in printed
