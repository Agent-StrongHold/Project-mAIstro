"""A corrected measurement can lower the AC-state floor; a regression cannot.

SPEC-082926-6f49. `fold` takes `max` across notes and notes outlive their
branches, so a merged branch's note holds the floor permanently and `--bank`
writes only the running branch's own. There was no way to say a recorded number
was wrong — which #631 needed, because its correction makes seven criteria stop
being counted as `reachable` on a module the baseline lists as unreachable.

Every case runs against a **real** repository, for the reason
`test_check_ac_state_ratchet.py` records: a fixture pointing `ROOT` at a
non-repository makes provenance fall back to the worktree, and then the base
fold and the worktree fold are the same set of notes — so a test that means to
prove "read at the base" passes with the mechanism stubbed out entirely.
`test_a_grant_written_in_the_same_change_does_not_take_effect` is the case that
would go quiet first, so `test_the_harness_reads_grants_from_the_base` pins the
harness itself.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"

pytestmark = [pytest.mark.contract("behavioral")]

#: "Leave the committed file as it is", as distinct from `None`, which writes an
#: empty grants file. A candidate that *removes* a grant is one of the states
#: under test, so the fixture has to be able to say both.
UNCHANGED = object()

#: Every ratcheted counter at a value the fixture keeps still, so a test reads
#: as arithmetic about one floor rather than a second copy of the corpus.
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
    "design_coverage": 20.0,
}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_ac_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    full_env = {**os.environ, **env} if env else None
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=full_env,
    )
    return proc.stdout.strip()


def _dated_commit_env(unix_seconds: int) -> dict[str, str]:
    """`GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` for a commit at an exact instant.

    Real wall-clock gaps between commits would make "landed after the grant"
    true by accident of test speed rather than by design, and second-level
    `%ct` granularity means two commits made in the same test run could tie.
    Explicit, strictly increasing timestamps make landing order a fact of the
    fixture, not a race.
    """
    stamp = f"@{unix_seconds} +0000"
    return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}


@pytest.fixture
def repo(gate, tmp_path, monkeypatch):
    """A real repository, with the base and worktree states under the test's control.

    `build(base=..., grant_at_base=..., grant_in_worktree=..., banked=...)`
    commits the base note (and any base grant) on `develop`, then leaves the
    branch's own note and any worktree-only grant on a branch off it.
    """
    root = tmp_path / "repo"
    notes_dir = root / "quality" / "ac-state-notes"
    notes_dir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], check=True, timeout=60)
    _git("config", "user.email", "t@example.com", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    monkeypatch.setattr(gate.ac_state_notes, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(gate.ac_state_notes, "ROOT", root)

    grants_path = root / "quality" / "ratchet-authorizations.json"

    def _note(name: str, coverage: float) -> None:
        (notes_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "branch": None if name == "_baseline" else name,
                    "measured_with_tests": True,
                    "counters": {**TOTALS, "design_coverage": coverage},
                }
            )
        )

    def _grant(entry: str | None) -> None:
        payload = (
            {}
            if entry is None
            else {
                "ac-state": {
                    entry: {
                        "owner": "@someone",
                        "issue": "#662",
                        "reason": "the anchors did not resolve, so the recorded floor "
                        "counted criteria nothing runs",
                    }
                }
            }
        )
        grants_path.write_text(json.dumps(payload))

    def build(
        base: float,
        *,
        grant_at_base: str | None = None,
        grant_in_worktree: str | None = UNCHANGED,
        banked: float | None = None,
        raw_grant_at_base: object = UNCHANGED,
        extra_base_notes: dict[str, float] | None = None,
        bundled_extra_notes: dict[str, float] | None = None,
    ) -> Path:
        # `_baseline` and the grant land together, at t=1000 -- this commit
        # *is* "when the grant was authorized" as `_grants_file_landing_commit`
        # reads it. Each `extra_base_notes` entry then gets its own commit, one
        # second later than the last, so "independently landed after the
        # grant" (SPEC-083026-fcc9) is a fact of the fixture's git history, the
        # same thing `_superseded_grants` itself reads, not merely a fold of
        # files that happen to sit in one working tree. `bundled_extra_notes`
        # is the opposite case: every entry lands in one shared commit, one
        # second after `_baseline`'s -- one review, however many files it
        # touches, which is what "distinct landing" must collapse to one.
        _note("_baseline", base)
        if raw_grant_at_base is not UNCHANGED:
            grants_path.write_text(json.dumps(raw_grant_at_base))
        else:
            _grant(grant_at_base)
        _git("add", "-A", cwd=root)
        _git("commit", "-qm", "base", cwd=root, env=_dated_commit_env(1000))
        for offset, (name, coverage) in enumerate(sorted((extra_base_notes or {}).items()), 1):
            _note(name, coverage)
            _git("add", "-A", cwd=root)
            _git("commit", "-qm", name, cwd=root, env=_dated_commit_env(1000 + offset))
        if bundled_extra_notes:
            for name, coverage in bundled_extra_notes.items():
                _note(name, coverage)
            _git("add", "-A", cwd=root)
            _git(
                "commit",
                "-qm",
                "bundle",
                cwd=root,
                env=_dated_commit_env(1000 + len(extra_base_notes or {}) + 1),
            )
        _git("update-ref", "refs/remotes/origin/develop", "HEAD", cwd=root)
        _git("checkout", "-q", "-b", "branch", cwd=root)
        if grant_in_worktree is not UNCHANGED:
            # `None` empties the file; UNCHANGED leaves whatever the base
            # committed. The two are different cases -- deleting a grant is one
            # of the states under test -- and collapsing them made "the
            # candidate removed it" untestable.
            _grant(grant_in_worktree)
        if banked is not None:
            _note("branch", banked)
        _git("add", "-A", cwd=root)
        # `--allow-empty`, because a case can legitimately change nothing on the
        # branch: "the grant landed and this change banked nothing" is one of
        # the states under test. The commit still has to exist, or the base ref
        # would resolve to HEAD and the resolver would refuse the run outright.
        _git("commit", "-q", "--allow-empty", "-m", "branch", cwd=root)
        return root

    return build


def _run(gate, coverage: float) -> int:
    return gate.ratchet({**TOTALS, "design_coverage": coverage}, measured=True, bank=False)


class TestTheHarness:
    def test_the_harness_reads_grants_from_the_base(self, gate, repo) -> None:
        """The control. If the base and the worktree ever collapse into one
        state again, the case that matters below cannot tell the fix from its
        absence — which is precisely how the #609 tests went quiet."""
        repo(20.0, grant_at_base="design_coverage@15.0", grant_in_worktree=None, banked=20.0)

        floors, _ = gate.authorized_floors(gate.ac_state_notes.bounds().base_sha)

        assert floors == {"design_coverage": 15.0}


