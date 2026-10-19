"""Extension quarantine and disable governance (#972, M9-G4).

These tests pin each acceptance criterion against reachable production
behavior: threshold-driven suspension from canonical security/sandbox/health
evidence, immediate refusal of new invocations after the authoritative state
change (including under concurrent callers), the extension's structural
inability to write or clear its own governance state, strike/history
retention across re-enable, the three distinct responses (version disable,
package quarantine, publisher-wide action), transient health failures that
change no state, and in-flight drain/terminate disposition. The race tests
assert ordering structure, not wall-clock timing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from maistro.extensions import ExtensionSandboxViolation
from maistro.extensions.isolation import ViolationKind
from maistro.extensions.quarantine import (
    ActorKind,
    AdmissionDecision,
    EvidenceKind,
    ExtensionEvidence,
    ExtensionGovernancePolicy,
    ExtensionGovernanceService,
    GovernanceActor,
    GovernanceState,
    InFlightDisposition,
    QuarantineAuthorityError,
    SandboxViolationBridge,
    health_evidence,
    security_evidence,
)

EXT = "acme.chart_tools"
VERSION = "1.4.0"
SIBLING = "1.5.0"
PUBLISHER = "acme"
OTHER_EXT = "acme.calendar_tools"
OTHER_PUBLISHER_EXT = "zenith.notes"
OTHER_PUBLISHER = "zenith"
AT = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

ADMIN = GovernanceActor(kind=ActorKind.HOST_ADMIN, id="host-admin-1")
ORG_ADMIN = GovernanceActor(kind=ActorKind.ORG_ADMIN, id="org-admin-2")
SYSTEM = GovernanceActor(kind=ActorKind.SYSTEM, id="system")
EXTENSION_ACTOR = GovernanceActor(kind=ActorKind.EXTENSION, id="ext-acme.chart_tools")


def _sandbox_violation(
    *,
    detail: str = "egress attempt",
    kind: ViolationKind = ViolationKind.RESOURCE_LIMIT_EXCEEDED,
) -> ExtensionSandboxViolation:
    return ExtensionSandboxViolation(
        extension_id=EXT,
        version=VERSION,
        kind=kind,
        detail=detail,
        at=AT,
    )


def _service(**policy_overrides: object) -> ExtensionGovernanceService:
    policy = ExtensionGovernancePolicy(**policy_overrides)  # type: ignore[arg-type]
    return ExtensionGovernanceService(policy=policy, clock=lambda: AT)


def _admit(service: ExtensionGovernanceService, **identity: str) -> AdmissionDecision:
    kwargs = {"extension_id": EXT, "version": VERSION, "publisher": PUBLISHER}
    kwargs.update(identity)
    return service.admit(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Threshold-driven suspension from canonical evidence
# --------------------------------------------------------------------------


def test_security_violation_quarantines_immediately() -> None:
    service = _service()
    decision = service.record(
        security_evidence(
            extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="sentinel: exec"
        ),
        actor=SYSTEM,
    )
    assert decision.suspended
    assert decision.changed
    assert decision.target.value == "package"
    refused = _admit(service)
    assert not refused.allowed
    assert refused.governing_state is GovernanceState.QUARANTINED
    assert "quarantined" in refused.reason


def test_sandbox_violations_accumulate_to_the_threshold() -> None:
    service = _service()
    bridge = SandboxViolationBridge(service, publisher=PUBLISHER)
    for strike in range(3):
        decision = bridge.record(_sandbox_violation(detail=f"strike {strike}"))
        if strike < 2:
            assert not decision.suspended
            assert _admit(service).allowed
    assert decision.suspended
    assert not _admit(service).allowed


def test_sandbox_threshold_matches_the_m9g2_escalation_point() -> None:
    """The default sandbox threshold is the same three-strike escalation the
    M9-G2 violation log warns about, so the named candidate is exactly the
    identity this flow suspends."""
    assert ExtensionGovernancePolicy().sandbox_threshold == 3


def test_transient_health_failures_change_no_state() -> None:
    """A health failure is availability, not policy violation: below the
    threshold it records evidence but the extension keeps admitting."""
    service = _service()
    for _ in range(2):
        decision = service.record(
            health_evidence(
                extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="timeout"
            ),
            actor=SYSTEM,
        )
        assert decision.state_after is GovernanceState.ACTIVE
        assert not decision.changed
    assert _admit(service).allowed
    assert service.strikes(extension_id=EXT, version=VERSION, kind=EvidenceKind.HEALTH_FAILURE) == 2


def test_health_failures_at_the_threshold_quarantine() -> None:
    service = _service()
    for _ in range(3):
        decision = service.record(
            health_evidence(
                extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="timeout"
            ),
            actor=SYSTEM,
        )
    assert decision.suspended
    assert not _admit(service).allowed


def test_thresholds_are_deployment_configurable() -> None:
    service = _service(sandbox_threshold=2, health_threshold=5)
    bridge = SandboxViolationBridge(service, publisher=PUBLISHER)
    bridge.record(_sandbox_violation())
    decision = bridge.record(_sandbox_violation())
    assert decision.suspended


def test_policy_rejects_nonpositive_thresholds() -> None:
    with pytest.raises(QuarantineAuthorityError):
        ExtensionGovernancePolicy(security_threshold=0)
    with pytest.raises(QuarantineAuthorityError):
        ExtensionGovernancePolicy(sandbox_threshold=0)
    with pytest.raises(QuarantineAuthorityError):
        ExtensionGovernancePolicy(health_threshold=0)


def test_evidence_is_attributed_and_digested() -> None:
    """Security violations are attributable to extension identity/version,
    and identical evidence digests identically (stable audit joins)."""
    first = security_evidence(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x", at=AT
    )
    second = security_evidence(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x", at=AT
    )
    other = security_evidence(
        extension_id=EXT, version=SIBLING, publisher=PUBLISHER, detail="x", at=AT
    )
    assert first.digest == second.digest
    assert first.digest != other.digest
    assert first.extension_id == EXT and first.version == VERSION and first.publisher == PUBLISHER


def test_evidence_requires_full_attribution() -> None:
    with pytest.raises(QuarantineAuthorityError):
        ExtensionEvidence(
            kind=EvidenceKind.SECURITY_VIOLATION,
            extension_id="",
            version=VERSION,
            publisher=PUBLISHER,
            at=AT,
            source="security",
        )


# --------------------------------------------------------------------------
# Quarantine and concurrent invocation cannot race past the state change
# --------------------------------------------------------------------------


def test_no_admission_after_the_authoritative_state_change() -> None:
    """Structure, not timing: begin_invocation is synchronous with admit, so
    an interleaving where an admission completes after quarantine has
    returned can only produce a refusal — the shared log proves no allowed
    admission follows the state change whatever the event-loop order."""
    service = _service()
    log: list[tuple[str, str]] = []

    async def scenario() -> None:
        async def quarantine() -> None:
            await asyncio.sleep(0)
            service.quarantine_package(
                extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="misbehaving"
            )
            log.append(("quarantine", "-"))

        async def admit() -> None:
            await asyncio.sleep(0)
            try:
                lease = service.begin_invocation(
                    extension_id=EXT, version=VERSION, publisher=PUBLISHER
                )
            except QuarantineAuthorityError as exc:
                log.append(("admit", f"denied:{exc}"))
            else:
                log.append(("admit", f"allowed:{lease.lease_id}"))

        await asyncio.gather(quarantine(), *[admit() for _ in range(25)])

    asyncio.run(scenario())
    quarantine_at = log.index(("quarantine", "-"))
    later = log[quarantine_at + 1 :]
    assert later, "some admissions must be scheduled after the state change"
    for kind, outcome in later:
        assert not (kind == "admit" and outcome.startswith("allowed")), outcome


def test_begin_invocation_raises_when_suspended() -> None:
    service = _service()
    service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    with pytest.raises(QuarantineAuthorityError, match="quarantined"):
        service.begin_invocation(extension_id=EXT, version=VERSION, publisher=PUBLISHER)


def test_disabled_version_refuses_begin_and_naming_is_accurate() -> None:
    service = _service()
    service.disable_version(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER, actor=ADMIN, reason="bad build"
    )
    decision = _admit(service)
    assert not decision.allowed
    assert decision.governing_state is GovernanceState.DISABLED
    assert "disabled" in decision.reason


def test_in_flight_work_drains_by_default() -> None:
    service = _service()
    lease = service.begin_invocation(extension_id=EXT, version=VERSION, publisher=PUBLISHER)
    service.quarantine_package(extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="x")
    assert service.disposition(lease) is InFlightDisposition.DRAIN
    # New work is refused either way.
    assert not _admit(service).allowed


def test_in_flight_work_terminates_when_policy_chooses_it() -> None:
    service = _service(in_flight=InFlightDisposition.TERMINATE)
    lease = service.begin_invocation(extension_id=EXT, version=VERSION, publisher=PUBLISHER)
    service.quarantine_package(extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="x")
    assert service.disposition(lease) is InFlightDisposition.TERMINATE


def test_disposition_is_a_pure_query() -> None:
    service = _service()
    lease = service.begin_invocation(extension_id=EXT, version=VERSION, publisher=PUBLISHER)
    assert service.disposition(lease) is InFlightDisposition.DRAIN
    assert service.disposition(lease) is InFlightDisposition.DRAIN
    service.finish_invocation(lease)


# --------------------------------------------------------------------------
# The extension never holds the pen
# --------------------------------------------------------------------------


def test_extension_actor_cannot_mutate_governance_state() -> None:
    """Every mutating method refuses an extension-kind actor: the extension
    cannot write or clear its own quarantine/security state."""
    service = _service(security_threshold=5)
    mutations = [
        lambda: service.record(
            security_evidence(
                extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="self-report"
            ),
            actor=EXTENSION_ACTOR,
        ),
        lambda: service.disable_version(
            extension_id=EXT,
            version=VERSION,
            publisher=PUBLISHER,
            actor=EXTENSION_ACTOR,
            reason="self-disable",
        ),
        lambda: service.quarantine_package(
            extension_id=EXT, publisher=PUBLISHER, actor=EXTENSION_ACTOR, reason="self-quarantine"
        ),
        lambda: service.quarantine_publisher(
            publisher=PUBLISHER, actor=EXTENSION_ACTOR, reason="self-quarantine"
        ),
        lambda: service.re_enable_package(
            extension_id=EXT, publisher=PUBLISHER, actor=EXTENSION_ACTOR, reason="self-clear"
        ),
        lambda: service.re_enable_version(
            extension_id=EXT,
            version=VERSION,
            publisher=PUBLISHER,
            actor=EXTENSION_ACTOR,
            reason="self-clear",
        ),
        lambda: service.re_enable_publisher(
            publisher=PUBLISHER, actor=EXTENSION_ACTOR, reason="self-clear"
        ),
    ]
    for mutation in mutations:
        with pytest.raises(QuarantineAuthorityError, match="extensions hold no authority"):
            mutation()
    assert _admit(service).allowed, "failed mutations must not have changed state"
    assert len(service.ledger) == 0


def test_extension_actor_cannot_clear_an_administrator_quarantine() -> None:
    service = _service()
    service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    with pytest.raises(QuarantineAuthorityError):
        service.re_enable_package(
            extension_id=EXT, publisher=PUBLISHER, actor=EXTENSION_ACTOR, reason="self-clear"
        )
    assert not _admit(service).allowed


def test_authorized_actors_can_mutate() -> None:
    service = _service()
    service.quarantine_package(
        extension_id=EXT, publisher=PUBLISHER, actor=ORG_ADMIN, reason="org decision"
    )
    assert not _admit(service).allowed
    service.re_enable_package(
        extension_id=EXT, publisher=PUBLISHER, actor=ORG_ADMIN, reason="reviewed and cleared"
    )
    assert _admit(service).allowed


def test_governance_actor_requires_an_id() -> None:
    with pytest.raises(QuarantineAuthorityError):
        GovernanceActor(kind=ActorKind.HOST_ADMIN, id="  ")


# --------------------------------------------------------------------------
# Distinct responses: version disable vs package quarantine vs publisher
# --------------------------------------------------------------------------


def test_version_disable_does_not_condemn_sibling_versions() -> None:
    """One bad version stops; unrelated signed versions keep running."""
    service = _service()
    service.disable_version(
        extension_id=EXT,
        version=VERSION,
        publisher=PUBLISHER,
        actor=ADMIN,
        reason="regression in 1.4.0",
    )
    assert not _admit(service).allowed
    sibling = _admit(service, version=SIBLING)
    assert sibling.allowed
    other = _admit(service, extension_id=OTHER_EXT, version=VERSION)
    assert other.allowed


def test_package_quarantine_blocks_all_versions_but_not_other_packages() -> None:
    service = _service()
    service.quarantine_package(extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="x")
    assert not _admit(service).allowed
    assert not _admit(service, version=SIBLING).allowed
    assert _admit(service, extension_id=OTHER_EXT).allowed
    assert _admit(service, extension_id=OTHER_PUBLISHER_EXT, publisher=OTHER_PUBLISHER).allowed


def test_publisher_quarantine_is_an_explicit_action() -> None:
    service = _service()
    service.quarantine_publisher(publisher=PUBLISHER, actor=ADMIN, reason="publisher-wide breach")
    assert not _admit(service).allowed
    assert not _admit(service, extension_id=OTHER_EXT).allowed
    assert _admit(service, extension_id=OTHER_PUBLISHER_EXT, publisher=OTHER_PUBLISHER).allowed


def test_publisher_wide_policy_quarantines_the_publisher_on_trigger() -> None:
    """Off by default (one bad package must not condemn its publisher); a
    deployment that chooses it gets the wide action."""
    default_service = _service()
    default_service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    assert _admit(default_service, extension_id=OTHER_EXT, version=SIBLING).allowed

    wide_service = _service(publisher_wide=True)
    wide_service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    refused = _admit(wide_service, extension_id=OTHER_EXT, version=SIBLING)
    assert not refused.allowed
    assert "publisher" in refused.reason


# --------------------------------------------------------------------------
# Publisher identity is pinned to the package (identity binding)
# --------------------------------------------------------------------------


def test_quarantined_package_cannot_be_bypassed_by_a_different_publisher() -> None:
    """A package pinned to publisher A stays quarantined even when admission
    names the same extension id under publisher B (fail-closed)."""
    service = _service()
    service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    refused = _admit(service, publisher=OTHER_PUBLISHER)
    assert not refused.allowed
    assert refused.governing_state is GovernanceState.QUARANTINED
    assert PUBLISHER in refused.reason and OTHER_PUBLISHER in refused.reason
    with pytest.raises(QuarantineAuthorityError):
        service.begin_invocation(
            extension_id=EXT, version=VERSION, publisher=OTHER_PUBLISHER
        )


def test_mismatched_publisher_cannot_blend_strikes_or_clear_a_package() -> None:
    """Evidence, and every package mutation, must name the pinned publisher;
    strikes never blend across publishers and a hold is never lifted under
    an impostor publisher."""
    service = _service()
    service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    with pytest.raises(QuarantineAuthorityError):
        service.record(
            security_evidence(
                extension_id=EXT, version=VERSION, publisher=OTHER_PUBLISHER, detail="y"
            ),
            actor=SYSTEM,
        )
    assert service.strikes(extension_id=EXT, version=VERSION, kind=EvidenceKind.SECURITY_VIOLATION) == 1
    for mutation in (
        lambda: service.disable_version(
            extension_id=EXT, version=VERSION, publisher=OTHER_PUBLISHER,
            actor=ADMIN, reason="x",
        ),
        lambda: service.quarantine_package(
            extension_id=EXT, publisher=OTHER_PUBLISHER, actor=ADMIN, reason="x"
        ),
        lambda: service.re_enable_version(
            extension_id=EXT, version=VERSION, publisher=OTHER_PUBLISHER,
            actor=ADMIN, reason="x",
        ),
        lambda: service.re_enable_package(
            extension_id=EXT, publisher=OTHER_PUBLISHER, actor=ADMIN, reason="x"
        ),
    ):
        with pytest.raises(QuarantineAuthorityError):
            mutation()
    assert not _admit(service).allowed


def test_first_pinning_wins_and_matching_publishers_are_unaffected() -> None:
    """The first publisher seen for an extension id is canonical; later
    operations under the same publisher behave exactly as before."""
    service = _service()
    service.disable_version(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER,
        actor=ADMIN, reason="bad build",
    )
    assert not _admit(service).allowed
    service.re_enable_version(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER,
        actor=ADMIN, reason="reviewed",
    )
    assert _admit(service).allowed
    assert _admit(service, extension_id=OTHER_PUBLISHER_EXT, publisher=OTHER_PUBLISHER).allowed


# --------------------------------------------------------------------------
# Re-enable is canonical, audited, and never erases evidence
# --------------------------------------------------------------------------


def test_re_enable_preserves_strikes_and_history() -> None:
    service = _service()
    service.record(
        security_evidence(
            extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="strike 1"
        ),
        actor=SYSTEM,
    )
    service.re_enable_package(extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="reviewed")
    assert _admit(service).allowed
    # Evidence and the quarantine decision remain queryable.
    history = service.ledger.history(extension_id=EXT)
    assert any(event.action == "quarantined" for event in history)
    assert any(event.action == "package_re_enabled" for event in history)
    assert (
        service.strikes(extension_id=EXT, version=VERSION, kind=EvidenceKind.SECURITY_VIOLATION)
        == 1
    )
    # The next violation re-quarantines from lifetime strikes, not a slate
    # wiped by re-enable.
    decision = service.record(
        security_evidence(
            extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="strike 2"
        ),
        actor=SYSTEM,
    )
    assert decision.suspended
    assert not _admit(service).allowed


def test_package_lift_under_quarantined_publisher_reports_effective_state() -> None:
    """``re_enable_package`` records the effective governing state, not just
    the package layer: lifting a package while its publisher stays
    quarantined must audit ``state_after=QUARANTINED`` (the identity is not
    actually active) and keep refusing admission."""
    service = _service()
    service.quarantine_publisher(publisher=PUBLISHER, actor=ADMIN, reason="publisher breach")
    service.quarantine_package(
        extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="bad package"
    )
    decision = service.re_enable_package(
        extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="package reviewed"
    )
    assert decision.changed
    assert decision.state_after is GovernanceState.QUARANTINED
    assert decision.suspended
    assert not _admit(service).allowed
    # Only lifting the publisher returns the identity to a genuinely active
    # state, and the package lift itself stays on the ledger.
    lifted = service.re_enable_publisher(publisher=PUBLISHER, actor=ADMIN, reason="reviewed")
    assert lifted.state_after is GovernanceState.ACTIVE
    assert not lifted.suspended
    assert _admit(service).allowed
    history = service.ledger.history(extension_id=EXT)
    assert any(
        event.action == "package_re_enabled" and event.state_after is GovernanceState.QUARANTINED
        for event in history
    )


def test_history_is_append_only_and_narrowable() -> None:
    service = _service()
    service.record(
        security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x"),
        actor=SYSTEM,
    )
    service.re_enable_package(extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="reviewed")
    before = service.ledger.history()
    service.record(
        security_evidence(extension_id=EXT, version=SIBLING, publisher=PUBLISHER, detail="y"),
        actor=SYSTEM,
    )
    after = service.ledger.history()
    assert after[: len(before)] == before, "history must never be rewritten"
    assert len(after) > len(before)
    narrowed = service.ledger.history(extension_id=EXT, version=VERSION)
    assert all(event.version == VERSION for event in narrowed)
    # Attribution: every row names the actor kind and id.
    assert all(":" in event.actor for event in after)
    assert all(event.reason for event in after)


def test_audit_rows_carry_evidence_digests() -> None:
    service = _service()
    evidence = security_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="x")
    service.record(evidence, actor=SYSTEM)
    (event,) = service.ledger.history(extension_id=EXT)
    assert event.evidence_digest == evidence.digest


# --------------------------------------------------------------------------
# The M9-G2 → M9-G4 seam
# --------------------------------------------------------------------------


def test_sandbox_bridge_feeds_boundary_events_into_governance() -> None:
    service = _service()
    bridge = SandboxViolationBridge(service, publisher=PUBLISHER)
    for strike in range(3):
        decision = bridge.record(_sandbox_violation(detail=f"strike {strike}"))
    assert decision.suspended
    assert not _admit(service).allowed
    assert (
        service.strikes(extension_id=EXT, version=VERSION, kind=EvidenceKind.SANDBOX_VIOLATION) == 3
    )
    (event,) = [e for e in service.ledger.history(extension_id=EXT) if e.action == "quarantined"]
    assert "resource_limit_exceeded: strike 2" in event.reason


def test_sandbox_bridge_kinds_round_trip() -> None:
    service = _service(sandbox_threshold=1)
    bridge = SandboxViolationBridge(service, publisher=PUBLISHER)
    decision = bridge.record(
        _sandbox_violation(kind=ViolationKind.SANDBOX_TEARDOWN_FAILURE, detail="leak")
    )
    assert decision.suspended
    (event,) = service.ledger.history(extension_id=EXT)
    assert "sandbox_teardown_failure: leak" in event.reason


def test_unknown_identity_admits_until_evidence_says_otherwise() -> None:
    """Governance is evidence-driven: an identity with no recorded evidence
    is active. (Deny-by-default enablement lives in the #971/#969 policy
    layers; this flow governs suspension, not onboarding.)"""
    service = _service()
    assert _admit(service).allowed


def test_re_enable_paths_work_on_never_governed_identities() -> None:
    """Degenerate path: lifting a suspension that was never imposed is a
    truthful no-op that still records who decided it."""
    service = _service()
    service.re_enable_version(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER, actor=ADMIN, reason="reviewed"
    )
    service.re_enable_publisher(publisher=PUBLISHER, actor=ADMIN, reason="reviewed")
    assert _admit(service).allowed
    assert len(service.ledger) == 2


def test_strikes_for_unknown_identity_is_zero() -> None:
    service = _service()
    assert (
        service.strikes(
            extension_id="never.seen", version="1.0.0", kind=EvidenceKind.SANDBOX_VIOLATION
        )
        == 0
    )


def test_evidence_on_governed_identities_reports_the_effective_state() -> None:
    """Below-threshold evidence rows report the identity's actual governing
    state — quarantined package, publisher, or disabled version — not a
    blanket ACTIVE."""
    service = _service(security_threshold=5)
    service.disable_version(
        extension_id=EXT, version=VERSION, publisher=PUBLISHER, actor=ADMIN, reason="x"
    )
    decision = service.record(
        health_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="timeout"),
        actor=SYSTEM,
    )
    assert decision.state_after is GovernanceState.DISABLED

    package_quarantine = _service(security_threshold=5)
    package_quarantine.quarantine_package(
        extension_id=EXT, publisher=PUBLISHER, actor=ADMIN, reason="x"
    )
    decision = package_quarantine.record(
        health_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="timeout"),
        actor=SYSTEM,
    )
    assert decision.state_after is GovernanceState.QUARANTINED

    publisher_quarantine = _service(security_threshold=5)
    publisher_quarantine.quarantine_publisher(publisher=PUBLISHER, actor=ADMIN, reason="x")
    decision = publisher_quarantine.record(
        health_evidence(extension_id=EXT, version=VERSION, publisher=PUBLISHER, detail="timeout"),
        actor=SYSTEM,
    )
    assert decision.state_after is GovernanceState.QUARANTINED
