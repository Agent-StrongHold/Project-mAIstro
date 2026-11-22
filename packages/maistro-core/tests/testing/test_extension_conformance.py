"""The shared extension-family conformance suite, executed end to end (#965).

Positive legs: the same check bodies run against the reference conformant
subject in all three families, against the real-backend egress leg (a real
loopback socket), and every check must pass with a valid claim.

Negative legs: one violator per broken semantic, each proving the suite fails
the implementation that breaks exactly that semantic — including the
raw-socket egress bypass, which is detected by wire evidence (the audit
server counts the request) rather than any source inspection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

import pytest

from maistro.conformance.checks import (
    check_bypass_refused,
    check_credential_ref_resolution,
    check_deadline_enforcement,
    check_egress,
    check_secrets_plaintext_refused,
    check_usage_and_provenance,
    declare_egress_origin,
)
from maistro.conformance.contract import (
    CONTRACT_ID,
    CONTRACT_VERSION,
    BackendKind,
    CheckId,
    CheckStatus,
    ConformanceFailure,
    SubjectFamily,
)
from maistro.conformance.runner import (
    ConformanceRunner,
    _AuditServer,
    assert_conformant,
    run_conformance,
)
from maistro.security.outbound import (
    configure_outbound_policy,
    current_outbound_policy,
    outbound_origin,
    reset_outbound_policy,
)
from testing.conformance_subjects import (
    AllRefusingSubject,
    BaseConformanceSubject,
    CrashingFetchSubject,
    DoubleFetchSubject,
    DriftedUsageSubject,
    ExceptingOnCancelSubject,
    IncompleteEffectSubject,
    NoFetchSubject,
    OffsiteFetchSubject,
    PlaintextSecretSubject,
    QuietRefusalSubject,
    RawSocketEgressSubject,
    RawThenGuardedSubject,
    ScopeDenyingSubject,
    StrippingSecretSubject,
    UncancellableSubject,
    UsageOnUnreportedSubject,
    WrongRefusalTypeSubject,
)

_FAMILIES = [SubjectFamily.PROVIDER, SubjectFamily.CONNECTOR, SubjectFamily.TOOL]


def _family_subject(family: SubjectFamily) -> BaseConformanceSubject:
    return BaseConformanceSubject(
        name=f"reference-{family.value}",
        family=family,
    )


@pytest.mark.parametrize("family", _FAMILIES)
async def test_reference_subject_conforms_with_valid_claim(family: SubjectFamily) -> None:
    """Each supported family runs the shared suite; a conforming subject claims."""
    report = await ConformanceRunner().run(_family_subject(family))

    assert report.failures == (), f"unexpected failures: {report.as_dict()}"
    assert report.skipped == (), f"unexpected skips: {report.as_dict()}"
    assert report.claim_valid
    assert report.conforms
    assert report.real_backend_executed
    assert report.backend.kind is BackendKind.REAL  # egress leg ran on a real socket
    assert report.descriptor.family is family


async def test_report_names_exact_contract_version_and_backend() -> None:
    """A conformance report names the exact tested contract id/version/backend."""
    report = await ConformanceRunner().run(_family_subject(SubjectFamily.PROVIDER))
    payload = report.as_dict()

    assert report.contract_id == CONTRACT_ID == "maistro.extension-conformance"
    assert report.contract_version == CONTRACT_VERSION
    assert payload["declared_contract_version"] == "1.0.0"
    assert payload["backend"]["name"] == "memory+memory"
    assert payload["backend"]["kind"] == "real"
    assert payload["real_backend_executed"] is True
    assert payload["claim_valid"] is True
    check_ids = {entry["check_id"] for entry in payload["results"]}
    assert check_ids == {check.value for check in CheckId}


async def test_plaintext_extension_secret_fails_conformance() -> None:
    """A subject that keeps plaintext secrets fails, and cannot claim."""
    report = await ConformanceRunner().run(PlaintextSecretSubject(name="leaky-config"))

    result = report.result(CheckId.SECRETS_PLAINTEXT_REFUSED)
    assert result is not None and result.status is CheckStatus.FAIL
    assert not report.claim_valid
    with pytest.raises(ConformanceFailure, match="leaky-config"):
        assert_conformant([report])


async def test_credential_ref_resolution_enforced_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credential-ref body is shared: plain ValueError refusals pass it.

    A subject may refuse plaintext with its own error type; the check accepts
    the canonical refusal shapes, and this pins that contract without
    re-running the whole suite.
    """
    from maistro.conformance.checks import PLAINTEXT_SECRET, check_secrets_plaintext_refused

    class ValueRefuser(BaseConformanceSubject):
        def prepare_config(self, config: dict[str, Any]) -> dict[str, Any]:
            if PLAINTEXT_SECRET in str(config):
                raise ValueError("plaintext refused")
            return dict(config)

    result = await check_secrets_plaintext_refused(ValueRefuser())
    assert result.status is CheckStatus.PASS
    monkeypatch.delenv("MAISTRO_REQUIRE_REAL_BACKEND_LEGS", raising=False)


