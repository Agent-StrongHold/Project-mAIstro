"""The runner, the family registry, and the machine-readable report (#974)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from maistro_ext_harness import REPORT_SCHEMA, RunRequest
from maistro_ext_harness.backends import Backend, BackendRegistry
from maistro_ext_harness.contract import CONTRACT_VERSION, FAMILIES
from maistro_ext_harness.families import (
    CaseOutcome,
    ConformanceCase,
    FamilyPlugin,
    available_families,
    family_cases,
    family_plugin,
    register_family,
    shared_cases,
)
from maistro_ext_harness.manifest import ManifestRejected
from maistro_ext_harness.runner import run_conformance


def _report(root: Path, **kwargs: object) -> object:
    request = RunRequest(subject=root, **kwargs)  # type: ignore[arg-type]
    return run_conformance(request)


def test_every_documented_family_has_a_plugin_with_cases() -> None:
    assert set(available_families()) == set(FAMILIES)
    for family in FAMILIES:
        cases = family_cases(family)
        shared = {case.case_id for case in shared_cases()}
        assert shared <= {case.case_id for case in cases}, family


def test_tool_family_adds_handler_cases() -> None:
    ids = {case.case_id for case in family_plugin("tool").extra_cases}
    assert "tool/handler-invocation-succeeds" in ids
    assert "tool/handler-repeat-invocation-stable" in ids


def test_registering_an_unknown_family_is_rejected() -> None:
    with pytest.raises(Exception, match="closed family"):
        register_family(FamilyPlugin(family="not-a-family", extra_cases=()))


def test_registered_family_cases_join_the_suite(conforming_extension: Path) -> None:
    """The reuse seam: a plug-in adds a case without touching the engine."""
    custom = ConformanceCase(
        case_id="acme/always-passes",
        description="a third-party family plug-in's own case",
        run=lambda env: CaseOutcome(True, "ran"),
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, custom)))
    try:
        report = _report(conforming_extension)
        ids = {case.case_id for case in report.cases}
        assert "acme/always-passes" in ids
    finally:
        register_family(original)


def test_family_scoped_cases_only_run_for_their_families(conforming_extension: Path) -> None:
    """A case scoped via its `families` field runs only for those families,
    even when a shared plug-in ships it."""
    scoped = ConformanceCase(
        case_id="acme/skill-only",
        description="a case only the skill family runs",
        run=lambda env: CaseOutcome(True, "ran"),
        families=("skill",),
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, scoped)))
    try:
        tool_ids = {case.case_id for case in family_cases("tool")}
    finally:
        register_family(original)
    assert "acme/skill-only" not in tool_ids


def test_report_summarizes_subject_contracts_and_required_backends(
    conforming_extension: Path,
) -> None:
    report = _report(conforming_extension)
    data = report.to_dict()
    assert data["subject_contracts"] == [">=1.0.0,<2.0.0"]
    assert data["required_backends"] == []


def test_report_names_contract_version_and_certification_distinction(
    conforming_extension: Path,
) -> None:
    report = _report(conforming_extension)
    data = report.to_dict()
    assert data["report_schema"] == REPORT_SCHEMA
    assert data["contract_version"] == CONTRACT_VERSION
    assert data["supported_contract_majors"] == [1]
    assert data["certification"]["platform_certified"] is False
    assert "NOT platform certification" in data["certification"]["note"]
    assert data["summary"]["failed"] == 0


def test_report_lists_every_case_with_status_and_reason(
    conforming_extension: Path,
) -> None:
    report = _report(conforming_extension)
    data = report.to_dict()
    assert data["summary"]["total"] == len(data["cases"])
    for case in data["cases"]:
        assert case["status"] in {"passed", "failed", "skipped"}
        assert case["detail"]


def test_dual_subject_run_uses_the_same_case_ids(conforming_extension: Path) -> None:
    """Acceptance: the same case runs against the reference built-in and the
    external implementation."""
    report = _report(conforming_extension, with_reference=True)
    data = report.to_dict()
    roles = {subject["role"] for subject in data["subjects"]}
    assert roles == {"external", "reference"}
    by_case: dict[str, set[str]] = {}
    for case in data["cases"]:
        by_case.setdefault(case["case_id"], set()).add(case["subject"])
    for case_id, subjects in by_case.items():
        if case_id.startswith("harness/"):
            continue  # harness self-checks are subject-independent by design
        assert subjects == {"external", "reference"}, case_id


def test_manifest_rejection_is_typed_before_any_code_runs(
    make_extension: Callable[..., Path], valid_manifest: dict[str, Any]
) -> None:
    root = make_extension(manifest={**valid_manifest, "family": "nope"})
    with pytest.raises(ManifestRejected):
        _report(root)


def test_requested_family_must_match_the_manifest(conforming_extension: Path) -> None:
    with pytest.raises(Exception, match="declared family"):
        _report(conforming_extension, family="skill")


def test_case_exception_is_contained_as_a_failed_record(
    conforming_extension: Path,
) -> None:
    broken = ConformanceCase(
        case_id="acme/buggy-case",
        description="a case whose implementation itself raises",
        run=lambda env: 1 / 0,
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, broken)))
    try:
        report = _report(conforming_extension)
    finally:
        register_family(original)
    failed = [case for case in report.cases if case.case_id == "acme/buggy-case"]
    assert len(failed) == 1
    assert failed[0].status.value == "failed"
    assert "ZeroDivisionError" in failed[0].detail
    # Containment: the run completed — every other case still has a verdict.
    assert report.failed
    assert report.passed_count > 0


def test_required_backend_fails_closed_when_absent(conforming_extension: Path) -> None:
    """Acceptance: a real-backend case with no backend FAILS — it does not
    silently skip, which would dress an unverified property as a result."""
    gated = ConformanceCase(
        case_id="acme/needs-real-service",
        description="a property that cannot be mocked honestly",
        run=lambda env: CaseOutcome(True, "ran against the real service"),
        requires_backend="acme-real-service",
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
    try:
        report = _report(conforming_extension)
    finally:
        register_family(original)
    records = [case for case in report.cases if case.case_id == "acme/needs-real-service"]
    assert records[0].status.value == "failed"
    assert "acme-real-service" in records[0].detail


def test_waived_backend_skips_explicitly_and_is_recorded(
    conforming_extension: Path,
) -> None:
    gated = ConformanceCase(
        case_id="acme/needs-real-service",
        description="a property that cannot be mocked honestly",
        run=lambda env: CaseOutcome(True, "ran against the real service"),
        requires_backend="acme-real-service",
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
    try:
        backends = BackendRegistry(
            backends={"acme-real-service": Backend("acme-real-service", probe=lambda: False)},
            waivers=frozenset({"acme-real-service"}),
        )
        report = _report(conforming_extension, backends=backends)
    finally:
        register_family(original)
    records = [case for case in report.cases if case.case_id == "acme/needs-real-service"]
    assert records[0].status.value == "skipped"
    assert "did NOT execute" in records[0].detail
    assert report.backend_waivers == ("acme-real-service",)


def test_registered_and_probed_backend_lets_the_case_execute(
    conforming_extension: Path,
) -> None:
    gated = ConformanceCase(
        case_id="acme/needs-real-service",
        description="a property that cannot be mocked honestly",
        run=lambda env: CaseOutcome(env.backends.probe("acme-real-service"), "probed"),
        requires_backend="acme-real-service",
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
    try:
        backends = BackendRegistry()
        backends.register(Backend("acme-real-service", probe=lambda: True))
        report = _report(conforming_extension, backends=backends)
    finally:
        register_family(original)
    records = [case for case in report.cases if case.case_id == "acme/needs-real-service"]
    assert records[0].status.value == "passed"


def test_report_json_is_stable_and_writable(conforming_extension: Path, tmp_path: Path) -> None:
    report = _report(conforming_extension)
    out = tmp_path / "nested" / "report.json"
    report.write_json(out)
    first = out.read_text(encoding="utf-8")
    document = json.loads(first)
    assert document["report_schema"] == REPORT_SCHEMA
    report.write_json(out)
    assert out.read_text(encoding="utf-8") == first, "report must be deterministic"
