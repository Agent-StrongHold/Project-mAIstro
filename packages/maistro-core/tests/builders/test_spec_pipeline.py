"""Behavioral tests for spec emission, property generation, coverage, and
verification — the machine-checkable contract path through Builders.
"""

from __future__ import annotations

import pytest

from maistro.builders.property_gen import generate_property_tests
from maistro.builders.spec_coverage import check_spec_coverage
from maistro.builders.spec_emitter import emit_spec
from maistro.builders.spec_templates import SpecTemplateStore
from maistro.builders.verifier import InvariantVerifier
from maistro.types.feedback import Severity, ViolationCategory
from maistro.types.spec import (
    Invariant,
    InvariantKind,
    PropertyTest,
    Spec,
    SpecStatus,
)

# ---------------------------------------------------------------------------
# emit_spec
# ---------------------------------------------------------------------------


def test_emit_spec_extracts_bullet_criteria() -> None:
    body = "Intro line\n- first criterion\n* second criterion\nnot a bullet"
    spec = emit_spec(issue_number=7, title="Add widget", body=body)
    assert spec.acceptance_criteria == ("first criterion", "second criterion")


def test_emit_spec_derives_one_invariant_per_criterion() -> None:
    spec = emit_spec(
        issue_number=7,
        title="t",
        body="- alpha\n- beta",
    )
    assert len(spec.invariants) == 2
    assert spec.invariants[0].name == "criterion_0"
    assert spec.invariants[0].description == "alpha"
    assert spec.invariants[0].kind is InvariantKind.POSTCONDITION
    assert spec.invariants[1].name == "criterion_1"


def test_emit_spec_infers_protocols_from_file_paths() -> None:
    spec = emit_spec(
        issue_number=7,
        title="t",
        files_touched=[
            "src/maistro/protocols/storage.py",
            "src/maistro/protocols/storage.py",  # duplicate dropped
            "src/maistro/protocols/auth.py",
            "src/maistro/router/scorer.py",  # not a protocol path
        ],
    )
    assert spec.protocols_touched == ("storage", "auth")


def test_emit_spec_maps_complexity() -> None:
    assert emit_spec(issue_number=1, title="t", complexity="simple").complexity == "S"
    assert emit_spec(issue_number=1, title="t", complexity="complex").complexity == "L"
    # Unknown complexity falls back to "M".
    assert emit_spec(issue_number=1, title="t", complexity="weird").complexity == "M"


def test_emit_spec_status_active_and_no_property_tests() -> None:
    spec = emit_spec(issue_number=1, title="t", body="- one")
    assert spec.status is SpecStatus.ACTIVE
    assert spec.property_tests == ()


def test_emit_spec_empty_body_yields_no_criteria() -> None:
    spec = emit_spec(issue_number=1, title="t", body="no bullets here")
    assert spec.acceptance_criteria == ()
    assert spec.invariants == ()


# ---------------------------------------------------------------------------
# generate_property_tests
# ---------------------------------------------------------------------------


def test_generate_property_tests_one_per_invariant() -> None:
    spec = emit_spec(issue_number=1, title="t", body="- a\n- b\n- c")
    tests = generate_property_tests(spec)
    assert len(tests) == 3
    assert [t.invariant_name for t in tests] == [
        "criterion_0",
        "criterion_1",
        "criterion_2",
    ]
    assert all(t.name == f"test_{t.invariant_name}" for t in tests)


def test_generate_property_tests_strategy_matches_kind() -> None:
    spec = Spec(
        issue_number=1,
        title="t",
        invariants=(
            Invariant(
                name="pre",
                description="d",
                kind=InvariantKind.PRECONDITION,
                expression="x",
            ),
            Invariant(
                name="state",
                description="d",
                kind=InvariantKind.STATE_INVARIANT,
                expression="x",
            ),
        ),
    )
    tests = {t.invariant_name: t for t in generate_property_tests(spec)}
    assert tests["pre"].strategy_code == "st.text(min_size=0, max_size=200)"
    assert tests["state"].strategy_code == "st.integers(min_value=0, max_value=1000)"
    assert "after >= before" in tests["state"].test_body


def test_generate_property_tests_module_path_uses_protocol() -> None:
    spec = Spec(
        issue_number=1,
        title="t",
        invariants=(
            Invariant(
                name="i_with",
                description="d",
                kind=InvariantKind.POSTCONDITION,
                expression="x",
                protocol="storage",
            ),
            Invariant(
                name="i_without",
                description="d",
                kind=InvariantKind.POSTCONDITION,
                expression="x",
            ),
        ),
    )
    tests = {t.invariant_name: t for t in generate_property_tests(spec)}
    assert tests["i_with"].module_path == "tests/protocols/test_storage_properties.py"
    assert tests["i_without"].module_path == ""


def test_generated_tests_cover_emitted_spec_invariants() -> None:
    # End-to-end: emit -> generate -> attach -> nothing uncovered.
    spec = emit_spec(issue_number=1, title="t", body="- a\n- b")
    tests = generate_property_tests(spec)
    covered = Spec(
        issue_number=spec.issue_number,
        title=spec.title,
        invariants=spec.invariants,
        property_tests=tuple(tests),
    )
    assert covered.uncovered_invariants == ()


