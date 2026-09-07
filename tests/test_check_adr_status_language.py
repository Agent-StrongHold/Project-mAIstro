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
import json
import runpy
import shutil
import subprocess
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


# --- category 2, the other half: a banner with nothing behind it -------------


def test_a_banner_on_a_document_with_no_superseded_by_fails(sandbox) -> None:
    """The banner claims a replacement the front matter never records.

    ADR-018 is Accepted with no `superseded-by:` at all, so a banner in its
    body names a replacement that nothing downstream of the front matter
    knows about — the inverse half of the banner category.
    """
    path = sandbox.DOC_ROOTS[0] / "ADR-018-task-record-persistence.md"
    path.write_text(path.read_text() + "\n**Superseded by [ADR-082126-f69c](x.md)**\n")

    problems = sandbox.audit()

    assert any(
        p.path.name == "ADR-018-task-record-persistence.md"
        and p.kind == "banner-without-superseded-by"
        for p in problems
    )


# --- display, body-splitting, and the ledger plumbing -----------------------


def test_a_path_outside_root_is_displayed_verbatim(sandbox) -> None:
    """A diagnostic must name the file even when it is not under the corpus —
    crashing on `relative_to` would hide the finding it was reporting."""
    outside = sandbox.ROOT.parent / "elsewhere.md"

    assert sandbox._display(outside) == str(outside)


def test_a_file_without_front_matter_is_all_body(sandbox, tmp_path) -> None:
    """The splitter's contract for a shape `audit` never feeds it today: no
    leading `---` means the whole text is body, not a hunt for a closing
    delimiter that cannot exist."""
    plain = tmp_path / "plain.md"
    plain.write_text("# Just a title\n\nNo front matter here.\n", encoding="utf-8")

    assert sandbox._body_without_front_matter(plain) == "# Just a title\n\nNo front matter here.\n"


def test_a_missing_ledger_means_no_known_exceptions(sandbox) -> None:
    """No bank means nothing may be paid for by the ratchet."""
    sandbox.LEDGER.unlink()

    assert sandbox._load_baseline() == frozenset()


def test_update_banks_the_current_state_and_then_passes(sandbox, capsys) -> None:
    """`--update` is how a reviewed legacy exception is banked: it writes
    exactly what the audit found, and the next ordinary run passes."""
    sandbox.LEDGER.unlink()
    found = {p.identity for p in sandbox.audit()}
    assert found, "the sandbox corpus carries the legacy contradictions"

    assert sandbox.main(["--update"]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert f"{len(found)} known contradiction" in out

    payload = json.loads(sandbox.LEDGER.read_text())
    assert set(payload["known"]) == found

    assert sandbox.main([]) == 0


def test_the_main_guard_exits_zero_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard line itself, executed: `run_name="__main__"` runs the file
    the way the interpreter does, and `sys.exit(main())` is the exit path."""
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert excinfo.value.code == 0


def test_the_script_runs_as_a_script() -> None:
    """The `__main__` guard: CI shells out, so a file that imports but does
    not run would pass every test above and still fail the pipeline."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
