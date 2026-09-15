"""route_request() admits and closes a canonical Run (#131).

The chat half of #41. A turn now enters the same spine a task does: admitted as
a Run, moved to running, terminalized whichever way the turn ends, and reported
back additively as `run_id`. These go through `create_container()` specifically,
because the wiring is the thing being tested -- constructing a `ChatRunAdmitter`
directly proves nothing about whether the container reaches for it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import pytest

from maistro.container import Container, create_container
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.chat_admission import (
    ADMISSION_INCOMPLETE,
    CHAT_ADMISSION_LEASE_TTL,
    CHAT_ADMISSION_RECEIPT_KEY,
    CHAT_SOURCE,
    SESSION_ID_KEY,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.types.config import AgentConfig


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


class _Conduit:
    """Stands in for the real Conduit, which needs agents this test has not."""

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self._raises = raises

    async def route_request(self, messages, **_kwargs):
        self.calls.append(messages)
        if self._raises is not None:
            raise self._raises
        return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}


async def test_a_turn_yields_a_run_id_that_resolves() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request(
        [{"role": "user", "content": "what broke?"}], session_id="sess-1"
    )

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE
    assert run.provenance[SESSION_ID_KEY] == "sess-1"


async def test_the_openai_shape_is_untouched() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert result["choices"][0]["message"]["content"] == "hi"
    # Additive, not replacing: a caller that only reads `choices` is unaffected.
    assert set(result) == {"choices", "run_id"}


async def test_the_run_is_completed_when_the_turn_ends() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_a_raising_turn_still_closes_its_run() -> None:
    """A Run left RUNNING is what recovery reads as a process that died."""
    container = await _container()
    container.conduit = _Conduit(raises=RuntimeError("upstream exploded"))

    with pytest.raises(RuntimeError, match="upstream exploded"):
        await container.route_request([{"role": "user", "content": "hi"}])

    runs = [run for run in _chat_runs(container) if run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE]
    assert len(runs) == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].status in TERMINAL_RUN_STATUSES


async def test_cancelled_turn_observes_cancelled_run_without_false_terminalization_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = await _container()
    container.conduit = _Conduit(raises=asyncio.CancelledError())

    with (
        caplog.at_level(logging.WARNING, logger="maistro.container"),
        pytest.raises(asyncio.CancelledError),
    ):
        await container.route_request([{"role": "user", "content": "disconnect"}])

    runs = [run for run in _chat_runs(container) if run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE]
    assert len(runs) == 1
    assert runs[0].status is RunStatus.CANCELLED
    assert "could not be terminalized" not in caplog.text


async def test_cancelled_close_rejects_error_payload() -> None:
    """Cancellation is a terminal cause, not a second failure payload."""
    container = await _container()
    run = await container.chat_admitter.admit([{"role": "user", "content": "hi"}])

    with pytest.raises(ValueError, match="cannot carry error or result"):
        await container._close_chat_run(run, cancelled=True, error="provider_error")

    unchanged = await container.run_store.get_run(run.run_id)
    assert unchanged is not None
    assert unchanged.status is RunStatus.CREATED


async def test_the_turn_is_answered_even_when_admission_fails() -> None:
    """The chat path has no receipt to fall back on, so it must not refuse."""
    container = await _container()
    conduit = _Conduit()
    container.conduit = conduit

    class _Broken:
        async def admit(self, *_args, **_kwargs):
            raise RuntimeError("no project")

    container.chat_admitter = _Broken()  # type: ignore[assignment]

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert len(conduit.calls) == 1
    assert "run_id" not in result


async def test_no_chat_admitter_means_no_run_id_and_no_failure() -> None:
    container = await _container()
    conduit = _Conduit()
    container.conduit = conduit
    container.chat_admitter = None  # type: ignore[assignment]

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert len(conduit.calls) == 1
    assert "run_id" not in result


async def test_the_chat_admitter_is_wired_by_the_container() -> None:
    container = await _container()

    assert container.chat_admitter is not None
    assert container.chat_admitter.retained == 0


def _chat_runs(container: Container):
    """Every Run in the container's store. Private access on purpose: the point
    is to see the Run the caller was *not* handed, because the turn raised."""
    return list(container.run_store._runs.values())  # type: ignore[attr-defined]


# --- review findings ------------------------------------------------------


async def test_the_run_records_the_answer_the_turn_gave() -> None:
    """The ADR promises a refused turn's answer is on the record."""
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.result is not None
    assert run.result["answer"] == "hi"
    assert run.result["finish_reason"] is None


