"""I31 — Invocation effect/idempotency semantics, against the real lifecycle service (#882).

Drives `InvocationExecutionService` over `InMemoryInvocationStore` — the
canonical Capability -> Provider -> Binding -> Invocation external-effect
boundary (ADR-081226-6b46) — with generated histories instead of the
hand-written retry scenarios the conformance suites enumerate. Correctness at
this seam depends on *prior outcomes* (COMPLETED replay, FAILED-with-proof
retry, UNKNOWN blocking), so the failure class worth generating is exactly the
one nobody thinks to write down: a retry after cancellation, a reconciliation
applied with the wrong disposition, a duplicate logical effect racing under a
new NodeRun.

**Candidate invariants, all from the documented contract** (the invocation
module docstring, ADR-081226-6b46, and issue #882's hypothesis — never from
asking the implementation what should happen next):

1. *A COMPLETED logical effect never dispatches twice.* Once a COMPLETED row
   exists for an admission identity, the provider-executor counter for that
   identity is frozen; every later `invoke` replays the canonical row.
2. *CREATED/RUNNING/UNKNOWN block automatic repetition.* `invoke` must raise
   `UnsafeEffectRetry` and never reach the provider while the latest outcome
   for the identity cannot be proven absent.
3. *Only proven-not-applied FAILED is retryable.* `EffectNotApplied` (and the
   pre-dispatch failure) terminalize FAILED; the next `invoke` is admitted.
   Generic exceptions and cancellation terminalize UNKNOWN — never retried
   until reconciliation settles them with evidence.
4. *Logical effect identity is stable across physical Attempts.* A
   `logical_effect=True` effect keys its admission on the Run, so a retry
   under a brand-new Attempt *and* NodeRun replays; an ordinary effect stays
   scoped to its NodeRun visit.
5. *Terminal records always carry terminal timestamps.* Every row observed in
   the store satisfies `status is terminal <=> finished_at is not None`.
6. *Concurrent same-effect attempts cannot double-dispatch.* Two workers
   racing one fresh logical effect under different NodeRuns produce exactly
   one provider execution; the loser is blocked or replays the winner's row.

**Oracle independence.** The machine keeps its own model of each admission
identity (fresh / blocked / completed / failed-retryable) from the actions it
took and the documented transition rules, and compares that model against the
store after every step. The provider executor is the only place a dispatch is
ever counted, so a duplicate dispatch can never hide behind bookkeeping.

**Demonstrated mutants** (each fails this file; the unmutated suite passes —
see `docs/research/882-invocation-effect-idempotency-stateful-testing.md`):
M1 dropping the foreign non-terminal admission guard, M2 making UNKNOWN
retryable, M3 dropping the terminal timestamp, M4 narrowing the #1194 logical
admission widening, M5 widening ordinary effects to Run scope.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    ReconciliationDisposition,
    UnsafeEffectRetry,
)

RUN_ID = "run-formal-882"
BINDING_ID = "binding-882"
WORKSPACE = "ws-882"
PROJECT = "project-882"
NODE_A = "node-attempt-a"
NODE_B = "node-attempt-b"

#: Effect keys are fixed at machine construction; the logical/physical scope
#: alternates by index so both admission scopes are explored deterministically.
EFFECT_KEYS = ("effect-write", "effect-notify", "effect-charge", "effect-finalize")
RACE_KEYS = ("effect-race-0", "effect-race-1", "effect-race-2")

#: Provider outcomes one dispatch can produce (issue #882's experiment list).
OUTCOMES = ("ok", "not_applied", "generic", "cancelled")
#: Statuses that block automatic repetition (issue invariant 2). UNKNOWN is
#: the subtlety this seam exists for: it blocks retries even though it is
#: lifecycle-terminal for timestamp purposes.
_BLOCKING = {
    InvocationStatus.CREATED,
    InvocationStatus.RUNNING,
    InvocationStatus.UNKNOWN,
}
#: Statuses whose records must carry `finished_at` (issue invariant 5).
_TERMINAL = {
    InvocationStatus.COMPLETED,
    InvocationStatus.FAILED,
    InvocationStatus.UNKNOWN,
}


class _Provider:
    name = "formal-invocation-provider"
    slot = "external_write"
    trust_tier = "trusted"


async def _resolve(_binding: Binding) -> _Provider:
    # A real resolution is I/O and yields to the loop; without this yield the
    # race rules collapse to one atomic worker admission and can never open
    # the interleaving window the admission guards exist to close.
    await asyncio.sleep(0)
    return _Provider()


@dataclass
class _EffectModel:
    """The machine's independent model of one admission identity."""

    status: str = "fresh"  # fresh | blocked | completed | failed
    invocation_id: str | None = None
    frozen_dispatches: int | None = None
    observed_revisions: dict[str, int] = field(default_factory=dict)


