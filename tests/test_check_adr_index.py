"""`ADR-INDEX.md` may not disagree with the ADR corpus (#379).

The index was excluded from registry validation, and 32 of its 82 rows carried
a status the ADR's own front matter contradicted — every one saying `Proposed`
about a decision that had since been Accepted, Deferred, Deprecated or
Superseded. That inverts the signal the index exists to carry.

The issue asks that the tests "mutate both index and front matter
independently", and the reason is worth stating: a checker that only ever sees
the index change could be comparing the index to itself and nobody would know.
So each direction is driven separately below.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-adr-index.py"
INDEX = ROOT / "docs" / "adr" / "ADR-INDEX.md"


def _gate():
    spec = importlib.util.spec_from_file_location("check_adr_index", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A copy of the real corpus this test may edit.

    A copy rather than a hand-built fixture: the thing under test is agreement
    with the *actual* ADR front matter, and a synthetic corpus would prove only
    that the parser agrees with itself.
    """
    module = _gate()
    adr_dir = tmp_path / "adr"
    shutil.copytree(ROOT / "docs" / "adr", adr_dir)
    monkeypatch.setattr(module, "ADR_DIR", adr_dir)
    monkeypatch.setattr(module, "INDEX", adr_dir / "ADR-INDEX.md")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


# --- the committed state -----------------------------------------------------


def test_the_committed_index_agrees_with_the_corpus() -> None:
    assert _gate().main([]) == 0


def test_every_indexed_adr_exists() -> None:
    _problems, structural = _gate().audit()

    assert structural == []


# --- mutate the index --------------------------------------------------------


def test_a_stale_status_in_the_index_fails(sandbox, capsys: pytest.CaptureFixture[str]) -> None:
    """The 32 rows this issue is about, reproduced deliberately."""
    index = sandbox.INDEX
    text = index.read_text().replace(
        "| ADR-019 | v4 | Accepted |", "| ADR-019 | v4 | Proposed |", 1
    )
    index.write_text(text)

    assert sandbox.main([]) == 1
    assert "ADR-019" in capsys.readouterr().out


def test_a_stale_accepted_date_in_the_index_fails(sandbox) -> None:
    index = sandbox.INDEX
    text = index.read_text().replace(
        "| ADR-019 | v4 | Accepted | 2026-05-06 | 2026-05-06 |",
        "| ADR-019 | v4 | Accepted | 2026-05-06 | — |",
        1,
    )
    index.write_text(text)

    problems, _structural = sandbox.audit()

    assert [p.field_name for p in problems] == ["accepted"]


def test_a_duplicate_row_fails(sandbox, capsys: pytest.CaptureFixture[str]) -> None:
    index = sandbox.INDEX
    lines = index.read_text().splitlines()
    row = next(line for line in lines if line.startswith("| ADR-019 |"))
    index.write_text("\n".join([*lines, row]) + "\n")

    assert sandbox.main([]) == 1
    assert "more than once" in capsys.readouterr().out


def test_a_row_for_an_adr_that_does_not_exist_fails(sandbox, capsys) -> None:
    index = sandbox.INDEX
    lines = index.read_text().splitlines()
    lines.append("| ADR-999 | v1 | Accepted | 2026-01-01 | 2026-01-01 | — | Invented. |")
    index.write_text("\n".join(lines) + "\n")

    assert sandbox.main([]) == 1
    assert "no ADR file carries that id" in capsys.readouterr().out


# --- mutate the front matter -------------------------------------------------


def test_a_status_change_in_front_matter_fails_the_index(sandbox) -> None:
    """The other direction, and the one that actually happened: the ADR moves
    on and the index is left behind. A checker that only saw index edits could
    be comparing the index to itself."""
    adr = next(sandbox.ADR_DIR.glob("ADR-019-*.md"))
    adr.write_text(adr.read_text().replace("status: Accepted", "status: Deprecated", 1))

    problems, _structural = sandbox.audit()

    assert any(p.adr_id == "ADR-019" and p.field_name == "status" for p in problems)


def test_a_created_date_change_in_front_matter_fails_the_index(sandbox) -> None:
    adr = next(sandbox.ADR_DIR.glob("ADR-019-*.md"))
    adr.write_text(adr.read_text().replace("created: 2026-05-06", "created: 2026-05-07", 1))

    problems, _structural = sandbox.audit()

    assert any(p.adr_id == "ADR-019" and p.field_name == "created" for p in problems)


# --- the fix -----------------------------------------------------------------


def test_fix_reconciles_the_index_to_the_corpus(sandbox) -> None:
    index = sandbox.INDEX
    index.write_text(
        index.read_text().replace("| ADR-019 | v4 | Accepted |", "| ADR-019 | v4 | Proposed |", 1)
    )

    assert sandbox.main(["--fix"]) == 0
    assert sandbox.main([]) == 0


def test_fix_leaves_the_reviewed_columns_alone(sandbox) -> None:
    """ "Preserves reviewed annotations outside generated regions": `Summary` is
    prose, and `Ver`/`Last Modified` come from git rather than front matter.
    Rewriting them from a source that does not hold them would destroy them."""
    import re

    index = sandbox.INDEX
    row = re.compile(r"^\|\s*(ADR-[A-Za-z0-9-]+)\s*\|([^|]*)\|[^|]*\|[^|]*\|[^|]*\|(.*)$")
    before = {
        m.group(1): (m.group(2), m.group(3))
        for line in index.read_text().splitlines()
        if (m := row.match(line))
    }
    index.write_text(
        index.read_text().replace("| ADR-019 | v4 | Accepted |", "| ADR-019 | v4 | Proposed |", 1)
    )

    sandbox.main(["--fix"])

    after = {
        m.group(1): (m.group(2), m.group(3))
        for line in index.read_text().splitlines()
        if (m := row.match(line))
    }
    assert before == after
    assert len(after) == 82


def test_fix_is_idempotent(sandbox) -> None:
    sandbox.main(["--fix"])
    once = sandbox.INDEX.read_text()

    sandbox.main(["--fix"])

    assert sandbox.INDEX.read_text() == once


# --- the accepted-date proxy the legend documents ----------------------------


def test_a_ratified_adr_without_an_accepted_field_gets_the_created_proxy(sandbox) -> None:
    """The legend's `†`. Dropping it would make an Accepted ADR look unratified;
    inventing a date would be worse."""
    module = sandbox

    class _Stub:
        accepted = None
        created = "2026-01-01"

        class status:
            value = "Accepted"

    assert module._expected_accepted(_Stub()) == f"2026-01-01{module.PROXY}"


def test_an_unratified_adr_shows_no_accepted_date(sandbox) -> None:
    class _Stub:
        accepted = None
        created = "2026-01-01"

        class status:
            value = "Proposed"

    assert sandbox._expected_accepted(_Stub()) == sandbox.ABSENT


def test_the_gate_runs_as_a_script_too() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