async def test_terminalization_survives_the_request_being_cancelled() -> None:
    """`CancelledError` is not an `Exception`, so the write is shielded."""
    import asyncio

    container = await _container()
    started = asyncio.Event()
    finished = asyncio.Event()

    class _SlowStore:
        """A store whose terminal write is slow enough to cancel mid-flight."""

        def __init__(self, inner):
            self._inner = inner
            self.terminal: list[str] = []

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def transition_run(self, run_id, target, **kwargs):
            if target not in TERMINAL_RUN_STATUSES:
                return await self._inner.transition_run(run_id, target, **kwargs)
            started.set()
            await asyncio.sleep(0.05)
            run = await self._inner.transition_run(run_id, target, **kwargs)
            self.terminal.append(run_id)
            finished.set()
            return run

    store = _SlowStore(container.run_store)
    container.run_store = store  # type: ignore[assignment]
    container.conduit = _Conduit()

    turn = asyncio.create_task(container.route_request([{"role": "user", "content": "hi"}]))
    await started.wait()
    turn.cancel()
    await asyncio.gather(turn, return_exceptions=True)

    # The shield detaches the write from the cancelled request rather than
    # completing it synchronously, so the turn ends first and the write lands
    # just after — which is the point: the Run does not stay RUNNING.
    await asyncio.wait_for(finished.wait(), timeout=5)
    assert len(store.terminal) == 1
    run = await store.get_run(store.terminal[0])
    assert run is not None
    assert run.status in TERMINAL_RUN_STATUSES


async def test_admission_defers_the_agent_when_no_hint_is_given() -> None:
    from maistro.runs.chat_admission import AGENT_SELECTION_KEY, DEFERRED_AGENT_SELECTION

    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.provenance[AGENT_SELECTION_KEY] == DEFERRED_AGENT_SELECTION


async def test_a_caller_supplied_run_is_adopted_rather_than_duplicated() -> None:
    """The seam a caller needs when it must name the Run before the answer.

    `/v1/chat/completions` puts the run_id in a response header, and a
    streaming response's headers are sent before the first byte — so it admits
    the Run itself and hands it over. Without this, the turn would carry two:
    the one the header advertised, and the one this method admitted and closed.
    """
    container = await _container()
    container.conduit = _Conduit()
    mine = await container.chat_admitter.admit([{"role": "user", "content": "hi"}])
    await container.run_store.transition_run(mine.run_id, RunStatus.QUEUED)
    await container.run_store.transition_run(mine.run_id, RunStatus.RUNNING)

    result = await container.route_request([{"role": "user", "content": "hi"}], run=mine)

    assert result["run_id"] == mine.run_id
    runs = [run for run in _chat_runs(container) if run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE]
    assert len(runs) == 1, "a second Run was admitted for a turn that already had one"


async def test_an_adopted_run_is_still_terminalized_here() -> None:
    """Adopting it means owning it. A caller that hands its Run over and then
    also closed it would be racing this method for the same transition; one
    that hands it over and closes nothing would leave it RUNNING, which is what
    recovery reads as a process that died."""
    container = await _container()
    container.conduit = _Conduit()
    mine = await container.chat_admitter.admit([{"role": "user", "content": "hi"}])
    await container.run_store.transition_run(mine.run_id, RunStatus.QUEUED)
    await container.run_store.transition_run(mine.run_id, RunStatus.RUNNING)

    await container.route_request([{"role": "user", "content": "hi"}], run=mine)

    closed = await container.run_store.get_run(mine.run_id)
    assert closed is not None
    assert closed.status is RunStatus.COMPLETED


