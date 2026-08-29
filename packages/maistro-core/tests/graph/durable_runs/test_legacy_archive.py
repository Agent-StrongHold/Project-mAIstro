"""Graph runs written before the convergence still read back (#44, criterion 5).

The fixture beside this file is not generated. It was captured by running a
two-node graph through `SqliteDurableRunStore` on the code as it stood at
`608f27e` — the commit before #565 moved identity onto the canonical spine —
and committing the resulting database byte for byte.

That is the whole point. A fixture written by today's models would only prove
today's models round-trip themselves, which is true of any schema and says
nothing about the migration. The failure criterion 5 guards against is a model
or validator change that makes *old* records unloadable, and only a record the
old code actually wrote can catch it.

What the archive must not do is as load-bearing as what it must. Those runs
carry NodeRun and Attempt ids the spine never saw, so replaying them through
`create_node_run`/`create_attempt` — which allocate identity themselves — would
either produce different ids, leaving the archive and the spine disagreeing
about one execution, or need an id-preserving write path, which is the second
system of record this issue removes. So it reproduces and refuses to resume.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.graph.durable_runs.legacy_archive import (
    LEGACY_TABLE,
    ArchivedGraphRun,
    LegacyGraphRunArchive,
    LegacyRunNotResumable,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunNotFound

FIXTURE = Path(__file__).parent / "fixtures" / "pre_convergence_durable_runs.sqlite3"


@pytest.fixture
def archive() -> LegacyGraphRunArchive:
    return LegacyGraphRunArchive(FIXTURE)


@pytest.fixture
def archived(archive: LegacyGraphRunArchive) -> ArchivedGraphRun:
    run_ids = archive.list_run_ids()
    assert len(run_ids) == 1, "the captured fixture holds exactly one archived run"
    run = archive.get(run_ids[0])
    assert run is not None
    return run


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_a_pre_convergence_run_reproduces_field_for_field(archived: ArchivedGraphRun) -> None:
    """The Run the old store persisted, through today's canonical model."""
    assert archived.run.workspace_id == "ws-legacy"
    assert archived.run.project_id == "proj-legacy"
    assert archived.run.status is RunStatus.COMPLETED
    assert archived.run.graph.materialize().name == "pre-convergence archive"
    assert [node.node_id for node in archived.run.graph.materialize().nodes] == [
        "first",
        "second",
    ]
    assert archived.version >= 1


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_the_execution_history_survives_whole(archived: ArchivedGraphRun) -> None:
    """Not just the Run: what it did. A projection that reproduced a Run and
    lost its NodeRuns would satisfy the letter of "the record loads" while
    destroying the history the criterion is about."""
    assert [item.node_id for item in archived.node_runs] == ["first", "second"]
    assert [item.ordinal for item in archived.node_runs] == [1, 2]
    assert [item.status for item in archived.node_runs] == [
        RunStatus.COMPLETED,
        RunStatus.COMPLETED,
    ]
    assert all(item.run_id == archived.run_id for item in archived.node_runs)

    for node_run in archived.node_runs:
        attempts = archived.attempts_for(node_run.node_run_id)
        assert [item.ordinal for item in attempts] == [1]
        assert [item.status for item in attempts] == [AttemptStatus.COMPLETED]


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_the_traversal_history_is_kept_beside_it(archived: ArchivedGraphRun) -> None:
    """The half `GraphContinuation` holds for live runs. An archived run has
    no continuation row, so it has to come out of the record."""
    assert archived.traversal_commits, "the captured run committed its frontier advances"
    assert archived.traversal_checkpoints
    assert archived.graph_state["run_id"] == archived.run_id


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
async def test_the_archive_is_not_on_the_spine_and_does_not_put_itself_there(
    archived: ArchivedGraphRun,
) -> None:
    """Reading history must not write it. If this ever fails, the archive has
    started minting canonical identity for ids the spine never admitted, which
    is precisely the duplicate `CanonicalDurableRunStore.create` refuses."""
    run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())

    assert await run_store.get_run(archived.run_id) is None
    # Stronger than an empty list: the spine refuses to answer questions about
    # a Run it never admitted, rather than reporting it has no NodeRuns.
    with pytest.raises(RunNotFound):
        await run_store.list_node_runs(archived.run_id)
    for status in RunStatus:
        assert await run_store.list_by_status(status, limit=10) == []


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_resuming_an_archived_run_is_refused_by_name(archived: ArchivedGraphRun) -> None:
    """Refused loudly rather than quietly re-admitted under a new id, because
    a silent re-admission is two records for one execution — and the caller
    would have no way to tell it happened."""
    with pytest.raises(LegacyRunNotResumable, match="read but not resumed"):
        archived.resume()


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_archived_runs_are_findable_by_status(archive: LegacyGraphRunArchive) -> None:
    completed = archive.list_by_status(RunStatus.COMPLETED)

    assert [item.run_id for item in completed] == archive.list_run_ids()
    assert archive.list_by_status(RunStatus.FAILED) == []


