"""The shipped `maistro backlog` CLI (#102) — the cutover entry point.

The operator tool began life as `scripts/backlog_cutover.py`; the
reachability ratchet (scripts/check-reachability.py) requires production
modules to sit on a real process entry path, so the tool now lives at the
shipped CLI root (`maistro.cli` → `maistro.cli._backlog`). These tests pin
the CLI-specific half of that contract: the file projections a cutover
performs (generated banner, export digest, authority marker), the exit codes
its refusals produce, and the fail-closed behavior of the agent verbs. The
domain behavior underneath — round-trip losslessness, claim/lease semantics,
deterministic export — stays pinned where it always was:
``test_markdown_migration``, ``test_authority_cutover``,
``test_agent_surface`` and ``test_backlog_store_conformance``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from maistro.cli._backlog import GENERATED_BANNER, app
from maistro.testing.postgres import postgres_dsn

runner = CliRunner()

WORKSPACE = "root-backlog"

DOCUMENT = """# Backlog

## Alpha

**[a-001] First item — Open — M1**

**[a-000] Done seed — Implemented — M1**
- Evidence: done in PR #1

## Beta

**[b-001] Second item — Open**
"""


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    """A scratch checkout: the document, the marker path, the database."""
    (tmp_path / "BACKLOG.md").write_text(DOCUMENT)
    return tmp_path


def _invoke(*args: str):
    return runner.invoke(app, [*args])


def _cut_over(docs: Path) -> None:
    """Import and cut over the scratch checkout, leaving db authority."""
    db = str(docs / "scratch.sqlite3")
    assert _invoke("import", "--db", db, "--document", str(docs / "BACKLOG.md")).exit_code == 0
    result = _invoke(
        "cutover",
        "--db",
        db,
        "--document",
        str(docs / "BACKLOG.md"),
        "--marker",
        str(docs / "quality" / "backlog-authority.json"),
        "--actor",
        "op",
    )
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# The authority lifecycle
# ---------------------------------------------------------------------------


def test_status_defaults_to_markdown_authority(docs: Path) -> None:
    result = _invoke("status", "--db", str(docs / "scratch.sqlite3"))
    assert result.exit_code == 0
    assert "authority: markdown" in result.output
    assert "never imported" in result.output


def test_import_is_idempotent_and_never_flips_authority(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    for _ in range(2):
        result = _invoke("import", "--db", db, "--document", str(docs / "BACKLOG.md"))
        assert result.exit_code == 0
        assert "authority unchanged" in result.output
    status = _invoke("status", "--db", db)
    assert "authority: markdown" in status.output
    assert "imported" in status.output and "never imported" not in status.output


def test_cutover_writes_banner_digest_and_flips_the_marker(docs: Path) -> None:
    marker = docs / "quality" / "backlog-authority.json"
    _cut_over(docs)

    record = json.loads(marker.read_text())
    generated = (docs / "BACKLOG.md").read_text()
    assert record["authority"] == "db"
    assert record["revision"] == 1
    assert record["export_sha256"] == hashlib.sha256(generated.encode()).hexdigest()
    assert generated.startswith(GENERATED_BANNER.format(revision=1)), (
        "the generated document must carry the banner"
    )


def test_generate_refused_under_markdown_authority(docs: Path) -> None:
    result = _invoke(
        "generate",
        "--db",
        str(docs / "scratch.sqlite3"),
        "--document",
        str(docs / "BACKLOG.md"),
        "--marker",
        str(docs / "quality" / "backlog-authority.json"),
    )
    assert result.exit_code == 1
    assert "refused: authority is markdown" in result.output
    assert (docs / "BACKLOG.md").read_text() == DOCUMENT


def test_revert_restores_the_hand_maintained_document(docs: Path) -> None:
    marker = docs / "quality" / "backlog-authority.json"
    _cut_over(docs)
    result = _invoke(
        "revert",
        "--db",
        str(docs / "scratch.sqlite3"),
        "--document",
        str(docs / "BACKLOG.md"),
        "--marker",
        str(marker),
        "--actor",
        "op",
    )
    assert result.exit_code == 0
    assert (docs / "BACKLOG.md").read_text() == DOCUMENT, "the banner must be stripped"
    record = json.loads(marker.read_text())
    assert record["authority"] == "markdown"
    assert record["export_sha256"] is None
    assert record["revision"] == 2, "revert appends its own ledger revision"


# ---------------------------------------------------------------------------
# The agent verbs: fail-closed by default, claim-checked when open
# ---------------------------------------------------------------------------


def test_agent_verbs_fail_closed_without_a_role(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    _cut_over(docs)

    # No role means no relationship to the workspace: the surface answers
    # with its fail-closed refusal, never with data.
    select = _invoke("select", "--workspace", WORKSPACE, "--db", db, "--actor", "agent-7")
    assert select.exit_code == 1
    assert "may not read" in select.output

    write = _invoke(
        "write",
        "a-001",
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-7",
        "--expected-version",
        "1",
        "--title",
        "hijack",
    )
    assert write.exit_code == 1
    assert "may not write" in write.output


def test_claim_write_release_roundtrip_through_the_cli(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    _cut_over(docs)

    selected = _invoke(
        "select", "--workspace", WORKSPACE, "--db", db, "--actor", "agent-7", "--role", "editor"
    )
    assert selected.exit_code == 0
    assert json.loads(selected.output)["item"]["item_id"] == "a-001"

    claim = _invoke(
        "claim",
        "a-001",
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-7",
        "--role",
        "editor",
    )
    assert claim.exit_code == 0
    claim_id = json.loads(claim.output)["claim_id"]

    write = _invoke(
        "write",
        "a-001",
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-7",
        "--role",
        "editor",
        "--claim-id",
        claim_id,
        "--expected-version",
        "1",
        "--title",
        "First item (claimed)",
    )
    assert write.exit_code == 0
    written = json.loads(write.output)
    assert written["title"] == "First item (claimed)"
    assert written["version"] == 2

    release = _invoke(
        "release",
        "a-001",
        "--claim-id",
        claim_id,
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-7",
        "--role",
        "editor",
    )
    assert release.exit_code == 0

    # The lease is gone, so a second actor may claim the same item.
    again = _invoke(
        "claim",
        "a-001",
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-8",
        "--role",
        "editor",
    )
    assert again.exit_code == 0


# ---------------------------------------------------------------------------
# The operator surface: opening paths, marker precedence, lifecycle edges
# ---------------------------------------------------------------------------


def test_asyncpg_dsn_normalizes_sqlalchemy_spellings() -> None:
    from maistro.cli._backlog import _asyncpg_dsn

    assert _asyncpg_dsn("postgresql://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"
    assert _asyncpg_dsn("postgres://u:p@h:5432/d") == "postgres://u:p@h:5432/d"
    # The SQLAlchemy spelling the rest of the repository ships is not one
    # asyncpg accepts; the CLI accepts it so `--db` can take MAISTRO_DATABASE_URL.
    assert _asyncpg_dsn("postgresql+asyncpg://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"


def test_item_json_null_contract() -> None:
    from maistro.cli._backlog import _item_json

    assert _item_json(None) == "null"


def test_marker_path_precedence_is_explicit_then_environment_then_checkout(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.cli._backlog import marker_path

    explicit = docs / "explicit.json"
    assert marker_path(explicit) == explicit, "an explicit --marker beats the environment"

    override = docs / "overridden-marker.json"
    monkeypatch.setenv("MAISTRO_BACKLOG_AUTHORITY_FILE", str(override))
    assert marker_path(None) == override
    assert marker_path(explicit) == explicit


def test_status_after_cutover_lists_the_ledger_history(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    marker = str(docs / "quality" / "backlog-authority.json")
    _cut_over(docs)

    result = _invoke("status", "--db", db, "--marker", marker)
    assert result.exit_code == 0
    assert "authority: db" in result.output
    assert "revision 1: db by op" in result.output
    assert '"authority": "db"' in result.output, "the marker line echoes the recorded marker"


def test_cutover_rolls_back_the_ledger_when_generated_files_cannot_be_written(
    docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated-file write failure must not leave db authority behind.

    The ledger is compensating-transaction territory: the flip only stands
    when the generated projections (document banner + marker digest) landed
    with it. Simulating the disk failure at the write seam keeps the test
    deterministic (no chmod-on-root flakiness) while still exercising the
    exact except-OSError path the CLI ships.
    """
    import maistro.cli._backlog as backlog_cli

    db = str(docs / "scratch.sqlite3")
    marker = str(docs / "quality" / "backlog-authority.json")
    document = docs / "BACKLOG.md"
    assert _invoke("import", "--db", db, "--document", str(document)).exit_code == 0

    def refuse(_document: Path, _text: str, _revision: int) -> str:
        raise OSError("read-only checkout")

    monkeypatch.setattr(backlog_cli, "_write_generated", refuse)
    result = _invoke(
        "cutover",
        "--db",
        db,
        "--document",
        str(document),
        "--marker",
        marker,
        "--actor",
        "op",
    )
    assert result.exit_code == 1

    # The ledger agrees with the files: authority stayed markdown, via the
    # compensating revision that names the failure.
    status = _invoke("status", "--db", db, "--marker", marker)
    assert status.exit_code == 0
    assert "authority: markdown" in status.output
    assert "revision 2: markdown by op" in status.output
    assert "cutover rolled back" in status.output
    assert "GENERATED" not in document.read_text(), "the document was never rewritten"

    # The compensating path is not a one-way door: a healthy cutover still works.
    monkeypatch.undo()
    retry = _invoke(
        "cutover",
        "--db",
        db,
        "--document",
        str(document),
        "--marker",
        marker,
        "--actor",
        "op",
    )
    assert retry.exit_code == 0, retry.output
    assert document.read_text().startswith(GENERATED_BANNER.format(revision=3))


