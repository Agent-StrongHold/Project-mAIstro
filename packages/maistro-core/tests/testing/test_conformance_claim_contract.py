"""Conformance claim-contract behavior: fatality, version refusal, discovery.

These pin the rules that make a conformance *claim* trustworthy (issue #965):

- a skipped check never supports a claim — including a skipped required
  real-backend leg, which is fatal under
  ``MAISTRO_REQUIRE_REAL_BACKEND_LEGS`` rather than passing;
- a declared contract-version mismatch refuses the claim even when every
  check passes;
- subjects are discovered only through the entry-point group — no name-based
  fallback that could run against the wrong implementation.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from maistro.conformance.contract import (
    MEMORY_BACKEND,
    CheckId,
    CheckResult,
    CheckStatus,
    ConformanceFailure,
    ConformanceReport,
    SubjectDescriptor,
    SubjectFamily,
    require_real_backends_from_env,
    version_compatible,
)
from maistro.conformance.runner import (
    ConformanceRunner,
    assert_conformant,
    discover_subjects,
    render_report,
)
from testing.conformance_subjects import (
    BaseConformanceSubject,
    UnavailableBackendSubject,
)


def _env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAISTRO_REQUIRE_REAL_BACKEND_LEGS", value)


async def test_unavailable_backend_skips_real_leg_and_refuses_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subject whose real backend cannot run skips the leg — and no claim."""
    _env(monkeypatch, "")
    report = await ConformanceRunner(require_real_backends=False).run(
        UnavailableBackendSubject(name="no-real-backend")
    )

    for check_id in (CheckId.EGRESS_UNDECLARED_BLOCKED, CheckId.EGRESS_DECLARED_ALLOWED):
        entry = report.result(check_id)
        assert entry is not None and entry.status is CheckStatus.SKIP
    assert report.real_backend_executed is False
    assert report.conforms  # nothing executed failed...
    assert not report.claim_valid  # ...but a partial run is no conformance claim.


async def test_skipped_required_real_backend_leg_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under MAISTRO_REQUIRE_REAL_BACKEND_LEGS a skipped leg fails the run."""
    _env(monkeypatch, "1")
    report = await ConformanceRunner(require_real_backends=True).run(
        UnavailableBackendSubject(name="no-real-backend")
    )

    runner = ConformanceRunner(require_real_backends=True)
    fatal = runner.fatal_skip(report)
    assert fatal is not None and "no-real-backend" in fatal
    with pytest.raises(ConformanceFailure, match="required real-backend leg"):
        assert_conformant([report])


async def test_executed_but_failing_leg_is_not_a_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuine failure is a conformance finding, not a missing leg.

    The raw-socket violator executes the real-backend leg (it fails it); under
    the require switch the fatality rule must not fire — the report fails for
    the right reason (the check FAILed) instead of a leg being absent.
    """
    from testing.conformance_subjects import RawSocketEgressSubject

    _env(monkeypatch, "1")
    report = await ConformanceRunner(require_real_backends=True).run(
        RawSocketEgressSubject(name="raw-socket")
    )

    assert report.real_backend_executed is True
    assert ConformanceRunner(require_real_backends=True).fatal_skip(report) is None
    with pytest.raises(ConformanceFailure, match=r"egress\.undeclared\-blocked\=fail"):
        assert_conformant([report])


async def test_declared_version_mismatch_refuses_claim() -> None:
    """A subject declaring a different contract major cannot claim, ever."""
    report = await ConformanceRunner(require_real_backends=False).run(
        BaseConformanceSubject(
            name="future-subject",
            declared_contract_version="2.0.0",
        )
    )

    assert report.failures == ()  # every check passed
    assert report.declared_version_compatible is False
    assert not report.claim_valid
    with pytest.raises(ConformanceFailure, match="future-subject"):
        assert_conformant([report])


def test_version_compatibility_is_major_only() -> None:
    """Same major with any minor/patch is compatible; other majors are not."""
    assert version_compatible("1.0.0")
    assert version_compatible("1.9.3")
    assert not version_compatible("2.0.0")
    assert not version_compatible("")
    assert not version_compatible("nonsense")


def test_require_real_backends_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch mirrors the established PG-legs truthy spellings."""
    for truthy in ("1", "true", "YES", "on"):
        _env(monkeypatch, truthy)
        assert require_real_backends_from_env()
    _env(monkeypatch, "")
    assert not require_real_backends_from_env()
    assert not require_real_backends_from_env({})


def test_discovery_requires_entry_point_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """Subjects come only from the entry-point group; a bad factory fails loud."""

    def _not_a_subject() -> object:
        return object()

    class _FakeEntry:
        name = "bogus"

        def load(self) -> object:
            return _not_a_subject

    monkeypatch.setattr(
        "maistro.conformance.runner.metadata.entry_points",
        lambda group: [_FakeEntry()],
    )
    with pytest.raises(ConformanceFailure, match="bogus"):
        discover_subjects()


async def test_discovery_empty_group_names_the_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty registration set is an error naming the group, not a silent pass."""
    from maistro.conformance.runner import run_registered_subjects

    monkeypatch.setattr("maistro.conformance.runner.metadata.entry_points", lambda group: [])
    with pytest.raises(ConformanceFailure, match=r"maistro\.conformance"):
        await run_registered_subjects()


async def test_render_report_carries_the_claim_surface() -> None:
    """The rendered report shows contract, backend, and per-check outcomes."""
    report = await ConformanceRunner(require_real_backends=False).run(
        BaseConformanceSubject(name="rendered-subject")
    )
    rendered = render_report(report)

    assert "rendered-subject" in rendered
    assert "maistro.extension-conformance @ 1.0.0" in rendered
    assert "claim valid: True" in rendered


def test_cli_registers_every_declared_command() -> None:
    """Each declared CLI callback is actually registered on the Typer app."""
    from maistro.cli._conformance import REGISTERED_COMMANDS, app

    registered = {command.callback for command in app.registered_commands}
    for callback in REGISTERED_COMMANDS:
        assert callback in registered


def test_assert_conformant_rejects_a_never_run_report() -> None:
    """An empty report is not a claim: no executed path, no conformance."""
    empty = ConformanceReport(
        descriptor=SubjectDescriptor(
            name="empty", family=SubjectFamily.TOOL, declared_contract_version="1.0.0"
        ),
        backend=MEMORY_BACKEND,
        results=[],
        real_backend_executed=False,
    )
    with pytest.raises(ConformanceFailure, match="no checks recorded"):
        assert_conformant([empty])


def test_check_result_statuses_are_distinct() -> None:
    """PASS/FAIL/SKIP stay distinct so a skip can never read as a pass."""
    result = CheckResult(
        check_id=CheckId.SCOPE_PROPAGATION, status=CheckStatus.SKIP, detail="not run"
    )
    assert result.status is not CheckStatus.PASS
    assert result.as_dict()["status"] == "skip"


def test_cli_lists_subjects_and_runs_empty_registry() -> None:
    """The CLI surfaces discovery and fails closed on an empty registry."""
    from maistro.cli._conformance import app

    runner = CliRunner()
    listed = runner.invoke(app, ["subjects"])
    assert listed.exit_code == 0

    ran = runner.invoke(app, ["run"])
    assert ran.exit_code == 1
    assert "conformance failed" in ran.output