class TestAGrantLowersTheFloor:
    @pytest.mark.ac("SPEC-082926-6f49/AC-1")
    def test_with_no_grant_the_fold_still_holds(self, gate, repo) -> None:
        repo(20.0, banked=15.0)

        assert _run(gate, 15.0) == 1

    @pytest.mark.ac("SPEC-082926-6f49/AC-2")
    def test_a_landed_grant_permits_the_fall_it_names(self, gate, repo, capsys) -> None:
        repo(20.0, grant_at_base="design_coverage@15.0", banked=15.0)

        assert _run(gate, 15.0) == 0
        out = capsys.readouterr().out
        assert "authorized floor: design_coverage may fall to 15.0" in out
        assert "anchors did not resolve" in out, "the reason travels with the permission"

    @pytest.mark.ac("SPEC-082926-6f49/AC-2")
    def test_a_grant_does_not_permit_a_deeper_fall(self, gate, repo) -> None:
        """The value is in the key so that one grant licenses one fall. A bare
        counter name would be an open season for as long as it sat there."""
        repo(20.0, grant_at_base="design_coverage@15.0", banked=12.0)

        assert _run(gate, 12.0) == 1


class TestAGrantMustBePrior:
    @pytest.mark.ac("SPEC-082926-6f49/AC-3")
    def test_a_grant_written_in_the_same_change_does_not_take_effect(self, gate, repo) -> None:
        """The property the whole mechanism is for. A change that could both
        lower the floor and permit itself to would be the self-approval this
        ratchet was built to close, wearing a reviewer's clothes."""
        repo(20.0, grant_at_base=None, grant_in_worktree="design_coverage@15.0", banked=15.0)

        assert _run(gate, 15.0) == 1


class TestAGrantOnlyLowers:
    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_grant_above_the_fold_does_not_raise_it(self, gate, repo) -> None:
        repo(20.0, grant_at_base="design_coverage@25.0", banked=20.0)

        lowered = gate._lowered({"design_coverage": 20.0}, {"design_coverage": 25.0})

        assert lowered["design_coverage"] == 20.0

    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_spent_grant_is_reported_rather_than_ignored(self, gate) -> None:
        """A grant that lowers nothing still sits in the file under an owner's
        name, ready to absorb the next real fall as the one that was reviewed."""
        stale = gate._stale_grants({"design_coverage": 20.0}, {"design_coverage": 25.0})

        assert stale and "lowers nothing" in stale[0]

    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_binding_grant_is_not_reported_as_spent(self, gate) -> None:
        assert gate._stale_grants({"design_coverage": 20.0}, {"design_coverage": 15.0}) == []

    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_spent_grant_fails_the_run_that_finds_it(self, gate, repo, capsys) -> None:
        """Reported has to mean *acted on*. A finding printed under a passing
        run is a finding nobody reads, and the grant it names goes on sitting
        in the file with an owner beside it."""
        repo(20.0, grant_at_base="design_coverage@25.0", banked=20.0)

        assert _run(gate, 20.0) == 1
        out = capsys.readouterr().out
        assert "authorized floor(s) the notes have overtaken" in out
        assert "design_coverage" in out

    def test_a_grant_cannot_conjure_a_counter_the_fold_does_not_carry(self, gate) -> None:
        """`_lowered` narrows a comparison; it must never widen one.

        A bound folded from notes that predate a counter does not carry it, and
        inventing the key here would put a number into the comparison that no
        note ever measured -- an authorized floor for a counter nobody has read.
        """
        assert gate._lowered({}, {"design_coverage": 15.0}) == {}


class TestTheAuthorizedFloorIsAValueNotARange:
    @pytest.mark.ac("SPEC-082926-6f49/AC-5")
    def test_a_measurement_above_the_grant_is_slack_to_bank(self, gate, repo) -> None:
        """A grant is not a floor a branch may sit anywhere under.

        Both folds take `max`, so the grant has to lower the exact comparison
        too or it would demand the number the correction disproved. That makes
        the authorized value the target, not a basement: measuring above it is
        an improvement, and improvements are banked, not pocketed.
        """
        repo(20.0, grant_at_base="design_coverage@15.0", banked=15.0)

        assert _run(gate, 17.0) == 1


class TestAMalformedGrantIsRefused:
    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_grant_on_a_debt_ceiling_is_refused(self, gate, repo) -> None:
        """A ceiling is raised by banking it, never by permission — the two
        directions are not symmetric and folding them would let a grant excuse
        new debt."""
        repo(20.0, grant_at_base="specs_implementing_nothing@80", banked=20.0)

        with pytest.raises(gate.RatchetProvenanceError, match="not a floored counter"):
            gate.authorized_floors(gate.ac_state_notes.bounds().base_sha)

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_grant_with_no_value_is_refused(self, gate, repo) -> None:
        repo(20.0, grant_at_base="design_coverage", banked=20.0)

        with pytest.raises(gate.RatchetProvenanceError, match="does not name the value"):
            gate.authorized_floors(gate.ac_state_notes.bounds().base_sha)

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_the_refusal_reaches_the_gate_rather_than_a_traceback(self, gate, repo, capsys) -> None:
        """A gate that dies with a traceback has not failed, it has crashed,
        and the two read differently to whoever is looking at the log."""
        repo(20.0, grant_at_base="design_coverage@not-a-number", banked=20.0)

        assert _run(gate, 20.0) == 1
        assert "does not name the value" in capsys.readouterr().out