def test_generate_regenerates_the_document_from_database_state(docs: Path) -> None:
    """`generate` is the post-cutover projection: DB changes reach the file,
    and the marker's digest certifies exactly what was written."""
    db = str(docs / "scratch.sqlite3")
    marker = str(docs / "quality" / "backlog-authority.json")
    document = docs / "BACKLOG.md"
    _cut_over(docs)

    # A database-side edit makes the file stale until generate runs.
    claim = _invoke(
        "claim", "a-001", "--workspace", WORKSPACE, "--db", db,
        "--actor", "agent-7", "--role", "editor",
    )
    assert claim.exit_code == 0, claim.output
    claim_id = json.loads(claim.output)["claim_id"]
    write = _invoke(
        "write", "a-001", "--workspace", WORKSPACE, "--db", db,
        "--actor", "agent-7", "--role", "editor", "--claim-id", claim_id,
        "--expected-version", "1", "--title", "Renamed in the database",
    )
    assert write.exit_code == 0, write.output
    assert "Renamed in the database" not in document.read_text()

    result = _invoke("generate", "--db", db, "--document", str(document), "--marker", marker)
    assert result.exit_code == 0, result.output
    assert "regenerated from the database (authority revision 1)" in result.output
    generated = document.read_text()
    assert "Renamed in the database" in generated, "the export reflects the DB change"
    record = json.loads(Path(marker).read_text())
    assert record["export_sha256"] == hashlib.sha256(generated.encode()).hexdigest()


