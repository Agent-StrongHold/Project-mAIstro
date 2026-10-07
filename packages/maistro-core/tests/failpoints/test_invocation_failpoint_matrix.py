"""External-effect failpoint matrix over the Invocation boundary (#883).

The canonical external-effect boundary is `capabilities/invocation.py`: one
`effect_key` per logical effect, admission against a durable ledger, and
reconciliation for ambiguous outcomes. This suite crosses the boundary's named
crash seams with recovery strategies and holds the issue's properties in every
combination:

* no duplicate external effect after an ambiguous crash -- the provider is
  physically entered at most once per logical effect, ever;
* crash-before-effect and crash-after-effect remain distinguishable -- the
  ledger row records whether dispatch started, and discovery plus evidence
  settle it either way;
* terminal state cannot regress -- asserted over the full recorded timeline,
  not just the endpoint;
* recovery resumes exactly where the contract permits -- a settled effect
  replays without a provider call; a proven-absent effect re-dispatches.

Every cell is deterministic: fixed inputs, one forced crash at a named write,
one recovery strategy. The cross-product is the experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationReconciliationEvidence,
    InvocationStatus,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)

from ._failpoints import (
    CrashPoint,
    CrashSimulated,
    EffectLedger,
    Failpoint,
    JournalingStore,
    StatusJournal,
)

_EFFECT_KEY = "write:incident-42"
_RUN_ID = "run-1"
_NODE_RUN_ID = "node-run-1"
_STALE = timedelta(hours=1)


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-fp",
        project_id="proj-fp",
        capability="external_write",
    )


def _stale_moment() -> datetime:
    return datetime.now(UTC) + _STALE


@dataclass(frozen=True)
class _Wiring:
    """One scenario's stores, service, provider counter, and remote ledger."""

    crash: CrashPoint
    journal: StatusJournal
    ledger: InMemoryInvocationStore
    remote: EffectLedger
    service: InvocationExecutionService
    calls: list[dict[str, Any]]

    @property
    def provider_calls(self) -> int:
        return len(self.calls)


def _executor_for(wiring: _Wiring) -> Any:
    """The modeled provider call: the remote system commits before returning."""

    async def executor(_provider: Any, request: dict[str, Any]) -> dict[str, Any]:
        wiring.calls.append({"request": request})
        wiring.remote.apply(_EFFECT_KEY)
        return {"remote_id": request["id"]}

    return executor


@dataclass(frozen=True)
class _Provider:
    """The smallest provider handle `ResolvedBinding.from_provider` accepts."""

    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


async def _resolve_ok(_binding: Binding) -> object:
    return _Provider()


def _wiring(seam: str, mode: str) -> _Wiring:
    """Build the boundary with one seam armed.

    Seams, named against `InvocationExecutionService.invoke`'s write sequence:

    admission
        The ledger `claim` that records the admitted effect -- the atomic
        `EffectClaimStore` path `_admit_effect` takes when the wrapped store
        still satisfies the protocol. `before` = the
        process dies before the row exists; `after` = a CREATED row is durable
        but dispatch never started.
    running_persistence
        The `save` that marks the effect RUNNING with `dispatch_active` before
        the provider is entered. Only `after` exists as a window: dying before
        this write is the admission seam's crash, so that alias is not a cell.
    terminal_commit
        The `save` that records the provider response as COMPLETED. `before` =
        the effect happened remotely and the terminal write is lost (the
        ambiguous crash-after-effect); `after` = everything landed.
    """
    journal = StatusJournal()
    ledger = InMemoryInvocationStore()
    remote = EffectLedger()
    calls: list[dict[str, Any]] = []
    crash = CrashPoint(
        JournalingStore(ledger, journal),
        [
            Failpoint("admission", "claim", before=(mode == "before")),
            Failpoint(
                "running_persistence",
                "save",
                when=lambda invocation, **_: invocation.status is InvocationStatus.RUNNING,
            ),
            Failpoint(
                "terminal_commit",
                "save",
                when=lambda invocation, **_: invocation.status is InvocationStatus.COMPLETED,
                before=(mode == "before"),
            ),
        ],
    )
    crash.arm(seam)
    service = InvocationExecutionService(store=crash)
    return _Wiring(
        crash=crash,
        journal=journal,
        ledger=ledger,
        remote=remote,
        service=service,
        calls=calls,
    )


