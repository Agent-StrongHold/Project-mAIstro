"""Tests for the acceptance-state debt ratchet (#31).

`check-ac-state.py` measures how far each completion claim outruns its evidence.
Measuring was the easy half; the half that holds a line is failing when a
counter moves. These pin both directions, the mode guard, and the property that
a wrong-mode invocation cannot damage the committed measurement.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"

TOTALS = {
    "completion_claims_contradicted": 9,
    "completion_claims_unverifiable": 68,
    "specs_awaiting_retrofit": 139,
    "markers_without_criterion": 2,
    "criteria_claimed_but_unproven": 0,
    "scenarios_without_ac_tag": 0,
    "gherkin_parse_errors": 0,
    "specs_implementing_nothing": 76,
    "adrs_without_implementing_spec": 35,
    "specs_declaring_no_criteria": 7,
    # The one counter that is a percentage and the one whose recorded number is
    # a floor rather than a ceiling. A round 4.0 here rather than the shipped
    # 3.9582, so a test asserting on the direction reads as arithmetic about
    # floors and not as a second copy of the corpus measurement.
    "design_coverage": 4.0,
}


def test_the_fixture_covers_every_ratcheted_counter(gate):
    """A missing key here surfaces as a `KeyError` inside the gate.

    `_bank` and `_compare` both index `totals[name]` for every ratcheted
    counter, so a fixture that has fallen behind fails five tests at once with a
    traceback that points at the gate rather than at the fixture. Naming the
    drift directly is the difference between a five-minute fix and a confusing
    one — which is the same argument the gate itself makes about ceilings.
    """
    bounded = {*gate.RATCHETED, *gate.FLOORED}
    assert bounded == set(TOTALS), "TOTALS is missing: " + ", ".join(sorted(bounded - set(TOTALS)))


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_ac_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ceilings(gate, tmp_path, monkeypatch):
    """Point the gate at a throwaway notes directory.

    Same claims as before #585 — the fixture name is kept so the assertions
    below read unchanged — but the bound is now folded from
    `quality/ac-state-notes/` rather than read off one shared line. Writing a
    single note is the equivalent of writing the old ceilings file: a fold over
    one note is that note.
    """
    notes_dir = tmp_path / "ac-state-notes"
    notes_dir.mkdir()
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", notes_dir)
    # No `origin/develop` in a tmp_path, so the resolver reads the worktree and
    # says so — the developer loop, which is what a unit test is.
    monkeypatch.setattr(gate.ac_state_notes, "ROOT", tmp_path)

    def write(**overrides):
        path = notes_dir / "_baseline.json"
        payload = {
            "branch": None,
            "measured_with_tests": True,
            "counters": {**TOTALS, **overrides},
        }
        path.write_text(json.dumps(payload))
        write.path = path
        return path

    write.path = notes_dir / "_baseline.json"
    write.dir = notes_dir
    return write


def test_sitting_exactly_on_the_ceilings_passes(gate, ceilings) -> None:
    ceilings()
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 0


def test_a_new_contradiction_fails(gate, ceilings, capsys) -> None:
    ceilings()
    worse = {**TOTALS, "completion_claims_contradicted": 10}
    assert gate.ratchet(worse, measured=True, bank=False) == 1
    assert "10 exceeds the ceiling of 9" in capsys.readouterr().out


def test_an_unbanked_improvement_also_fails(gate, ceilings, capsys) -> None:
    """Slack a later regression could spend. The same weakness every count
    ceiling has, and the reason the vulture ledger stopped being one."""
    ceilings()
    better = {**TOTALS, "specs_awaiting_retrofit": 130}
    assert gate.ratchet(better, measured=True, bank=False) == 1
    out = capsys.readouterr().out
    assert "unbanked improvement" in out
    assert "130, ceiling still says 139" in out


def test_banking_an_improvement_then_passes(gate, ceilings) -> None:
    ceilings()
    better = {**TOTALS, "specs_awaiting_retrofit": 130}
    assert gate.ratchet(better, measured=True, bank=True) == 0
    # Banking writes this branch's own note, not the shared line (#585). The
    # fold over the two then carries the improvement.
    banked = json.loads((ceilings.dir / "detached.json").read_text())
    assert banked["counters"]["specs_awaiting_retrofit"] == 130
    assert gate.ratchet(better, measured=True, bank=False) == 0


def test_a_counter_with_no_ceiling_fails(gate, ceilings) -> None:
    path = ceilings()
    payload = json.loads(path.read_text())
    del payload["counters"]["gherkin_parse_errors"]
    path.write_text(json.dumps(payload))
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1


def test_comparing_across_measurement_modes_is_refused(gate, ceilings, capsys) -> None:
    """Without --run-tests nothing reaches the passing rung, so every claim above
    it reads as contradicted. Comparing anyway would make the gate's verdict
    depend on how it was invoked."""
    ceilings()
    assert gate.ratchet(TOTALS, measured=False, bank=False) == 1
    assert "e-run in that mode" in capsys.readouterr().out


def test_the_mode_guard_reports_before_anything_is_measured(gate, ceilings) -> None:
    """The guard exists so a wrong-mode run cannot overwrite the committed
    measurement with an unmeasured payload and only then complain."""
    ceilings()
    assert gate._mode_mismatch(run_tests=True) is None
    assert "Nothing was measured or written" in str(gate._mode_mismatch(run_tests=False))


def test_a_missing_ceilings_file_fails_with_the_bank_instruction(
    gate, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", tmp_path / "absent")
    monkeypatch.setattr(gate.ac_state_notes, "ROOT", tmp_path)
    monkeypatch.setattr(gate.ac_state_notes, "RETIRED_CEILINGS", tmp_path / "also-absent.json")
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1
    assert "--ratchet --bank" in capsys.readouterr().out


def test_the_shipped_baseline_note_covers_every_ratcheted_counter(gate) -> None:
    recorded = json.loads((ROOT / "quality" / "ac-state-notes" / "_baseline.json").read_text())
    assert set(recorded["counters"]) == {*gate.RATCHETED, *gate.FLOORED}
    assert recorded["measured_with_tests"] is True


def test_every_shipped_note_parses_and_agrees_on_the_measurement_mode(gate) -> None:
    """A malformed note is a non-passing state, so no shipped note may be one."""
    notes = sorted((ROOT / "quality" / "ac-state-notes").glob("*.json"))
    assert notes, "the notes directory is the ledger; it may not be empty"
    for path in notes:
        note = gate.ac_state_notes.Note.parse(path.name, path.read_text())
        assert note.measured_with_tests is True, path.name


class TestTheFloorUnderProgress:
    """`design_coverage` is the first counter where higher is better (#166).

    `_compare` compared ten counters in one direction before this, so the
    failure mode worth pinning is not "the floor does not work" but "the floor
    is quietly a ceiling" — a fall reported as an improvement to bank, which
    would ratchet the number *down* on every PR that lost ground and call it
    progress. These assert on which list each move lands in, not merely that
    something failed.
    """

    def test_design_coverage_is_floored_and_not_also_a_debt_counter(self, gate) -> None:
        """The membership assertion comes first because `isdisjoint` alone is
        vacuously true when `FLOORED` is empty — which is exactly the state the
        predicted bug leaves it in."""
        assert "design_coverage" in gate.FLOORED
        assert "design_coverage" not in gate.RATCHETED
        assert set(gate.RATCHETED).isdisjoint(gate.FLOORED)

    def test_a_fall_is_a_regression_and_names_the_floor(self, gate, ceilings, capsys) -> None:
        ceilings()
        worse = {**TOTALS, "design_coverage": 3.9}
        assert gate.ratchet(worse, measured=True, bank=False) == 1
        out = capsys.readouterr().out
        assert "3.9 falls below the floor of 4.0" in out
        assert "unbanked improvement" not in out, "a fall was offered as progress to bank"

    def test_a_rise_is_an_unbanked_improvement_not_a_regression(
        self, gate, ceilings, capsys
    ) -> None:
        """Proving a criterion must not read as a new contradiction."""
        ceilings()
        better = {**TOTALS, "design_coverage": 4.5}
        assert gate.ratchet(better, measured=True, bank=False) == 1
        out = capsys.readouterr().out
        assert "4.5, floor still says 4.0" in out
        assert "exceeds the ceiling" not in out

    def test_banking_a_rise_raises_the_floor(self, gate, ceilings) -> None:
        ceilings()
        better = {**TOTALS, "design_coverage": 4.5}
        assert gate.ratchet(better, measured=True, bank=True) == 0
        banked = json.loads((ceilings.dir / "detached.json").read_text())
        assert banked["counters"]["design_coverage"] == 4.5
        assert gate.ratchet(better, measured=True, bank=False) == 0
        # ...and the raised floor is what makes the old value a regression.
        assert gate.ratchet(TOTALS, measured=True, bank=False) == 1

    def test_a_missing_floor_fails_rather_than_defaulting_to_zero(self, gate, ceilings) -> None:
        """`ceilings.get(name)` is None for an absent key, and `0 < None` raises
        while `actual > None` would too — but a `0` default would silently pass
        anything. The absence has to be its own failure."""
        path = ceilings()
        payload = json.loads(path.read_text())
        del payload["counters"]["design_coverage"]
        path.write_text(json.dumps(payload))
        assert gate.ratchet(TOTALS, measured=True, bank=False) == 1


# --- the paths that report rather than measure (#585) -------------------------
#
# Everything below is a failure mode of the *scheme*, not of the corpus: a note
# directory that cannot be read, a fold with nothing in it, a maintenance
# command run on an empty tree. Each one has to say what is wrong instead of
# passing quietly, because a ratchet that answers "fine" when it could not read
# its oracle is a ratchet that has stopped ratcheting.


def _raise(exc: Exception):
    def fail(*_args, **_kwargs):
        raise exc

    return fail


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_an_unreadable_note_stops_the_ratchet_rather_than_passing_it(
    gate, ceilings, monkeypatch, capsys
) -> None:
    ceilings()
    monkeypatch.setattr(
        gate.ac_state_notes, "bounds", _raise(gate.ac_state_notes.AcStateNoteError("bad note"))
    )

    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1
    assert "the AC-state bound could not be established: bad note" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_an_unreadable_note_stops_the_mode_check_too(gate, ceilings, monkeypatch, capsys) -> None:
    """The mode guard runs before the bound is read, so it needs its own answer."""
    ceilings()
    monkeypatch.setattr(
        gate.ac_state_notes,
        "load_notes",
        _raise(gate.ac_state_notes.AcStateNoteError("unreadable")),
    )

    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1
    assert "the AC-state notes could not be read: unreadable" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_an_empty_fold_names_the_bank_command(gate, ceilings, capsys) -> None:
    """No notes at the base is not "no ceiling"; it is "nothing to compare to"."""
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1

    out = capsys.readouterr().out
    assert "nothing to compare against" in out
    assert "--run-tests --ratchet --bank" in out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_show_bounds_prints_every_bounded_counter(gate, ceilings, capsys) -> None:
    ceilings()

    assert gate._show_bounds() == 0

    out = capsys.readouterr().out
    assert "design_coverage" in out and "floor" in out
    assert "specs_awaiting_retrofit" in out and "ceiling" in out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_show_bounds_fails_when_the_fold_is_empty(gate, ceilings, capsys) -> None:
    assert gate._show_bounds() == 1
    assert "no notes at the base revision" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_show_bounds_reports_an_unreadable_note(gate, ceilings, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        gate.ac_state_notes, "bounds", _raise(gate.ac_state_notes.AcStateNoteError("bad note"))
    )

    assert gate._show_bounds() == 1
    assert "the AC-state bound could not be established: bad note" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_on_a_missing_directory_is_a_no_op_not_a_failure(
    gate, tmp_path, monkeypatch, capsys
) -> None:
    """Maintenance run before the scheme has any notes. Nothing to do is not
    an error, and reporting it as one would train people to ignore it."""
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", tmp_path / "absent")

    assert gate._compact() == 0
    assert "does not exist" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_on_an_empty_directory_is_a_no_op_not_a_failure(gate, ceilings, capsys) -> None:
    assert gate._compact() == 0
    assert "no notes in" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_refuses_a_malformed_note_rather_than_folding_around_it(
    gate, ceilings, capsys
) -> None:
    """Compaction rewrites the baseline. Skipping a note it cannot parse would
    silently drop whatever bound that note was holding."""
    ceilings()
    (ceilings.dir / "broken.json").write_text("{ not json", encoding="utf-8")

    assert gate._compact() == 1
    assert "broken.json is not valid JSON" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_a_counter_no_note_carries_is_left_out_of_the_report(gate, ceilings, capsys) -> None:
    """A fold over notes need not bound every counter — a counter nothing
    measured has no bound, and printing one would invent it."""
    (ceilings.dir / "_baseline.json").write_text(
        json.dumps(
            {
                "branch": None,
                "measured_with_tests": True,
                "counters": {"design_coverage": 4.0},
            }
        )
    )

    assert gate._show_bounds() == 0

    out = capsys.readouterr().out
    assert "design_coverage" in out
    assert "specs_awaiting_retrofit" not in out


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_show_bounds_is_reachable_from_the_command_line(gate, ceilings) -> None:
    ceilings()
    assert gate.main(["--show-bounds"]) == 0


@pytest.mark.ac("SPEC-082926-25a2/AC-4")
def test_compact_is_reachable_from_the_command_line(gate, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", tmp_path / "absent")
    assert gate.main(["--compact"]) == 0


@pytest.mark.ac("SPEC-082926-25a2/AC-6")
def test_a_notes_module_that_fails_to_load_leaves_nothing_behind(
    gate, tmp_path, monkeypatch
) -> None:
    """A half-initialised module left in `sys.modules` is worse than the error.

    The next caller gets the cache hit and a module whose top level never
    finished — an `AttributeError` three frames away from the real fault.
    """
    broken = tmp_path / "ac_state_notes.py"
    broken.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    monkeypatch.setattr(gate, "_NOTES_SOURCE", broken)
    monkeypatch.delitem(sys.modules, "_ac_state_notes", raising=False)

    with pytest.raises(RuntimeError, match="boom"):
        gate._load_notes_module()

    assert "_ac_state_notes" not in sys.modules


# --- the stacked case, at the ratchet (#609, rebuilt for #616) ----------------
#
# The first version of these built on the `ceilings` fixture, which points
# `ac_state_notes.ROOT` at a directory that is not a Git repository. Provenance
# then falls back to reading the worktree, so the *base* fold and the *worktree*
# fold were the same set of notes — and every one of these passed with the fold
# stubbed out entirely, which is exactly the pre-#609 behaviour they claimed to
# rule out. They proved nothing about the wiring (Codex, #609).
#
# So they run against a real repository now: `develop` holds only the weaker
# note, the branch adds the stronger ones, and the two folds genuinely differ.
# `test_the_harness_can_tell_the_two_folds_apart` is the control that keeps this
# honest — without it, a future fixture change could quietly collapse them again
# and nothing here would notice.


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60
    )
    return proc.stdout.strip()


def _write_note(notes_dir: Path, name: str, *, with_tests: bool = True, **counters) -> None:
    (notes_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "branch": None if name == "_baseline" else name,
                "measured_with_tests": with_tests,
                "counters": {**TOTALS, **counters},
            }
        )
    )


@pytest.fixture
def stacked(gate, tmp_path, monkeypatch):
    """A real repository whose base and worktree folds are different.

    Returns a callable: `stacked(base=20.0, "parent"=21.0, ...)` commits the
    base note on `develop`, then leaves the named notes in the worktree on a
    branch off it — the shape a stacked PR has, where both notes are new
    relative to the base.
    """
    root = tmp_path / "repo"
    notes_dir = root / "quality" / "ac-state-notes"
    notes_dir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], check=True, timeout=60)
    _git("config", "user.email", "t@example.com", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(gate.ac_state_notes, "ROOT", root)

    def build(base: float, **worktree: float) -> Path:
        _write_note(notes_dir, "_baseline", design_coverage=base)
        _git("add", "-A", cwd=root)
        _git("commit", "-qm", "base", cwd=root)
        # A remote-tracking ref, because that is what the resolver looks for.
        _git("update-ref", "refs/remotes/origin/develop", "HEAD", cwd=root)
        _git("checkout", "-q", "-b", "stacked", cwd=root)
        for name, value in worktree.items():
            _write_note(notes_dir, name, design_coverage=value)
        # Committed, because a stacked PR's notes are: the resolver refuses a
        # base that resolves to HEAD itself, and rightly — the baseline would
        # then be read from the commit under judgement.
        _git("add", "-A", cwd=root)
        _git("commit", "-qm", "stack", cwd=root)
        return root

    build.dir = notes_dir
    return build


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_the_harness_can_tell_the_two_folds_apart(gate, stacked) -> None:
    """The control, and the reason the rest of this block is evidence.

    If the base fold and the worktree fold ever read the same notes again, this
    fails and the tests below stop being able to distinguish the fix from its
    absence — which is what happened the first time.
    """
    stacked(20.0, parent=21.0, own=22.0)

    assert gate.ac_state_notes.bounds().counters["design_coverage"] == 20.0
    assert gate.ac_state_notes.banked_bound().counters["design_coverage"] == 22.0


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_stack_that_banked_its_measurement_passes(gate, stacked) -> None:
    """Two notes, both new relative to the base: the shape that used to fail.

    The old rule asked for exactly one changed note, found two, answered "none",
    and compared the measurement against the base fold — so the stack's own
    improvement read as unbanked and no amount of re-banking helped.
    """
    stacked(20.0, parent=21.0, own=22.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 22.0}, measured=True, bank=False) == 0


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_stack_that_measured_above_every_note_is_still_told_to_bank(
    gate, stacked, capsys
) -> None:
    """The half that must not get weaker: the fold is `max`, so measuring above
    all of them is still slack a later regression could spend."""
    stacked(20.0, parent=21.0, own=22.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 23.0}, measured=True, bank=False) == 1
    out = capsys.readouterr().out
    assert "unbanked improvement" in out
    assert "23.0, floor still says 22.0" in out


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_banking_below_what_was_measured_is_still_refused(gate, stacked, capsys) -> None:
    """#609's AC-4. One note, the case that already worked, unchanged."""
    stacked(20.0, understated=21.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 23.0}, measured=True, bank=False) == 1
    assert "unbanked improvement" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_weak_note_beside_a_strong_one_buys_no_slack(gate, stacked, capsys) -> None:
    """A candidate cannot lower the claim by adding a note: the fold is `max`."""
    stacked(20.0, real=22.0, cheat=1.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 23.0}, measured=True, bank=False) == 1
    assert "23.0, floor still says 22.0" in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_deleting_every_note_cannot_reach_the_bound_that_judges_regressions(
    gate, stacked, capsys
) -> None:
    """The deletion the worktree fold does not catch, caught by the other half.

    `regressions` is folded at the base, which nothing in the worktree can
    reach — so emptying the directory does not lower the line a regression is
    judged against.
    """
    root = stacked(20.0, own=22.0)
    for note in (root / "quality" / "ac-state-notes").glob("*.json"):
        note.unlink()

    assert gate.ratchet({**TOTALS, "design_coverage": 19.0}, measured=True, bank=False) == 1
    assert "moved away from its recorded state" in capsys.readouterr().out