class TestTheMergeGroupHonoursTheSameGrant:
    """The comparison that decides whether the fall can ever land.

    `check-ac-state.py` measures the actual base revision in the merge group and
    compares it to the candidate, independently of any note. That comparison did
    not know about grants, so an authorized fall passed every note-based check on
    the branch and was then rejected as a regression by the queue — working
    everywhere except the one place it had to work.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_an_authorized_fall_is_not_a_regression_from_the_actual_base(self, gate) -> None:
        base = {**TOTALS, "design_coverage": 20.0}
        candidate = {**TOTALS, "design_coverage": 15.0}

        assert gate._actual_base_regressions(base, candidate, {"design_coverage": 15.0}) == []

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_the_same_fall_without_a_grant_still_is(self, gate) -> None:
        """The control. If the grant were not doing the work here, the case
        above would pass for the wrong reason and the guard would be gone."""
        base = {**TOTALS, "design_coverage": 20.0}
        candidate = {**TOTALS, "design_coverage": 15.0}

        assert gate._actual_base_regressions(base, candidate, {}) != []

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_a_grant_does_not_excuse_a_deeper_fall_from_the_actual_base(self, gate) -> None:
        base = {**TOTALS, "design_coverage": 20.0}
        candidate = {**TOTALS, "design_coverage": 12.0}

        assert gate._actual_base_regressions(base, candidate, {"design_coverage": 15.0}) != []

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_public_guard_reads_the_base_grant_before_comparing(
        self, gate, tmp_path, monkeypatch, capsys
    ) -> None:
        base_report = tmp_path / "base.json"
        candidate_report = tmp_path / "candidate.json"
        base_report.write_text(json.dumps({"measured": True, "totals": TOTALS}))
        candidate_report.write_text(
            json.dumps({"measured": True, "totals": {**TOTALS, "design_coverage": 15.0}})
        )
        seen: list[str] = []

        def authorized(base_rev: str):
            seen.append(base_rev)
            return {"design_coverage": 15.0}, {"design_coverage": "approved correction"}

        monkeypatch.setattr(gate._impl, "authorized_floors", authorized)

        assert gate._guard_actual_base(base_report, candidate_report, "base-sha") == 0
        assert seen == ["base-sha"]
        assert "preserves the actual measured AC-state" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_public_guard_reports_the_grant_when_a_deeper_fall_is_refused(
        self, gate, tmp_path, monkeypatch, capsys
    ) -> None:
        base_report = tmp_path / "base.json"
        candidate_report = tmp_path / "candidate.json"
        base_report.write_text(json.dumps({"measured": True, "totals": TOTALS}))
        candidate_report.write_text(
            json.dumps({"measured": True, "totals": {**TOTALS, "design_coverage": 12.0}})
        )
        monkeypatch.setattr(
            gate._impl,
            "authorized_floors",
            lambda _rev: ({"design_coverage": 15.0}, {"design_coverage": "approved correction"}),
        )

        assert gate._guard_actual_base(base_report, candidate_report, "base-sha") == 1
        out = capsys.readouterr().out
        assert "regressed from the actual measured base base-sha" in out
        assert "Authorized floors were applied" in out
        assert "design_coverage@15.0" in out

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_public_guard_fails_closed_when_base_grant_provenance_is_invalid(
        self, gate, tmp_path, monkeypatch, capsys
    ) -> None:
        base_report = tmp_path / "base.json"
        candidate_report = tmp_path / "candidate.json"
        base_report.write_text(json.dumps({"measured": True, "totals": TOTALS}))
        candidate_report.write_text(json.dumps({"measured": True, "totals": TOTALS}))

        def refuse(_rev: str):
            raise gate._impl.RatchetProvenanceError("malformed authorization at base")

        monkeypatch.setattr(gate._impl, "authorized_floors", refuse)

        assert gate._guard_actual_base(base_report, candidate_report, "base-sha") == 1
        assert "malformed authorization at base" in capsys.readouterr().out


class TestAGrantMustSurviveTheChangeThatSpendsIt:
    @pytest.mark.ac("SPEC-082926-6f49/AC-8")
    def test_spending_a_grant_and_deleting_it_is_refused(self, gate, repo, capsys) -> None:
        """Permission is read at the base, so removing the grant here would
        still let the fall land — and leave the next run looking at a number
        nobody can account for."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=15.0,
        )

        assert _run(gate, 15.0) == 1
        assert "spent by this change and deleted by it" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-8")
    def test_keeping_the_binding_grant_is_what_passes(self, gate, repo) -> None:
        """The control, and the ordinary case: the file still names the fall."""
        repo(20.0, grant_at_base="design_coverage@15.0", banked=15.0)

        assert _run(gate, 15.0) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_change_whose_only_edit_prunes_a_spent_grant_passes(self, gate, repo) -> None:
        """Stale-ness is read from the candidate, and this is why.

        Read from the base, a spent grant failed every later run including the
        one that removed it: the base still carried the row the gate was
        demanding be pruned. The instruction was unfollowable.
        """
        repo(
            15.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=15.0,
        )

        assert _run(gate, 15.0) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-4")
    def test_a_spent_grant_left_in_place_still_fails(self, gate, repo, capsys) -> None:
        repo(15.0, grant_at_base="design_coverage@15.0", banked=15.0)

        assert _run(gate, 15.0) == 1
        assert "lowers nothing" in capsys.readouterr().out


class TestAMalformedSectionRefusesRatherThanCrashes:
    """A gate that dies with an `AttributeError` has not refused; it has
    crashed, and AC-6 promises a refusal. The helper raising it is shared with
    the wiring ratchet, so the shape is translated here rather than tightened
    there in a change that is not about that gate.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_candidate_section_that_is_not_an_object_is_refused(self, gate, repo) -> None:
        """`or {}` read this as "no grants" and passed. An absent section is no
        grants; a present one of the wrong shape is a malformed file, and the
        two must not answer the same."""
        repo(20.0, banked=20.0, grant_in_worktree=None)
        (gate.ac_state_notes.ROOT / "quality" / "ratchet-authorizations.json").write_text(
            '{"ac-state": []}'
        )

        with pytest.raises(gate.RatchetProvenanceError, match="malformed"):
            gate.candidate_grants()

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_base_section_that_is_not_an_object_is_refused(self, gate, repo) -> None:
        repo(20.0, raw_grant_at_base={"ac-state": []}, banked=20.0)

        with pytest.raises(gate.RatchetProvenanceError, match="malformed"):
            gate.authorized_floors(gate.ac_state_notes.bounds().base_sha)

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_record_that_is_a_scalar_is_refused(self, gate, repo) -> None:
        repo(
            20.0,
            raw_grant_at_base={"ac-state": {"design_coverage@15.0": "because I said so"}},
            banked=20.0,
        )

        with pytest.raises(gate.RatchetProvenanceError, match="malformed"):
            gate.authorized_floors(gate.ac_state_notes.bounds().base_sha)

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_the_malformed_refusal_reaches_the_gate(self, gate, repo, capsys) -> None:
        """A crash and a refusal read differently in a build log, which is the
        whole reason this is translated rather than left to propagate."""
        repo(20.0, raw_grant_at_base={"ac-state": []}, banked=20.0)

        assert _run(gate, 20.0) == 1
        assert "malformed" in capsys.readouterr().out


class TestReadingTheCandidateFileAtAll:
    """`candidate_grants`' two ways of finding nothing, which are not the same.

    A repository with no authorization file has no grants, and that is the
    ordinary state -- the gate must not require the file to exist. A file that
    exists and cannot be parsed is a different fact, and reading it as "no
    grants" would silently ignore whatever somebody wrote there.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-1")
    def test_no_file_at_all_is_no_grants(self, gate, repo) -> None:
        root = repo(20.0, banked=20.0)
        (root / "quality" / "ratchet-authorizations.json").unlink()

        assert gate.candidate_grants() == {}

    @pytest.mark.ac("SPEC-082926-6f49/AC-6")
    def test_a_file_that_is_not_json_is_refused(self, gate, repo) -> None:
        root = repo(20.0, banked=20.0)
        (root / "quality" / "ratchet-authorizations.json").write_text("{not json")

        with pytest.raises(gate.RatchetProvenanceError, match="could not be read"):
            gate.candidate_grants()