async def _dispatch(wiring: _Wiring, *, attempt_id: str) -> Any:
    """One delivery of the same logical effect under the named Attempt."""
    return await wiring.service.invoke(
        binding=_binding(),
        run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        attempt_id=attempt_id,
        effect_key=_EFFECT_KEY,
        request={"id": "remote-1"},
        resolver=_resolve_ok,
        executor=_executor_for(wiring),
    )


def _require_single_effect(wiring: _Wiring) -> None:
    """The headline property: at most one physical application, ever."""
    applied = wiring.remote.count(_EFFECT_KEY)
    assert applied <= 1, f"effect applied {applied}x after an ambiguous crash"
    assert wiring.provider_calls <= 1


def _require_no_terminal_regression(wiring: _Wiring) -> None:
    regressions = wiring.journal.regressions()
    assert regressions == [], f"terminal state regressed: {regressions}"


async def _settle_not_applied(wiring: _Wiring, invocation_id: str, reason: str) -> None:
    await wiring.service.reconcile(
        invocation_id,
        disposition=ReconciliationDisposition.NOT_APPLIED,
        source="operator",
        actor="operator-1",
        reason=reason,
        evidence={"provider_receipt": "none"},
        workspace_id="ws-fp",
        project_id="proj-fp",
        stale_before=_stale_moment(),
    )


# --- the matrix -----------------------------------------------------------


@pytest.mark.parametrize("mode", ["before", "after"])
async def test_admission_seam(mode: str) -> None:
    """Crash at the admission write: before dies unrecorded, after leaves a row."""
    wiring = _wiring("admission", mode)
    with pytest.raises(CrashSimulated):
        await _dispatch(wiring, attempt_id="attempt-1")
    assert wiring.crash.fired == [("admission", mode)]
    assert wiring.provider_calls == 0

    if mode == "after":
        # A CREATED row with dispatch never started is durable evidence of a
        # crash-before-effect, and a bare retry must not dispatch over it.
        with pytest.raises(UnsafeEffectRetry):
            await _dispatch(wiring, attempt_id="attempt-2")
        assert wiring.provider_calls == 0

        stale = await wiring.service.discover_ambiguous(stale_before=_stale_moment())
        assert [row.effect_key for row in stale] == [_EFFECT_KEY]
        assert stale[0].status is InvocationStatus.CREATED
        assert stale[0].dispatch_active is False

        await _settle_not_applied(
            wiring, stale[0].invocation_id, "provider confirms no write left its queue"
        )
        recovered = await _dispatch(wiring, attempt_id="attempt-2")
        assert recovered.status is InvocationStatus.COMPLETED
    else:
        # Nothing was recorded, so the retry admits fresh and dispatches once.
        wiring.crash.disarm()
        outcome = await _dispatch(wiring, attempt_id="attempt-2")
        assert outcome.status is InvocationStatus.COMPLETED

    assert wiring.provider_calls == 1
    assert wiring.remote.count(_EFFECT_KEY) == 1
    _require_single_effect(wiring)
    _require_no_terminal_regression(wiring)


async def test_running_persistence_seam_is_the_dispatch_announcement() -> None:
    """RUNNING persisted, provider not entered: a crash-before-effect row."""
    wiring = _wiring("running_persistence", "after")
    with pytest.raises(CrashSimulated):
        await _dispatch(wiring, attempt_id="attempt-1")
    assert wiring.crash.fired == [("running_persistence", "after")]

    with pytest.raises(UnsafeEffectRetry):
        await _dispatch(wiring, attempt_id="attempt-2")
    assert wiring.provider_calls == 0
    assert wiring.remote.count(_EFFECT_KEY) == 0

    stale = await wiring.service.discover_ambiguous(stale_before=_stale_moment())
    assert [row.effect_key for row in stale] == [_EFFECT_KEY]
    assert stale[0].status is InvocationStatus.RUNNING
    assert stale[0].dispatch_active is True

    await _settle_not_applied(
        wiring,
        stale[0].invocation_id,
        "provider dispatched nothing; the RUNNING row predates the evidence cut",
    )
    recovered = await _dispatch(wiring, attempt_id="attempt-2")
    assert recovered.status is InvocationStatus.COMPLETED
    assert wiring.provider_calls == 1
    assert wiring.remote.count(_EFFECT_KEY) == 1

    _require_single_effect(wiring)
    _require_no_terminal_regression(wiring)