async def test_undeclared_direct_egress_fails_with_wire_evidence() -> None:
    """A raw-socket fetch bypassing the guarded seam fails — server saw bytes.

    This is the behavioral bypass detection the issue demands: the violation
    is proven by the audit server's request counter, not by reading code.
    """
    report = await ConformanceRunner().run(RawSocketEgressSubject(name="raw-socket"))

    undeclared = report.result(CheckId.EGRESS_UNDECLARED_BLOCKED)
    assert undeclared is not None and undeclared.status is CheckStatus.FAIL
    assert undeclared.evidence.get("hits_after", 0) != undeclared.evidence.get("hits_before", -1)
    assert not report.claim_valid


async def test_uncancellable_effect_fails_deadline_check() -> None:
    """An effect that shields cancellation cannot claim deadline conformance."""
    report = await ConformanceRunner().run(UncancellableSubject(name="uncancellable"))

    deadline = report.result(CheckId.DEADLINE_ENFORCEMENT)
    assert deadline is not None and deadline.status is CheckStatus.FAIL
    assert not report.claim_valid


async def test_outbound_policy_restored_after_run() -> None:
    """The runner leaves the outbound policy exactly as it found it."""
    before = current_outbound_policy()
    await run_conformance(_family_subject(SubjectFamily.CONNECTOR))
    after = current_outbound_policy()

    assert after == before


async def test_run_is_deterministically_repeatable() -> None:
    """Two runs of the same subject produce the same verdicts (no leg order luck)."""
    first = await ConformanceRunner().run(_family_subject(SubjectFamily.TOOL))
    second = await ConformanceRunner().run(_family_subject(SubjectFamily.TOOL))

    assert [entry.check_id for entry in first.results] == [
        entry.check_id for entry in second.results
    ]
    assert [entry.status for entry in first.results] == [entry.status for entry in second.results]
    assert first.claim_valid and second.claim_valid


# --- check-body verdict branches -------------------------------------------
#
# Each test drives ONE shared check body directly against a single-property
# violator, pinning the exact verdict branch the body must take. The full-runner
# tests above prove the legs compose; these prove each body classifies its
# refusal/leak/fetch shapes correctly in isolation.


@asynccontextmanager
async def _audit_socket() -> AsyncIterator[_AuditServer]:
    """A real loopback audit socket with the outbound policy left untouched."""
    audit = await _AuditServer().start()
    try:
        yield audit
    finally:
        await audit.stop()


@asynccontextmanager
async def _declared(audit: _AuditServer) -> AsyncIterator[str]:
    """Declare the audit origin for a probe, restoring policy afterwards."""
    saved = current_outbound_policy()
    reset_outbound_policy()
    probe_url = f"http://127.0.0.1:{audit.port}/conformance-probe"
    declare_egress_origin(outbound_origin(probe_url))
    try:
        yield probe_url
    finally:
        reset_outbound_policy()
        configure_outbound_policy(*sorted(saved.origins))