#: One event loop for the whole module: `InMemoryInvocationStore` guards itself
#: with an `asyncio.Lock`, and a lock rebound per `asyncio.run` loop would
#: refuse its second rule. Per-example isolation comes from fresh stores and
#: services, not from fresh loops.
_SHARED_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro: Any) -> Any:
    global _SHARED_LOOP
    if _SHARED_LOOP is None:
        _SHARED_LOOP = asyncio.new_event_loop()
    return _SHARED_LOOP.run_until_complete(coro)


class InvocationEffectMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.binding = Binding(
            binding_id=BINDING_ID,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            capability="external_write",
        )
        self.store = InMemoryInvocationStore()
        # Two workers sharing one ledger: the primary drives the single-worker
        # rules, the peer only ever races, so cross-service admission goes
        # through the store's atomic claim rather than one process-local lock.
        self.service = InvocationExecutionService(store=self.store)
        self.peer = InvocationExecutionService(store=self.store)
        self.effects: dict[tuple[str, str | None], _EffectModel] = {
            (key, None if index % 2 == 0 else NODE_A): _EffectModel() for index, key in enumerate(EFFECT_KEYS)
        }
        self.provider_calls: Counter[tuple[str, str | None]] = Counter()
        self.next_attempt = 0
        self.next_race = 0

    # ---------------------------------------------------------------- helpers

    def _attempt(self) -> str:
        """Every retry arrives under a fresh physical Attempt id (#882)."""
        self.next_attempt += 1
        return f"attempt-{self.next_attempt}"

    def _identity_for(self, key: str) -> tuple[str, str | None]:
        """The live model identity for a key, if the machine has touched it."""
        candidates = [identity for identity in self.effects if identity[0] == key]
        return candidates[0] if candidates else (key, None)

    async def _history(self, identity: tuple[str, str | None]) -> list[Invocation]:
        return await self.store.list_effect(
            run_id=RUN_ID,
            node_run_id=identity[1],
            binding_id=BINDING_ID,
            effect_key=identity[0],
        )

    async def _all_histories(self) -> dict[tuple[str, str | None], list[Invocation]]:
        return {identity: await self._history(identity) for identity in self.effects}

    async def _execute(self, _provider: _Provider, request: dict[str, Any]) -> str:
        """The only place a provider dispatch is ever counted.

        The yield models real provider I/O: it holds the dispatch open across
        a loop tick so a racing worker's admission can observe the effect
        mid-flight, which is exactly the state the guards must refuse.
        """
        self.provider_calls[request["identity"]] += 1
        await asyncio.sleep(0)
        outcome = request["outcome"]
        if outcome == "not_applied":
            raise EffectNotApplied("proof: provider committed no external effect")
        if outcome == "generic":
            raise RuntimeError("provider exploded mid-call")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return f"committed:{request['identity'][0]}"

    def _invoke(
        self,
        service: InvocationExecutionService,
        identity: tuple[str, str | None],
        outcome: str,
        node_run_id: str,
    ) -> Any:
        request = {"identity": identity, "outcome": outcome}
        return _run(
            service.invoke(
                binding=self.binding,
                run_id=RUN_ID,
                node_run_id=node_run_id,
                attempt_id=self._attempt(),
                effect_key=identity[0],
                request=request,
                logical_effect=identity[1] is None,
                resolver=_resolve,
                executor=self._execute,
            )
        )

    # ------------------------------------------------------------------ rules

    @rule(
        key=st.sampled_from(EFFECT_KEYS),
        outcome=st.sampled_from(OUTCOMES),
        switch_node=st.booleans(),
    )
    def invoke_effect(self, key: str, outcome: str, switch_node: bool) -> None:
        """One `invoke` with a generated provider outcome, under a fresh Attempt.

        Oracle: blocked identities must refuse without dispatching; completed
        identities must replay the canonical row without dispatching; fresh
        and failed identities must dispatch exactly once and terminalize the
        row into the outcome's documented class.
        """
        logical = (key, None) in self.effects
        base_node = NODE_A
        node = (NODE_B if base_node == NODE_A else NODE_A) if switch_node else base_node
        identity = (key, None) if logical else (key, node)
        model = self.effects.setdefault(identity, _EffectModel())
        was_blocked = model.status == "blocked"
        frozen = model.frozen_dispatches
        before = self.provider_calls[identity]

        try:
            invocation = self._invoke(self.service, identity, outcome, node)
        except UnsafeEffectRetry:
            assert was_blocked, f"safe retry of {model.status} identity {identity} was refused"
            assert self.provider_calls[identity] == before, "blocked retry reached the provider"
            return
        except EffectNotApplied:
            assert not was_blocked and frozen is None, "dispatched a frozen/blocked effect"
            assert self.provider_calls[identity] == before + 1
            row = _run(self._history(identity))[-1]
            assert row.status is InvocationStatus.FAILED
            assert row.finished_at is not None
            model.status = "failed"
            model.invocation_id = row.invocation_id
            return
        except (RuntimeError, asyncio.CancelledError):
            # Generic exceptions and cancellation must land UNKNOWN, blocking
            # repetition until reconciliation produces evidence.
            assert not was_blocked and frozen is None, "dispatched a frozen/blocked effect"
            assert self.provider_calls[identity] == before + 1
            row = _run(self._history(identity))[-1]
            assert row.status is InvocationStatus.UNKNOWN
            assert row.finished_at is not None
            model.status = "blocked"
            model.invocation_id = row.invocation_id
            return

        # A returned Invocation is always the canonical COMPLETED row.
        assert not was_blocked, "blocked effect silently re-dispatched to completion"
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.finished_at is not None
        if frozen is not None:
            assert self.provider_calls[identity] == frozen, "completed effect dispatched again"
            assert invocation.invocation_id == model.invocation_id, "replay minted a new row"
        else:
            assert self.provider_calls[identity] == before + 1
            model.status = "completed"
            model.invocation_id = invocation.invocation_id
            model.frozen_dispatches = self.provider_calls[identity]

    @rule(hint=st.sampled_from(RACE_KEYS))
    def race_duplicate_logical_effect(self, hint: str) -> None:
        """Two workers race one fresh logical effect under different NodeRuns.

        Oracle (#1194, invariant 6): exactly one provider execution; every
        returned row is the same canonical COMPLETED Invocation; the loser
        raises UnsafeEffectRetry or replays.
        """
        key = hint
        while (key, None) in self.effects:
            # The oracle below demands a fresh effect; a used key would replay
            # on both workers and dispatch nothing.
            key = f"effect-race-{self.next_race}"
            self.next_race += 1
        identity = (key, None)
        model = _EffectModel()
        self.effects[identity] = model
        before = self.provider_calls[identity]

        async def race() -> list[Any]:
            results = await asyncio.gather(
                self._invoke_async(self.service, key, NODE_A),
                self._invoke_async(self.peer, key, NODE_B),
                return_exceptions=True,
            )
            return list(results)

        results = _run(race())
        assert self.provider_calls[identity] == before + 1, (
            f"expected exactly one dispatch, saw {self.provider_calls[identity] - before}"
        )
        rows = [r for r in results if isinstance(r, Invocation)]
        assert rows, f"no worker completed the effect: {results!r}"
        canonical = rows[0].invocation_id
        for row in rows:
            assert row.invocation_id == canonical, "two canonical rows for one logical effect"
            assert row.status is InvocationStatus.COMPLETED
            assert row.finished_at is not None
        for result in results:
            assert isinstance(result, (Invocation, UnsafeEffectRetry)), f"race produced {result!r}"
        model.status = "completed"
        model.invocation_id = canonical
        model.frozen_dispatches = self.provider_calls[identity]

    async def _invoke_async(self, service: InvocationExecutionService, key: str, node_run_id: str) -> Any:
        identity = (key, None)
        request = {"identity": identity, "outcome": "ok"}
        return await service.invoke(
            binding=self.binding,
            run_id=RUN_ID,
            node_run_id=node_run_id,
            attempt_id=self._attempt(),
            effect_key=key,
            request=request,
            logical_effect=True,
            resolver=_resolve,
            executor=self._execute,
        )

    @rule(
        key=st.sampled_from(EFFECT_KEYS + RACE_KEYS),
        disposition=st.sampled_from(ReconciliationDisposition),
    )
    def reconcile_effect(self, key: str, disposition: ReconciliationDisposition) -> None:
        """Apply operator evidence through the authority and re-check blocking.

        Oracle: APPLIED completes (frozen forever), NOT_APPLIED fails the row
        into the one retryable class, INDETERMINATE leaves the effect blocked;
        a terminal row is returned untouched; an unadmitted identity is
        refused instead of invented.
        """
        identity = self._identity_for(key)
        model = self.effects.get(identity)
        before = self.provider_calls[identity]
        kwargs: dict[str, Any] = dict(
            disposition=disposition,
            source="formal-model",
            actor="operator",
            reason=f"evidence for {disposition.value}",
            evidence={"probe": key},
            workspace_id=WORKSPACE,
            project_id=PROJECT,
        )
        if model is None or model.status == "fresh":
            with pytest.raises(KeyError):
                _run(self.service.reconcile("no-such-invocation", **kwargs))
            return

        assert model.invocation_id is not None
        settled = _run(self.service.reconcile(model.invocation_id, **kwargs))
        assert self.provider_calls[identity] == before, "reconciliation dispatched the provider"

        if model.status == "completed":
            assert settled.status is InvocationStatus.COMPLETED
            assert settled.finished_at is not None
            return
        if model.status == "failed":
            assert settled.status is InvocationStatus.FAILED
            return
        # Blocked identity: only evidence changes the lifecycle.
        if disposition is ReconciliationDisposition.APPLIED:
            assert settled.status is InvocationStatus.COMPLETED
            assert settled.finished_at is not None
            model.status = "completed"
            model.frozen_dispatches = before
        elif disposition is ReconciliationDisposition.NOT_APPLIED:
            assert settled.status is InvocationStatus.FAILED
            assert settled.error is not None
            model.status = "failed"
        else:
            assert settled.status is InvocationStatus.UNKNOWN
            assert settled.error is not None
            # UNKNOWN was already terminalized when the ambiguity was
            # recorded; INDETERMINATE evidence leaves that record in place.
            assert settled.finished_at is not None

    # ------------------------------------------------------------- invariants

    @invariant()
    def store_matches_model(self) -> None:
        """The store observable agrees with the machine's independent model.

        Counterexample class: the service terminalizes a different row than it
        reported, mints a second completed row for one admission identity,
        leaves a terminal record without a terminal timestamp, or widens or
        narrows an admission identity so history appears where the contract
        says none does.
        """
        histories = _run(self._all_histories())
        for identity, model in self.effects.items():
            rows = histories[identity]
            if model.status == "fresh":
                assert not rows, f"history exists for untouched identity {identity}: {rows!r}"
                continue
            assert rows, f"store lost history for {identity}"
            completed = [row for row in rows if row.status is InvocationStatus.COMPLETED]
            assert len(completed) <= 1, f"two completed rows for admission identity {identity}"
            latest = rows[-1]
            expected = {
                "completed": InvocationStatus.COMPLETED,
                "failed": InvocationStatus.FAILED,
            }.get(model.status)
            if expected is None:
                assert latest.status in _BLOCKING, f"{identity}: blocked model but store says {latest.status.value}"
            else:
                assert latest.status is expected, (
                    f"{identity}: model {model.status} but store says {latest.status.value}"
                )
            assert (latest.status in _TERMINAL) == (latest.finished_at is not None), (
                f"{identity}: terminal/timestamp disagreement on {latest.status.value}"
            )
            if model.status == "completed":
                assert self.provider_calls[identity] == model.frozen_dispatches
                assert latest.invocation_id == model.invocation_id
            if model.invocation_id is not None:
                seen = model.observed_revisions.get(latest.invocation_id)
                if seen is not None:
                    assert latest.revision >= seen, "revision went backwards"
                model.observed_revisions[latest.invocation_id] = latest.revision


