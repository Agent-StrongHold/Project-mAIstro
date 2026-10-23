"""Published evidence manifests: trace, manifest, refused diffs (#104 M4-G).

The manifest is the artifact the epic actually asks for: a falsifiable record
of what a run did, with every section checksummed and every unquotable claim
refused. These tests check the refusals (what the manifest will *not* carry)
as carefully as the happy path, because the refusals are the point.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro_evolve.eval_metering import RunMetering, attach_run_metering
from maistro_evolve.evidence_manifest import (
    MANIFEST_VERSION,
    SECTION_NAMES,
    ManifestVerificationError,
    RefusedDiff,
    _sha256,
    build_evidence_manifest,
    load_evidence_manifest,
    publish_evidence_manifest,
    verify_evidence_manifest,
)
from maistro_evolve.lift_matrix import LiftReport
from maistro_evolve.types import EvalResult
from maistro_evolve.verdict_probes import run_conformance


def _result(
    benchmark: str = "proxy_ifeval",
    *,
    score: float = 0.42,
    samples: int = 10,
    metadata: dict | None = None,
) -> EvalResult:
    return EvalResult(
        benchmark=benchmark,
        score=score,
        cost_usd=0.02,
        duration_seconds=1.0,
        samples_evaluated=samples,
        metadata=metadata or {},
    )


def _lift_report(**overrides) -> LiftReport:
    base = {
        "benchmark": "proxy_ifeval",
        "baseline_version": "baseline-v1",
        "w_base": 0.20,
        "w_evo": 0.50,
        "f_base": 0.80,
        "f_evo": 0.85,
        "lift": 0.30,
        "gap": 0.60,
        "gap_closure": 0.5,
        "transfer": 0.05,
        "inversion": False,
        "transfer_stale": False,
    }
    base.update(overrides)
    return LiftReport(**base)


def _manifest(**kwargs):
    params = {
        "run_id": "run-1",
        "results": [_result()],
        "lift_reports": [_lift_report()],
        "verdict_conformance": run_conformance(),
        "metering": RunMetering(
            cost_usd=0.02,
            duration_seconds=1.0,
            samples_evaluated=10,
            security_events={},
            security_tax=0.0,
            gaming_signals={},
            rhae_estimate=0.0,
            unresolved_security_violations=0,
        ),
    }
    params.update(kwargs)
    return build_evidence_manifest(**params)


class TestBuild:
    def test_a_well_formed_manifest_verifies(self) -> None:
        manifest = _manifest()
        assert manifest["manifest_version"] == MANIFEST_VERSION
        assert manifest["run_id"] == "run-1"
        assert verify_evidence_manifest(manifest) == []

    def test_a_manifest_without_a_conformance_report_is_refused(self) -> None:
        """The verdict must be shown host-owned *before* publication."""
        with pytest.raises(ValueError, match="verdict-conformance report"):
            build_evidence_manifest(
                "run-1",
                [_result()],
                lift_reports=[_lift_report()],
                metering=RunMetering(
                    cost_usd=0.0,
                    duration_seconds=0.0,
                    samples_evaluated=1,
                    security_events={},
                    security_tax=0.0,
                    gaming_signals={},
                    rhae_estimate=0.0,
                    unresolved_security_violations=0,
                ),
            )

    def test_a_failing_conformance_report_is_refused(self) -> None:
        report = run_conformance([])
        with pytest.raises(ValueError, match="does not hold"):
            build_evidence_manifest("run-1", [_result()], verdict_conformance=report)

    def test_a_score_with_zero_samples_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unquotable"):
            build_evidence_manifest(
                "run-1",
                [_result(samples=0, score=0.5)],
                verdict_conformance=run_conformance(),
                metering_absent_reason="no metering in this run",
            )

    def test_a_numeric_gap_closure_without_a_baseline_version_is_refused(self) -> None:
        with pytest.raises(ValueError, match="without baseline_version"):
            build_evidence_manifest(
                "run-1",
                [_result()],
                lift_reports=[_lift_report(baseline_version="")],
                verdict_conformance=run_conformance(),
                metering_absent_reason="no metering in this run",
            )

    def test_an_absent_gap_closure_survives_to_publication(self) -> None:
        """``None`` means "this benchmark cannot measure lift"; it must not
        become 0.0 on the way to the manifest."""
        manifest = _manifest(lift_reports=[_lift_report(gap_closure=None, gap=0.0)])
        row = manifest["lift"][0]
        assert row["gap_closure"] is None
        assert verify_evidence_manifest(manifest) == []


class TestMetering:
    def test_metering_is_read_back_off_the_results(self) -> None:
        results = [_result(), _result(benchmark="proxy_bfcl")]
        attach_run_metering(results)
        manifest = build_evidence_manifest(
            "run-1",
            results,
            verdict_conformance=run_conformance(),
        )
        assert manifest["metering"]["samples_evaluated"] == 20
        assert manifest["metering_absent_reason"] is None
        assert verify_evidence_manifest(manifest) == []

    def test_results_that_disagree_about_the_run_are_refused(self) -> None:
        """Two different costs in one run did not measure one run."""
        first = _result()
        second = _result(benchmark="proxy_bfcl")
        attach_run_metering([first, second])
        second.run_metering = dict(second.run_metering or {})
        second.run_metering["cost_usd"] = 99.0
        with pytest.raises(ValueError, match="different metered blocks"):
            build_evidence_manifest(
                "run-1",
                [first, second],
                verdict_conformance=run_conformance(),
            )

    def test_absent_metering_must_be_explained(self) -> None:
        with pytest.raises(ValueError, match="metering_absent_reason"):
            build_evidence_manifest(
                "run-1",
                [_result()],
                verdict_conformance=run_conformance(),
            )

    def test_metering_cannot_be_both_present_and_absent(self) -> None:
        with pytest.raises(ValueError, match="cannot claim both"):
            build_evidence_manifest(
                "run-1",
                [_result()],
                verdict_conformance=run_conformance(),
                metering=RunMetering(
                    cost_usd=0.0,
                    duration_seconds=0.0,
                    samples_evaluated=1,
                    security_events={},
                    security_tax=0.0,
                    gaming_signals={},
                    rhae_estimate=0.0,
                    unresolved_security_violations=0,
                ),
                metering_absent_reason="actually not measured",
            )

    def test_an_explicit_absence_reason_is_published(self) -> None:
        manifest = build_evidence_manifest(
            "run-1",
            [_result()],
            verdict_conformance=run_conformance(),
            metering_absent_reason="the run was a replay of a recorded trace",
        )
        assert manifest["metering"] is None
        assert manifest["metering_absent_reason"].startswith("the run was a replay")
        assert verify_evidence_manifest(manifest) == []


class TestRefusalsArePublished:
    def test_a_refused_diff_is_published_with_its_reason(self) -> None:
        manifest = _manifest(
            refused_diffs=[
                RefusedDiff(
                    candidate_id="cand-7",
                    diff="--- a\n+++ b\n",
                    reason="patch touches the policy gate",
                )
            ]
        )
        assert manifest["refused_diffs"][0]["candidate_id"] == "cand-7"
        assert manifest["refused_diffs"][0]["reason"] == "patch touches the policy gate"
        assert verify_evidence_manifest(manifest) == []

    def test_a_refusal_without_a_reason_does_not_verify(self) -> None:
        manifest = _manifest()
        manifest["refused_diffs"] = [{"candidate_id": "cand-7", "diff": "x", "reason": "  "}]
        errors = verify_evidence_manifest(manifest)
        assert any("refusal without a reason" in e for e in errors)


class TestTrace:
    def test_the_trace_records_every_phase_in_order(self) -> None:
        manifest = _manifest(
            refused_diffs=[
                RefusedDiff(candidate_id="cand-7", diff="x", reason="policy refused"),
            ]
        )
        phases = [event["phase"] for event in manifest["trace"]]
        assert phases[0] == "evaluate"
        assert phases[-1] == "refuse"
        assert set(phases) == {"evaluate", "compare", "verify-verdict", "refuse"}
        assert [event["step"] for event in manifest["trace"]] == list(
            range(1, len(manifest["trace"]) + 1)
        )

    def test_the_trace_narrates_the_numbers_it_is_built_from(self) -> None:
        """The trace is derived, so it cannot contradict the manifest."""
        manifest = _manifest()
        compare = next(e for e in manifest["trace"] if e["phase"] == "compare")
        assert "lift 0.3" in compare["detail"]
        assert "gap 0.6" in compare["detail"]

    def test_an_empty_trace_does_not_verify(self) -> None:
        manifest = _manifest()
        manifest["trace"] = []
        assert any(
            "trace section missing or empty" in e for e in verify_evidence_manifest(manifest)
        )

    def test_an_out_of_order_trace_does_not_verify(self) -> None:
        manifest = _manifest()
        manifest["trace"][1]["step"] = 7
        assert any("out of order" in e for e in verify_evidence_manifest(manifest))


class TestTamperDetection:
    def test_editing_a_section_breaks_its_checksum(self) -> None:
        manifest = _manifest()
        manifest["results"][0]["score"] = 0.99
        errors = verify_evidence_manifest(manifest)
        assert any("does not match its checksum" in e for e in errors)

    def test_editing_the_run_id_breaks_the_manifest_checksum(self) -> None:
        manifest = _manifest()
        manifest["run_id"] = "run-2"
        errors = verify_evidence_manifest(manifest)
        assert any("manifest checksum does not match" in e for e in errors)

    def test_dropping_the_conformance_section_is_detected(self) -> None:
        manifest = _manifest()
        manifest["verdict_conformance"] = []
        errors = verify_evidence_manifest(manifest)
        assert any("verdict_conformance section missing or empty" in e for e in errors)

    def test_a_manifest_without_checksums_is_not_verifiable(self) -> None:
        manifest = _manifest()
        del manifest["checksums"]
        assert verify_evidence_manifest(manifest) == [
            "manifest has no checksums section — not a verifiable artifact"
        ]

    def test_a_conformance_row_that_accepted_a_hostile_response_does_not_verify(self) -> None:
        manifest = _manifest()
        manifest["verdict_conformance"][0]["hostile_rejected"] = 0
        errors = verify_evidence_manifest(manifest)
        assert any("hostile" in e for e in errors)


class TestSectionRules:
    """The refusal rules, each judged on its own.

    Every case here re-seals the manifest after the tamper, so the rule under
    test is the one that fires — not the checksum that notices the edit.
    """

    @staticmethod
    def _reseal(manifest: dict) -> dict:
        checksums = {
            name: _sha256(manifest[name])
            for name in SECTION_NAMES
            if manifest.get(name) is not None
        }
        checksums["manifest"] = _sha256({"run_id": manifest.get("run_id"), **checksums})
        manifest["checksums"] = checksums
        return manifest

    def test_a_section_that_was_never_written_is_not_a_checksum_error(self) -> None:
        """An absent section was never checksummed; its absence is judged by
        the section rules, not by a checksum that was never recorded."""
        manifest = _manifest()
        del manifest["lift"]
        assert verify_evidence_manifest(manifest) == []

    def test_results_must_be_a_non_empty_list(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["results"] = []
        errors = verify_evidence_manifest(manifest)
        assert any("results section missing or empty" in e for e in errors)

    def test_a_results_row_that_is_not_an_object_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["results"] = ["proxy_ifeval scored 0.42"]
        errors = verify_evidence_manifest(manifest)
        assert any("results row is not an object" in e for e in errors)

    def test_a_result_without_a_sample_count_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        del manifest["results"][0]["samples_evaluated"]
        errors = verify_evidence_manifest(manifest)
        assert any("no samples_evaluated" in e for e in errors)

    def test_a_negative_sample_count_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["results"][0]["samples_evaluated"] = -3
        errors = verify_evidence_manifest(manifest)
        assert any("must be a non-negative int" in e for e in errors)

    def test_a_score_with_zero_samples_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["results"][0]["samples_evaluated"] = 0
        manifest["results"][0]["score"] = 0.42
        errors = verify_evidence_manifest(manifest)
        assert any("zero samples evaluated is unquotable" in e for e in errors)

    def test_a_zero_sample_result_with_a_zero_score_is_not_unquotable(self) -> None:
        """Nothing was evaluated and nothing was claimed: that is honest, and
        the rule must not fire on it."""
        manifest = self._reseal(_manifest())
        manifest["results"][0]["samples_evaluated"] = 0
        manifest["results"][0]["score"] = 0.0
        errors = verify_evidence_manifest(manifest)
        assert not any("unquotable" in e for e in errors)

    def test_the_lift_section_must_be_a_list(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["lift"] = {"proxy_ifeval": 0.3}
        errors = verify_evidence_manifest(manifest)
        assert any("lift section is not a list" in e for e in errors)

    def test_a_lift_row_that_is_not_an_object_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["lift"] = ["lift 0.3"]
        errors = verify_evidence_manifest(manifest)
        assert any("lift row is not an object" in e for e in errors)

    def test_a_numeric_gap_closure_without_a_baseline_version_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["lift"][0]["baseline_version"] = ""
        errors = verify_evidence_manifest(manifest)
        assert any("without baseline_version" in e for e in errors)

    def test_a_non_numeric_gap_closure_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["lift"][0]["gap_closure"] = "half"
        errors = verify_evidence_manifest(manifest)
        assert any("gap_closure must be a number or null" in e for e in errors)

    def test_a_lift_row_without_a_transfer_is_refused(self) -> None:
        """Without the transfer column an inversion cannot be detected."""
        manifest = self._reseal(_manifest())
        del manifest["lift"][0]["transfer"]
        errors = verify_evidence_manifest(manifest)
        assert any("no transfer" in e for e in errors)

    def test_a_conformance_row_that_is_not_an_object_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["verdict_conformance"] = ["all hostile responses rejected"]
        errors = verify_evidence_manifest(manifest)
        assert any("verdict_conformance row is not an object" in e for e in errors)

    def test_a_conformance_row_without_hostile_probes_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["verdict_conformance"][0]["hostile_total"] = 0
        errors = verify_evidence_manifest(manifest)
        assert any("no hostile responses were probed" in e for e in errors)

    def test_a_conformance_row_that_accepted_a_hostile_response_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["verdict_conformance"][0]["hostile_rejected"] = 0
        errors = verify_evidence_manifest(manifest)
        assert any("hostile responses rejected" in e for e in errors)

    def test_a_conformance_row_whose_mutant_survived_is_refused(self) -> None:
        """A permissive grader that survived the corpus proves nothing."""
        manifest = self._reseal(_manifest())
        manifest["verdict_conformance"][0]["mutant_killed"] = False
        errors = verify_evidence_manifest(manifest)
        assert any("mutant survived" in e for e in errors)

    def test_a_conformance_row_reported_as_not_passed_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["verdict_conformance"][0]["passed"] = False
        errors = verify_evidence_manifest(manifest)
        assert any("reported as not passed" in e for e in errors)

    def test_the_refused_diffs_section_must_be_a_list(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["refused_diffs"] = "none"
        errors = verify_evidence_manifest(manifest)
        assert any("refused_diffs section is not a list" in e for e in errors)

    def test_a_trace_event_that_is_not_an_object_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["trace"][0] = "evaluated the benchmark"
        errors = verify_evidence_manifest(manifest)
        assert any("trace event is not an object" in e for e in errors)

    def test_a_trace_event_without_a_phase_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["trace"][0]["phase"] = "  "
        errors = verify_evidence_manifest(manifest)
        assert any("no phase" in e for e in errors)

    def test_a_trace_event_without_a_detail_is_refused(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["trace"][0]["detail"] = ""
        errors = verify_evidence_manifest(manifest)
        assert any("no detail" in e for e in errors)

    def test_absent_metering_without_a_reason_does_not_verify(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["metering"] = None
        manifest["metering_absent_reason"] = ""
        errors = verify_evidence_manifest(manifest)
        assert any("metering absent without metering_absent_reason" in e for e in errors)

    def test_metering_present_alongside_an_absence_reason_does_not_verify(self) -> None:
        manifest = self._reseal(_manifest())
        manifest["metering_absent_reason"] = "actually not measured"
        errors = verify_evidence_manifest(manifest)
        assert any("metering present alongside metering_absent_reason" in e for e in errors)


class TestPublish:
    def test_publishing_writes_a_manifest_that_loads_back(self, tmp_path: Path) -> None:
        manifest = _manifest()
        target = publish_evidence_manifest(manifest, tmp_path)
        assert target.name == "manifest.json"
        loaded = load_evidence_manifest(target)
        assert loaded["run_id"] == "run-1"
        assert loaded["checksums"] == manifest["checksums"]

    def test_publishing_refuses_a_manifest_that_does_not_verify(self, tmp_path: Path) -> None:
        manifest = _manifest()
        manifest["results"][0]["score"] = 0.99
        with pytest.raises(ManifestVerificationError, match="refusing to publish"):
            publish_evidence_manifest(manifest, tmp_path)
        assert not (tmp_path / "manifest.json").exists()

    def test_loading_a_tampered_file_raises(self, tmp_path: Path) -> None:
        manifest = _manifest()
        target = publish_evidence_manifest(manifest, tmp_path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["results"][0]["score"] = 0.99
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ManifestVerificationError, match="does not match its checksum"):
            load_evidence_manifest(target)

    def test_loading_a_non_object_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ManifestVerificationError, match="not a JSON object"):
            load_evidence_manifest(path)
