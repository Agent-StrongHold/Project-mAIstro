"""Tests for the backlog authority mode of the consistency gate (#102).

After the cutover, ``BACKLOG.md`` is generated documentation and the database
is the authority — so the gate's job changes: the file must carry the
generated banner and match the recorded export digest, making a direct hand
edit fail CI instead of silently diverging. Before the cutover (or with no
marker at all) nothing changes: the hand-maintained file is audited exactly
as #30 defined it. The marker lives in ``quality/backlog-authority.json``;
these tests point the gate at a temp copy so the repository state is never
mutated.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-backlog-consistency.py"

GENERATED_BANNER = (
    "<!-- GENERATED from the backlog database (authority revision 4). "
    "Direct edits are not authoritative. -->"
)

MODULE_NAME = "check_backlog_consistency_gate_test"


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def marker(gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp marker file the gate reads, without touching the repo's."""
    (tmp_path / "quality").mkdir()
    path = tmp_path / "quality" / "backlog-authority.json"
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    return path


def _write_marker(path: Path, authority: str, digest: str | None, revision: int = 4) -> None:
    path.write_text(
        json.dumps(
            {
                "authority": authority,
                "revision": revision,
                "updated_at": None,
                "export_sha256": digest,
            }
        )
    )


def test_the_shipped_marker_is_the_pre_cutover_default() -> None:
    """The repository ships pre-cutover: markdown authority, revision 0."""
    record = json.loads((ROOT / "quality" / "backlog-authority.json").read_text())
    assert record["authority"] == "markdown"
    assert record["revision"] == 0
    assert record["export_sha256"] is None


def test_markdown_authority_ignores_banner_and_digest(gate, marker) -> None:
    text = (ROOT / "BACKLOG.md").read_text()
    _write_marker(marker, "markdown", "0" * 64)
    assert gate._authority_failures(text, gate._authority_record()) == []


def test_generated_file_matching_the_digest_passes(gate, marker) -> None:
    text = GENERATED_BANNER + "\n" + (ROOT / "BACKLOG.md").read_text()
    _write_marker(marker, "db", hashlib.sha256(text.encode()).hexdigest())
    assert gate._authority_failures(text, gate._authority_record()) == []


def test_a_direct_edit_under_db_authority_fails(gate, marker) -> None:
    """The heart of the cutover: hand edits to the generated file are not
    authoritative — they fail the gate until regenerated or reverted."""
    original = (ROOT / "BACKLOG.md").read_text()
    text = GENERATED_BANNER + "\n" + original
    _write_marker(marker, "db", hashlib.sha256(text.encode()).hexdigest())

    tampered = text.replace("# Backlog", "# Backlog\n- sneaky hand edit", 1)
    failures = gate._authority_failures(tampered, gate._authority_record())
    assert any("not authoritative" in failure for failure in failures)


def test_a_generated_file_without_the_banner_fails(gate, marker) -> None:
    text = (ROOT / "BACKLOG.md").read_text()
    _write_marker(marker, "db", hashlib.sha256(text.encode()).hexdigest())
    failures = gate._authority_failures(text, gate._authority_record())
    assert any("does not carry the generated banner" in failure for failure in failures)


def test_a_missing_marker_defaults_to_markdown(gate, marker) -> None:
    """No marker file at all: pre-cutover behavior, never a flip."""
    text = (ROOT / "BACKLOG.md").read_text()
    assert not marker.exists()  # the fixture only prepares the path
    assert gate._authority_failures(text, gate._authority_record()) == []