TestInvocationEffectMachine = InvocationEffectMachine.TestCase


# ---------------------------------------------------------------------------
# Minimal-sequence properties (the shrinking companions to the machine)


def _fresh_service() -> tuple[Binding, InMemoryInvocationStore, InvocationExecutionService, Counter]:
    binding = Binding(
        binding_id=BINDING_ID,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        capability="external_write",
    )
    store = InMemoryInvocationStore()
    return binding, store, InvocationExecutionService(store=store), Counter()


@given(retries=st.integers(min_value=1, max_value=8), replay_node=st.sampled_from([NODE_A, NODE_B]))
@settings(max_examples=25)
def test_completed_logical_effect_replays_without_redispatch(retries: int, replay_node: str) -> None:
    """Invariants 1+4, minimized: complete once, then replay from anywhere.

    Counterexample class: a replay that mints a second row or re-dispatches
    under a new Attempt or NodeRun — double application of a committed effect.
    """
    binding, store, service, calls = _fresh_service()

    async def execute(_provider: Any, request: dict[str, Any]) -> str:
        calls["dispatch"] += 1
        return "committed"

    async def scenario() -> Invocation:
        first = await service.invoke(
            binding=binding,
            run_id=RUN_ID,
            node_run_id=NODE_A,
            attempt_id="attempt-first",
            effect_key="effect-replay",
            request={"outcome": "ok"},
            logical_effect=True,
            resolver=_resolve,
            executor=execute,
        )
        for attempt in range(retries):
            replay = await service.invoke(
                binding=binding,
                run_id=RUN_ID,
                node_run_id=replay_node,
                attempt_id=f"attempt-retry-{attempt}",
                effect_key="effect-replay",
                request={"outcome": "ok"},
                logical_effect=True,
                resolver=_resolve,
                executor=execute,
            )
            assert replay.invocation_id == first.invocation_id
            assert replay.status is InvocationStatus.COMPLETED
            assert replay.finished_at is not None
        return first

    first = _run(scenario())
    assert calls["dispatch"] == 1
    rows = _run(store.list_effect(run_id=RUN_ID, node_run_id=None, binding_id=BINDING_ID, effect_key="effect-replay"))
    assert len(rows) == 1
    assert rows[0].invocation_id == first.invocation_id


