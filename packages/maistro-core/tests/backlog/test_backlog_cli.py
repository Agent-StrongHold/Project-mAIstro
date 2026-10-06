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

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from maistro.cli._backlog import GENERATED_BANNER, app

runner = CliRunner()

WORKSPACE = "root-backlog"

DOCUMENT = """# Backlog

## Alpha

**[a-001] First item — Open — M1**

**[a-000] Done seed — Done**

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
