"""Extension quarantine/health-response authority (#972, M9-G4).

These tests drive the quarantine authority against its acceptance criteria
using reachable production behavior: an extension cannot write or clear its
own quarantine/security state; a suspended extension receives no new
invocations regardless of who asks; history stays queryable; re-enable is a
canonical authorized action that erases nothing; a bad version is disabled
without condemning unrelated signed versions unless policy chooses
publisher-wide action; and the race between quarantine and concurrent
invocation is decided by structure (one per-identity lock), proven with
deterministic gates rather than wall-clock timing.
"""

from __future__ import annotations

import asyncio
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from maistro.capabilities.invocation import InvocationStatus
from maistro.container import Container
from maistro.extensions import (
    CANONICAL_VIOLATION_SOURCES,
    ExtensionQuarantineAuthority,
    ExtensionQuarantined,
    ExtensionQuarantineError,
    ExtensionScope,
    ExtensionViolationEvent,
    InFlightDisposition,
    InMemoryQuarantineStore,
    InvocationAdmission,
    NonCanonicalViolationSource,
    QuarantineNotActive,
    QuarantinePolicy,
    QuarantineRecord,
    QuarantineState,
    UnauthorizedQuarantineActor,
    ViolationSeverity,
)

# Package-level "ViolationKind" is the sandbox-boundary enum from
# maistro.extensions.isolation (develop's M9-G2 surface); the quarantine
# evidence-stream enum rides under its own module namespace.
from maistro.extensions.quarantine import ViolationKind

ORG = "org-1"
SCOPE = ExtensionScope(org_id=ORG, workspace_id="")
EXT = "acme.chart_tools"
VERSION = "1.4.0"
OTHER_VERSION = "1.5.0"
ADMIN = "admin@org-1"
EXTENSION_ACTOR = f"extension:{EXT}"