# --- #338: admission failures are compensated, never stranded ---------------


class _VetoStore:
    """Refuses one chosen lifecycle transition once, then behaves normally."""

    def __init__(self, inner, veto: RunStatus) -> None:
        self._inner = inner
        self._veto: RunStatus | None = veto

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def transition_run(self, run_id, target, **kwargs):
        if target is self._veto:
            self._veto = None
            raise RuntimeError("store hiccup")
        return await self._inner.transition_run(run_id, target, **kwargs)


class _PostWriteVetoStore(_VetoStore):
    """Commits one transition, then loses its response to model an uncertain write."""

    async def transition_run(self, run_id, target, **kwargs):
        if target is self._veto:
            self._veto = None
            await self._inner.transition_run(run_id, target, **kwargs)
            raise RuntimeError("connection dropped after commit")
        return await self._inner.transition_run(run_id, target, **kwargs)


class _MultiVetoStore(_VetoStore):
    """Refuses a prescribed set of transitions once each."""

    def __init__(self, inner, vetoes: tuple[RunStatus, ...]) -> None:
        self._inner = inner
        self._vetoes = set(vetoes)

    async def transition_run(self, run_id, target, **kwargs):
        if target in self._vetoes:
            self._vetoes.remove(target)
            raise RuntimeError("store hiccup")
        return await self._inner.transition_run(run_id, target, **kwargs)


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_a_failure_persisting_running_cancels_the_queued_run() -> None:
    """#338's exact reproduction: QUEUED persists, RUNNING raises.

    The Run used to stay QUEUED forever — admission swallowed the exception and
    returned None, so `_close_chat_run` had nothing to settle and no sweeper
    owns a QUEUED chat Run. Compensation cancels it with a sanitized category.
    """
    container = await _container()
    container.run_store = _VetoStore(container.run_store, RunStatus.RUNNING)  # type: ignore[assignment]
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    # The turn is still answered — admission failing must not refuse the turn.
    assert result["choices"][0]["message"]["content"] == "hi"
    assert "run_id" not in result
    (run,) = _chat_runs(container)
    assert run.status is RunStatus.CANCELLED
    assert run.error == ADMISSION_INCOMPLETE