class TestTheGuardAgainstARealBaseRevision:
    """The two cases the stubbed guard tests above cannot reach.

    Those monkeypatch `authorized_floors`, which is the right shape for
    asserting *that* the guard consults it and *what* it prints. It leaves two
    things unproven: that the real call resolves a real base revision, and that
    the guard refuses before comparing when a measurement is missing.
    """

    def _report(self, path: Path, coverage: float) -> Path:
        path.write_text(
            json.dumps({"measured": True, "totals": {**TOTALS, "design_coverage": coverage}})
        )
        return path

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_an_unauthorized_fall_fails_against_a_real_base(self, gate, repo, tmp_path) -> None:
        """No stub: `authorized_floors` resolves the base revision itself and
        finds nothing, which is the ordinary state and must still refuse."""
        repo(20.0, banked=20.0)
        base = self._report(tmp_path / "base.json", 20.0)
        candidate = self._report(tmp_path / "candidate.json", 15.0)

        assert gate._guard_actual_base(base, candidate, gate.ac_state_notes.bounds().base_sha) == 1

    @pytest.mark.ac("SPEC-082926-6f49/AC-7")
    def test_an_authorized_fall_passes_against_a_real_base(self, gate, repo, tmp_path) -> None:
        """The whole point, with the grant read from a real committed file
        rather than handed to the guard by the test."""
        repo(20.0, grant_at_base="design_coverage@15.0", banked=15.0)
        base = self._report(tmp_path / "base.json", 20.0)
        candidate = self._report(tmp_path / "candidate.json", 15.0)

        assert gate._guard_actual_base(base, candidate, gate.ac_state_notes.bounds().base_sha) == 0

    def test_an_unreadable_report_refuses_before_anything_else(self, gate, tmp_path) -> None:
        """The guard's first job is to be sure it is comparing two real
        measurements. A missing file must not read as "nothing moved"."""
        missing = tmp_path / "absent.json"
        present = self._report(tmp_path / "candidate.json", 20.0)

        assert gate._guard_actual_base(missing, present, "irrelevant") == 1