@given(
    outcome=st.sampled_from(["generic", "cancelled"]),
    settle=st.sampled_from(ReconciliationDisposition),
)
@settings(max_examples=15)
def test_ambiguous_outcome_blocks_until_evidence(outcome: str, settle: ReconciliationDisposition) -> None:
    """Invariants 2+3, minimized: generic/cancelled -> UNKNOWN blocks; evidence releases.

    Counterexample class: an UNKNOWN outcome treated as retryable (duplicate
    application risk), or a row still blocking after proof has settled it.
    """
    binding, store, service, calls = _fresh_service()

    async def execute(_provider: Any, request: dict[str, Any]) -> str:
        calls["dispatch"] += 1
        if request["outcome"] == "generic":
            raise RuntimeError("provider exploded mid-call")
        if request["outcome"] == "cancelled":
            raise asyncio.CancelledError()
        return "committed"

    async def scenario() -> None:
        with pytest.raises((RuntimeError, asyncio.CancelledError)):
            await service.invoke(
                binding=binding,
                run_id=RUN_ID,
                node_run_id=NODE_A,
                attempt_id="attempt-ambiguous",
                effect_key="effect-ambiguous",
                request={"outcome": outcome},
                resolver=_resolve,
                executor=execute,
            )
        assert calls["dispatch"] == 1
        blocked = await store.list_effect(
            run_id=RUN_ID, node_run_id=NODE_A, binding_id=BINDING_ID, effect_key="effect-ambiguous"
        )
        assert blocked[-1].status is InvocationStatus.UNKNOWN
        assert blocked[-1].finished_at is not None

        with pytest.raises(UnsafeEffectRetry):
            await service.invoke(
                binding=binding,
                run_id=RUN_ID,
                node_run_id=NODE_A,
                attempt_id="attempt-too-soon",
                effect_key="effect-ambiguous",
                request={"outcome": "ok"},
                resolver=_resolve,
                executor=execute,
            )
        assert calls["dispatch"] == 1

        settled = await service.reconcile(
            blocked[-1].invocation_id,
            disposition=settle,
            source="formal-model",
            actor="operator",
            reason="probe evidence",
            evidence={"probe": True},
            workspace_id=WORKSPACE,
            project_id=PROJECT,
        )
        if settle is ReconciliationDisposition.INDETERMINATE:
            assert settled.status is InvocationStatus.UNKNOWN
            with pytest.raises(UnsafeEffectRetry):
                await service.invoke(
                    binding=binding,
                    run_id=RUN_ID,
                    node_run_id=NODE_A,
                    attempt_id="attempt-still-blocked",
                    effect_key="effect-ambiguous",
                    request={"outcome": "ok"},
                    resolver=_resolve,
                    executor=execute,
                )
            assert calls["dispatch"] == 1
            return
        if settle is ReconciliationDisposition.APPLIED:
            assert settled.status is InvocationStatus.COMPLETED
            assert settled.finished_at is not None
            replay = await service.invoke(
                binding=binding,
                run_id=RUN_ID,
                node_run_id=NODE_B,
                attempt_id="attempt-replay",
                effect_key="effect-ambiguous",
                request={"outcome": "ok"},
                logical_effect=True,
                resolver=_resolve,
                executor=execute,
            )
            assert replay.invocation_id == settled.invocation_id
            assert calls["dispatch"] == 1
            return
        assert settled.status is InvocationStatus.FAILED
        retried = await service.invoke(
            binding=binding,
            run_id=RUN_ID,
            node_run_id=NODE_A,
            attempt_id="attempt-after-proof",
            effect_key="effect-ambiguous",
            request={"outcome": "ok"},
            resolver=_resolve,
            executor=execute,
        )
        assert retried.status is InvocationStatus.COMPLETED
        assert retried.finished_at is not None
        assert calls["dispatch"] == 2

    _run(scenario())