async def test_a_failure_persisting_queued_cancels_the_created_run() -> None:
    """The hop before: admit() persisted CREATED, QUEUED raises."""
    container = await _container()
    container.run_store = _VetoStore(container.run_store, RunStatus.QUEUED)  # type: ignore[assignment]
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert "run_id" not in result
    (run,) = _chat_runs(container)
    assert run.status is RunStatus.CANCELLED
    assert run.error == ADMISSION_INCOMPLETE


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_recovery_does_not_cancel_an_admission_still_in_flight() -> None:
    """A recovery tick must not win the CREATED/QUEUED admission race."""
    container = await _container()
    entered = asyncio.Event()
    release = asyncio.Event()

    class _SlowQueued:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def transition_run(self, run_id, target, **kwargs):
            if target is RunStatus.QUEUED:
                entered.set()
                await release.wait()
            return await self._inner.transition_run(run_id, target, **kwargs)

    container.run_store = _SlowQueued(container.run_store)  # type: ignore[assignment]
    container.conduit = _Conduit()
    turn = asyncio.create_task(container.route_request([{"role": "user", "content": "hi"}]))
    await entered.wait()

    assert await container.recover_abandoned_attempts() == 0
    (during,) = _chat_runs(container)
    assert during.status is RunStatus.CREATED

    release.set()
    result = await turn
    assert result["run_id"] == during.run_id
    finished = await container.run_store.get_run(during.run_id)
    assert finished is not None
    assert finished.status is RunStatus.COMPLETED


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_expired_chat_admission_receipt_is_recovery_owned() -> None:
    """A row left after its admitter died is cancelled after its receipt expires."""
    container = await _container()
    run = await container.chat_admitter.admit([{"role": "user", "content": "hi"}])
    receipt = run.provenance[CHAT_ADMISSION_RECEIPT_KEY]
    expiry = datetime.fromisoformat(receipt["expires_at"])

    assert await container.recover_abandoned_attempts(now=expiry + timedelta(microseconds=1)) == 0
    recovered = await container.run_store.get_run(run.run_id)
    assert recovered is not None
    assert recovered.status is RunStatus.CANCELLED
    assert recovered.error == ADMISSION_INCOMPLETE


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_recovery_paginates_past_live_chat_receipts() -> None:
    """A live oldest prefix must not starve an expired admission behind it."""
    container = await _container()
    runs = [
        await container.chat_admitter.admit([{"role": "user", "content": "hi"}]) for _ in range(101)
    ]
    for run in runs:
        await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)

    expired_receipt = runs[-1].provenance[CHAT_ADMISSION_RECEIPT_KEY]
    expiry = datetime.fromisoformat(expired_receipt["expires_at"])
    for run in runs[:-1]:
        receipt = run.provenance[CHAT_ADMISSION_RECEIPT_KEY]
        live_expiry = datetime.fromisoformat(receipt["expires_at"])
        assert await container.run_store.renew_chat_admission_receipt(
            run.run_id,
            holder=receipt["holder"],
            ttl=CHAT_ADMISSION_LEASE_TTL,
            at=live_expiry - timedelta(seconds=1),
        )

    await container.recover_abandoned_attempts(now=expiry + timedelta(microseconds=1), limit=100)

    expired = await container.run_store.get_run(runs[-1].run_id)
    assert expired is not None
    assert expired.status is RunStatus.CANCELLED
    assert expired.error == ADMISSION_INCOMPLETE
    live = await container.run_store.get_run(runs[0].run_id)
    assert live is not None
    assert live.status is RunStatus.QUEUED


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_a_renewed_receipt_protects_an_admission_from_another_container() -> None:
    """Recovery trusts the durable lease, not the owner's process-local set."""
    owner = await _container()
    recovery = await _container()
    recovery.run_store = owner.run_store
    run = await owner.chat_admitter.admit([{"role": "user", "content": "hi"}])
    receipt = run.provenance[CHAT_ADMISSION_RECEIPT_KEY]
    expiry = datetime.fromisoformat(receipt["expires_at"])
    holder = receipt["holder"]

    listed = asyncio.Event()
    release = asyncio.Event()

    class _StaleListing:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def list_by_status(self, status, **kwargs):
            rows = await self._inner.list_by_status(status, **kwargs)
            if status is RunStatus.CREATED:
                listed.set()
                await release.wait()
            return rows

    recovery.run_store = _StaleListing(owner.run_store)
    tick = asyncio.create_task(
        recovery.recover_abandoned_attempts(now=expiry + timedelta(microseconds=1))
    )
    await listed.wait()
    assert await owner.run_store.renew_chat_admission_receipt(
        run.run_id,
        holder=holder,
        ttl=CHAT_ADMISSION_LEASE_TTL,
        at=expiry - timedelta(seconds=1),
    )
    release.set()
    assert await tick == 0
    still_live = await owner.run_store.get_run(run.run_id)
    assert still_live is not None
    assert still_live.status is RunStatus.CREATED


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_slow_admission_renews_its_receipt_for_a_remote_recovery_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The container heartbeat keeps a slow durable transition owned."""
    import maistro.container as container_module
    import maistro.runs.chat_admission as chat_admission_module

    ttl = timedelta(milliseconds=30)
    monkeypatch.setattr(chat_admission_module, "CHAT_ADMISSION_LEASE_TTL", ttl)
    monkeypatch.setattr(container_module, "CHAT_ADMISSION_LEASE_TTL", ttl)

    owner = await _container()
    recovery = await _container()
    recovery.run_store = owner.run_store
    entered = asyncio.Event()

    class _SlowQueued:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def transition_run(self, run_id, target, **kwargs):
            if target is RunStatus.QUEUED:
                entered.set()
                await asyncio.sleep(0.08)
            return await self._inner.transition_run(run_id, target, **kwargs)

    owner.run_store = _SlowQueued(owner.run_store)  # type: ignore[assignment]
    recovery.run_store = owner.run_store
    admission = asyncio.create_task(owner._admit_chat_turn([{"role": "user", "content": "hi"}]))
    await entered.wait()
    (started,) = _chat_runs(owner)
    original_expiry = datetime.fromisoformat(
        started.provenance[CHAT_ADMISSION_RECEIPT_KEY]["expires_at"]
    )
    await asyncio.sleep(0.05)
    renewed = await owner.run_store.get_run(started.run_id)
    assert renewed is not None
    renewed_expiry = datetime.fromisoformat(
        renewed.provenance[CHAT_ADMISSION_RECEIPT_KEY]["expires_at"]
    )
    assert renewed_expiry > original_expiry
    assert (
        await recovery.recover_abandoned_attempts(now=original_expiry + timedelta(microseconds=1))
        == 0
    )

    admitted = await admission
    assert admitted is not None
    await owner.run_store.transition_run(admitted.run_id, RunStatus.CANCELLED)


@pytest.mark.parametrize("failed_target", [RunStatus.QUEUED, RunStatus.RUNNING])
@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_a_transition_that_commits_before_raising_is_compensated(
    failed_target: RunStatus,
) -> None:
    """An uncertain write must not leave a pre-dispatch Run unowned.

    A database can commit a transition and lose the response. The admission
    code therefore compensates from durable state, including RUNNING: no
    Attempt exists yet, so this Run has not been dispatched.
    """
    container = await _container()
    container.run_store = _PostWriteVetoStore(  # type: ignore[assignment]
        container.run_store, failed_target
    )
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert result["choices"][0]["message"]["content"] == "hi"
    assert "run_id" not in result
    (run,) = _chat_runs(container)
    assert run.status is RunStatus.CANCELLED
    assert run.error == ADMISSION_INCOMPLETE
    open_runs, _oldest = await container.run_store.non_terminal_run_stats()
    assert open_runs == 0


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_admission_receipt_remains_live_until_attempt_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery must not cancel RUNNING while the first Attempt is being created."""
    import maistro.container as container_module
    import maistro.runs.chat_admission as chat_admission_module

    ttl = timedelta(milliseconds=30)
    monkeypatch.setattr(chat_admission_module, "CHAT_ADMISSION_LEASE_TTL", ttl)
    monkeypatch.setattr(container_module, "CHAT_ADMISSION_LEASE_TTL", ttl)

    container = await _container()
    entered = asyncio.Event()
    release = asyncio.Event()

    class _SlowNodeRun:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def create_node_run(self, run_id, *, node_id):
            entered.set()
            await release.wait()
            return await self._inner.create_node_run(run_id, node_id=node_id)

    container.run_store = _SlowNodeRun(container.run_store)  # type: ignore[assignment]
    container.conduit = _Conduit()
    turn = asyncio.create_task(container.route_request([{"role": "user", "content": "hi"}]))
    await entered.wait()

    (run,) = [
        candidate
        for candidate in container.run_store._inner._runs.values()  # type: ignore[attr-defined]
        if candidate.provenance[ADMISSION_SOURCE] == CHAT_SOURCE
    ]
    expiry = datetime.fromisoformat(run.provenance[CHAT_ADMISSION_RECEIPT_KEY]["expires_at"])
    await asyncio.sleep(0.05)

    # The admission heartbeat has renewed the receipt while no Attempt exists.
    assert await container.recover_abandoned_attempts(now=expiry + timedelta(microseconds=1)) == 0
    still_running = await container.run_store.get_run(run.run_id)
    assert still_running is not None
    assert still_running.status is RunStatus.RUNNING

    release.set()
    result = await turn
    assert result["run_id"] == run.run_id
    completed = await container.run_store.get_run(run.run_id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    node_runs = await container.run_store.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    assert len(await container.run_store.list_attempts(node_runs[0].node_run_id)) == 1


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_recovery_tick_retries_a_failed_compensation() -> None:
    """A store outage during compensation leaves a row the recovery tick owns."""
    container = await _container()
    container.run_store = _MultiVetoStore(  # type: ignore[assignment]
        container.run_store, (RunStatus.RUNNING, RunStatus.CANCELLED)
    )
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert result["choices"][0]["message"]["content"] == "hi"
    (run,) = _chat_runs(container)
    assert run.status is RunStatus.QUEUED

    assert await container.recover_abandoned_attempts() == 0
    recovered = await container.run_store.get_run(run.run_id)
    assert recovered is not None
    assert recovered.status is RunStatus.CANCELLED
    assert recovered.error == ADMISSION_INCOMPLETE
    assert await container.recover_abandoned_attempts() == 0


@pytest.mark.ac("ADR-082826-08f0/AC-6")
async def test_repeated_compensation_is_idempotent_and_respects_settled_runs() -> None:
    """Compensating twice, or after the Run settled, changes nothing."""
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])
    settled = await container.run_store.get_run(result["run_id"])
    assert settled is not None
    assert settled.status is RunStatus.COMPLETED

    await container._cancel_incomplete_admission(settled)
    await container._cancel_incomplete_admission(settled)

    current = await container.run_store.get_run(settled.run_id)
    assert current is not None
    assert current.status is RunStatus.COMPLETED
    assert current.error is None


