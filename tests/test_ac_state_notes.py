"""Per-branch AC-state notes and the fold — SPEC-082926-25a2 / ADR-082926-25a2 (#585).

The claim this suite has to settle is not "the fold computes a number". It is
that **two branches cut from the same base do not collide**, which is a claim
about git, not about arithmetic. So the collision tests build real repositories
with real branches and really merge them, rather than asserting over a
dictionary and hoping.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ac_state_notes.py"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("ac_state_notes_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


notes_mod = _module()


def _note(name: str, **counters: float) -> Any:
    return notes_mod.Note(name=name, branch=name, measured_with_tests=True, counters=dict(counters))


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repository with a develop branch and the notes directory seeded."""
    root = tmp_path / "repo"
    (root / "quality" / "ac-state-notes").mkdir(parents=True)
    _git("init", "-q", "-b", "develop", cwd=tmp_path) if False else None
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], check=True, timeout=60)
    _git("config", "user.email", "t@example.com", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    (root / "quality" / "ac-state-notes" / "_baseline.json").write_text(
        json.dumps(
            {
                "branch": None,
                "measured_with_tests": True,
                "counters": {"design_coverage": 20.0, "specs_awaiting_retrofit": 139},
            },
            indent=2,
        )
        + "\n"
    )
    _git("add", "-A", cwd=root)
    _git("commit", "-qm", "seed", cwd=root)
    return root


def _bank_on_branch(repo: Path, branch: str, **counters: float) -> None:
    _git("checkout", "-q", "-b", branch, "develop", cwd=repo)
    notes_mod.write_note(
        dict(counters),
        branch=branch,
        measured_with_tests=True,
        notes_dir=repo / "quality" / "ac-state-notes",
        root=repo,
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", f"bank {branch}", cwd=repo)


# --- AC-1: two branches from one base do not collide --------------------


@pytest.mark.ac("SPEC-082926-25a2/AC-1")
def test_two_branches_raising_coverage_do_not_conflict(repo: Path) -> None:
    _bank_on_branch(repo, "feature-a", design_coverage=21.0, specs_awaiting_retrofit=138)
    _bank_on_branch(repo, "feature-b", design_coverage=21.5, specs_awaiting_retrofit=137)

    _git("checkout", "-q", "develop", cwd=repo)
    _git("merge", "-q", "--no-edit", "feature-a", cwd=repo)
    merged = subprocess.run(
        ["git", "merge", "--no-edit", "feature-b"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert "CONFLICT" not in merged.stdout


@pytest.mark.ac("SPEC-082926-25a2/AC-1")
def test_the_shared_ceiling_file_would_have_conflicted(repo: Path) -> None:
    # The control. Without it "no conflict" proves nothing — it could just mean
    # the two branches wrote identical bytes.
    shared = repo / "quality" / "ac-state-ceilings.json"
    for branch, value in (("shared-a", 21.0), ("shared-b", 21.5)):
        _git("checkout", "-q", "-b", branch, "develop", cwd=repo)
        shared.write_text(json.dumps({"ceilings": {"design_coverage": value}}, indent=2) + "\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "-qm", f"bank {branch}", cwd=repo)

    _git("checkout", "-q", "develop", cwd=repo)
    _git("merge", "-q", "--no-edit", "shared-a", cwd=repo)
    merged = subprocess.run(
        ["git", "merge", "--no-edit", "shared-b"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert merged.returncode != 0
    assert "CONFLICT" in merged.stdout


# --- AC-2: the fold keeps both contributions ----------------------------


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_after_both_merge_the_fold_reflects_both(repo: Path) -> None:
    _bank_on_branch(repo, "feature-a", design_coverage=21.0, specs_awaiting_retrofit=138)
    _bank_on_branch(repo, "feature-b", design_coverage=21.5, specs_awaiting_retrofit=137)
    _git("checkout", "-q", "develop", cwd=repo)
    _git("merge", "-q", "--no-edit", "feature-a", cwd=repo)
    _git("merge", "-q", "--no-edit", "feature-b", cwd=repo)

    notes, _origin, _sha = notes_mod.load_notes(
        notes_dir=repo / "quality" / "ac-state-notes", root=repo
    )
    folded = notes_mod.fold(notes)

    assert folded["design_coverage"] == 21.5
    assert folded["specs_awaiting_retrofit"] == 137
    assert len(notes) == 3


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_a_floored_counter_folds_by_maximum() -> None:
    assert notes_mod.fold([_note("a", design_coverage=20.0), _note("b", design_coverage=22.5)]) == {
        "design_coverage": 22.5
    }


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_a_ratcheted_counter_folds_by_minimum() -> None:
    assert notes_mod.fold(
        [_note("a", specs_awaiting_retrofit=139), _note("b", specs_awaiting_retrofit=131)]
    ) == {"specs_awaiting_retrofit": 131}


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_counters_fold_independently_of_each_other() -> None:
    # A note holding the best coverage says nothing about the debt counters, and
    # folding whole notes would let one strong note drag every bound with it.
    folded = notes_mod.fold(
        [
            _note("a", design_coverage=25.0, specs_awaiting_retrofit=139),
            _note("b", design_coverage=20.0, specs_awaiting_retrofit=100),
        ]
    )

    assert folded == {"design_coverage": 25.0, "specs_awaiting_retrofit": 100}


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_a_counter_only_one_note_carries_still_bounds() -> None:
    folded = notes_mod.fold([_note("a", design_coverage=21.0), _note("b", gherkin_parse_errors=0)])

    assert folded == {"design_coverage": 21.0, "gherkin_parse_errors": 0}


# --- AC-3: a regression is still refused --------------------------------


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_a_candidates_own_note_does_not_enter_the_bound(repo: Path) -> None:
    """The self-approval hole #534 closed, applied to this ledger.

    The candidate writes a weaker note and commits it. The fold is read at the
    base, so the weaker value is invisible to the comparison that judges it.
    """
    _git("checkout", "-q", "-b", "launderer", "develop", cwd=repo)
    notes_mod.write_note(
        {"design_coverage": 1.0},
        branch="launderer",
        measured_with_tests=True,
        notes_dir=repo / "quality" / "ac-state-notes",
        root=repo,
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "weaken", cwd=repo)

    bound = notes_mod.bounds(
        base="develop", notes_dir=repo / "quality" / "ac-state-notes", root=repo
    )

    assert bound.counters["design_coverage"] == 20.0
    assert "launderer.json" not in bound.notes


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_editing_another_branchs_merged_note_does_not_move_the_bound(repo: Path) -> None:
    _git("checkout", "-q", "-b", "editor", "develop", cwd=repo)
    (repo / "quality" / "ac-state-notes" / "_baseline.json").write_text(
        json.dumps(
            {
                "branch": None,
                "measured_with_tests": True,
                "counters": {"design_coverage": 1.0, "specs_awaiting_retrofit": 999},
            },
            indent=2,
        )
        + "\n"
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "rewrite someone else's note", cwd=repo)

    bound = notes_mod.bounds(
        base="develop", notes_dir=repo / "quality" / "ac-state-notes", root=repo
    )

    assert bound.counters == {"design_coverage": 20.0, "specs_awaiting_retrofit": 139}


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_deleting_every_note_does_not_empty_the_bound(repo: Path) -> None:
    _git("checkout", "-q", "-b", "deleter", "develop", cwd=repo)
    (repo / "quality" / "ac-state-notes" / "_baseline.json").unlink()
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "delete the ledger", cwd=repo)

    bound = notes_mod.bounds(
        base="develop", notes_dir=repo / "quality" / "ac-state-notes", root=repo
    )

    assert bound.empty is False
    assert bound.counters["design_coverage"] == 20.0


# --- AC-4: staleness is defined ----------------------------------------


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_a_dominated_note_is_stale() -> None:
    strong = _note("strong", design_coverage=25.0, specs_awaiting_retrofit=100)
    weak = _note("weak", design_coverage=21.0, specs_awaiting_retrofit=130)

    assert [note.name for note in notes_mod.stale([strong, weak])] == ["weak"]


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_a_note_holding_one_best_value_is_not_stale() -> None:
    a = _note("a", design_coverage=25.0, specs_awaiting_retrofit=130)
    b = _note("b", design_coverage=21.0, specs_awaiting_retrofit=100)

    assert notes_mod.stale([a, b]) == []


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_removing_the_stale_notes_leaves_the_bound_unchanged() -> None:
    notes = [
        _note("strong", design_coverage=25.0, specs_awaiting_retrofit=100),
        _note("weak", design_coverage=21.0, specs_awaiting_retrofit=130),
        _note("weaker", design_coverage=20.5, specs_awaiting_retrofit=131),
    ]
    before = notes_mod.fold(notes)

    dropped = {note.name for note in notes_mod.stale(notes)}
    after = notes_mod.fold([note for note in notes if note.name not in dropped])

    assert dropped == {"weak", "weaker"}
    assert after == before


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_duplicate_notes_do_not_both_vanish() -> None:
    # Each is dominated by the other. Dropping both would loosen the bound, so
    # staleness is computed against the survivors, one note at a time.
    twins = [_note("a", design_coverage=21.0), _note("b", design_coverage=21.0)]

    dropped = notes_mod.stale(twins)

    assert len(dropped) == 1
    assert notes_mod.fold([note for note in twins if note is not dropped[0]]) == {
        "design_coverage": 21.0
    }


# --- Notes are data, and malformed data is a non-passing state ----------


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ('{"measured_with_tests": true, "counters": {}}', "records no counters"),
        ('{"measured_with_tests": true}', "records no counters"),
        ('{"counters": {"design_coverage": 1}}', "whether it was measured"),
        (
            '{"measured_with_tests": true, "counters": {"invented": 1}}',
            "does not know",
        ),
        (
            '{"measured_with_tests": true, "counters": {"design_coverage": "high"}}',
            "non-numeric",
        ),
        (
            '{"measured_with_tests": true, "counters": {"design_coverage": true}}',
            "non-numeric",
        ),
    ],
)
def test_a_malformed_note_is_refused_not_skipped(text: str, match: str) -> None:
    with pytest.raises(notes_mod.AcStateNoteError, match=match):
        notes_mod.Note.parse("bad.json", text)


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_the_bound_describes_where_it_came_from(repo: Path) -> None:
    # On a branch with a commit of its own: `develop` resolving to HEAD with a
    # clean worktree is the self-referential baseline `ratchet_provenance`
    # refuses, and refusing it is right — a bound read from the commit under
    # judgement could not fail.
    _bank_on_branch(repo, "describer", design_coverage=21.0)

    bound = notes_mod.bounds(
        base="develop", notes_dir=repo / "quality" / "ac-state-notes", root=repo
    )

    described = bound.describe()

    assert "_baseline.json" in described
    assert bound.base_sha is not None and bound.base_sha[:12] in described


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_an_empty_bound_says_so_rather_than_reading_as_zero() -> None:
    empty = notes_mod.Bounds(counters={}, notes=(), origin="empty", base_sha=None)

    assert empty.empty is True
    assert "nothing is bounded yet" in empty.describe()


@pytest.mark.ac("SPEC-082926-25a2/AC-1")
def test_a_branch_name_becomes_a_filename() -> None:
    assert notes_mod.slug("claude/issue-585-ac-state") == "claude-issue-585-ac-state"
    assert notes_mod.slug("///") == "detached"


@pytest.mark.ac("SPEC-082926-25a2/AC-2")
def test_a_written_note_round_trips(tmp_path: Path) -> None:
    path = notes_mod.write_note(
        {"design_coverage": 21.5, "specs_awaiting_retrofit": 138, "not_a_counter": 1},
        branch="feature/x",
        measured_with_tests=True,
        notes_dir=tmp_path,
    )

    note = notes_mod.Note.parse(path.name, path.read_text())

    assert note.branch == "feature/x"
    assert note.counters == {"specs_awaiting_retrofit": 138, "design_coverage": 21.5}


@pytest.mark.ac("SPEC-082926-25a2/AC-5")
def test_the_measurement_file_is_not_tracked() -> None:
    """AC-5: the per-decision report is generated, not committed."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "quality/ac-state.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert tracked.returncode != 0, "quality/ac-state.json is still tracked"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "quality/ac-state.json"],
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert ignored.returncode == 0, "quality/ac-state.json is not ignored"


@pytest.mark.ac("SPEC-082926-25a2/AC-5")
def test_the_retired_ceiling_file_is_gone() -> None:
    assert not (ROOT / "quality" / "ac-state-ceilings.json").exists()
    assert (ROOT / "quality" / "ac-state-notes" / "_baseline.json").is_file()


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_a_self_referential_base_is_refused_rather_than_folded(repo: Path) -> None:
    """`develop` resolving to HEAD with a clean tree cannot be a trusted oracle.

    Inherited from `ratchet_provenance` (#534) and asserted here because the
    fold is a second consumer of that guarantee: a directory listed out of the
    commit under judgement would be the candidate approving itself, one file at
    a time instead of one line at a time.
    """
    provenance = notes_mod.provenance()

    with pytest.raises(provenance.SelfReferentialBaseline):
        notes_mod.bounds(base="develop", notes_dir=repo / "quality" / "ac-state-notes", root=repo)


# --- The two oracles: a regression and slack answer to different files ---


def _gate() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_ac_state_for_notes", ROOT / "scripts" / "check-ac-state.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BASE_COUNTERS: dict[str, float] = {
    "completion_claims_contradicted": 0,
    "completion_claims_unverifiable": 0,
    "specs_awaiting_retrofit": 139,
    "markers_without_criterion": 2,
    "criteria_claimed_but_unproven": 0,
    "scenarios_without_ac_tag": 0,
    "gherkin_parse_errors": 0,
    "specs_implementing_nothing": 76,
    "adrs_without_implementing_spec": 33,
    "specs_declaring_no_criteria": 7,
    "design_coverage": 20.0,
}


@pytest.fixture
def gate_on(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The gate pointed at a throwaway notes directory outside any repository."""
    gate = _gate()
    notes_dir = tmp_path / "ac-state-notes"
    notes_dir.mkdir()
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(gate.ac_state_notes, "ROOT", tmp_path)
    (notes_dir / "_baseline.json").write_text(
        json.dumps({"branch": None, "measured_with_tests": True, "counters": _BASE_COUNTERS})
    )
    gate.notes_dir = notes_dir
    return gate


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_an_improvement_passes_once_it_is_banked_in_the_branchs_own_note(
    gate_on: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half that made the first version of this design unusable.

    The fold excludes the candidate's own note, so a candidate that legitimately
    improves is *above* the base bound — which is what improving means. Judging
    slack against the base would make every genuine gain unpassable. Slack is
    judged against the branch's own note instead.
    """
    better = {**_BASE_COUNTERS, "design_coverage": 21.5}

    assert gate_on.ratchet(better, measured=True, bank=False) == 1
    assert "unbanked improvement" in capsys.readouterr().out

    assert gate_on.ratchet(better, measured=True, bank=True) == 0
    assert gate_on.ratchet(better, measured=True, bank=False) == 0


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_banking_cannot_launder_a_regression(gate_on: Any) -> None:
    """A note is not a licence. Banking a weaker value still fails, because the
    regression half is judged against the base fold, which the candidate did not
    write."""
    worse = {**_BASE_COUNTERS, "design_coverage": 10.0}

    assert gate_on.ratchet(worse, measured=True, bank=True) == 0  # writing is allowed
    assert gate_on.ratchet(worse, measured=True, bank=False) == 1


@pytest.mark.ac("SPEC-082926-25a2/AC-3")
def test_banking_less_than_you_measured_is_slack_and_fails(
    gate_on: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    gate_on.ratchet({**_BASE_COUNTERS, "design_coverage": 21.0}, measured=True, bank=True)

    assert (
        gate_on.ratchet({**_BASE_COUNTERS, "design_coverage": 22.0}, measured=True, bank=False) == 1
    )
    assert "unbanked improvement" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_show_bounds_prints_the_fold_and_its_provenance(
    gate_on: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate_on._show_bounds() == 0

    out = capsys.readouterr().out
    assert "_baseline.json" in out
    assert "design_coverage" in out and "floor" in out
    assert "specs_awaiting_retrofit" in out and "ceiling" in out


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_folds_the_notes_and_drops_the_ones_that_say_nothing(
    gate_on: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    notes_dir = gate_on.notes_dir
    for name, coverage in (("strong", 25.0), ("weak", 21.0)):
        (notes_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "branch": name,
                    "measured_with_tests": True,
                    "counters": {**_BASE_COUNTERS, "design_coverage": coverage},
                }
            )
        )
    before = notes_mod.fold(
        [
            notes_mod.Note.parse(path.name, path.read_text())
            for path in sorted(notes_dir.glob("*.json"))
        ]
    )

    assert gate_on._compact() == 0

    remaining = sorted(path.name for path in notes_dir.glob("*.json"))
    after = notes_mod.fold(
        [
            notes_mod.Note.parse(path.name, path.read_text())
            for path in sorted(notes_dir.glob("*.json"))
        ]
    )
    assert after == before
    assert "_baseline.json" in remaining
    assert "weak.json" not in remaining
    assert "compacted" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_refuses_a_malformed_note_rather_than_skipping_it(
    gate_on: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    (gate_on.notes_dir / "broken.json").write_text("{nope")

    assert gate_on._compact() == 1
    assert "not valid JSON" in capsys.readouterr().out
