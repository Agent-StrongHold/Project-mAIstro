"""The capability InvocationStore contract, as runnable checks (#892).

Every check is a behavior the protocol's consumers rely on, written once
against :class:`maistro.capabilities.invocation.InvocationStore` — never
against a backend. The suite runs each check unchanged against every
production implementation (in-memory, SQLite, PostgreSQL); a check that
fails on one leg and passes on another is a semantic drift between
implementations of one protocol, which is exactly the defect class this
experiment hunts.

Contract authority, in order:

1. the protocol docstrings in ``maistro.capabilities.invocation`` (in
   particular ``InvocationExecutionService.invoke``: a completed prior is a
   replay; ``CREATED``/``RUNNING``/``UNKNOWN`` block repetition; only a
   ``FAILED`` prior — proved-not-applied evidence — is retryable);
2. the durable twins' own pinned tests (``tests/capabilities/
   test_invocation_store.py`` claim tests), which are the system of record
   for multi-worker dispatch;
3. the in-memory reference, which the container wires for local execution.

Where the three disagree, the check encodes authority 1-2 and the diverging
leg is xfail-marked in the test module with its finding number from
``docs/testing/conformance-suite-evidence.md`` — never silently.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    EffectClaimStore,
    Invocation,
    InvocationStatus,
    StaleInvocationUpdate,
    UnsafeEffectRetry,
)

#: Statuses whose remote outcome cannot be proven absent, so a second
#: admission beside them is unsafe (per ``invoke``'s contract and the
#: active-status predicate both durable stores enforce).
_BLOCKING_STATUSES = (
    InvocationStatus.CREATED,
    InvocationStatus.RUNNING,
    InvocationStatus.UNKNOWN,
)


class ConformanceViolation(AssertionError):
    """One contract check failed against one leg."""


class _Provider:
    """Minimal provider the way every binding leg in the suite resolves one."""

    name = "conformance-provider"
    slot = "external_write"
    trust_tier = "trusted"


def _binding(ns: str) -> ResolvedBinding:
    binding = Binding(
        binding_id=f"binding-{ns}",
        workspace_id=f"ws-{ns}",
        project_id=f"project-{ns}",
        capability="external_write",
    )
    return ResolvedBinding.from_provider(binding, _Provider())


def _invocation(
    ns: str,
    invocation_id: str,
    *,
    node_run_id: str = "node-run-1",
    effect_key: str = "write:conformance",
    run_id: str | None = None,
    binding: ResolvedBinding | None = None,
    **overrides: Any,
) -> Invocation:
    fields: dict[str, Any] = {
        "invocation_id": f"{invocation_id}",
        "run_id": run_id or f"run-{ns}",
        "node_run_id": node_run_id,
        "attempt_id": "attempt-1",
        "binding": binding or _binding(ns),
        "effect_key": effect_key,
    }
    fields.update(overrides)
    return Invocation(**fields)


def _finished(_status: InvocationStatus) -> datetime:
    """A terminal Invocation requires finished_at; the instant is irrelevant."""
    return datetime.now(UTC)


def _fail(text: str) -> ConformanceViolation:
    return ConformanceViolation(text)


# ── record fidelity ───────────────────────────────────────────────────


async def round_trip_preserves_the_record(store: Any, leg: Any) -> None:
    """create → get returns the same record, detached from the store."""
    ns = uuid.uuid4().hex
    original = _invocation(
        ns,
        f"inv-{ns}",
        request={"path": f"/{ns}", "nested": {"k": [1, 2]}},
    )
    await store.create(original)
    got = await store.get(f"inv-{ns}")
    if got is None:
        raise _fail("get() returned None for an Invocation create() just accepted")
    for field, expected in (
        ("run_id", original.run_id),
        ("node_run_id", original.node_run_id),
        ("attempt_id", original.attempt_id),
        ("effect_key", original.effect_key),
        ("status", InvocationStatus.CREATED),
        ("revision", 0),
        ("request", original.request),
    ):
        if getattr(got, field) != expected:
            raise _fail(f"readback {field} is {getattr(got, field)!r}, expected {expected!r}")
    if got.binding.binding_id != original.binding.binding_id:
        raise _fail("readback lost the binding identity")
    if got.binding.provider_name != _Provider.name:
        raise _fail(
            "readback lost the resolved-provider snapshot: "
            f"{got.binding.provider_name!r} != {_Provider.name!r}"
        )
    # A readback is a copy: mutating it must not corrupt the store's record.
    got.status = InvocationStatus.RUNNING
    got.request["path"] = "/mutated"
    again = await store.get(f"inv-{ns}")
    if again is None or again.status is not InvocationStatus.CREATED:
        raise _fail("mutating a readback changed the stored record")
    if again.request["path"] == "/mutated":
        raise _fail("mutating a readback's payload changed the stored record")


async def missing_invocations_are_absent_not_errors(store: Any, leg: Any) -> None:
    """get() of a missing id is None; save() of a missing id is a KeyError."""
    ns = uuid.uuid4().hex
    if await store.get(f"inv-{ns}-absent") is not None:
        raise _fail("get() invented a record for an id that was never stored")
    try:
        await store.save(_invocation(ns, f"inv-{ns}-absent"))
    except KeyError:
        return
    raise _fail("save() of a missing invocation did not raise KeyError")


async def save_is_optimistic_concurrency_controlled(store: Any, leg: Any) -> None:
    """A stale revision can never overwrite; a winner bumps revision by one."""
    ns = uuid.uuid4().hex
    created = await store.create(_invocation(ns, f"inv-{ns}"))
    running = created.model_copy(
        update={"status": InvocationStatus.RUNNING, "started_at": datetime.now(UTC)}
    )
    saved = await store.save(running)
    if saved.revision != created.revision + 1:
        raise _fail(f"save() reported revision {saved.revision}, expected exactly one bump")
    readback = await store.get(f"inv-{ns}")
    if readback is None or readback.status is not InvocationStatus.RUNNING:
        raise _fail("save() did not persist the RUNNING transition")
    try:
        await store.save(created)  # stale: still carries the pre-save revision
    except StaleInvocationUpdate:
        pass
    else:
        raise _fail("save() accepted a stale revision (lost update)")
    terminal = saved.model_copy(
        update={
            "status": InvocationStatus.FAILED,
            "error": "provider proved the effect not applied",
            "finished_at": _finished(InvocationStatus.FAILED),
        }
    )
    final = await store.save(terminal)
    if final.revision != saved.revision + 1:
        raise _fail("second save() did not bump the revision exactly once")
    if (await store.get(f"inv-{ns}")).status is not InvocationStatus.FAILED:
        raise _fail("terminal save() did not persist")


# ── admission ─────────────────────────────────────────────────────────


async def create_refuses_second_admission_of_a_live_effect(store: Any, leg: Any) -> None:
    """A CREATED/RUNNING/UNKNOWN prior blocks admission for the same effect."""
    for status in _BLOCKING_STATUSES:
        ns = uuid.uuid4().hex
        terminal = status is InvocationStatus.UNKNOWN
        await store.create(
            _invocation(
                ns,
                f"inv-{ns}-prior",
                status=status,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC) if terminal else None,
            )
        )
        try:
            await store.create(_invocation(ns, f"inv-{ns}-second"))
        except UnsafeEffectRetry:
            continue
        raise _fail(f"create() admitted a second Invocation beside a {status.value} prior")


async def create_refuses_second_admission_of_a_completed_effect(store: Any, leg: Any) -> None:
    """A COMPLETED prior is a replay, not a fresh admission, at the ledger."""
    ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-done",
            status=InvocationStatus.COMPLETED,
            result={"applied": True},
            finished_at=_finished(InvocationStatus.COMPLETED),
        )
    )
    try:
        await store.create(_invocation(ns, f"inv-{ns}-second"))
    except UnsafeEffectRetry:
        return
    raise _fail(
        "create() admitted a second Invocation beside a COMPLETED prior: "
        "terminal dedup is missing from the ledger and moves into every caller"
    )


async def only_a_failed_prior_is_retryable(store: Any, leg: Any) -> None:
    """FAILED is proved-not-applied evidence: the one prior a retry may follow."""
    ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-failed",
            status=InvocationStatus.FAILED,
            error="EffectNotApplied",
            finished_at=_finished(InvocationStatus.FAILED),
        )
    )
    retry = await store.create(
        _invocation(
            ns,
            f"inv-{ns}-retry",
            node_run_id="node-run-2",
            attempt_id="attempt-2",
        )
    )
    if retry.invocation_id != f"inv-{ns}-retry":
        raise _fail("create() after a FAILED prior did not return the new candidate")
    history = await store.list_effect(
        run_id=f"run-{ns}",
        node_run_id=None,
        binding_id=_binding(ns).binding_id,
        effect_key="write:conformance",
    )
    if len(history) != 2:
        raise _fail(f"FAILED-prior retry left {len(history)} rows, expected both attempts")


async def create_refuses_a_duplicate_invocation_id(store: Any, leg: Any) -> None:
    """An invocation_id is a primary key: a second create with it is refused.

    The refusal *type* is deliberately not pinned here: the in-memory
    reference raises ``ValueError`` while both durable twins raise
    ``UnsafeEffectRetry`` (finding F2). Until an owner picks the canonical
    mapping, the portable property is "refuses".
    """
    ns = uuid.uuid4().hex
    await store.create(_invocation(ns, f"inv-{ns}"))
    try:
        await store.create(_invocation(ns, f"inv-{ns}"))
    except Exception:
        return
    raise _fail("create() silently accepted a duplicate invocation_id")


# ── queries ───────────────────────────────────────────────────────────


async def list_effect_matches_scope_spans_node_runs_and_orders_by_creation(
    store: Any, leg: Any
) -> None:
    """list_effect filters on its full scope, spans NodeRuns on demand, and
    orders by (created_at, invocation_id)."""
    ns = uuid.uuid4().hex
    binding = _binding(ns)
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 1, 2, tzinfo=UTC)
    await store.create(_invocation(ns, f"inv-{ns}-a", node_run_id="node-run-1", created_at=early))
    await store.create(_invocation(ns, f"inv-{ns}-b", node_run_id="node-run-2", created_at=late))
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-other-effect",
            node_run_id="node-run-1",
            effect_key="write:other",
            created_at=early,
        )
    )
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-other-run",
            node_run_id="node-run-1",
            run_id=f"run-{ns}-other",
            created_at=early,
        )
    )
    other_binding = _binding(f"{ns}-x")
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-other-binding",
            node_run_id="node-run-1",
            binding=other_binding,
            created_at=early,
        )
    )

    scoped = await store.list_effect(
        run_id=f"run-{ns}",
        node_run_id="node-run-1",
        binding_id=binding.binding_id,
        effect_key="write:conformance",
    )
    if [item.invocation_id for item in scoped] != [f"inv-{ns}-a"]:
        raise _fail(f"node_run-scoped list_effect returned {[i.invocation_id for i in scoped]}")

    spanned = await store.list_effect(
        run_id=f"run-{ns}",
        node_run_id=None,
        binding_id=binding.binding_id,
        effect_key="write:conformance",
    )
    if [item.invocation_id for item in spanned] != [f"inv-{ns}-a", f"inv-{ns}-b"]:
        raise _fail(
            "node_run_id=None must span NodeRuns in creation order, got "
            f"{[i.invocation_id for i in spanned]}"
        )


async def list_ambiguous_selects_unknown_and_stale_nonterminal_only(store: Any, leg: Any) -> None:
    """UNKNOWN is always ambiguous; CREATED/RUNNING only once stale; terminal never."""
    ns = uuid.uuid4().hex
    stale_at = datetime.now(UTC) - timedelta(hours=1)
    # Each row gets its own effect key: this check queries ambiguity, it does
    # not exercise admission, and a second row under one admission scope
    # would be refused before it could ever be listed.
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-unknown",
            effect_key="write:unknown",
            status=InvocationStatus.UNKNOWN,
            started_at=stale_at,
            finished_at=_finished(InvocationStatus.UNKNOWN),
        )
    )
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-stale",
            effect_key="write:stale",
            created_at=stale_at,
            started_at=stale_at,
        )
    )
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-failed",
            effect_key="write:failed",
            status=InvocationStatus.FAILED,
            error="proved not applied",
            created_at=stale_at,
            finished_at=_finished(InvocationStatus.FAILED),
        )
    )
    # The cutoff sits between the stale rows and the fresh one, so the
    # predicate is probed deterministically — no wall-clock race: the fresh
    # row's started_at is pinned one second past the cutoff.
    cutoff = datetime.now(UTC)
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-fresh",
            effect_key="write:fresh",
            status=InvocationStatus.RUNNING,
            created_at=cutoff + timedelta(seconds=1),
            started_at=cutoff + timedelta(seconds=1),
        )
    )
    ambiguous = await store.list_ambiguous(stale_before=cutoff)
    ids = [item.invocation_id for item in ambiguous]
    if f"inv-{ns}-unknown" not in ids:
        raise _fail("UNKNOWN must be listed as ambiguous regardless of age")
    if f"inv-{ns}-stale" not in ids:
        raise _fail("a CREATED older than the cutoff must be listed as ambiguous")
    if f"inv-{ns}-fresh" in ids:
        raise _fail("a RUNNING invocation newer than the cutoff is not ambiguous")
    if f"inv-{ns}-failed" in ids:
        raise _fail("FAILED is terminal evidence and must never be ambiguous")

    # Boundary: exactly at the cutoff counts as stale (<=), matching all
    # three implementations' shared predicate.
    boundary_ns = uuid.uuid4().hex
    exact = datetime.now(UTC) - timedelta(minutes=5)
    await store.create(
        _invocation(boundary_ns, f"inv-{boundary_ns}-edge", created_at=exact, started_at=exact)
    )
    edges = await store.list_ambiguous(stale_before=exact)
    if f"inv-{boundary_ns}-edge" not in [item.invocation_id for item in edges]:
        raise _fail("an invocation exactly at stale_before must count as stale (<=)")


async def list_effect_orders_created_at_ties_by_invocation_id(store: Any, leg: Any) -> None:
    """Equal created_at ties order by invocation_id — the durable ORDER BY.

    Both durable twins document ``ORDER BY created_at ASC, invocation_id ASC``
    as the history contract, and consumers read ``history[-1]`` as *the
    latest* Invocation. An implementation that breaks ties by insertion order
    can answer "latest" differently than the system of record for the same
    rows (finding F6).
    """
    ns = uuid.uuid4().hex
    tied_binding = _binding(ns)
    tied_at = datetime(2026, 2, 1, tzinfo=UTC)
    # Different NodeRuns: one admission scope per row, so only ordering is
    # under test; the spanned query (node_run_id=None) is the one consumers
    # read for a logical effect's history.
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-b",
            node_run_id="node-run-2",
            binding=tied_binding,
            created_at=tied_at,
        )
    )
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-a",
            node_run_id="node-run-1",
            binding=tied_binding,
            created_at=tied_at,
        )
    )
    tied = await store.list_effect(
        run_id=f"run-{ns}",
        node_run_id=None,
        binding_id=tied_binding.binding_id,
        effect_key="write:conformance",
    )
    if [item.invocation_id for item in tied] != [f"inv-{ns}-a", f"inv-{ns}-b"]:
        raise _fail(
            "equal created_at must tiebreak on invocation_id, got "
            f"{[i.invocation_id for i in tied]}"
        )


# ── EffectClaimStore ──────────────────────────────────────────────────


async def claim_replays_a_completed_prior(store: Any, leg: Any) -> None:
    """claim() on a completed effect returns the canonical row — a replay.

    Checked for an ordinary same-NodeRun prior and for the #1194 logical
    effect whose completed canonical row lives under an *earlier* NodeRun:
    the persisted discriminator makes the effect Run-scoped, so a retry that
    minted a new NodeRun must be answered with the completed row, never with
    a fresh admission.
    """
    ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-done",
            status=InvocationStatus.COMPLETED,
            result={"applied": True},
            finished_at=_finished(InvocationStatus.COMPLETED),
        )
    )
    replay = await store.claim(_invocation(ns, f"inv-{ns}-second"))
    if replay.invocation_id != f"inv-{ns}-done":
        raise _fail(f"claim() beside a completed prior returned {replay.invocation_id!r}")

    logical_ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            logical_ns,
            f"inv-{logical_ns}-done",
            status=InvocationStatus.COMPLETED,
            result={"applied": True},
            finished_at=_finished(InvocationStatus.COMPLETED),
            logical_effect=True,
        )
    )
    logical_replay = await store.claim(
        _invocation(
            logical_ns,
            f"inv-{logical_ns}-retry",
            node_run_id="node-run-2",
            attempt_id="attempt-2",
            logical_effect=True,
        )
    )
    if logical_replay.invocation_id != f"inv-{logical_ns}-done":
        raise _fail(
            "claim() for a logical effect beside a completed canonical row "
            f"under another NodeRun returned {logical_replay.invocation_id!r} "
            "(a fresh admission double-dispatches the effect)"
        )


async def claim_never_admits_beside_a_live_prior(store: Any, leg: Any) -> None:
    """A RUNNING prior means the outcome cannot be proven absent: refuse."""
    ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-live",
            status=InvocationStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
    )
    try:
        await store.claim(_invocation(ns, f"inv-{ns}-second"))
    except UnsafeEffectRetry:
        return
    raise _fail("claim() beside a RUNNING prior did not raise UnsafeEffectRetry")


async def claim_admits_only_after_failure(store: Any, leg: Any) -> None:
    """FAILED is the one prior a claim may follow with a fresh admission."""
    ns = uuid.uuid4().hex
    await store.create(
        _invocation(
            ns,
            f"inv-{ns}-failed",
            status=InvocationStatus.FAILED,
            error="EffectNotApplied",
            finished_at=_finished(InvocationStatus.FAILED),
        )
    )
    claimed = await store.claim(_invocation(ns, f"inv-{ns}-retry"))
    if claimed.invocation_id != f"inv-{ns}-retry":
        raise _fail("claim() after a FAILED prior did not admit the new candidate")


#: The InvocationStore contract, check name → (check, requirement).
#: ``requirement`` names an additional protocol a check presupposes (the
#: optional atomic claim); the matrix skips a leg whose store does not
#: satisfy it — that is protocol knowledge, not backend knowledge, so the
#: checks stay implementation-free.
INVOCATION_CHECKS: dict[str, tuple[Callable[[Any, Any], Awaitable[None]], type | None]] = {
    check.__name__: (check, None)
    for check in (
        round_trip_preserves_the_record,
        missing_invocations_are_absent_not_errors,
        save_is_optimistic_concurrency_controlled,
        create_refuses_second_admission_of_a_live_effect,
        create_refuses_second_admission_of_a_completed_effect,
        only_a_failed_prior_is_retryable,
        create_refuses_a_duplicate_invocation_id,
        list_effect_matches_scope_spans_node_runs_and_orders_by_creation,
        list_ambiguous_selects_unknown_and_stale_nonterminal_only,
        list_effect_orders_created_at_ties_by_invocation_id,
    )
}
for _claim_check in (
    claim_replays_a_completed_prior,
    claim_never_admits_beside_a_live_prior,
    claim_admits_only_after_failure,
):
    INVOCATION_CHECKS[_claim_check.__name__] = (_claim_check, EffectClaimStore)


def check_applies(store: Any, requires: type | None) -> bool:
    """Whether *store* satisfies a check's protocol requirement."""
    if requires is None:
        return True
    return isinstance(store, requires)


__all__ = [
    "INVOCATION_CHECKS",
    "ConformanceViolation",
    "check_applies",
    *INVOCATION_CHECKS.keys(),
]