def test_items_lists_open_work_for_an_authorized_actor(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    _cut_over(docs)

    listed = _invoke(
        "items", "--workspace", WORKSPACE, "--db", db, "--actor", "agent-7", "--role", "editor"
    )
    assert listed.exit_code == 0, listed.output
    ids = [item["item_id"] for item in json.loads(listed.output)]
    assert sorted(ids) == ["a-001", "b-001"], "closed a-000 stays invisible"

    # The --status filter narrows before the surface's terminal-state rule;
    # a done-only query therefore still answers empty, fail-closed.
    closed = _invoke(
        "items",
        "--workspace",
        WORKSPACE,
        "--db",
        db,
        "--actor",
        "agent-7",
        "--role",
        "editor",
        "--status",
        "done",
    )
    assert closed.exit_code == 0, closed.output
    assert json.loads(closed.output) == []


def test_select_with_nothing_claimable_answers_none_without_error(docs: Path) -> None:
    db = str(docs / "scratch.sqlite3")
    _cut_over(docs)

    # Every open item claimed: select still exits 0, with the plain answer.
    for item_id in ("a-001", "b-001"):
        claim = _invoke(
            "claim", item_id, "--workspace", WORKSPACE, "--db", db,
            "--actor", "agent-7", "--role", "editor",
        )
        assert claim.exit_code == 0, claim.output

    result = _invoke(
        "select", "--workspace", WORKSPACE, "--db", db, "--actor", "agent-7", "--role", "editor"
    )
    assert result.exit_code == 0
    assert "no claimable item" in result.output
    assert "agent-7" in result.output and WORKSPACE in result.output


def test_agent_verbs_run_against_the_postgres_store() -> None:
    """`--db` opens the shipped PostgreSQL store directly (the asyncpg path).

    Deliberately not the root-backlog document path: the cutover's round-trip
    proof is workspace-global, so on a shared migrated database it would have
    to own `root-backlog` exclusively. This leg pins what the CLI adds over
    the store suites — the DSN opening path and the agent verbs driving the
    real PgBacklogStore — inside a throwaway workspace, the same isolation the
    conformance suite uses. The PostgreSQL leg runs in the coverage-postgres
    producer, where `MAISTRO_REQUIRE_PG_LEGS` makes a silent skip fatal.
    """
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL CLI leg cannot run and must not be silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    import asyncpg

    from maistro.backlog.pg_store import PgBacklogStore

    workspace = f"pg-cli-{uuid.uuid4().hex[:12]}"

    async def seed() -> str:
        pool = await asyncpg.create_pool(dsn)
        assert pool is not None
        try:
            store = PgBacklogStore(pool)
            item = await store.create_item(
                workspace_id=workspace, title="PG CLI work", actor="human:op", priority=2
            )
            return item.item_id
        finally:
            await pool.close()

    item_id = asyncio.run(seed())

    listed = _invoke(
        "items", "--workspace", workspace, "--db", dsn, "--actor", "agent-9", "--role", "editor"
    )
    assert listed.exit_code == 0, listed.output
    assert [item["item_id"] for item in json.loads(listed.output)] == [item_id]

    selected = _invoke(
        "select", "--workspace", workspace, "--db", dsn, "--actor", "agent-9", "--role", "editor"
    )
    assert selected.exit_code == 0, selected.output
    assert json.loads(selected.output)["item"]["item_id"] == item_id

    claimed = _invoke(
        "claim", item_id, "--workspace", workspace, "--db", dsn,
        "--actor", "agent-9", "--role", "editor",
    )
    assert claimed.exit_code == 0, claimed.output
    claim_id = json.loads(claimed.output)["claim_id"]

    written = _invoke(
        "write", item_id, "--workspace", workspace, "--db", dsn,
        "--actor", "agent-9", "--role", "editor", "--claim-id", claim_id,
        "--expected-version", "1", "--title", "PG CLI progress",
    )
    assert written.exit_code == 0, written.output
    assert json.loads(written.output)["title"] == "PG CLI progress"

    released = _invoke(
        "release", item_id, "--claim-id", claim_id, "--workspace", workspace,
        "--db", dsn, "--actor", "agent-9", "--role", "editor",
    )
    assert released.exit_code == 0, released.output
