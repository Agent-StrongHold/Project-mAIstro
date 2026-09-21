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
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

#: ADR-092126-a28a declares a behavioral contract — a body status line is a
#: finding whatever it says — and names this suite as its evidence.
pytestmark = [pytest.mark.contract("behavioral")]

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

    Still a copy rather than a synthetic corpus, though the reason has moved.
    It used to be that 63 ADRs carried a body status line a synthetic case
    would never reproduce; ADR-092126-a28a removed all of them. What the real
    corpus now provides is the *absence* — these tests assert that no document
    carries one, and that a document the gate skips cannot be silently chosen
    to carry the one they introduce. Categories 2 and 3 still read ADR-046's
    real banner and real prose.
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


@pytest.mark.ac("ADR-092126-a28a/AC-1")
def test_the_corpus_carries_no_body_status_line_at_all(sandbox) -> None:
    """The retirement itself, asserted against the real corpus.

    ADR-092126-a28a removed the line from all 83 documents that had one. This
    is the test that fails if any comes back — including via a merge that
    reinstates an old revision, which no per-document test would notice.
    """
    offenders = [
        path.name
        for path in sorted(sandbox.DOC_ROOTS[0].glob("*.md"))
        if _BODY_STATUS_LINE_RE.search(path.read_text())
    ]

    assert offenders == []


@pytest.mark.ac("ADR-092126-a28a/AC-2")
def test_a_body_status_line_fails_even_when_it_agrees(sandbox) -> None:
    """Absence, not agreement — the rule that makes the retirement durable.

    This is the case the old agreement check let through, and the one that
    restarts the drift: a line that copies front matter correctly today is a
    second place to edit tomorrow. #387's whole history is that copy going
    stale.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    path.write_text(_with_status_line(path.read_text(), _front_matter_status(path)))

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


@pytest.mark.ac("ADR-092126-a28a/AC-3")
def test_a_disagreeing_body_status_line_still_fails(sandbox) -> None:
    """The original #387 shape keeps failing under the retirement rule."""
    path = _an_adr(sandbox.DOC_ROOTS[0])
    other = "Proposed" if _front_matter_status(path) != "Proposed" else "Accepted"
    path.write_text(_with_status_line(path.read_text(), other))

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


@pytest.mark.ac("ADR-092126-a28a/AC-3")
def test_a_list_item_status_line_is_not_exempt(sandbox) -> None:
    """`- **Status:** X` is the same declaration as the bare `**Status:** X`.

    The gate matched only the bare spelling for a year, so the 3 ADRs and 20
    specs writing the list-item form were exempt from this category outright —
    the *form* of the line, not its content, decided whether it could be seen.
    Retirement has to cover both spellings or it just relocates the habit.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    patched = _with_status_line(path.read_text(), "Accepted", bullet="- ")
    assert "\n- **Status:**" in patched, "the mutation must write the list form"
    path.write_text(patched)

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


@pytest.mark.ac("ADR-092126-a28a/AC-3")
def test_a_status_line_dressed_up_with_trailing_prose_is_still_caught(sandbox) -> None:
    """Decoration is not an exemption.

    This started as a question about *parsing*: under the agreement check,
    `**Status:** Accepted — ratified 2026-01-01` read as claiming the whole
    string, so it failed against a front matter saying `Accepted`. That was
    incidental to the regex rather than stated intent, and worth pinning.

    Retirement changes what is at stake. There is no claim to parse any more,
    so the question is no longer "what does this line say" but "is a qualified
    line still a line" — the evasion route that would otherwise let the
    duplication back in wearing a hat. It is, and this is the test that says
    so.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    status = _front_matter_status(path)
    path.write_text(_with_status_line(path.read_text(), f"{status} — ratified 2026-01-01"))

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


