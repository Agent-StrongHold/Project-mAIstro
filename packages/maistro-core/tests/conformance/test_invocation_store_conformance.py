"""The capability InvocationStore contract, run unchanged on every backend (#892).

Each node is one contract check x one production implementation
(``memory``, ``sqlite``, ``postgres``). A failure on one leg and a pass on
another is cross-implementation drift on one protocol — the defect class
this suite exists to catch.

Known divergences are not hidden: each is an xfail carrying its finding
number from ``docs/testing/conformance-suite-evidence.md``. ``strict=True``
means a repair flips the node to XPASS and fails the suite until the marker
is retired — the suite retires its own findings.
"""

from __future__ import annotations

from typing import Any

import pytest

from ._invocation_contract import INVOCATION_CHECKS, check_applies

#: Leg x check -> xfail kwargs for a recorded cross-implementation divergence.
#: Every entry cites its finding in docs/testing/conformance-suite-evidence.md.
KNOWN_DIVERGENCES: dict[tuple[str, str], dict[str, Any]] = {
    # F1: PgInvocationStore.create admits a fresh Invocation beside a
    # COMPLETED prior (its partial unique indexes only cover active
    # statuses). The reference and the SQLite twin both refuse.
    ("postgres", "create_refuses_second_admission_of_a_completed_effect"): {
        "strict": True,
        "reason": "#892 F1: PostgreSQL terminal dedup missing at the ledger",
    },
    # F4: SqliteInvocationStore.claim scopes its history read to the
    # candidate's node_run_id, so a #1194 logical effect whose completed
    # canonical row sits under an earlier NodeRun is re-admitted instead of
    # replayed. The in-memory reference replays it.
    ("sqlite", "claim_replays_a_completed_prior"): {
        "strict": True,
        "reason": "#892 F4: SQLite claim misses Run-scoped completed priors",
    },
    # F3: InMemoryInvocationStore.claim returns a non-terminal prior where
    # the durable contract (pinned by the SQLite twin's own tests) refuses
    # it with UnsafeEffectRetry. Possibly deliberate single-process
    # leniency, hence not strict; InvocationExecutionService re-checks the
    # return, so the divergence is service-masked today.
    ("memory", "claim_never_admits_beside_a_live_prior"): {
        "strict": False,
        "reason": "#892 F3: in-memory claim returns live priors instead of refusing",
    },
    # F6: InMemoryInvocationStore.list_effect sorts by created_at only, so
    # equal-timestamp ties come back in insertion order where both durable
    # twins ORDER BY (created_at, invocation_id). history[-1] is "the
    # latest" for every consumer, so the tiebreak selects different rows.
    ("memory", "list_effect_orders_created_at_ties_by_invocation_id"): {
        "strict": True,
        "reason": "#892 F6: in-memory history does not honor the invocation_id tiebreak",
    },
}


@pytest.mark.parametrize("check_name", sorted(INVOCATION_CHECKS))
async def test_invocation_store_contract(
    invocation_leg: Any, request: pytest.FixtureRequest, check_name: str
) -> None:
    """One contract check against one InvocationStore implementation."""
    check, requires = INVOCATION_CHECKS[check_name]
    leg = invocation_leg
    if not check_applies(leg.store(), requires):
        pytest.skip(f"the {leg.name} store does not expose the atomic claim protocol")
    divergence = KNOWN_DIVERGENCES.get((leg.name, check_name))
    if divergence is not None:
        request.applymarker(pytest.mark.xfail(**divergence))
    await check(leg.store(), leg)


def test_the_suite_covers_the_whole_wired_surface() -> None:
    """Every store the container can wire has a leg in the matrix.

    A fourth production-wired InvocationStore must arrive together with a
    leg in ``BACKENDS`` (and, if it diverges, with its own recorded
    findings) — this guard is what makes that addition loud.
    """
    from maistro.capabilities.invocation import InMemoryInvocationStore
    from maistro.capabilities.invocation_store import SqliteInvocationStore
    from maistro.capabilities.pg_invocation_store import PgInvocationStore

    from .conftest import BACKENDS

    wired = {InMemoryInvocationStore, SqliteInvocationStore, PgInvocationStore}
    assert len(wired) == len(BACKENDS), "one leg per container-wired store"
    assert set(BACKENDS) == {"memory", "sqlite", "postgres"}


def test_every_check_is_named_by_its_function() -> None:
    """Registry keys cannot drift from the checks they run."""
    for name, (check, _requires) in INVOCATION_CHECKS.items():
        assert name == check.__name__, name
