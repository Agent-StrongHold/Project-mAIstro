"""Chat Attempts carry the canonical lease and repair from durable facts (#1170).

The chat half of ADR-082526-b36a. Tasks have had it since #232: an Attempt
whose holder stops renewing is reclaimed, the reclaim is fenced, and a
restarted worker retries through a *new* chronological Attempt. A chat turn
drove the same spine but created its Attempts without a TTL, so a process that
died mid-turn left a RUNNING Attempt nothing could ever reclaim — #1170's bug.

Everything here goes through the same seams the task contract does: the
constructor's `lease_ttl` reaches `AttemptExecutionService` unchanged, the
reclaim is `Container.recover_abandoned_attempts` (the canonical tick, not a
chat-private sweep), and the fence is the store's `transition_attempt` fence.
Crash-injection style: death is simulated as renewals that stop, the exact
shape of a SIGKILLed or partitioned worker, never as an orderly in-process
stop — an orderly stop terminalizes its own Attempt and leaves nothing to
reclaim.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.runs.chat_execution import (
    CHAT_EXECUTOR_ID,
    DEFAULT_CHAT_LEASE_TTL,
    ChatAttemptExecutor,
)
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import StaleExecutionFence
from maistro.types.config import AgentConfig

MESSAGES = [{"role": "user", "content": "hi"}]


class _Conduit:
    """The Conduit stand-in used across the chat suites."""

    def __init__(
        self,
        *,
        content: str = "the answer",
        raises: Exception | None = None,
    ) -> None:
        self.calls = 0
        self._content = content
        self._raises = raises

    async def route_request(self, _messages: Any, **_kw: Any) -> dict[str, Any]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": self._content},
                    "finish_reason": "stop",
                }
            ],
            "agent": "general",
        }


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _open_run(container: Container) -> Any:
    """A chat Run admitted to RUNNING, as admission leaves it before dispatch."""
    run = await container.chat_admitter.admit(MESSAGES)
    await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
    return await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)


async def _spine(container: Container, run_id: str) -> tuple[Any, list[Any]]:
    """The Run's single NodeRun and its Attempts, oldest first."""
    node_runs = await container.run_store.list_node_runs(run_id)
    assert len(node_runs) == 1, f"expected one NodeRun, got {len(node_runs)}"
    return node_runs[0], await container.run_store.list_attempts(node_runs[0].node_run_id)


def _dispatching(conduit: _Conduit) -> Callable[[], Any]:
    async def _dispatch() -> dict[str, Any]:
        return await conduit.route_request(MESSAGES)

    return _dispatch