class _Clock:
    """Deterministic clock the tests advance explicitly — no wall-clock races."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class _GatedStore(InMemoryQuarantineStore):
    """Store whose first ``record_for`` read pauses inside the caller's lock.

    The pause point sits inside :meth:`admit_invocation`'s critical section,
    which is exactly where a TOCTOU bug would let a concurrent quarantine
    land between the state check and the admit.
    """

    def __init__(self) -> None:
        super().__init__()
        self.gate_entered = asyncio.Event()
        self.release_gate = asyncio.Event()
        self.record_for_calls = 0

    async def record_for(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> QuarantineRecord | None:
        self.record_for_calls += 1
        if self.record_for_calls == 1:
            self.gate_entered.set()
            await asyncio.wait_for(self.release_gate.wait(), timeout=5)
        return await super().record_for(scope, extension_id, version)


def make_authority(
    *,
    policy: QuarantinePolicy | None = None,
    publishers: dict[str, str] | None = None,
    store: InMemoryQuarantineStore | None = None,
) -> tuple[ExtensionQuarantineAuthority, InMemoryQuarantineStore, _Clock]:
    store = store or InMemoryQuarantineStore()
    clock = _Clock()
    publisher_map = publishers if publishers is not None else {EXT: "pub-acme"}
    authority = ExtensionQuarantineAuthority(
        store,
        policy=policy,
        clock=clock,
        publisher_for=lambda _scope, extension_id, _version: publisher_map.get(extension_id),
    )
    return authority, store, clock


async def security_violation(
    authority: ExtensionQuarantineAuthority,
    *,
    severity: ViolationSeverity = ViolationSeverity.CRITICAL,
    version: str = VERSION,
    reason: str = "warden flagged secret exfiltration in payload",
) -> tuple[ExtensionViolationEvent, QuarantineRecord | None]:
    return await authority.record_security_violation(
        SCOPE,
        EXT,
        version,
        source="warden",
        severity=severity,
        reason=reason,
        evidence_ref="warden:event-41",
    )


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestQuarantineBlocksNewInvocations:
    """Suspended targets receive no new Invocations, whoever requests them."""

    async def test_package_quarantine_refuses_every_version(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="severe warden finding")

        for version in (VERSION, OTHER_VERSION):
            with pytest.raises(ExtensionQuarantined) as excinfo:
                await authority.admit_invocation(SCOPE, EXT, version)
            assert "severe warden finding" in str(excinfo.value)

    async def test_version_disable_refuses_only_that_version(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.quarantine(
            SCOPE, EXT, actor=ADMIN, reason="1.4.0 misbehaves", version=VERSION
        )

        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)
        admitted = await authority.admit_invocation(SCOPE, EXT, OTHER_VERSION)
        assert admitted.version == OTHER_VERSION

    async def test_refusal_is_immediate_with_no_grace_window(self) -> None:
        authority, _store, clock = make_authority()
        before = clock.now
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="now")
        # Same tick, same instant: the block is already authoritative.
        assert clock.now == before
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_version_reenable_cannot_undercut_package_quarantine(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="package compromised")

        with pytest.raises(QuarantineNotActive, match="package-quarantined"):
            await authority.reenable(
                SCOPE, EXT, actor=ADMIN, reason="partial lift", version=VERSION
            )
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)

        await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="reviewed and cleared")
        admitted = await authority.admit_invocation(SCOPE, EXT, VERSION)
        assert admitted.open is True

    async def test_scopes_are_independent(self) -> None:
        authority, _store, _clock = make_authority()
        other_scope = ExtensionScope(org_id="org-2")
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="org-1 finding")

        admitted = await authority.admit_invocation(other_scope, EXT, VERSION)
        assert admitted.org_id == "org-2"
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestExtensionCannotWriteOrClearItsOwnState:
    """The extension has no path to its own quarantine/security state."""

    async def test_extension_actor_cannot_quarantine(self) -> None:
        authority, store, _clock = make_authority()
        with pytest.raises(UnauthorizedQuarantineActor, match="reserved"):
            await authority.quarantine(SCOPE, EXT, actor=EXTENSION_ACTOR, reason="self-suspension")
        assert await store.records_for_extension(SCOPE, EXT) == ()

    async def test_extension_actor_cannot_reenable(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="compromised")
        with pytest.raises(UnauthorizedQuarantineActor):
            await authority.reenable(SCOPE, EXT, actor=EXTENSION_ACTOR, reason="self-clear")
        records = await authority.state(SCOPE, EXT)
        assert records[0].state is QuarantineState.QUARANTINED

    async def test_extension_actor_cannot_reenable_with_case_or_space_games(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="compromised")
        for actor in (f"Extension:{EXT}", f"  {EXTENSION_ACTOR}  "):
            with pytest.raises(UnauthorizedQuarantineActor):
                await authority.reenable(SCOPE, EXT, actor=actor, reason="self-clear")

    async def test_extension_controlled_source_cannot_mint_evidence(self) -> None:
        authority, store, _clock = make_authority()
        for source in (EXT, f"extension:{EXT}", "my-own-probe", ""):
            with pytest.raises(NonCanonicalViolationSource):
                await authority.record_security_violation(
                    SCOPE,
                    EXT,
                    VERSION,
                    source=source,
                    severity=ViolationSeverity.CRITICAL,
                    reason="self-reported",
                )
            with pytest.raises(NonCanonicalViolationSource):
                await authority.record_health_failure(
                    SCOPE, EXT, VERSION, reason="self-reported", source=source
                )
        assert await store.events_for(SCOPE, EXT) == ()
        # And the refused reports never became a suspension either.
        await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_state_changes_require_accountable_actor_and_reason(self) -> None:
        authority, _store, _clock = make_authority()
        with pytest.raises(ValueError, match="actor is required"):
            await authority.quarantine(SCOPE, EXT, actor="  ", reason="x")
        with pytest.raises(ValueError, match="reason is required"):
            await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="  ")
        with pytest.raises(ValueError, match="actor is required"):
            await authority.reenable(SCOPE, EXT, actor="", reason="x")

    async def test_admission_token_is_inert_data(self) -> None:
        authority, _store, _clock = make_authority()
        admission = await authority.admit_invocation(SCOPE, EXT, VERSION)

        # Frozen: no attribute write can reshape the token...
        with pytest.raises(Exception, match="cannot assign to field"):
            admission.open = False  # type: ignore[misc]
        # ...and it carries only plain data — no service, store or callable
        # back-reference an extension could reach state through.
        for f in fields(admission):
            value = getattr(admission, f.name)
            assert not callable(value), f"admission field {f.name} is callable"

    async def test_evidence_ledger_has_no_delete_seam(self) -> None:
        store = InMemoryQuarantineStore()
        mutators = {name for name in dir(store) if not name.startswith("_")}
        forbidden = {"delete", "purge", "trim", "clear", "rewrite", "erase", "drop"}
        assert not mutators & forbidden, f"store exposes an erasure seam: {mutators & forbidden}"
        # And everything ever appended stays readable.
        authority, _wired, _clock = make_authority()
        await security_violation(authority)
        assert len(await authority.violation_history(SCOPE, EXT)) == 1


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestThresholdsAndStateDistinction:
    """Package quarantine, version disable and transient failure stay distinct."""

    async def test_transient_health_failure_records_but_does_not_block(self) -> None:
        authority, _store, _clock = make_authority()
        verdict = await authority.record_health_failure(
            SCOPE, EXT, VERSION, reason="first timeout in a week"
        )
        assert verdict.quarantined is False
        assert verdict.strikes_in_window == 1
        assert verdict.record is None
        admitted = await authority.admit_invocation(SCOPE, EXT, VERSION)
        assert admitted.open is True

    async def test_strike_limit_auto_disables_the_failing_version(self) -> None:
        authority, _store, _clock = make_authority()
        limit = authority._policy.health_strike_limit
        verdict = None
        for n in range(1, limit + 1):
            verdict = await authority.record_health_failure(
                SCOPE, EXT, VERSION, reason=f"failure {n}"
            )
        assert verdict is not None and verdict.quarantined is True
        assert verdict.record is not None
        assert verdict.record.state is QuarantineState.DISABLED
        assert verdict.record.version == VERSION
        assert verdict.record.strikes == limit
        assert verdict.record.actor == "policy:auto-quarantine"
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_strikes_age_out_of_the_window_but_events_remain(self) -> None:
        authority, _store, clock = make_authority()
        window = authority._policy.health_strike_window
        for n in range(3):
            await authority.record_health_failure(SCOPE, EXT, VERSION, reason=f"failure {n}")
            clock.advance(window + timedelta(seconds=1))
        verdict = await authority.record_health_failure(
            SCOPE, EXT, VERSION, reason="one more, long after"
        )
        assert verdict.quarantined is False
        assert verdict.strikes_in_window == 1
        assert verdict.cumulative_failures == 4
        assert len(await authority.violation_history(SCOPE, EXT)) == 4
        await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_security_below_floor_is_evidence_without_suspension(self) -> None:
        authority, _store, _clock = make_authority()
        event, record = await security_violation(authority, severity=ViolationSeverity.LOW)
        assert event.kind is ViolationKind.SECURITY_POLICY
        assert record is None
        await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_security_at_floor_disables_exactly_the_violating_version(self) -> None:
        authority, _store, _clock = make_authority()
        event, record = await security_violation(authority, severity=ViolationSeverity.HIGH)
        assert record is not None
        assert record.state is QuarantineState.DISABLED
        assert record.version == VERSION
        assert event.evidence_ref == "warden:event-41"
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)
        admitted = await authority.admit_invocation(SCOPE, EXT, OTHER_VERSION)
        assert admitted.version == OTHER_VERSION

    async def test_publisher_wide_policy_is_a_policy_choice(self) -> None:
        wide = QuarantinePolicy(publisher_wide_on_severe=True)
        authority, _store, _clock = make_authority(policy=wide)
        _event, record = await security_violation(authority, severity=ViolationSeverity.CRITICAL)
        assert record is not None
        assert record.state is QuarantineState.QUARANTINED
        assert record.version == ""
        for version in (VERSION, OTHER_VERSION):
            with pytest.raises(ExtensionQuarantined):
                await authority.admit_invocation(SCOPE, EXT, version)

    async def test_repeated_auto_quarantine_records_one_transition(self) -> None:
        authority, store, _clock = make_authority()
        for n in range(6):
            await authority.record_health_failure(SCOPE, EXT, VERSION, reason=f"failure {n}")
        transitions = await store.transitions_for(SCOPE, EXT)
        auto = [t for t in transitions if t.actor == "policy:auto-quarantine"]
        assert len(auto) == 1
        assert auto[0].to_state is QuarantineState.DISABLED
        assert len(await store.events_for(SCOPE, EXT)) == 6

    async def test_policy_rejects_degenerate_thresholds(self) -> None:
        with pytest.raises(ValueError, match="health_strike_limit"):
            QuarantinePolicy(health_strike_limit=0)
        with pytest.raises(ValueError, match="health_strike_window"):
            QuarantinePolicy(health_strike_window=timedelta(0))


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestInFlightDisposition:
    """Suspension dispositions in-flight work per policy, immediately."""

    async def test_default_policy_cancels_in_flight_work(self) -> None:
        authority, _store, _clock = make_authority()
        first = await authority.admit_invocation(SCOPE, EXT, VERSION)
        second = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="stop everything")

        live = await authority.state(SCOPE, EXT)
        assert live[0].state is QuarantineState.QUARANTINED
        # Dispositions are recorded on the authoritative rows at the moment
        # the suspension lands; hosts drain from the in_flight view.
        in_flight = await authority.in_flight(SCOPE, EXT)
        assert {a.admission_id for a in in_flight} == {first.admission_id, second.admission_id}
        for admission in in_flight:
            assert admission.disposition is InFlightDisposition.CANCEL
            assert admission.quarantined_at is not None
            assert admission.open is True  # disposition is the host's cue

        closed = await authority.complete_invocation(first, outcome=InvocationStatus.UNKNOWN)
        assert closed.outcome is InvocationStatus.UNKNOWN
        assert closed.open is False
        # Completion is evidence, never a state change.
        live_after = await authority.state(SCOPE, EXT)
        assert live_after[0].state is QuarantineState.QUARANTINED

    async def test_let_finish_policy_is_available_to_hosts(self) -> None:
        policy = QuarantinePolicy(in_flight_disposition=InFlightDisposition.LET_FINISH)
        authority, _store, _clock = make_authority(policy=policy)
        admission = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="drain gracefully")
        stored = (await authority.in_flight(SCOPE, EXT))[0]
        assert stored.disposition is InFlightDisposition.LET_FINISH

        closed = await authority.complete_invocation(admission, outcome=InvocationStatus.COMPLETED)
        assert closed.outcome is InvocationStatus.COMPLETED

    async def test_completion_of_dispositioned_work_cannot_lift_state(self) -> None:
        authority, _store, _clock = make_authority()
        admission = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="suspend now")
        await authority.complete_invocation(admission, outcome=InvocationStatus.UNKNOWN)
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_invocation_completes_at_most_once(self) -> None:
        authority, _store, _clock = make_authority()
        admission = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.complete_invocation(admission, outcome=InvocationStatus.COMPLETED)
        with pytest.raises(ExtensionQuarantineError, match="at most once"):
            await authority.complete_invocation(admission, outcome=InvocationStatus.FAILED)

    async def test_completion_refuses_non_terminal_canonical_statuses(self) -> None:
        authority, _store, _clock = make_authority()
        admission = await authority.admit_invocation(SCOPE, EXT, VERSION)
        for non_terminal in (InvocationStatus.CREATED, InvocationStatus.RUNNING):
            with pytest.raises(ValueError, match="terminal canonical invocation status"):
                await authority.complete_invocation(admission, outcome=non_terminal)
        # The refused completion recorded nothing.
        stored = (await authority.in_flight(SCOPE, EXT))[0]
        assert stored.outcome is None and stored.open is True


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestReenableAndEvidenceRetention:
    """Re-enable is canonical, audited, and erases nothing."""

    async def test_reenable_requires_an_active_suspension(self) -> None:
        authority, _store, _clock = make_authority()
        with pytest.raises(QuarantineNotActive):
            await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="nothing suspended")
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="suspend")
        await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="reviewed")
        with pytest.raises(QuarantineNotActive):
            await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="already lifted")

    async def test_reenable_erases_no_strike_or_violation_evidence(self) -> None:
        authority, _store, _clock = make_authority()
        for n in range(3):
            await authority.record_health_failure(SCOPE, EXT, VERSION, reason=f"failure {n}")
        before_events = await authority.violation_history(SCOPE, EXT)
        before_admissions = await authority.invocation_history(SCOPE, EXT)

        # The strike-out disabled exactly this version; the operator lifts
        # that suspension by name.
        await authority.reenable(
            SCOPE, EXT, actor=ADMIN, reason="operator reviewed the strikes", version=VERSION
        )

        assert await authority.violation_history(SCOPE, EXT) == before_events
        after_admissions = await authority.invocation_history(SCOPE, EXT)
        assert len(after_admissions) == len(before_admissions)
        # The full story is in the audit trail, including the lift.
        transitions = await authority.transition_history(SCOPE, EXT)
        assert [(t.from_state, t.to_state) for t in transitions] == [
            (QuarantineState.NONE, QuarantineState.DISABLED),
            (QuarantineState.DISABLED, QuarantineState.NONE),
        ]
        assert transitions[-1].actor == ADMIN

        # Evidence survives a relapse — with teeth: the clock has not moved,
        # so the three pre-re-enable strikes are still inside the policy
        # window, and the first post-re-enable failure re-suspends the
        # version immediately. Re-enable bought review, not an expungement.
        verdict = await authority.record_health_failure(
            SCOPE, EXT, VERSION, reason="relapse after re-enable"
        )
        assert verdict.quarantined is True
        assert verdict.strikes_in_window == 4
        assert verdict.record is not None
        assert verdict.record.state is QuarantineState.DISABLED
        assert len(await authority.violation_history(SCOPE, EXT)) == 4

    async def test_history_remains_queryable_across_quarantine(self) -> None:
        authority, _store, _clock = make_authority()
        first = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await authority.complete_invocation(first, outcome=InvocationStatus.COMPLETED)
        _second = await authority.admit_invocation(SCOPE, EXT, VERSION)
        await security_violation(authority)

        history = await authority.invocation_history(SCOPE, EXT)
        assert len(history) == 2
        assert history[0].outcome is InvocationStatus.COMPLETED
        assert history[1].outcome is None
        assert {a.disposition for a in history if a.disposition is not None} == {
            InFlightDisposition.CANCEL
        }
        violations = await authority.violation_history(SCOPE, EXT)
        assert violations[0].source == "warden"
        assert violations[0].publisher_id == "pub-acme"

    async def test_record_attribution_carries_extension_version_publisher(self) -> None:
        authority, _store, _clock = make_authority()
        _event, record = await security_violation(authority)
        assert record is not None
        assert record.publisher_id == "pub-acme"
        assert record.extension_id == EXT
        assert record.version == VERSION

        unattributed = make_authority(publishers={})[0]
        admission = await unattributed.admit_invocation(SCOPE, "other.ext", "2.0.0")
        assert admission.publisher_id == ""


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestRaceQuarantineVersusInvocation:
    """Quarantine and concurrent invocation cannot admit work after the change.

    Determinism note: every interleaving below is forced with explicit
    gates/events under the authority's own per-identity lock — none depends
    on scheduler timing or sleeps.
    """

    async def test_no_admission_succeeds_after_quarantine_returns(self) -> None:
        authority, store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="authoritative change")

        # A concurrent storm of client/UI retries after the change: all lose.
        results = await asyncio.gather(
            *(authority.admit_invocation(SCOPE, EXT, f"1.4.{n}") for n in range(50)),
            return_exceptions=True,
        )
        assert all(isinstance(r, ExtensionQuarantined) for r in results)
        assert await store.admissions_for(SCOPE, EXT) == ()

    async def test_concurrent_admissions_before_quarantine_all_land(self) -> None:
        authority, store, _clock = make_authority()
        admissions = await asyncio.gather(
            *(authority.admit_invocation(SCOPE, EXT, VERSION) for _ in range(25))
        )
        assert len({a.admission_id for a in admissions}) == 25
        assert len(await store.admissions_for(SCOPE, EXT)) == 25

    async def test_suspension_cannot_interleave_inside_an_admission(self) -> None:
        """The TOCTOU proof.

        An admission pauses mid-flight *inside* the per-identity lock (on its
        first authoritative state read). A concurrent quarantine must block
        until the admission completes; the authoritative change then lands
        and dispositions that in-flight admission; and anything arriving
        after the change is refused. There is no interleaving in which a
        state check passes and the suspension slips in before the admit.
        """
        store = _GatedStore()
        authority, _wired, _clock = make_authority(store=store)

        admission_task = asyncio.create_task(authority.admit_invocation(SCOPE, EXT, VERSION))
        await asyncio.wait_for(store.gate_entered.wait(), timeout=5)

        quarantine_task = asyncio.create_task(
            authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="racing the gate")
        )
        # Let the quarantine task run up to the identity lock and block there.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not quarantine_task.done(), "quarantine must wait for the in-flight admission"
        assert store.record_for_calls == 1, "quarantine must not observe state mid-admission"

        store.release_gate.set()
        admission = await asyncio.wait_for(admission_task, timeout=5)
        quarantine_record = await asyncio.wait_for(quarantine_task, timeout=5)

        # The pre-change admission completed, then the change landed over it:
        # it is in-flight work now, dispositioned by the authoritative state.
        assert admission.open is True
        stored = (await authority.in_flight(SCOPE, EXT))[0]
        assert stored.admission_id == admission.admission_id
        assert stored.disposition is InFlightDisposition.CANCEL
        assert stored.quarantined_at is not None
        assert quarantine_record.state is QuarantineState.QUARANTINED

        # And after the authoritative change: nothing new gets in.
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)
        history = await store.admissions_for(SCOPE, EXT)
        assert len(history) == 1
        assert history[0].admission_id == admission.admission_id

    async def test_auto_quarantine_fires_exactly_once_under_concurrent_failures(self) -> None:
        authority, store, _clock = make_authority()
        verdicts = await asyncio.gather(
            *(
                authority.record_health_failure(SCOPE, EXT, VERSION, reason=f"failure {n}")
                for n in range(10)
            )
        )
        # Failures 1..2 are transient; the limit strike lands the suspension;
        # every later failure reports an already-active suspension.
        assert [v.quarantined for v in verdicts[:2]] == [False, False]
        assert all(v.quarantined for v in verdicts[2:])
        first_quarantine = verdicts[2]
        assert first_quarantine.record is not None
        assert first_quarantine.record.strikes == authority._policy.health_strike_limit
        transitions = await store.transitions_for(SCOPE, EXT)
        assert len(transitions) == 1
        assert transitions[0].actor == "policy:auto-quarantine"
        assert transitions[0].to_state is QuarantineState.DISABLED
        assert len(await store.events_for(SCOPE, EXT)) == 10
        with pytest.raises(ExtensionQuarantined):
            await authority.admit_invocation(SCOPE, EXT, VERSION)

    async def test_disposition_covers_every_open_admission_exactly_once(self) -> None:
        authority, store, _clock = make_authority()
        admissions = [await authority.admit_invocation(SCOPE, EXT, VERSION) for _ in range(8)]
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="drain")
        # Re-affirming the suspension must not re-disposition (or rewrite) them.
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="still suspended")
        stored = {a.admission_id: a for a in await store.admissions_for(SCOPE, EXT)}
        for admission in admissions:
            stored_row = stored[admission.admission_id]
            assert stored_row.disposition is InFlightDisposition.CANCEL
            assert stored_row.open is True


# --------------------------------------------------------------------------
# Container wiring
# --------------------------------------------------------------------------


def _bare_container() -> Container:
    return Container(
        config=None,
        router=None,
        classifier=None,
        quota_tracker=None,
        learning_store=None,
        learning_extractor=None,
        outcome_store=None,
        session_store=None,
        warden=None,
        gate=None,
        sentinel=None,
        context_builder=None,
        intent_registry=None,
    )


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestContainerWiring:
    def test_authority_is_lazily_built_and_cached(self) -> None:
        container = _bare_container()
        assert container.extension_quarantine_authority is None
        authority = container.ensure_extension_quarantine_authority()
        assert authority is container.ensure_extension_quarantine_authority()
        assert container.extension_quarantine_authority is authority

    def test_default_wiring_uses_in_memory_store(self) -> None:
        container = _bare_container()
        authority = container.ensure_extension_quarantine_authority()
        assert isinstance(authority._store, InMemoryQuarantineStore)

    def test_pre_wired_store_is_kept(self) -> None:
        store = InMemoryQuarantineStore()
        container = _bare_container()
        container.extension_quarantine_store = store
        authority = container.ensure_extension_quarantine_authority()
        assert authority._store is store


# --------------------------------------------------------------------------
# Structure the acceptance criteria lean on
# --------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestCanonicalVocabulary:
    def test_canonical_sources_exclude_extension_controlled_reporters(self) -> None:
        assert (
            frozenset({"warden", "sandbox", "orchestrator", "health"})
            == CANONICAL_VIOLATION_SOURCES
        )
        assert not any(source.startswith("extension:") for source in CANONICAL_VIOLATION_SOURCES)

    def test_frozen_record_write_is_refused(self) -> None:
        record = QuarantineRecord(
            org_id=ORG,
            workspace_id="",
            extension_id=EXT,
            version="",
            publisher_id="pub-acme",
            state=QuarantineState.QUARANTINED,
            reason="r",
            actor=ADMIN,
        )
        with pytest.raises(Exception, match="cannot assign to field"):
            record.state = QuarantineState.NONE  # type: ignore[misc]
        assert record.suspended is True
        assert replace(record, state=QuarantineState.NONE).suspended is False

    def test_admission_fields_are_plain_data(self) -> None:
        import typing

        hints = typing.get_type_hints(InvocationAdmission)
        plain = (str, bool, datetime, InvocationStatus, InFlightDisposition)
        for name, hint in hints.items():
            origin = typing.get_origin(hint)
            assert hint in plain or origin is not None, (
                f"admission field {name} must be plain data, got {hint}"
            )

    async def test_admit_refuses_blank_identity(self) -> None:
        authority, _store, _clock = make_authority()
        with pytest.raises(ValueError, match="extension_id and version"):
            await authority.admit_invocation(SCOPE, " ", "")
        with pytest.raises(ValueError, match="extension_id and version"):
            await authority.admit_invocation(SCOPE, EXT, "")


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestSuspensionRecordsKeptAfterLift:
    async def test_lifted_target_keeps_its_row_and_blocks_nothing(self) -> None:
        authority, _store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="suspend", version=VERSION)
        await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="reviewed", version=VERSION)
        records = await authority.state(SCOPE, EXT)
        assert records[0].state is QuarantineState.NONE
        assert records[0].suspended is False
        admitted = await authority.admit_invocation(SCOPE, EXT, VERSION)
        assert admitted.open is True

    async def test_re_suspend_after_lift_records_true_from_state(self) -> None:
        authority, store, _clock = make_authority()
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="first offense")
        await authority.reenable(SCOPE, EXT, actor=ADMIN, reason="first review")
        await authority.quarantine(SCOPE, EXT, actor=ADMIN, reason="second offense")
        transitions = await store.transitions_for(SCOPE, EXT)
        assert [(t.from_state, t.to_state, t.version) for t in transitions] == [
            (QuarantineState.NONE, QuarantineState.QUARANTINED, ""),
            (QuarantineState.QUARANTINED, QuarantineState.NONE, ""),
            (QuarantineState.NONE, QuarantineState.QUARANTINED, ""),
        ]
