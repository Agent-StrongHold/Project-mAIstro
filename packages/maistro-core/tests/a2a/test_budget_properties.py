"""ADR-058 Hypothesis property test: for any generated delegation tree,
depth never exceeds max_depth and no agent id repeats on any root-to-leaf path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from maistro.a2a import DelegationBudget, DelegationRefused

_AGENT_IDS = st.sampled_from([f"agent-{i}" for i in range(8)])


@given(
    max_depth=st.integers(min_value=0, max_value=5),
    targets=st.lists(_AGENT_IDS, min_size=1, max_size=12),
)
def test_delegation_path_respects_depth_and_has_no_repeats(
    max_depth: int, targets: list[str]
) -> None:
    """Simulate one root-to-leaf path of a delegation tree by repeatedly
    checking + spending the budget for each generated target hop."""
    budget = DelegationBudget(
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        token_budget=1_000,
        trace_id="prop-trace",
        max_depth=max_depth,
    )
    hops = 0
    for target in targets:
        try:
            budget.check(target)
        except DelegationRefused:
            # Refusal must be for a legitimate reason: depth exhausted or cycle.
            assert budget.max_depth <= 0 or target in budget.chain
            continue
        budget = budget.spend(target)
        hops += 1

    # Depth invariant: hops taken never exceed the original max_depth.
    assert hops <= max_depth
    assert budget.max_depth >= 0
    # Path invariant: no agent id appears twice on the accepted path.
    assert len(set(budget.chain)) == len(budget.chain)