async def test_cancellation_during_admission_compensates_and_propagates() -> None:
    """A client disconnecting mid-admission must not strand the QUEUED Run.

    `CancelledError` is not an `Exception`, so without its own handler the old
    code path never even logged — the Run stayed QUEUED and the cancellation
    escaped before the turn's own shielded terminalization could see a Run.
    """
    import asyncio

    container = await _container()
    started = asyncio.Event()

    class _SlowRunning:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def transition_run(self, run_id, target, **kwargs):
            if target is RunStatus.RUNNING:
                started.set()
                await asyncio.sleep(0.05)
            return await self._inner.transition_run(run_id, target, **kwargs)

    container.run_store = _SlowRunning(container.run_store)  # type: ignore[assignment]
    container.conduit = _Conduit()

    turn = asyncio.create_task(container.route_request([{"role": "user", "content": "hi"}]))
    await started.wait()
    turn.cancel()
    results = await asyncio.gather(turn, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)

    async def _compensated() -> bool:
        (run,) = _chat_runs(container)
        return run.status is RunStatus.CANCELLED

    # The shield detaches the compensating write from the cancelled request,
    # so it lands just after the turn ends rather than being aborted with it.
    for _ in range(100):
        if await _compensated():
            break
        await asyncio.sleep(0.01)
    (run,) = _chat_runs(container)
    assert run.status is RunStatus.CANCELLED
    assert run.error == ADMISSION_INCOMPLETE


async def test_compensation_declines_a_run_already_past_queued() -> None:
    """A Run at RUNNING returned from admission, so it is `_close_chat_run`'s
    to settle — compensation must observe and step away, not cancel live work."""
    from maistro.graph import Graph, Node

    container = await _container()
    project_id = (await container.project_scope_store.create_root("compensation")).project_id
    graph = Graph(
        workspace_id="compensation",
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run = await container.run_store.create_run(graph)
    await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
    running = await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)

    await container._cancel_incomplete_admission(running)

    current = await container.run_store.get_run(run.run_id)
    assert current is not None
    assert current.status is RunStatus.RUNNING
    assert current.error is None


async def test_compensation_failure_is_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Compensation must not replace the turn's answer: a store that breaks
    during the compensating write itself is logged, and nothing propagates."""
    container = await _container()
    container.conduit = _Conduit()
    result = await container.route_request([{"role": "user", "content": "hi"}])
    run = await container.run_store.get_run(result["run_id"])
    assert run is not None

    class _BrokenGet:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def get_run(self, run_id):
            raise RuntimeError("store down")

    container.run_store = _BrokenGet(container.run_store)  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING):
        await container._cancel_incomplete_admission(run)

    assert "could not be compensated" in caplog.text
