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

from typing import Any

import pytest

from maistro.conformance.contract import (
    CONTRACT_ID,
    CONTRACT_VERSION,
    BackendKind,
    CheckId,
    CheckStatus,
    ConformanceFailure,
    SubjectFamily,
)
from maistro.conformance.runner import ConformanceRunner, assert_conformant, run_conformance
from maistro.security.outbound import current_outbound_policy
from testing.conformance_subjects import (
    BaseConformanceSubject,
    PlaintextSecretSubject,
    RawSocketEgressSubject,
    UncancellableSubject,
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
