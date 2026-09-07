"""Body status language may not contradict front matter (#387).

ADR-046 spent three weeks with `status: Superseded` in front matter, a
"Superseded by" banner, *and* a body paragraph asserting "The status therefore
stays `Accepted`". Nothing read the body's status claims, so every reader got
a different authority answer. These tests drive each detection category
independently — a checker that only ever saw one category mutate could be
comparing the corpus to itself.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-adr-status-language.py"
LEDGER = ROOT / "quality" / "adr-status-language-baseline.json"


def _gate():
    spec = importlib.util.spec_from_file_location("check_adr_status_language", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A copy of the real corpus, with the baseline pointed at a copy too.

    A copy rather than a synthetic corpus: the check under test is agreement
    between *real* front matter and real body text, and 60 ADRs carry a body
    status line the synthetic case would never reproduce.
    """
    module = _gate()
    adr_dir = tmp_path / "docs" / "adr"
    shutil.copytree(ROOT / "docs" / "adr", adr_dir)
    monkeypatch.setattr(module, "DOC_ROOTS", (adr_dir,))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    # The ledger's identities are repo-relative (docs/adr/...), so the sandbox
    # reproduces the real layout under tmp_path rather than flattening it.
    ledger = tmp_path / "quality" / "adr-status-language-baseline.json"
    ledger.parent.mkdir()
    shutil.copy(LEDGER, ledger)
    monkeypatch.setattr(module, "LEDGER", ledger)
    return module


# --- the committed state -----------------------------------------------------


def test_the_committed_corpus_has_no_new_contradictions() -> None:
    assert _gate().main([]) == 0


def test_adr_046_is_no_longer_a_contradiction() -> None:
    """The document this issue is about, checked by identity.

    Front matter says Superseded, the banner names ADR-082126-f69c, and the
    historical note is framed as history — none of the three detection
    categories may fire on it.
    """
    problems = [p for p in _gate().audit() if "ADR-046" in str(p.path)]

    assert problems == []


# --- category 1: body status lines -------------------------------------------


def test_a_body_status_line_disagreeing_with_front_matter_fails(sandbox) -> None:
    path = next(p for p in sandbox.DOC_ROOTS[0].glob("*.md") if not p.name.startswith("ADR-INDEX"))
    text = path.read_text()
    front_matter_status = _front_matter_status(path)
    other = "Proposed" if front_matter_status != "Proposed" else "Accepted"
    patched, count = _replace_first_status_line(text, other)
    assert count == 1 or "**Status:**" not in text
    if count == 0:
        # No body line to mutate; append one under the title instead.
        patched = text + f"\n**Status:** {other}\n"
    path.write_text(patched)

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


def _front_matter_status(path: Path) -> str:
    for line in path.read_text().splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no status line in {path}")


def _replace_first_status_line(text: str, value: str) -> tuple[str, int]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("**Status:**"):
            replaced = f"**Status:** {value}"
            if line.endswith("  "):
                replaced += "  "
            lines[index] = replaced
            return "\n".join(lines) + "\n", 1
    return text, 0


def test_fixing_a_baselined_body_status_line_requires_pruning(sandbox, capsys) -> None:
    """A fixed contradiction must shrink the ledger in the same change."""
    ledgered = next(
        line.strip().strip('"')
        for line in sandbox.LEDGER.read_text().splitlines()
        if " :: body-status-line" in line
    )
    filename = ledgered.split(" ::")[0].split("/")[-1]
    path = sandbox.DOC_ROOTS[0] / filename
    status = _front_matter_status(path)
    patched, count = _replace_first_status_line(path.read_text(), status)
    assert count == 1, f"{filename} has no body status line to fix"
    path.write_text(patched)

    assert sandbox.main([]) == 1
    assert "no longer found" in capsys.readouterr().out


# --- category 2: replacement banners -----------------------------------------


def test_a_banner_naming_a_different_replacement_fails(sandbox) -> None:
    path = sandbox.DOC_ROOTS[0] / "ADR-046-scheduler.md"
    text = path.read_text().replace(
        "ADR-082126-f69c](ADR-082126-f69c-recurrence-produces-runs.md)",
        "ADR-018](ADR-018-task-record-persistence.md)",
        1,
    )
    path.write_text(text)

    problems = sandbox.audit()

    assert any(
        p.path.name == "ADR-046-scheduler.md" and p.kind == "banner-names-other-replacement"
        for p in problems
    )


# --- category 3: status-asserting prose --------------------------------------


def test_unqualified_status_stays_prose_on_a_superseded_adr_fails(sandbox) -> None:
    """The ADR-046 defect, verbatim shape, on any Superseded document."""
    path = sandbox.DOC_ROOTS[0] / "ADR-046-scheduler.md"
    text = path.read_text().replace(
        "`Accepted` was\nthe status at that time.",
        "the status therefore stays `Accepted` for now.",
        1,
    )
    path.write_text(text)

    problems = sandbox.audit()

    assert any(
        p.path.name == "ADR-046-scheduler.md" and p.kind == "body-asserts-status-stays"
        for p in problems
    )


def test_wrapped_status_stays_prose_still_matches(sandbox) -> None:
    """The phrase that hides across a line break in flowing prose."""
    path = sandbox.DOC_ROOTS[0] / "ADR-046-scheduler.md"
    text = path.read_text().replace(
        "`Accepted` was\nthe status at that time.",
        "the status\nstays `Accepted` for now.",
        1,
    )
    path.write_text(text)

    problems = sandbox.audit()

    assert any(p.kind == "body-asserts-status-stays" for p in problems)


def test_dated_past_status_statements_are_history_not_assertions(sandbox) -> None:
    """Historical rationale is #387's own requirement, so it must not trip.

    "The status was `Accepted` at that time" is a dated fact about then; the
    gate's line is drawn between that and an assertion of continuing status.
    """
    path = sandbox.DOC_ROOTS[0] / "ADR-046-scheduler.md"

    problems = [p for p in sandbox.audit() if p.path == path]

    assert problems == []  # the committed text is the dated-past form


# --- the baseline ratchet -----------------------------------------------------


def test_a_new_body_status_line_contradiction_is_not_absorbed_by_the_baseline(
    sandbox, capsys
) -> None:
    """Per-identity: the 28 legacy entries cannot pay for a 29th."""
    test_a_body_status_line_disagreeing_with_front_matter_fails(sandbox)

    assert sandbox.main([]) == 1
    assert "new body/front-matter status contradiction" in capsys.readouterr().out
