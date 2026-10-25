"""Branch closers for InvocationUsage validation (invocation.py 90, 92, 94).

Diff coverage on PR #1040 flagged the three ``_validate_usage`` raise lines as
uncovered. Each test drives one validator rejection; the accepting direction
of every condition is covered by the egress suite attaching usage metadata.
"""

from __future__ import annotations

import pytest

from maistro.capabilities.invocation import InvocationUsage


def test_blank_units_rejected() -> None:
    """Line 90: ``units`` must be a non-empty string."""
    with pytest.raises(ValueError, match="units must be a non-empty string"):
        InvocationUsage(units="   ")


def test_negative_input_units_rejected() -> None:
    """Line 92 (input side): usage units cannot be negative."""
    with pytest.raises(ValueError, match="usage units cannot be negative"):
        InvocationUsage(input_units=-1)


def test_negative_output_units_rejected() -> None:
    """Line 92 (output side): the other operand of the same condition."""
    with pytest.raises(ValueError, match="usage units cannot be negative"):
        InvocationUsage(output_units=-1)


def test_negative_cost_rejected() -> None:
    """Line 94: a measured cost cannot be negative."""
    with pytest.raises(ValueError, match="cost_cents cannot be negative"):
        InvocationUsage(cost_cents=-0.01)


def test_valid_usage_and_zero_cost_accepted() -> None:
    """The accepting direction: zero is a measured cost, absence is None."""

    usage = InvocationUsage(
        units="tokens", input_units=10, output_units=5, cost_cents=0.0, model="m"
    )
    assert usage.input_units == 10
    assert usage.cost_cents == 0.0
    assert InvocationUsage().cost_cents is None  # unmeasured stays absent