@pytest.mark.parametrize("mode", ["before", "after"])
async def test_terminal_commit_seam(mode: str) -> None:
    """The ambiguous crash-after-effect, and the settled replay."""
    wiring = _wiring("terminal_commit", mode)
    with pytest.raises(CrashSimulated):
        await _dispatch(wiring, attempt_id="attempt-1")
    assert wiring.crash.fired == [("terminal_commit", mode)]

    # The effect happened remotely; the crash must not cause a second one.
    assert wiring.remote.count(_EFFECT_KEY) == 1
    assert wiring.provider_calls == 1

    if mode == "before":
        # Crash-after-effect is distinguishable from crash-before-effect: the
        # row says RUNNING/dispatch_active, and a provider-adapter report
        # settles it APPLIED from the provider's own records.
        with pytest.raises(UnsafeEffectRetry):
            await _dispatch(wiring, attempt_id="attempt-2")
        stale = await wiring.service.discover_ambiguous(stale_before=_stale_moment())
        assert [row.effect_key for row in stale] == [_EFFECT_KEY]
        assert stale[0].status is InvocationStatus.RUNNING

        settled = await wiring.service.reconcile_with_provider(
            stale[0].invocation_id,
            _ProviderReport(),
            stale_before=_stale_moment(),
        )
        assert settled.status is InvocationStatus.COMPLETED
    else:
        # The terminal write landed; a retry is a pure replay of the same row.
        replayed = await _dispatch(wiring, attempt_id="attempt-2")
        assert replayed.status is InvocationStatus.COMPLETED

    # After settlement the effect replays without ever calling the provider.
    history = await wiring.ledger.list_effect(
        run_id=_RUN_ID, node_run_id=_NODE_RUN_ID, binding_id="binding-1", effect_key=_EFFECT_KEY
    )
    settled_id = history[0].invocation_id
    again = await _dispatch(wiring, attempt_id="attempt-3")
    assert again.status is InvocationStatus.COMPLETED
    assert again.invocation_id == settled_id
    assert wiring.provider_calls == 1
    assert wiring.remote.count(_EFFECT_KEY) == 1

    _require_single_effect(wiring)
    _require_no_terminal_regression(wiring)


@dataclass(frozen=True)
class _ProviderReport:
    """A reconciliation adapter that reads the remote system's own ledger."""

    async def reconcile(self, _invocation: Any) -> InvocationReconciliationEvidence:
        return InvocationReconciliationEvidence(
            disposition=ReconciliationDisposition.APPLIED,
            source="provider-adapter",
            actor="system",
            reason="remote ledger holds remote-1 under incident-42",
            evidence={"remote_id": "remote-1"},
            result={"remote_id": "remote-1"},
        )


async def test_machinery_without_a_crash_is_a_plain_dispatch() -> None:
    """The control cell: no armed failpoint, ordinary exactly-once behavior."""
    wiring = _wiring("terminal_commit", "before")
    wiring.crash.disarm()
    assert wiring.crash.fired == []
    outcome = await _dispatch(wiring, attempt_id="attempt-1")
    assert outcome.status is InvocationStatus.COMPLETED
    replay = await _dispatch(wiring, attempt_id="attempt-2")
    assert replay.status is InvocationStatus.COMPLETED
    assert wiring.provider_calls == 1
    _require_single_effect(wiring)
    _require_no_terminal_regression(wiring)
