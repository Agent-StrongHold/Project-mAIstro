"""The conformance suite has teeth (#892).

A suite that cannot fail is decoration. Each test here introduces exactly
one deliberate semantic drift into a reference store — the kind a future
implementation could introduce by accident — and asserts the suite flags
that check and only that check. This is the experiment's "is the suite still
strict enough to catch meaningful divergence" evidence, kept executable.
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    InMemoryApprovalStore,
)
from maistro.capabilities.invocation import InMemoryInvocationStore

from ._approval_contract import APPROVAL_CHECKS
from ._invocation_contract import INVOCATION_CHECKS, check_applies
from ._legs import ConformanceLeg, in_memory_approval_leg, in_memory_invocation_leg


async def _run_suite(checks: Any, leg: ConformanceLeg) -> dict[str, str]:
    """Run every applicable check; return the failures by check name.

    Any exception counts as a flag here — a shim drifting admission raises
    the store's own ``UnsafeEffectRetry``, not a ``ConformanceViolation`` —
    and a check that crashed for a wiring bug would surface immediately in
    the honest-leg expectation test below.
    """
    violations: dict[str, str] = {}
    for name, entry in checks.items():
        check, requires = entry if isinstance(entry, tuple) else (entry, None)
        if not check_applies(leg.store(), requires):
            continue
        try:
            await check(leg.store(), leg)
        except Exception as exc:
            violations[name] = f"{type(exc).__name__}: {exc}"
    return violations


class _AdmitsAnything(InMemoryInvocationStore):
    """Drift: admission never refuses (the ledger becomes write-only)."""

    async def create(self, invocation: Any) -> Any:
        self._items[invocation.invocation_id] = invocation.model_copy(deep=True)
        return invocation.model_copy(deep=True)

    async def claim(self, invocation: Any) -> Any:
        self._items.setdefault(invocation.invocation_id, invocation.model_copy(deep=True))
        return invocation.model_copy(deep=True)


class _BlindSave(InMemoryInvocationStore):
    """Drift: last write wins (lost updates)."""

    async def save(self, invocation: Any) -> Any:
        async with self._lock:
            self._items[invocation.invocation_id] = invocation.model_copy(deep=True)
            return invocation.model_copy(deep=True)


class _ReordersHistory(InMemoryInvocationStore):
    """Drift: history comes back newest-first."""

    async def list_effect(self, **kwargs: Any) -> list[Any]:
        return list(await super().list_effect(**kwargs))[::-1]


class _AmnesiacClaim(InMemoryInvocationStore):
    """Drift: claim() answers with the candidate instead of the canonical row."""

    async def claim(self, invocation: Any) -> Any:
        return await self.create(invocation)


class _AnonymousDecisions(InMemoryApprovalStore):
    """Drift: resolves without a verified principal (#329 regression)."""

    async def resolve(self, request_id: str, *, approved: bool, actor: str) -> Any:
        return await super().resolve(request_id, approved=approved, actor=actor or "anonymous")


class _LastVoteWins(InMemoryApprovalStore):
    """Drift: re-resolution overwrites the first decision."""

    async def resolve(self, request_id: str, *, approved: bool, actor: str) -> Any:
        existing = self._items.get(request_id)
        if existing is None:
            raise KeyError(f"approval request {request_id!r} does not exist")
        resolved = existing.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
                "actor": actor,
                "resolved_at": existing.resolved_at,
            }
        )
        self._items[request_id] = resolved
        return resolved.model_copy(deep=True)


class _AmnesiacApprovalStore(InMemoryApprovalStore):
    """Drift: restart loses the decision (durability contract)."""


def _leg_with(store: Any, *, invocation: bool) -> ConformanceLeg:
    base = in_memory_invocation_leg() if invocation else in_memory_approval_leg()
    base._store = store
    return base


# ── InvocationStore teeth ─────────────────────────────────────────────


async def test_the_suite_flags_a_store_that_admits_anything() -> None:
    leg = _leg_with(_AdmitsAnything(), invocation=True)
    violations = await _run_suite(INVOCATION_CHECKS, leg)
    assert "create_refuses_second_admission_of_a_live_effect" in violations
    assert "create_refuses_second_admission_of_a_completed_effect" in violations


async def test_the_suite_flags_a_lost_update() -> None:
    leg = _leg_with(_BlindSave(), invocation=True)
    violations = await _run_suite(INVOCATION_CHECKS, leg)
    assert "save_is_optimistic_concurrency_controlled" in violations


async def test_the_suite_flags_reordered_history() -> None:
    leg = _leg_with(_ReordersHistory(), invocation=True)
    violations = await _run_suite(INVOCATION_CHECKS, leg)
    assert "list_effect_matches_scope_spans_node_runs_and_orders_by_creation" in violations


async def test_the_suite_flags_a_claim_that_never_replays() -> None:
    leg = _leg_with(_AmnesiacClaim(), invocation=True)
    violations = await _run_suite(INVOCATION_CHECKS, leg)
    assert "claim_replays_a_completed_prior" in violations


# ── ApprovalStore teeth ───────────────────────────────────────────────


async def test_the_suite_flags_an_unattributable_decision() -> None:
    leg = _leg_with(_AnonymousDecisions(), invocation=False)
    violations = await _run_suite(APPROVAL_CHECKS, leg)
    assert "resolve_requires_a_verified_actor" in violations


async def test_the_suite_flags_a_second_decision_overwriting_the_first() -> None:
    leg = _leg_with(_LastVoteWins(), invocation=False)
    violations = await _run_suite(APPROVAL_CHECKS, leg)
    assert "resolve_is_idempotent_and_first_decision_wins" in violations


async def test_the_suite_flags_a_decision_lost_across_a_restart() -> None:
    async def forget() -> Any:
        return InMemoryApprovalStore()

    leg = ConformanceLeg("memory", durable=False, _store=_AmnesiacApprovalStore(), _restart=forget)
    violations = await _run_suite(APPROVAL_CHECKS, leg)
    assert "a_resolved_approval_survives_a_restart" in violations


# ── the suite against honest stores ──────────────────────────────────


async def test_an_honest_memory_leg_violates_only_the_recorded_findings() -> None:
    """The suite is not accidentally red: the in-memory reference violates
    exactly the findings the xfail matrix records for it (#892 F3 and F6),
    and nothing else."""
    invocation_violations = await _run_suite(INVOCATION_CHECKS, in_memory_invocation_leg())
    approval_violations = await _run_suite(APPROVAL_CHECKS, in_memory_approval_leg())
    assert set(invocation_violations) == {
        "claim_never_admits_beside_a_live_prior",
        "list_effect_orders_created_at_ties_by_invocation_id",
    }
    assert approval_violations == {}