class _VetoStore:
    """Refuses one chosen lifecycle transition the first time, then behaves.

    A store outage, not a policy refusal: the write raises and every later
    write succeeds, which is the transient failure `_close_chat_run` exists to
    survive without pretending it succeeded.
    """

    def __init__(self, inner: Any, veto: RunStatus) -> None:
        self._inner = inner
        self._veto: RunStatus | None = veto

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def transition_run(self, run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        if target is self._veto:
            self._veto = None
            raise RuntimeError("store hiccup")
        return await self._inner.transition_run(run_id, target, **kwargs)


class _MultiVetoStore(_VetoStore):
    """Refuses each of several transitions once. Order-independent, one shot each."""

    def __init__(self, inner: Any, vetoes: tuple[RunStatus, ...]) -> None:
        self._inner = inner
        self._pending = set(vetoes)

    async def transition_run(self, run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        if target in self._pending:
            self._pending.discard(target)
            raise RuntimeError("store hiccup")
        return await self._inner.transition_run(run_id, target, **kwargs)


# --- the lease contract -----------------------------------------------------


class TestChatAttemptsAreLeased:
    async def test_the_container_wires_chat_with_the_canonical_lease(self) -> None:
        """#1170's first acceptance, through the production wiring.

        `route_request` builds the executor bare, so the constructor default is
        what production runs on. The Attempt this turn leaves must carry a live
        lease naming the chat executor — the record a sweep reads to decide
        ownership.
        """
        container = await _container()
        container.conduit = _Conduit()

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        lease = attempts[0].execution_lease
        assert lease is not None
        assert lease.holder == CHAT_EXECUTOR_ID
        assert lease.expires_at is not None

    async def test_the_default_ttl_is_the_canonical_one(self) -> None:
        """One number across entry points. The schedule consumer reclaims on 30s;
        a chat crash being an outage on one surface and a blip on another would
        make recovery speed a property of which seam answered, not of the crash.
        """
        from maistro.runs.consumption import DEFAULT_SCHEDULE_LEASE_TTL

        assert DEFAULT_CHAT_LEASE_TTL == DEFAULT_SCHEDULE_LEASE_TTL
        assert timedelta(0) < DEFAULT_CHAT_LEASE_TTL

    async def test_the_lease_starts_at_the_configured_ttl(self) -> None:
        container = await _container()
        container.conduit = _Conduit()

        result = await container.route_request(MESSAGES)

        _, attempts = await _spine(container, result["run_id"])
        lease = attempts[0].execution_lease
        assert lease is not None
        assert lease.expires_at is not None
        assert lease.expires_at - lease.issued_at >= DEFAULT_CHAT_LEASE_TTL

    async def test_lease_ttl_none_opts_chat_out(self) -> None:
        """The ADR's original default, still available: no TTL, no expiry, and
        the sweep — which reads expiries — has nothing to act on."""
        container = await _container()
        run = await _open_run(container)
        chat_executor = ChatAttemptExecutor(container.run_store, lease_ttl=None)

        await chat_executor.execute(
            run_id=run.run_id,
            messages=MESSAGES,
            dispatch=_dispatching(_Conduit()),
        )

        _, attempts = await _spine(container, run.run_id)
        assert attempts[0].execution_lease is not None
        assert attempts[0].execution_lease.expires_at is None
        assert await container.run_store.reclaim_expired_attempts() == []

    def test_a_non_positive_lease_ttl_is_refused_before_anything_exists(self) -> None:
        """Refused at construction by the one seam that owns the heartbeat, so a
        misconfiguration orphans no NodeRun."""
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        with pytest.raises(ValueError, match="lease_ttl must be positive"):
            ChatAttemptExecutor(store, lease_ttl=timedelta(0))

    async def test_a_slow_turn_survives_its_ttl(self) -> None:
        """ADR-082526-b36a AC-8 on the chat seam. A TTL that reaped a healthy
        slow turn would trade a stuck Attempt for a broken answer; the
        heartbeat, renewing from this process, is what makes the TTL safe."""
        container = await _container()
        run = await _open_run(container)
        ttl = timedelta(seconds=0.09)

        async def _slower_than_its_ttl() -> dict[str, Any]:
            await asyncio.sleep(0.2)  # > 2x the TTL: survival proves renewal
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": "late but done"}},
                    {"finish_reason": "stop"},
                ]
            }

        chat_executor = ChatAttemptExecutor(container.run_store, lease_ttl=ttl)
        await chat_executor.execute(
            run_id=run.run_id,
            messages=MESSAGES,
            dispatch=_slower_than_its_ttl,
        )

        _, attempts = await _spine(container, run.run_id)
        assert attempts[0].status is AttemptStatus.COMPLETED
        lease = attempts[0].execution_lease
        assert lease is not None and lease.expires_at is not None
        assert lease.expires_at > attempts[0].created_at, (
            "the heartbeat must have pushed the expiry past where it started"
        )


# --- worker death, reclaim, and the fence -----------------------------------