# --- the fold's own error paths (#616) ---------------------------------------


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_worktree_note_in_the_wrong_mode_is_refused(gate, stacked, capsys) -> None:
    """`_mode_mismatch` only ever saw the notes at the *base*.

    A stacked branch carries notes the base has never seen, so one banked
    without `--run-tests` was folded into a `--run-tests` target — mixing two
    measurement modes this gate treats as incomparable everywhere else, in the
    direction that can only loosen the bound (Codex, #609).
    """
    root = stacked(20.0, parent=21.0)
    _write_note(root / "quality" / "ac-state-notes", "own", with_tests=False, design_coverage=22.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 22.0}, measured=True, bank=False) == 1
    out = capsys.readouterr().out
    assert "banked without --run-tests" in out
    assert "own" in out


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_note_in_the_right_mode_is_not_refused(gate, stacked) -> None:
    """The other side, or a check that refused everything would satisfy the
    test above."""
    stacked(20.0, parent=21.0, own=22.0)

    assert gate.ratchet({**TOTALS, "design_coverage": 22.0}, measured=True, bank=False) == 0


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_a_malformed_worktree_note_is_a_diagnostic_not_a_traceback(gate, stacked, capsys) -> None:
    """The base notes parse, so `bounds()` succeeds and the failure lands on the
    fold — which was read outside the handler, so the gate exited with a
    traceback instead of its own message (Codex, #609).

    `_baseline.json` specifically: the old one-note rule skipped it and the fold
    does not, which is what made this newly reachable.
    """
    root = stacked(20.0, own=22.0)
    (root / "quality" / "ac-state-notes" / "_baseline.json").write_text("{not json")

    assert gate.ratchet({**TOTALS, "design_coverage": 22.0}, measured=True, bank=False) == 1
    assert "the banked AC-state fold could not be read" in capsys.readouterr().out
