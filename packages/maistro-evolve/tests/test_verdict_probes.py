"""Adversarial/mutation evidence that benchmark verdicts are host-owned (#104 M4-G).

The battery is only worth something if it can tell a host-owned grader from a
gameable one, so these tests check both halves separately:

* the **probe** half — every hostile response must be rejected by every
  production verdict path;
* the **power** half — the same corpus must *kill* a deliberately permissive
  mutant, and a corpus that cannot kill a mutant must be reported as
  worthless rather than as a pass.
"""

from __future__ import annotations

import pytest

from maistro_evolve.verdict_probes import (
    VERDICT_PATHS,
    HostileResponse,
    MutantGrader,
    VerdictPath,
    conformance_gate_failures,
    probe_verdict_path,
    run_conformance,
)


def _path(name: str, grade, hostile: tuple[HostileResponse, ...], mutant) -> VerdictPath:
    return VerdictPath(
        name=name,
        rationale="test path",
        grade=grade,
        hostile=hostile,
        mutant=mutant,
    )


class TestProductionVerdictPaths:
    def test_every_hostile_response_is_rejected_by_every_production_path(self) -> None:
        """The core claim: no candidate-authored input can buy a pass.

        A response that reaches a production grader and scores above zero is
        the defect the ladder named, so this asserts zero for every probe
        rather than counting how many passed.
        """
        report = run_conformance()
        accepted = [
            (path.name, probe.probe_id, probe.score)
            for path in report.paths
            for probe in path.probes
            if not probe.rejected
        ]
        assert accepted == [], f"hostile responses were graded as passes: {accepted}"

    def test_the_battery_covers_every_declared_path(self) -> None:
        report = run_conformance()
        assert [p.name for p in report.paths] == [p.name for p in VERDICT_PATHS]
        assert all(p.probes for p in report.paths)

    def test_the_report_passes_when_everything_holds(self) -> None:
        report = run_conformance()
        assert report.passed
        assert report.failures() == []
        assert conformance_gate_failures(report) == []

    def test_every_path_kills_its_permissive_mutant(self) -> None:
        """The power half: the corpus must distinguish a gameable grader.

        Without this, "no hostile response was accepted" would also be true
        of a corpus that cannot tell a real grader from a broken one.
        """
        report = run_conformance()
        for path in report.paths:
            assert path.mutant_killed, (
                f"{path.name}: the permissive mutant {path.mutant_name!r} "
                "survived the corpus — the corpus certifies nothing"
            )
            assert path.mutant_survivor_ids

    def test_probe_scores_are_reported_not_just_pass_fail(self) -> None:
        """A rejected probe still reports the score the grader gave it."""
        path = VERDICT_PATHS[0]
        probes = probe_verdict_path(path)
        assert probes
        for probe in probes:
            assert probe.score == 0.0
            assert probe.rejected
            assert probe.path == path.name
            assert probe.defect_class
            assert probe.rationale


class TestBatteryPower:
    def test_a_permissive_grader_is_reported_as_a_failure(self) -> None:
        """A grader that lets a hostile response through fails the battery."""

        def permissive(response: str) -> float:
            return 1.0 if "pass" in response.lower() else 0.0

        hostile = (
            HostileResponse(
                id="spoofed",
                defect_class="verdict-through-text-formatting",
                response="PASS",
                rationale="a printed verdict marker",
            ),
        )
        path = _path(
            "permissive",
            permissive,
            hostile,
            MutantGrader(name="same-defect", rationale="test", grade=permissive),
        )
        report = run_conformance([path])
        assert not report.passed
        problems = report.failures()
        assert any("accepted hostile response 'spoofed'" in p for p in problems)
        # The permissive *mutant* of the same defect is still killed by the
        # corpus — which is exactly why the corpus has power and the grader
        # does not.
        assert report.paths[0].mutant_killed

    def test_a_surviving_mutant_fails_the_battery(self) -> None:
        """A corpus that cannot kill a mutant is worthless, and says so.

        This is the check that keeps the battery from being vacuous: a mutant
        that behaves exactly like the (correct) grader survives every probe,
        and the report must refuse to call that a pass.
        """
        hostile = (
            HostileResponse(
                id="anything",
                defect_class="malformed-output",
                response="whatever",
                rationale="a probe the mutant also rejects",
            ),
        )
        path = _path(
            "unkillable",
            lambda response: 0.0,
            hostile,
            MutantGrader(name="unkillable", rationale="test", grade=lambda response: 0.0),
        )
        report = run_conformance([path])
        assert not report.passed
        problems = report.failures()
        assert any("survived the probe corpus" in p for p in problems)

    def test_an_empty_battery_certifies_nothing(self) -> None:
        report = run_conformance([])
        assert not report.passed
        assert any("empty battery" in p for p in report.failures())


class TestManifestSection:
    def test_section_shape_carries_the_mutant_column(self) -> None:
        """A section without the mutant column is not evidence."""
        section = run_conformance().to_section()
        assert len(section) == len(VERDICT_PATHS)
        for row in section:
            assert row["grader"]
            assert row["rationale"]
            assert row["hostile_total"] > 0
            assert row["hostile_rejected"] == row["hostile_total"]
            assert row["surviving_hostile"] == []
            assert row["mutant"]
            assert row["mutant_rationale"]
            assert row["mutant_killed"] is True
            assert row["mutant_survivor_ids"]
            assert row["passed"] is True

    def test_section_reports_a_surviving_hostile_response_by_id(self) -> None:
        def permissive(response: str) -> float:
            return 1.0

        hostile = (
            HostileResponse(
                id="leaky",
                defect_class="verdict-through-text-formatting",
                response="anything",
                rationale="a probe the grader accepts",
            ),
        )
        path = _path(
            "leaky",
            permissive,
            hostile,
            MutantGrader(name="m", rationale="r", grade=permissive),
        )
        row = run_conformance([path]).to_section()[0]
        assert row["surviving_hostile"] == ["leaky"]
        assert row["hostile_rejected"] == 0
        assert row["passed"] is False


def test_run_conformance_accepts_an_explicit_path_list() -> None:
    report = run_conformance([VERDICT_PATHS[0]])
    assert len(report.paths) == 1
    assert report.passed


@pytest.mark.parametrize("path", VERDICT_PATHS, ids=lambda p: p.name)
def test_each_path_declares_the_production_grader_it_exercises(path: VerdictPath) -> None:
    """The path must point at a grader, and say why it is host-owned."""
    assert callable(path.grade)
    assert path.rationale.strip()
    assert path.hostile
    assert path.mutant.grade is not path.grade