async def test_secret_check_accepts_strip_but_not_foreign_errors() -> None:
    """Stripping plaintext passes; a non-refusal crash fails by error type."""
    stripped = await check_secrets_plaintext_refused(StrippingSecretSubject())
    assert stripped.status is CheckStatus.PASS

    crashed = await check_secrets_plaintext_refused(WrongRefusalTypeSubject())
    assert crashed.status is CheckStatus.FAIL
    assert "KeyError" in crashed.detail


async def test_credential_ref_check_classifies_scope_and_leak_shapes() -> None:
    """Subject-side denials and repr leaks fail the credential-ref body."""
    denied = await check_credential_ref_resolution(ScopeDenyingSubject())
    assert denied.status is CheckStatus.FAIL
    assert "authorized reference did not resolve" in denied.detail


async def test_credential_ref_check_catches_a_repr_leak_in_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the resolved provider's repr embeds the credential, the body fails it.

    ``CredentialBackedProvider`` carries a hand-written safe repr; this drives
    the check body against the regression it exists to catch (the repr falling
    back to the dataclass default, which would embed the api_key).
    """

    def _default_repr(self: Any) -> str:
        fields = ", ".join(f"{key}={value!r}" for key, value in asdict(self).items())
        return f"CredentialBackedProvider({fields})"

    monkeypatch.setattr(
        "maistro.capabilities.credential_routing.CredentialBackedProvider.__repr__",
        _default_repr,
    )
    result = await check_credential_ref_resolution(BaseConformanceSubject())

    assert result.status is CheckStatus.FAIL
    assert "plaintext" in result.detail

    unavailable = await check_credential_ref_resolution(AllRefusingSubject())
    assert unavailable.status is CheckStatus.FAIL
    assert "unavailable" in unavailable.detail


@pytest.mark.parametrize(
    ("subject_type", "allow_origin", "expected_status", "detail_fragment"),
    [
        pytest.param(
            QuietRefusalSubject, False, CheckStatus.PASS, "normalized error", id="quiet-refusal"
        ),
        pytest.param(CrashingFetchSubject, False, CheckStatus.FAIL, "RuntimeError", id="crash"),
        pytest.param(NoFetchSubject, True, CheckStatus.FAIL, "no request reached", id="no-fetch"),
        pytest.param(
            DoubleFetchSubject, True, CheckStatus.FAIL, "produced 2 server hits", id="double-fetch"
        ),
        pytest.param(
            OffsiteFetchSubject, True, CheckStatus.FAIL, "declared origin was refused", id="offsite"
        ),
        pytest.param(
            AllRefusingSubject, False, CheckStatus.FAIL, "subject unavailable", id="unavailable"
        ),
    ],
)
async def test_egress_verdicts_classify_fetch_shapes(
    subject_type: type[BaseConformanceSubject],
    allow_origin: bool,
    expected_status: CheckStatus,
    detail_fragment: str,
) -> None:
    """One subject shape per egress verdict branch, proven against a real socket."""
    async with _audit_socket() as audit:
        if allow_origin:
            async with _declared(audit) as probe_url:
                result = await check_egress(
                    subject_type(), probe_url=probe_url, audit_server=audit, allow_origin=True
                )
        else:
            probe_url = f"http://127.0.0.1:{audit.port}/conformance-probe"
            result = await check_egress(
                subject_type(), probe_url=probe_url, audit_server=audit, allow_origin=False
            )
    assert result.status is expected_status, result.detail
    assert detail_fragment in result.detail


async def test_raw_then_guarded_bypass_is_caught_by_wire_evidence() -> None:
    """A bypass followed by a policy refusal still fails on the wire count."""
    async with _audit_socket() as audit:
        probe_url = f"http://127.0.0.1:{audit.port}/conformance-probe"
        result = await check_egress(
            RawThenGuardedSubject(), probe_url=probe_url, audit_server=audit, allow_origin=False
        )
    assert result.status is CheckStatus.FAIL
    assert "received the request anyway" in result.detail
    assert result.evidence["hits_after"] > result.evidence["hits_before"]


class _WrongShapeService:
    """A canonical-service stand-in that surfaces the wrong refusal shape."""

    def __init__(self, exc_type: type[BaseException]) -> None:
        self._exc_type = exc_type

    async def invoke(self, **_kwargs: Any) -> Any:
        raise self._exc_type("conformance probe: wrong refusal shape")


@pytest.mark.parametrize(
    ("service_name", "exc_type", "detail_fragment"),
    [
        pytest.param(
            "InvocationExecutionService",
            PermissionError,
            "expected CapabilityUnavailable",
            id="unavailable-permission-error",
        ),
        pytest.param(
            "GovernedInvocationExecutionService",
            PermissionError,
            "expected InvocationDenied",
            id="policy-denial-permission-error",
        ),
    ],
)
def test_bypass_probes_fail_on_wrong_refusal_shapes(
    monkeypatch: pytest.MonkeyPatch,
    service_name: str,
    exc_type: type[BaseException],
    detail_fragment: str,
) -> None:
    """A canonical service surfacing the wrong denial shape fails the bypass probe.

    The probes trust the platform to fail closed with its canonical error
    types; these pins hold the probes to that trust — any other shape is a
    conformance finding, never a pass.
    """
    import asyncio

    from maistro.conformance import checks as checks_module

    monkeypatch.setattr(checks_module, service_name, lambda **_kwargs: _WrongShapeService(exc_type))

    class _StubAudit:
        def hit_count(self) -> int:
            return 0

    result = asyncio.run(check_bypass_refused(BaseConformanceSubject(), audit_server=_StubAudit()))

    assert result.status is CheckStatus.FAIL
    assert detail_fragment in result.detail


async def test_deadline_check_rejects_unavailable_and_exception_surfaces() -> None:
    """Unavailable providers fail; exception-on-cancel never reads as success."""
    unavailable = await check_deadline_enforcement(AllRefusingSubject())
    assert unavailable.status is CheckStatus.FAIL
    assert "unavailable" in unavailable.detail

    surfaced = await check_deadline_enforcement(ExceptingOnCancelSubject())
    assert surfaced.status is CheckStatus.FAIL
    assert "instead of propagating" in surfaced.detail


async def test_deadline_probe_refuses_to_be_vacuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe that asks for no hang fails loudly instead of passing vacuously."""

    class _NoHangRequest:
        def __init__(self, **_kwargs: Any) -> None:
            hang_seconds = 0.0
            self.hang_seconds = hang_seconds

    monkeypatch.setattr("maistro.conformance.checks.EffectRequest", _NoHangRequest)
    result = await check_deadline_enforcement(BaseConformanceSubject())

    assert result.status is CheckStatus.FAIL
    assert "vacuous" in result.detail


async def test_usage_check_rejects_incomplete_effects_and_drifted_units() -> None:
    """A failed effect and drifted units each fail the usage body."""
    incomplete = await check_usage_and_provenance(IncompleteEffectSubject())
    assert incomplete.status is CheckStatus.FAIL
    assert "did not complete" in incomplete.detail

    drifted = await check_usage_and_provenance(DriftedUsageSubject())
    assert drifted.status is CheckStatus.FAIL
    assert "in=8" in drifted.detail


async def test_usage_check_rejects_usage_claimed_on_unreported_effects() -> None:
    """Usage on a no-usage effect is not an unreported marker — it fails."""
    result = await check_usage_and_provenance(UsageOnUnreportedSubject())

    assert result.status is CheckStatus.FAIL
    assert "unreported marker" in result.detail


async def test_usage_check_fails_if_negative_units_ever_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative-usage refusal rests on canonical validation, not hope.

    If InvocationUsage ever stopped refusing negative units, the check body
    must still fail the subject rather than pass the suite.
    """

    class _LaxUsage:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr("maistro.conformance.checks.InvocationUsage", _LaxUsage)
    result = await check_usage_and_provenance(BaseConformanceSubject())
    assert result.status is CheckStatus.FAIL
    assert "negative" in result.detail
