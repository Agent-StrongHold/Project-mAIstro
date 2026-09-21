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
from collections.abc import Callable, Iterable
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
    between *real* front matter and real body text, and 63 ADRs carry a body
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
    path = _an_adr_whose_body_status_agrees(sandbox.DOC_ROOTS[0])
    front_matter_status = _front_matter_status(path)
    other = "Proposed" if front_matter_status != "Proposed" else "Accepted"
    patched, count = _replace_first_status_line(path.read_text(), other)
    assert count == 1, f"{path.name} lost the body status line its selection promised"
    path.write_text(patched)

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


def test_the_mutated_adr_is_chosen_the_same_way_whatever_the_filesystem_yields(sandbox) -> None:
    """Every test that mutates an ADR must pick the same one on any checkout.

    `Path.glob` yields in `os.scandir` order, which varies by filesystem. When
    the corpus was walked raw, the document the category-1 tests mutated was
    whichever one the checkout happened to hand over first — and on a
    filesystem yielding one of the three list-form ADRs, the bare-form-only
    rewrite helper matched nothing, so both
    `test_a_body_status_line_disagreeing_with_front_matter_fails` and the
    baseline-ratchet test that calls it failed. CI was green only because its
    order yielded `ADR-000-template.md`, which carries no body status line at
    all: the escape clause fired and an appended synthetic line was tested
    instead of the corpus.

    So the selection is by property, not position: any order must produce a
    document that satisfies both requirements the mutation makes of it.
    """
    forward = _an_adr_whose_body_status_agrees(sandbox.DOC_ROOTS[0])
    backward = _an_adr_whose_body_status_agrees(
        sandbox.DOC_ROOTS[0], order=lambda paths: sorted(paths, reverse=True)
    )

    assert forward == _an_adr_whose_body_status_agrees(sandbox.DOC_ROOTS[0])
    assert forward != backward, "a corpus of one would not prove order-independence"
    for chosen in (forward, backward):
        assert _body_status_claim(chosen.read_text()) == _front_matter_status(chosen)
        assert _replace_first_status_line(chosen.read_text(), "Proposed")[1] == 1


def _an_adr_whose_body_status_agrees(
    root: Path, *, order: Callable[[Iterable[Path]], list[Path]] = sorted
) -> Path:
    """An ADR carrying a body status line that agrees with its front matter.

    Both properties are what the mutation tests need, so both are selected for
    rather than hoped for. A **body status line** — bare or in the list-item
    form (`- **Status:** X`) three ADRs use — is what there is to mutate.
    **Agreement today** is what makes the mutation a *new* contradiction:
    mutating a site the baseline already records would reuse that entry's
    identity, and the ratchet would rightly stay silent.

    `order` exists so a test can prove the choice does not depend on the
    filesystem's iteration order. A corpus that stops carrying a qualifying
    ADR raises here, loudly, instead of quietly degrading the tests into
    proving nothing.
    """
    for path in order(p for p in root.glob("*.md") if not p.name.startswith("ADR-INDEX")):
        text = path.read_text()
        claim = _body_status_claim(text)
        if claim is not None and claim == _front_matter_status(path):
            return path
    raise AssertionError(f"no ADR under {root} carries a body status line agreeing with its own")


def _front_matter_status(path: Path) -> str:
    for line in path.read_text().splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no status line in {path}")


#: A body status declaration in either form the corpus writes: bare, or as a
#: Markdown list item. Group 1 is the list bullet (so a rewrite can preserve
#: it), group 2 the claim.
_BODY_STATUS_LINE_RE = re.compile(r"^([-*+]\s+)?\*\*Status:\*\*(.*)$")


def _body_status_claim(text: str) -> str | None:
    """What the first body status line claims, or `None` if there is none."""
    for line in text.splitlines():
        match = _BODY_STATUS_LINE_RE.match(line)
        if match is not None:
            return match[2].strip().strip("*").strip() or None
    return None


def _replace_first_status_line(
    text: str, value: str, *, bullet: str | None = None
) -> tuple[str, int]:
    """Rewrite the first body status line, keeping the form it was written in.

    `bullet` overrides that form, so a test can write the list-item spelling
    onto a document that used the bare one.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _BODY_STATUS_LINE_RE.match(line)
        if match is None:
            continue
        replaced = f"{bullet if bullet is not None else match[1] or ''}**Status:** {value}"
        if line.endswith("  "):
            replaced += "  "
        lines[index] = replaced
        return "\n".join(lines) + "\n", 1
    return text, 0


def test_a_list_item_status_line_is_not_exempt(sandbox) -> None:
    """`- **Status:** X` is the same declaration as the bare `**Status:** X`.

    The gate matched only the bare spelling, so the 3 ADRs and 20 specs that
    write the line as a Markdown list item were exempt from this category
    outright — the *form* of the line, not its content, decided whether a
    contradiction could be seen at all.
    """
    path = _an_adr_whose_body_status_agrees(sandbox.DOC_ROOTS[0])
    other = "Proposed" if _front_matter_status(path) != "Proposed" else "Accepted"
    patched, count = _replace_first_status_line(path.read_text(), other, bullet="- ")
    assert count == 1
    assert "\n- **Status:**" in patched, "the mutation must write the list form"
    path.write_text(patched)

    problems = sandbox.audit()

    assert any(p.path == path and p.kind == "body-status-line" for p in problems)


def test_a_status_line_with_nothing_after_it_declares_nothing(sandbox) -> None:
    """An empty `**Status:**` is malformed markup, not a claim of any status.

    Reporting it would name a status the document never asserts, and the
    comparison itself would raise on the `None` rather than report the finding
    it was in the middle of making. Driven through `audit()`, not the helper
    alone: the guard lives in the audit loop, and a unit test of the parser
    leaves the branch that consumes it unexercised.
    """
    path = _an_adr_whose_body_status_agrees(sandbox.DOC_ROOTS[0])
    patched, count = _replace_first_status_line(path.read_text(), "")
    assert count == 1

    path.write_text(patched)

    assert not any(p.path == path and p.kind == "body-status-line" for p in sandbox.audit())


def test_the_claim_is_the_whole_value_not_its_first_word(sandbox) -> None:
    """The vocabulary has multi-word members, and the markup is presentation.

    Reading only the first word reported `AC` against a front matter saying
    `AC Defined` — a contradiction that was not one, on the single document
    whose list-item line already agreed.
    """
    assert sandbox._claimed_status(" AC Defined") == "AC Defined"
    assert sandbox._claimed_status(" **Accepted**  ") == "Accepted"
    assert sandbox._claimed_status("   ") is None


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