# ---------------------------------------------------------------------------
# check_spec_coverage
# ---------------------------------------------------------------------------


def test_check_spec_coverage_none_returns_empty() -> None:
    assert check_spec_coverage(None) == []


def test_check_spec_coverage_fully_covered_returns_empty() -> None:
    inv = Invariant(name="c0", description="d", kind=InvariantKind.POSTCONDITION, expression="x")
    spec = Spec(
        issue_number=1,
        title="t",
        invariants=(inv,),
        property_tests=(
            PropertyTest(
                name="test_c0",
                invariant_name="c0",
                strategy_code="st.none()",
                test_body="assert True",
            ),
        ),
    )
    assert check_spec_coverage(spec) == []


def test_check_spec_coverage_flags_uncovered_invariants() -> None:
    inv = Invariant(
        name="c0",
        description="must persist",
        kind=InvariantKind.POSTCONDITION,
        expression="x",
    )
    spec = Spec(issue_number=1, title="t", invariants=(inv,))
    findings = check_spec_coverage(spec)
    assert len(findings) == 1
    f = findings[0]
    assert f.category is ViolationCategory.SPEC_COVERAGE_GAP
    assert f.severity is Severity.CRITICAL
    assert "c0" in f.description
    assert "must persist" in f.description


# ---------------------------------------------------------------------------
# InvariantVerifier
# ---------------------------------------------------------------------------


async def test_verifier_passes_when_no_invariants() -> None:
    verifier = InvariantVerifier()
    spec = Spec(issue_number=1, title="t")
    result = await verifier.verify(spec, "tests_written", {})
    assert result.passed is True
    assert result.coverage_pct == 100.0
    assert result.failures == ()


async def test_verifier_full_coverage_passes() -> None:
    inv = Invariant(name="c0", description="d", kind=InvariantKind.POSTCONDITION, expression="x")
    spec = Spec(
        issue_number=5,
        title="t",
        invariants=(inv,),
        property_tests=(
            PropertyTest(
                name="test_c0",
                invariant_name="c0",
                strategy_code="st.none()",
                test_body="assert True",
            ),
        ),
    )
    result = await InvariantVerifier().verify(spec, "tests_written", {})
    assert result.passed is True
    assert result.coverage_pct == 100.0
    assert result.spec_issue_number == 5
    assert result.stage == "tests_written"


async def test_verifier_partial_coverage_fails_with_pct() -> None:
    invs = tuple(
        Invariant(
            name=f"c{i}",
            description="d",
            kind=InvariantKind.POSTCONDITION,
            expression="x",
        )
        for i in range(4)
    )
    spec = Spec(
        issue_number=1,
        title="t",
        invariants=invs,
        property_tests=(
            PropertyTest(
                name="test_c0",
                invariant_name="c0",
                strategy_code="st.none()",
                test_body="assert True",
            ),
        ),
    )
    result = await InvariantVerifier().verify(spec, "tests_written", {})
    assert result.passed is False
    assert result.coverage_pct == pytest.approx(25.0)
    assert len(result.failures) == 3
    assert "c1" in " ".join(result.failures)


# ---------------------------------------------------------------------------
# SpecTemplateStore
# ---------------------------------------------------------------------------


def _verified_spec() -> Spec:
    inv = Invariant(name="c0", description="d", kind=InvariantKind.POSTCONDITION, expression="x")
    return Spec(
        issue_number=10,
        title="original",
        protocols_touched=("storage",),
        invariants=(inv,),
        acceptance_criteria=("must persist",),
        status=SpecStatus.VERIFIED,
    )


def test_template_store_rejects_unverified_specs() -> None:
    store = SpecTemplateStore()
    draft = Spec(issue_number=1, title="t", status=SpecStatus.ACTIVE)
    assert store.save_template(draft, "crud") is False
    assert store.match("crud") is None


def test_template_store_saves_and_matches_verified_spec() -> None:
    store = SpecTemplateStore()
    spec = _verified_spec()
    assert store.save_template(spec, "crud") is True
    assert store.match("crud") is spec
    assert store.list_classes() == ["crud"]


def test_template_store_adapt_preserves_invariant_structure() -> None:
    store = SpecTemplateStore()
    template = _verified_spec()
    store.save_template(template, "crud")

    adapted = store.adapt("crud", issue_number=99, title="new issue")
    assert adapted is not None
    assert adapted.issue_number == 99
    assert adapted.title == "new issue"
    assert adapted.invariants == template.invariants
    assert adapted.protocols_touched == template.protocols_touched
    assert adapted.acceptance_criteria == template.acceptance_criteria
    # Adapted spec starts fresh: no files, no property tests, status ACTIVE.
    assert adapted.files_touched == ()
    assert adapted.property_tests == ()
    assert adapted.status is SpecStatus.ACTIVE


def test_template_store_adapt_missing_class_returns_none() -> None:
    assert SpecTemplateStore().adapt("nope", issue_number=1, title="t") is None