class TestACrashedChatWorkerIsReclaimed:
    @staticmethod
    async def _crashed_mid_turn(
        container: Container,
    ) -> tuple[asyncio.Task[None], Any, Any, str]:
        """A turn whose worker stops proving it is alive, mid-dispatch.

        Returns the (still pending) worker task, its NodeRun, its durably
        RUNNING Attempt, and the fencing token the dead worker still holds.
        """
        run = await _open_run(container)
        chat_executor = ChatAttemptExecutor(container.run_store, lease_ttl=timedelta(seconds=0.06))
        arrived = asyncio.Event()

        async def _dispatch() -> dict[str, Any]:
            arrived.set()
            await asyncio.sleep(3600)
            raise AssertionError("the crashed dispatch never returns")  # pragma: no cover

        async def _worker() -> None:
            with contextlib.suppress(BaseException):
                await chat_executor.execute(
                    run_id=run.run_id,
                    messages=MESSAGES,
                    dispatch=_dispatch,
                )

        worker = asyncio.create_task(_worker())
        await arrived.wait()

        node_run, attempts = await _spine(container, run.run_id)
        attempt = attempts[0]
        assert attempt.status is AttemptStatus.RUNNING
        lease = attempt.execution_lease
        assert lease is not None and lease.expires_at is not None, (
            "the executor must opt its Attempt into a TTL, or nothing is reclaimable"
        )
        token = lease.fencing_token

        # Death: renewals stop while the dispatch never returns. The process
        # that could terminalize this Attempt is gone; its heartbeat is too.
        async def _dead(*_args: Any, **_kwargs: Any) -> Any:
            raise ConnectionError("worker is gone")

        container.run_store.renew_lease = _dead  # type: ignore[method-assign]
        await asyncio.sleep(0.15)  # past the TTL, with no successful renewal
        return worker, node_run, attempt, token

    async def test_death_before_lease_expiry_makes_the_attempt_reclaimable(self) -> None:
        """#1170's headline window. After the crash the durable record still
        claims the turn is executing — that is the bug working as designed
        until the lease lapses. The canonical tick, not any chat-specific
        code, then settles it: Attempt CANCELLED naming the holder, NodeRun
        parked for retry, Run parked with it."""
        container = await _container()
        worker, node_run, attempt, _token = await self._crashed_mid_turn(container)

        # The crash window: RUNNING claims work nothing is running.
        still = await container.run_store.get_attempt(attempt.attempt_id)
        assert still is not None and still.status is AttemptStatus.RUNNING

        assert await container.recover_abandoned_attempts() == 1

        settled = await container.run_store.get_attempt(attempt.attempt_id)
        assert settled is not None
        assert settled.status is AttemptStatus.CANCELLED, (
            "reclaim is a cancellation, not a failure: the work did not fail, "
            "its worker stopped proving it was alive (ADR-082526-b36a)"
        )
        assert CHAT_EXECUTOR_ID in (settled.error or ""), (
            "the record must name the holder that went quiet"
        )
        parked_node = await container.run_store.get_node_run(node_run.node_run_id)
        assert parked_node is not None and parked_node.status is RunStatus.WAITING
        run = await container.run_store.get_run(node_run.run_id)
        assert run is not None and run.status is RunStatus.WAITING

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def test_repeated_recovery_is_idempotent(self) -> None:
        """Two ticks — or two replicas ticking — is normal operation. The second
        sweep finds nothing expired and rewrites nothing."""
        container = await _container()
        worker, _node_run, attempt, _token = await self._crashed_mid_turn(container)

        assert await container.recover_abandoned_attempts() == 1
        first = await container.run_store.get_attempt(attempt.attempt_id)

        assert await container.recover_abandoned_attempts() == 0
        second = await container.run_store.get_attempt(attempt.attempt_id)
        assert first is not None and second is not None
        assert second.status is first.status
        assert second.error == first.error

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def test_a_late_stale_completion_cannot_rewrite_a_reclaimed_attempt(self) -> None:
        """The partition heals and the dead worker's dispatch finally returns.
        Its write carries its own attempt and token — but the attempt is
        terminal now, and the normal lifecycle guard refuses to resurrect it."""
        container = await _container()
        worker, _node_run, attempt, token = await self._crashed_mid_turn(container)
        await container.recover_abandoned_attempts()

        with pytest.raises(InvalidLifecycleTransition):
            await container.run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.COMPLETED,
                result={"answer": "late"},
                fencing_token=token,
            )

        settled = await container.run_store.get_attempt(attempt.attempt_id)
        assert settled is not None and settled.status is AttemptStatus.CANCELLED
        assert settled.result is None, "the late write must not have landed"

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def test_the_dead_workers_token_cannot_touch_the_retry(self) -> None:
        """Reclaim, then a restarted process retries the turn. The retry is a
        second chronological Attempt under the same NodeRun — new epoch, new
        token — and the dead worker's token is exactly the wrong one for it.
        Successful repair after restart, and the fence that makes it safe."""
        container = await _container()
        worker, node_run, _attempt, token = await self._crashed_mid_turn(container)
        await container.recover_abandoned_attempts()

        chat_executor = ChatAttemptExecutor(container.run_store)
        await chat_executor.execute(
            run_id=node_run.run_id, messages=MESSAGES, dispatch=_dispatching(_Conduit())
        )

        _node, attempts = await _spine(container, node_run.run_id)
        assert [a.ordinal for a in attempts] == [1, 2], "chronological canonical evidence"
        assert attempts[0].status is AttemptStatus.CANCELLED
        assert attempts[1].status is AttemptStatus.COMPLETED
        assert attempts[1].execution_lease is not None
        assert attempts[1].execution_lease.fencing_token != token

        with pytest.raises(StaleExecutionFence):
            await container.run_store.transition_attempt(
                attempts[1].attempt_id,
                AttemptStatus.COMPLETED,
                result={"answer": "stale"},
                fencing_token=token,
            )

        run = await container.run_store.get_run(node_run.run_id)
        assert run is not None and run.status is RunStatus.COMPLETED

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


# --- terminal-write failure is evidence, not a swallowed no-op ---------------