class TestAGrantIsPermissionNotACap:
    """SPEC-082926-6f49 AC-9 (#691).

    A grant permits one fall to one value. Applied to a change that measures
    *above* it, it stopped being permission and became a ceiling: `_lowered`
    pulled the exact target back to the granted value, the measurement read as
    unbanked slack, and banking could not clear it — the fold rose and the
    grant pulled it down again. The gate printed "bank it" as the remedy for a
    state banking could not reach.

    Nor could anyone retire the grant. `_stale_grants` fires when the fold is
    at or below the grant; `_removed_binding_grants` refuses removal while the
    fold is above it. Complementary conditions on the same pair, so exactly one
    held at all times and the grant could never leave.

    The numbers below are develop's own on 2026-08-30: base fold 28.2327 from
    the merged #328 note, a grant at 27.8791 from #686, and #688 measuring
    28.4214. Nothing had merged since #649.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_an_improvement_above_a_landed_grant_passes_once_banked(self, gate, repo) -> None:
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=28.4214)

        assert _run(gate, 28.4214) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_the_same_improvement_unbanked_still_fails_as_slack(self, gate, repo, capsys) -> None:
        """The other half, and the one that keeps AC-5 true: the grant no
        longer caps the target, so the *fold* does — and an improvement nobody
        recorded is still slack a later regression could spend. This is the
        case that proves the printed remedy is now reachable rather than
        decorative."""
        repo(28.2327, grant_at_base="design_coverage@27.8791")

        assert _run(gate, 28.4214) == 1
        assert "unbanked improvement" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_taking_the_authorized_fall_is_still_exact(self, gate, repo) -> None:
        """AC-2 unchanged. The grant still applies to the change that is using
        it, so #649's own shape — measuring exactly the granted value against a
        higher fold — still passes."""
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)

        assert _run(gate, 27.8791) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_a_deeper_fall_is_still_refused(self, gate, repo) -> None:
        """AC-3 unchanged. Below the grant is still a regression it does not
        cover — the half that must not loosen when the other half stops
        capping."""
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.0)

        assert _run(gate, 27.0) == 1

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_an_improvement_between_the_grant_and_the_fold_passes_once_banked(
        self, gate, repo
    ) -> None:
        """The case a narrower fix misses, and the one that catches most PRs.

        A grant exists because the inherited fold is *wrong* — higher than what
        the repository actually measures. So the interesting branches do not
        clear the stale fold at all; they land between the grant and it. Here
        27.9012 is a genuine gain over develop's real 27.8791 while sitting well
        under the 28.2327 the merged notes still assert.

        Excluding the grant from the exact comparison whenever the measurement
        is above it would refuse this as a fall to 27.9012 from 28.2327. Keeping
        it would demand exactly 27.8791. Only correcting the inherited bound and
        then honouring what this tree banked admits it.
        """
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.9012)

        assert _run(gate, 27.9012) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_that_improvement_unbanked_is_still_slack(self, gate, repo, capsys) -> None:
        """Same measurement, nothing recorded: the corrected floor stands at the
        grant, and a gain above it nobody wrote down is still slack."""
        repo(28.2327, grant_at_base="design_coverage@27.8791")

        assert _run(gate, 27.9012) == 1
        assert "unbanked improvement" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_a_stale_note_cannot_stand_in_for_banking_a_lower_value(
        self, gate, repo, capsys
    ) -> None:
        """The loosening this must not buy. Banking is "some note in this tree
        records what I measured", so a change measuring *below* the grant does
        not escape by pointing at the inherited note — that note says 28.2327,
        not 27.0, and the regression half is folded at the base where nothing in
        the worktree can reach it."""
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.0)

        assert _run(gate, 27.0) == 1
        assert "unbanked improvement" not in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_the_inherited_notes_are_not_what_banking_is_asked_about(self, gate, repo) -> None:
        """Why the fold is split rather than taken whole.

        The inherited notes are the record a grant corrects, so they must not
        also answer "did you bank it?" — folded in with `max` they pin the
        target at the number the grant just disowned. Only the notes this
        change writes carry that question, and here that is the candidate's own
        27.9012 rather than the merged 28.2327 sitting beside it.
        """
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.9012)

        assert gate._fresh_note_bound()["design_coverage"] == 27.9012

    @pytest.mark.ac("SPEC-082926-6f49/AC-9")
    def test_weakening_an_inherited_note_is_still_caught(self, gate, repo, capsys) -> None:
        """The property the split must not cost (Codex, #692).

        Correcting the inherited record must not stop the run seeing an
        inherited note this change *rewrote downward*. Here the sole note goes
        20 -> 15 while the measurement stays 20. The base comparison reads the
        measurement, not the notes, so it is happy; only the worktree fold sees
        the weakened note, and against it 20 is unbanked slack. Left undetected
        the floor would silently drop to 15 for everyone after the merge.
        """
        root = repo(20.0)
        note = root / "quality" / "ac-state-notes" / "_baseline.json"
        note.write_text(
            json.dumps(
                {
                    "branch": None,
                    "measured_with_tests": True,
                    "counters": {**TOTALS, "design_coverage": 15.0},
                }
            )
        )

        assert _run(gate, 20.0) == 1
        assert "unbanked improvement" in capsys.readouterr().out


def _write_grants(root, section) -> None:
    """Put an arbitrary `ac-state` section in the worktree's grants file."""
    (root / "quality" / "ratchet-authorizations.json").write_text(json.dumps({"ac-state": section}))


class TestTheCandidateFileIsReadTheWayTheBaseReadsIt:
    """SPEC-082926-6f49 AC-10 (#685 finding 1).

    `candidate_grants` used to iterate keys and suppress the `ValueError`, so a
    change could keep a binding key, replace its record with `{}` or a scalar,
    and pass: `_removed_binding_grants` saw the key, the value parsed, and
    nothing looked inside. After the merge `load_authorizations` reads the same
    file as the base and *does* look — so every subsequent run failed on a file
    only another grant could repair. A gate that refuses runs nobody can fix.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_a_record_emptied_to_a_mapping_is_refused(self, gate, repo) -> None:
        root = repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)
        _write_grants(root, {"design_coverage@27.8791": {}})

        with pytest.raises(gate.RatchetProvenanceError, match="missing owner, issue, reason"):
            gate.candidate_grants()

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_a_record_replaced_by_a_scalar_is_refused(self, gate, repo) -> None:
        """The shape that reached the base helper's `.get()` as an
        AttributeError — a crash, which reads differently in a log from a
        refusal, and on the candidate side was not even reached."""
        root = repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)
        _write_grants(root, {"design_coverage@27.8791": 5})

        with pytest.raises(gate.RatchetProvenanceError, match="is a int, not a record"):
            gate.candidate_grants()

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_a_malformed_key_is_named_rather_than_dropped(self, gate, repo) -> None:
        """`contextlib.suppress(ValueError)` discarded an entry whose value did
        not parse. Written, expected to be enforced, ignored without a word —
        the failure #672 finding 4 closed for the section and left open here."""
        root = repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)
        _write_grants(
            root,
            {
                "design_coverage@not-a-number": {
                    "owner": "@someone",
                    "issue": "#685",
                    "reason": "a reason",
                }
            },
        )

        with pytest.raises(gate.RatchetProvenanceError, match="does not name the value"):
            gate.candidate_grants()

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_a_counter_that_is_not_a_floor_is_refused_here_too(self, gate, repo) -> None:
        """The base refuses a grant naming a debt ceiling. The candidate said
        nothing, so the two revisions disagreed about the same file."""
        root = repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)
        _write_grants(
            root,
            {"specs_with_no_criteria@3": {"owner": "@x", "issue": "#685", "reason": "r"}},
        )

        with pytest.raises(gate.RatchetProvenanceError, match="not a floored counter"):
            gate.candidate_grants()

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_a_well_formed_candidate_file_still_reads(self, gate, repo) -> None:
        """The half that must not move: validation is not refusal of everything."""
        repo(28.2327, grant_at_base="design_coverage@27.8791", banked=27.8791)

        assert gate.candidate_grants() == {"design_coverage": 27.8791}