def test_the_named_table_is_the_one_the_queries_read() -> None:
    """`LEGACY_TABLE` documents the table but is not interpolated into the SQL.

    A table name cannot be a bind parameter, so using the constant in a query
    means building the statement by string construction -- bandit B608, which
    this repository runs at a strict zero baseline. The constant and the
    literals are therefore kept in step by an assertion instead of by an
    f-string, which is the only part of that arrangement that could drift.
    """
    import inspect

    from maistro.graph.durable_runs import legacy_archive

    source = inspect.getsource(legacy_archive)

    assert f"FROM {LEGACY_TABLE} " in source or f"FROM {LEGACY_TABLE}\n" in source
    assert 'f"SELECT' not in source, "SQL must not be built by f-string (bandit B608)"


def test_an_unknown_run_is_absent(archive: LegacyGraphRunArchive) -> None:
    assert archive.get("no-such-run") is None


def test_a_missing_archive_says_so_rather_than_reading_empty(tmp_path: Path) -> None:
    """An archive path that does not exist would otherwise open cleanly and
    report no history at all, which reads exactly like a successful migration
    that lost everything."""
    with pytest.raises(FileNotFoundError):
        LegacyGraphRunArchive(tmp_path / "absent.sqlite3")


def test_the_archive_cannot_write_to_the_database_it_reads(
    archive: LegacyGraphRunArchive, tmp_path: Path
) -> None:
    """The read-only guarantee is SQLite's, not this class's good intentions."""
    import sqlite3

    conn = archive._connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM durable_graph_runs")
    finally:
        conn.close()


# --- the operator entry point (#44) ----------------------------------------


def _cli(*args: str) -> str:
    """Invoke `maistro archive ...` the way an operator would."""
    from typer.testing import CliRunner

    from maistro.cli import app

    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_an_operator_can_list_archived_runs() -> None:
    """The reason this criterion needs an entry point and not only a class.

    A library nobody can invoke does not make history reachable: the operator
    holding a database written before #565 has to be able to open it, and until
    there is a command they cannot.
    """
    output = _cli("archive", "list", str(FIXTURE))

    assert "completed" in output


@pytest.mark.ac("ADR-082826-d9f5/AC-6")
def test_an_operator_can_reproduce_one_archived_run(archived: ArchivedGraphRun) -> None:
    output = _cli("archive", "show", str(FIXTURE), archived.run_id)

    assert "ws-legacy" in output
    assert "first" in output
    assert "second" in output
    # The refusal is on the screen, not only in the exception: an operator
    # reading this must not go looking for a resume command.
    assert "cannot be" in output


def test_the_commands_say_so_rather_than_failing_on_an_unknown_run() -> None:
    assert "No archived run" in _cli("archive", "show", str(FIXTURE), "no-such-run")


def test_listing_an_empty_archive_says_it_is_empty(tmp_path: Path) -> None:
    """An empty archive and a broken reader must not look the same."""
    import sqlite3

    empty = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(empty)
    conn.execute(
        "CREATE TABLE durable_graph_runs "
        "(run_id TEXT PRIMARY KEY, status TEXT, created_at TEXT, record_json TEXT)"
    )
    conn.commit()
    conn.close()

    assert "No archived runs" in _cli("archive", "list", str(empty))