class TestATerminalWriteFailureIsNotSwallowed:
    async def test_close_chat_run_reports_a_failed_terminal_write(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The closure caller can now tell cleanup happened from cleanup owed:
        False on a failed write, True once the write lands, True again — without
        a second write — once the Run is already terminal. Repeated recovery is
        idempotent by the terminal guard, not by pretending."""
        container = await _container()
        container.run_store = _VetoStore(container.run_store, RunStatus.FAILED)  # type: ignore[assignment]
        run = await _open_run(container)

        with caplog.at_level(logging.WARNING, logger="maistro.container"):
            closed = await container._close_chat_run(run, error="provider_error")

        assert closed is False
        assert "could not be terminalized" in caplog.text
        still_open = await container.run_store.get_run(run.run_id)
        assert still_open is not None and still_open.status is RunStatus.RUNNING

        # The store recovers: the same closure now lands, and repeating it is a
        # no-op read rather than a second write.
        assert await container._close_chat_run(run, error="provider_error") is True
        assert await container._close_chat_run(run, error="provider_error") is True
        closed_run = await container.run_store.get_run(run.run_id)
        assert closed_run is not None and closed_run.status is RunStatus.FAILED

    async def test_a_closure_failure_does_not_replace_the_turns_own_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed turn whose cleanup also fails must still arrive as the
        failed turn. The endpoint maps the exception *type* to a status code;
        a closure failure that surfaced instead would lie about what happened.
        The durable evidence is the retriable record: FAILED Attempt, parked
        NodeRun, Run left open — and a restarted executor retries it through a
        new Attempt to a completed Run."""
        container = await _container()
        container.run_store = _VetoStore(container.run_store, RunStatus.FAILED)  # type: ignore[assignment]
        container.conduit = _Conduit(raises=RuntimeError("upstream exploded"))

        with (
            caplog.at_level(logging.WARNING, logger="maistro.container"),
            pytest.raises(RuntimeError, match="upstream exploded"),
        ):
            await container.route_request(MESSAGES)

        assert "could not be terminalized" in caplog.text
        runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
        run_id = runs[0].run_id
        node_run, attempts = await _spine(container, run_id)
        assert attempts[0].status is AttemptStatus.FAILED
        assert node_run.status is RunStatus.WAITING

        run = await container.run_store.get_run(run_id)
        assert run is not None and run.status is RunStatus.RUNNING, (
            "the failed closure left the Run exactly where recovery reads"
        )

        # Restart: a fresh executor retries the same NodeRun chronologically.
        chat_executor = ChatAttemptExecutor(container.run_store)
        await chat_executor.execute(
            run_id=runs[0].run_id,
            messages=MESSAGES,
            dispatch=_dispatching(_Conduit()),
        )

        _node, attempts = await _spine(container, run_id)
        assert [a.ordinal for a in attempts] == [1, 2]
        assert attempts[1].status is AttemptStatus.COMPLETED
        repaired = await container.run_store.get_run(run_id)
        assert repaired is not None and repaired.status is RunStatus.COMPLETED

    async def test_a_completed_attempt_with_a_failed_run_settle_is_reconcilable(self) -> None:
        """#1170's repair acceptance, end to end.

        The turn answers; the Attempt completes and is accepted; then the store
        fails both Run writes that would have said so. The caller gets the
        store error — never a success that did not happen — and what remains on
        disk is the canonical evidence itself: a COMPLETED, accepted Attempt
        under a RUNNING Run. The canonical reconciliation authority (the same
        `AttemptLifecycleReconciler` the recovery sweep drives) re-derives the
        Run from those facts alone, from a freshly constructed instance —
        a restarted process reading nothing but durable state. No chat-private
        sweep exists to do it.
        """
        container = await _container()
        container.run_store = _MultiVetoStore(  # type: ignore[assignment]
            container.run_store, (RunStatus.COMPLETED, RunStatus.FAILED)
        )
        container.conduit = _Conduit(content="the answer")

        with pytest.raises(RuntimeError, match="store hiccup"):
            await container.route_request(MESSAGES)

        runs = list(container.run_store._runs.values())  # type: ignore[attr-defined]
        run_id = runs[0].run_id
        node_run, attempts = await _spine(container, run_id)

        # Physical work is durable and authoritative: the Attempt completed with
        # the answer as evidence, and the NodeRun accepted exactly that result.
        attempt = attempts[0]
        assert attempt.status is AttemptStatus.COMPLETED
        assert attempt.result is not None and attempt.result["answer"] == "the answer"
        assert node_run.status is RunStatus.COMPLETED
        assert node_run.accepted_outcome is not None

        run = await container.run_store.get_run(run_id)
        assert run is not None and run.status is RunStatus.RUNNING, (
            "both Run terminal writes failed; the Run must not claim an outcome"
        )

        # Repair after restart: the canonical authority, over durable facts only.
        reconciler = AttemptLifecycleReconciler(
            container.run_store,
            source="maistro.tests.chat_attempt_recovery",
        )
        await reconciler.reconcile(attempt)

        repaired = await container.run_store.get_run(run_id)
        assert repaired is not None and repaired.status is RunStatus.COMPLETED
        assert repaired.result == node_run.result

        # Idempotent: re-deriving from the same evidence changes nothing.
        await reconciler.reconcile(attempt)
        again = await container.run_store.get_run(run_id)
        assert again is not None and again.status is RunStatus.COMPLETED