class TestAProtectedPushCannotSpendAGrantAndDeleteIt:
    """SPEC-082926-6f49 AC-11 (#685 finding 2).

    `check-ac-state.py` strips `--ratchet` on a push to develop, integration or
    main, so `ratchet()` never runs and neither does its retention bookkeeping.
    `_guard_actual_base` still applied the base grant to the base before
    comparing — so on the one path with no review in front of it, a commit
    could consume an authorized fall and remove the grant permitting it, and
    the guard passed.

    A merge group is not this path: it keeps `--ratchet`, so
    `_removed_binding_grants` already answers there.
    """

    @staticmethod
    def _reports(tmp_path, candidate_coverage: float):
        base_report = tmp_path / "base.json"
        candidate_report = tmp_path / "candidate.json"
        base_report.write_text(json.dumps({"measured": True, "totals": TOTALS}))
        candidate_report.write_text(
            json.dumps(
                {"measured": True, "totals": {**TOTALS, "design_coverage": candidate_coverage}}
            )
        )
        return base_report, candidate_report

    @staticmethod
    def _floors(gate, monkeypatch, value: float | None) -> None:
        monkeypatch.setattr(
            gate._impl,
            "authorized_floors",
            lambda base_rev: (
                ({}, {})
                if value is None
                else ({"design_coverage": value}, {"design_coverage": "approved correction"})
            ),
        )

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_spending_a_grant_and_removing_it_is_refused(
        self, gate, repo, tmp_path, monkeypatch, capsys
    ) -> None:
        root = repo(28.2327, grant_at_base="design_coverage@15.0", banked=15.0)
        _write_grants(root, {})
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, 15.0)

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 1
        )
        assert "spends an authorized floor and removes it: design_coverage@15.0" in (
            capsys.readouterr().out
        )

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_spending_a_grant_it_still_ships_passes(
        self, gate, repo, tmp_path, monkeypatch
    ) -> None:
        repo(28.2327, grant_at_base="design_coverage@15.0", banked=15.0)
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, 15.0)

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 0
        )

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_pruning_a_grant_this_push_does_not_need_still_passes(
        self, gate, repo, tmp_path, monkeypatch
    ) -> None:
        """The honest case the guard must not catch. This push regresses
        nothing, so dropping the grant changes no verdict — it has nothing to
        answer for, and refusing it would make a spent grant unprunable, which
        is the shape #673 existed to fix."""
        root = repo(28.2327, grant_at_base="design_coverage@15.0", banked=15.0)
        _write_grants(root, {})
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, TOTALS["design_coverage"])

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 0
        )

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_a_merge_group_is_not_asked_twice(self, gate, repo, tmp_path, monkeypatch) -> None:
        """Same removal, `check_retention` off: a merge group keeps `--ratchet`,
        so `_removed_binding_grants` is the one that answers. Enforcing it here
        as well would make either place look optional."""
        root = repo(28.2327, grant_at_base="design_coverage@15.0", banked=15.0)
        _write_grants(root, {})
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, 15.0)

        assert gate._guard_actual_base(base_report, candidate_report, "base-sha") == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_the_base_measurement_itself_asks_nothing(self, gate, tmp_path, monkeypatch) -> None:
        """The other side of the recursion guard, and the reason the test above
        must delete it by name. `_measure_base` re-invokes this script inside
        the base worktree with the guard set; that run must delegate straight
        to `_impl.main` and never measure a base of its own."""
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_REF", "refs/heads/develop")
        monkeypatch.setenv(gate._BASE_MEASUREMENT, "1")
        measured: list[str] = []
        monkeypatch.setattr(gate, "_measure_base", lambda base_rev, report: measured.append("no"))
        monkeypatch.setattr(gate._impl, "main", lambda argv: 0)

        assert gate.main(["--ratchet", "--out", str(tmp_path / "out.json")]) == 0
        assert measured == []

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_a_deeper_fall_is_reported_as_the_fall_it_is(
        self, gate, repo, tmp_path, monkeypatch, capsys
    ) -> None:
        """Codex, #693. Base 20, grant 15, candidate 12, grant removed.

        The counter regresses *either way*, so the grant is not what permits
        this push and its removal is not the story. Comparing the rendered
        lines made it look load-bearing — they name different floors, 15 with
        the grant and 20 without — and the run then refused the push for the
        removal instead of for the deeper fall, which is the more serious of
        the two and the one an operator needs told.
        """
        root = repo(28.2327, grant_at_base="design_coverage@15.0", banked=12.0)
        _write_grants(root, {})
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, 12.0)
        base_report.write_text(
            json.dumps({"measured": True, "totals": {**TOTALS, "design_coverage": 20.0}})
        )

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 1
        )
        printed = capsys.readouterr().out
        assert "regressed from the actual measured base" in printed
        assert "spends an authorized floor and removes it" not in printed

    @pytest.mark.ac("SPEC-082926-6f49/AC-10")
    def test_the_first_grant_a_push_adds_is_validated_too(
        self, gate, repo, tmp_path, monkeypatch, capsys
    ) -> None:
        """Codex, #693. A protected push adding the *first* grant has no base
        floors, so an early return on `not floors` skipped the only validation
        this path performs — and `--ratchet` is stripped here, so nothing else
        looks. The malformed record then became the base every later run reads
        and refuses."""
        root = repo(28.2327, banked=28.2327)
        _write_grants(root, {"design_coverage@15.0": {}})
        self._floors(gate, monkeypatch, None)
        base_report, candidate_report = self._reports(tmp_path, 28.2327)

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 1
        )
        assert "missing owner, issue, reason" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_a_push_with_no_grant_in_play_is_not_asked_anything(self, gate, tmp_path) -> None:
        """No floors, no question — and no read of the grants file either."""
        base_report, candidate_report = self._reports(tmp_path, TOTALS["design_coverage"])

        assert (
            gate._spent_grants_removed(
                gate._report_totals(base_report), gate._report_totals(candidate_report), {}
            )
            == []
        )

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    def test_a_malformed_candidate_file_fails_the_push_closed(
        self, gate, repo, tmp_path, monkeypatch, capsys
    ) -> None:
        """The two findings meet here. A candidate file the base will refuse
        must not pass on this path either — and it must refuse, not raise: a
        traceback is not a gate verdict, and the two read differently in a log.
        """
        root = repo(28.2327, grant_at_base="design_coverage@15.0", banked=15.0)
        _write_grants(root, {"design_coverage@15.0": {}})
        self._floors(gate, monkeypatch, 15.0)
        base_report, candidate_report = self._reports(tmp_path, 15.0)

        assert (
            gate._guard_actual_base(base_report, candidate_report, "base-sha", check_retention=True)
            == 1
        )
        assert "missing owner, issue, reason" in capsys.readouterr().out

    @pytest.mark.ac("SPEC-082926-6f49/AC-11")
    @pytest.mark.parametrize(
        ("event", "ref", "expected"),
        [("push", "refs/heads/develop", True), ("merge_group", "refs/heads/develop", False)],
    )
    def test_main_asks_for_retention_only_on_a_protected_push(
        self, gate, tmp_path, monkeypatch, event: str, ref: str, expected: bool
    ) -> None:
        """The wiring, not the decision. `_spent_grants_removed` being right
        while `main` never turns it on is the shape this repository's gates
        exist to catch — and it is the shape the guard was in before #685,
        since `--ratchet` was stripped and nothing else asked.
        """
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        monkeypatch.setenv("GITHUB_REF", ref)
        # The constant, not a guessed literal (Codex, #693). `_measure_base`
        # sets this while running `check-ac-state.py --run-tests`, so an
        # AC-marked test launched by that run inherits it; deleting the wrong
        # name left `main` returning early on the recursion guard, the mocked
        # guard uncalled, and this criterion graded unproven in the very base
        # measurement it exists to protect.
        monkeypatch.delenv(gate._BASE_MEASUREMENT, raising=False)
        monkeypatch.setattr(gate, "_actual_base_revision", lambda: "base-sha")
        monkeypatch.setattr(gate, "_measure_base", lambda base_rev, report: None)
        monkeypatch.setattr(gate._impl, "main", lambda argv: 0)
        seen: list[bool] = []

        def guard(base_report, candidate_report, base_rev, *, check_retention=False):
            seen.append(check_retention)
            return 0

        monkeypatch.setattr(gate, "_guard_actual_base", guard)

        assert gate.main(["--ratchet", "--out", str(tmp_path / "out.json")]) == 0
        assert seen == [expected]