@pytest.mark.ac("ADR-092126-a28a/AC-3")
def test_an_empty_status_line_is_still_a_retired_line(sandbox) -> None:
    """`**Status:**` with no value is reported too.

    Under the old agreement check this was deliberately skipped — an empty
    line claimed no status to disagree with, and comparing `None` would have
    raised. Retirement removes that subtlety along with the branch: the line
    is the finding, so there is no value to parse and nothing to skip.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    path.write_text(_with_status_line(path.read_text(), ""))

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


def _an_adr(root: Path) -> Path:
    """A deterministic ADR that the gate actually audits.

    Sorted, not `Path.glob` order, which is `os.scandir` order and varies by
    filesystem — the defect that made two of these tests pass in CI and fail
    everywhere else.

    "That the gate audits" is the other half, and it is not pedantry. Sorted
    order puts `ADR-000-template.md` first, and the template's front matter
    does not parse, so `_audit_file` returns early and a status line written
    there is never seen. That is the same trap in a new costume: CI's old
    iteration order happened to yield the template too, which is exactly why
    the original tests passed while proving nothing. Selecting through the
    validator the gate itself uses means a document it skips cannot be chosen
    silently.
    """
    from maistro_registry.validator import validate_file  # the gate puts this on sys.path

    chosen = next(
        p
        for p in sorted(root.glob("*.md"))
        if not p.name.startswith("ADR-INDEX") and validate_file(p).front_matter is not None
    )
    assert not _BODY_STATUS_LINE_RE.search(chosen.read_text()), (
        f"{chosen.name} already carries a body status line; these tests must introduce the only one"
    )
    return chosen


def _front_matter_status(path: Path) -> str:
    for line in path.read_text().splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no status line in {path}")


#: A body status declaration in either spelling: bare, or as a Markdown list
#: item. Multiline so it can be searched against a whole document.
_BODY_STATUS_LINE_RE = re.compile(r"^([-*+]\s+)?\*\*Status:\*\*.*$", re.M)


def _with_status_line(text: str, value: str, *, bullet: str = "") -> str:
    """Put a body status line under the document's title.

    Written below the `# ` heading rather than appended, which is where the 83
    retired lines lived — a gate that only noticed one at the end of a file
    would miss every real occurrence.
    """
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("# "))
    lines.insert(index + 1, f"{bullet}**Status:** {value}")
    return "\n".join(lines) + "\n"


def test_fixing_a_banked_body_status_line_requires_pruning(sandbox, capsys) -> None:
    """A fixed finding must shrink the ledger in the same change.

    Introduced and banked here rather than borrowed from the committed ledger.
    It used to read whichever identity the real ledger happened to carry, which
    made the test a hostage of the corpus's legacy debt: draining that ledger
    to zero left the `next(...)` with nothing to find, and the ratchet's
    central rule untested exactly when the corpus was finally clean.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    original = path.read_text()
    path.write_text(_with_status_line(original, _front_matter_status(path)))
    assert sandbox.main(["--update"]) == 0, "the finding is banked first"
    capsys.readouterr()

    path.write_text(original)

    assert sandbox.main([]) == 1
    assert "no longer found" in capsys.readouterr().out


# --- category 2: replacement banners -----------------------------------------


@pytest.mark.ac("ADR-092126-a28a/AC-4")
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


@pytest.mark.ac("ADR-092126-a28a/AC-4")
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


@pytest.mark.ac("ADR-092126-a28a/AC-4")
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


def test_a_reintroduced_body_status_line_is_not_absorbed_by_the_baseline(sandbox, capsys) -> None:
    """The ledger is empty, so a reintroduced line has nothing to hide behind.

    Per-identity was what stopped the 28 legacy entries paying for a 29th.
    With the ledger drained it is simpler still: every finding is new, and the
    run that reports one exits non-zero.
    """
    test_a_body_status_line_fails_even_when_it_agrees(sandbox)

    assert sandbox.main([]) == 1
    assert "new body/front-matter status contradiction" in capsys.readouterr().out


# --- category 2, the other half: a banner with nothing behind it -------------


@pytest.mark.ac("ADR-092126-a28a/AC-4")
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
    exactly what the audit found, and the next ordinary run passes.

    The state to bank is introduced here. Asserting that the *corpus* carries
    findings made a clean corpus fail this test, which inverts what the suite
    is for — the gate's banking behavior is the subject, not how much legacy
    debt happens to be outstanding.
    """
    path = _an_adr(sandbox.DOC_ROOTS[0])
    path.write_text(_with_status_line(path.read_text(), _front_matter_status(path)))
    sandbox.LEDGER.unlink()
    found = {p.identity for p in sandbox.audit()}
    assert found, "the introduced finding is what --update must bank"

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