class TestPruningASpentGrantAndBankingAGainTogether:
    """SPEC-082926-6f49 AC-12 (#685 finding 3).

    #673 made pruning a spent grant possible, but only for a change that
    improved nothing: `_lowered` still applied the base grant to the exact
    target, so a candidate measuring above it read as unbanked slack and the PR
    whose only job was to prune could not also carry a gain.

    #692 is what closed it — the exact target is the grant-lowered fold *raised
    by the notes this change writes*, so the candidate's own measurement is
    what it is compared against. This pins that the combination works, because
    the two changes are separate and nothing else states the joint property.
    """

    @pytest.mark.ac("SPEC-082926-6f49/AC-12")
    def test_a_spent_grant_can_be_pruned_by_a_change_that_also_improves(self, gate, repo) -> None:
        """Codex's scenario on #673, verbatim: base fold and grant both at 15,
        candidate note and measurement at 20, and the grant gone from the
        candidate file."""
        repo(15.0, grant_at_base="design_coverage@15.0", grant_in_worktree=None, banked=20.0)

        assert _run(gate, 20.0) == 0

    @pytest.mark.ac("SPEC-082926-6f49/AC-12")
    def test_the_same_prune_without_the_improvement_still_passes(self, gate, repo) -> None:
        """The case #673 already allowed, which must not regress: pruning a
        grant the fold has overtaken, changing nothing else."""
        repo(15.0, grant_at_base="design_coverage@15.0", grant_in_worktree=None, banked=15.0)

        assert _run(gate, 15.0) == 0


class TestSupersededGrantsDirectly:
    """SPEC-083026-fcc9's own detection, at the function level.

    `_stale_grants`/`_removed_binding_grants` are complementary by
    `SPEC-082926-6f49`'s own design (its AC-9 test class documents the
    deadlock), so once a floored counter's honest growth outpaces a grant,
    no PR can ever remove it under the original mechanism: `counters[counter]
    > floor` holds for every future base, regardless of that base's own
    content or of what the removing change touches. `_superseded_grants` is
    the escape -- multiple *independent* already-landed notes, not the fold's
    `max`, each clearing the floor on their own.

    Real git history, not synthetic `Note` objects: Codex's #720 finding on
    the first version was exactly that a purely value-based count cannot tell
    "three files" from "three reviews", or "before the correction" from
    "after" -- and neither can a test that hands the function an in-memory
    list with no git behind it. These read `_superseded_grants` against a
    real repository built by the same `repo` fixture the rest of this file
    uses, per this file's own header on stubbed provenance going quiet.
    """

    def test_a_note_absent_from_git_history_is_ignored(self, gate, repo) -> None:
        """`_superseded_grants` reads only what `notes` names, but nothing
        stops a caller from handing it a note `load_notes()` never produced
        -- a hand-built list, a future caller's own construction. One with no
        landing commit at all must not crash the count or be mistaken for a
        well-provenanced one."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            extra_base_notes={"a": 20.0, "b": 20.0},
        )
        base_sha = gate.ac_state_notes.bounds().base_sha
        notes, _, _ = gate.ac_state_notes.load_notes(base=base_sha)
        phantom = gate.ac_state_notes.Note(
            name="phantom",
            branch="phantom",
            measured_with_tests=True,
            counters={"design_coverage": 99.0},
        )

        superseded = gate._superseded_grants(
            [*notes, phantom], {"design_coverage": 15.0}, base_sha=base_sha
        )

        assert superseded == {}, (
            "a and b alone are two -- short of three -- and phantom must not make three"
        )

    def test_no_grants_means_nothing_to_supersede(self, gate, repo) -> None:
        repo(20.0, grant_at_base="design_coverage@15.0", extra_base_notes={"a": 20.0})
        base_sha = gate.ac_state_notes.bounds().base_sha
        notes, _, _ = gate.ac_state_notes.load_notes(base=base_sha)

        assert gate._superseded_grants(notes, {}, base_sha=base_sha) == {}

    def test_no_base_sha_refuses_to_guess(self, gate, repo) -> None:
        """Landing history cannot be resolved without a revision to resolve it
        against -- the safe default is to count nothing, not to fall back to
        treating every note as equally provenanced."""
        repo(20.0, grant_at_base="design_coverage@15.0", extra_base_notes={"a": 20.0})
        notes, _, _ = gate.ac_state_notes.load_notes()

        assert gate._superseded_grants(notes, {"design_coverage": 15.0}, base_sha=None) == {}

    def test_note_landing_commits_tolerates_an_unreachable_root(self, gate) -> None:
        """`root` pointing nowhere makes `subprocess.run`'s `cwd` raise
        before git ever executes -- the helper absorbs that the same way a
        real git failure is absorbed, rather than propagating it into a
        caller whose job is only to compute supersession."""
        assert (
            gate._note_landing_commits(
                Path("quality/ac-state-notes"), "HEAD", root=Path("/nonexistent-root-xyz")
            )
            == {}
        )

    def test_note_landing_commits_tolerates_a_non_git_root(self, gate, tmp_path) -> None:
        """A real directory that is simply not a git repository fails with a
        non-zero exit rather than an exception -- the other failure shape
        the helper must absorb the same way."""
        assert (
            gate._note_landing_commits(Path("quality/ac-state-notes"), "HEAD", root=tmp_path) == {}
        )

    def test_grants_file_landing_commit_tolerates_an_unreachable_root(self, gate) -> None:
        assert gate._grants_file_landing_commit("HEAD", root=Path("/nonexistent-root-xyz")) is None

    def test_grants_file_landing_commit_tolerates_a_non_git_root(self, gate, tmp_path) -> None:
        assert gate._grants_file_landing_commit("HEAD", root=tmp_path) is None

    def test_commit_timestamps_tolerates_an_unreachable_root(self, gate) -> None:
        assert gate._commit_timestamps({"deadbeef"}, root=Path("/nonexistent-root-xyz")) == {}

    def test_commit_timestamps_tolerates_a_non_git_root(self, gate, tmp_path) -> None:
        assert gate._commit_timestamps({"deadbeef"}, root=tmp_path) == {}

    def test_an_unresolvable_grant_timestamp_supersedes_nothing(
        self, gate, repo, monkeypatch
    ) -> None:
        """The grant's own landing commit can resolve
        (`_grants_file_landing_commit` succeeds) while its timestamp still
        cannot -- `_commit_timestamps` failing for that one sha, in
        practice. Without a grant time to compare against, nothing can be
        said to land after it, so the count must not silently treat every
        note as later."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            extra_base_notes={"a": 20.0, "b": 20.0, "c": 20.0},
        )
        base_sha = gate.ac_state_notes.bounds().base_sha
        notes, _, _ = gate.ac_state_notes.load_notes(base=base_sha)
        monkeypatch.setattr(gate._impl, "_commit_timestamps", lambda shas, **kwargs: {})

        assert gate._superseded_grants(notes, {"design_coverage": 15.0}, base_sha=base_sha) == {}


class TestASupersededGrantCanBePruned:
    """SPEC-083026-fcc9.

    Verified against `develop` on 2026-08-30 before this was written: a grant
    at `design_coverage@27.8791` (#631/#662), a base fold of `31.7134`, and
    nineteen already-merged notes independently clearing it -- and no PR could
    remove the grant, because `_removed_binding_grants` refused for exactly
    the reason `counters[counter] > floor` names, on every base from then on.
    These pin the fix at the same real-repository granularity
    `SPEC-082926-6f49`'s own tests use, per this file's own header on stubbed
    provenance going quiet.
    """

    @pytest.mark.ac("SPEC-083026-fcc9/AC-1")
    @pytest.mark.ac("SPEC-083026-fcc9/AC-7")
    def test_fewer_than_three_independent_notes_do_not_excuse_removal(self, gate, repo) -> None:
        """`_baseline` lands in the same commit as the grant itself, so it
        never counts toward supersession (it is the record the grant exists
        beside, not independent evidence against it) -- two more, each in
        its own later commit, is still short of the three this spec
        requires, so the grant is still binding and removing it is still
        refused, exactly as before this spec existed."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=20.0,
            extra_base_notes={"other-one": 16.0, "other-two": 17.0},
        )

        assert _run(gate, 20.0) == 1

    @pytest.mark.ac("SPEC-083026-fcc9/AC-2")
    def test_three_independent_notes_fail_the_run_until_pruned(self, gate, repo, capsys) -> None:
        """The grant is still in the candidate's own file -- not yet pruned
        -- and the run fails and says why: independent landings, named, not
        the ordinary "bank it" message that sent #713/#715/#720 looking in
        the wrong place three times."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            banked=20.0,
            extra_base_notes={"n1": 16.0, "n2": 17.0, "n3": 18.0},
        )

        assert _run(gate, 20.0) == 1
        out = capsys.readouterr().out
        assert "authorized floor(s) independent landings have superseded" in out
        assert "design_coverage" in out
        assert "n1" in out and "n2" in out and "n3" in out

    @pytest.mark.ac("SPEC-083026-fcc9/AC-3")
    def test_a_superseded_grant_may_be_pruned(self, gate, repo) -> None:
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=20.0,
            extra_base_notes={"n1": 16.0, "n2": 17.0, "n3": 18.0},
        )

        assert _run(gate, 20.0) == 0

    @pytest.mark.ac("SPEC-083026-fcc9/AC-4")
    def test_pruning_a_superseded_grant_needs_no_fresh_note_of_its_own(self, gate, repo) -> None:
        """No `banked=` at all -- this change only edits the grants file --
        and the run still passes, because the comparison excludes a
        superseded grant entirely rather than relying on a fresh note to
        outrun it (the shape SPEC-082926-6f49 AC-12 already closed for the
        ordinary case, reopened here for supersession)."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            extra_base_notes={"n1": 16.0, "n2": 17.0, "n3": 18.0},
        )

        assert _run(gate, 20.0) == 0

    @pytest.mark.ac("SPEC-083026-fcc9/AC-5")
    def test_the_candidates_own_note_cannot_manufacture_supersession(self, gate, repo) -> None:
        """Two independent base notes, each in its own later commit -- short
        of three -- plus this change's own measurement, well above the
        grant. Three by a naive count, but the candidate's own claim about
        itself must not count toward supersession: removal is still
        refused."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=25.0,
            extra_base_notes={"n1": 16.0, "n2": 17.0},
        )

        assert _run(gate, 25.0) == 1

    def test_a_note_exactly_at_the_floor_does_not_count(self, gate, repo) -> None:
        """`>`, not `>=`: a note naming the grant's own value is not evidence
        against it -- it is the fall the grant permits, taken."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=15.0,
            extra_base_notes={"n1": 15.0, "n2": 15.0, "n3": 15.0},
        )

        assert _run(gate, 15.0) == 1

    @pytest.mark.ac("SPEC-083026-fcc9/AC-8")
    def test_notes_landed_in_one_commit_count_as_one_landing(self, gate, repo) -> None:
        """Three note files added in a single commit are one review, not
        three -- this repository's own squash-merge convention makes "one
        commit" and "one merged PR" the same fact (Codex, #720). Short of
        the three independent landings this spec requires, so removal is
        still refused even though three *files* clear the floor."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=20.0,
            bundled_extra_notes={"n1": 16.0, "n2": 17.0, "n3": 18.0},
        )

        assert _run(gate, 20.0) == 1

    @pytest.mark.ac("SPEC-083026-fcc9/AC-8")
    def test_one_bundled_commit_plus_two_independent_ones_supersedes(
        self, gate, repo, capsys
    ) -> None:
        """The bundle is one landing; two more independent ones make three,
        and the grant is superseded -- distinct landings, not distinct
        files, is what the threshold counts."""
        repo(
            20.0,
            grant_at_base="design_coverage@15.0",
            grant_in_worktree=None,
            banked=20.0,
            extra_base_notes={"n1": 16.0, "n2": 17.0},
            bundled_extra_notes={"n3": 18.0, "n4": 19.0},
        )

        assert _run(gate, 20.0) == 0

    @pytest.mark.ac("SPEC-083026-fcc9/AC-6")
    def test_a_grant_with_no_independent_notes_above_it_is_unaffected(self, gate, repo) -> None:
        """No extra base notes at all -- the ordinary case this spec must not
        change. Removal while still binding is refused exactly as
        SPEC-082926-6f49 AC-8 already established."""
        repo(20.0, grant_at_base="design_coverage@15.0", grant_in_worktree=None, banked=20.0)

        assert _run(gate, 20.0) == 1
