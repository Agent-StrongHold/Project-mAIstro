"""The durable ApprovalStore contract, run unchanged on every backend (#892).

One contract check x one production implementation per node. See
``test_invocation_store_conformance.py`` for the xfail discipline; the
approval contract currently records one divergence (F5: duplicate-request_id
error mapping) which is portable enough to check as a plain refusal — the
type drift is recorded in the evidence document instead.
"""

from __future__ import annotations

from typing import Any

import pytest

from ._approval_contract import APPROVAL_CHECKS


@pytest.mark.parametrize("check_name", sorted(APPROVAL_CHECKS))
async def test_approval_store_contract(
    approval_leg: Any, request: pytest.FixtureRequest, check_name: str
) -> None:
    """One contract check against one ApprovalStore implementation."""
    check = APPROVAL_CHECKS[check_name]
    await check(approval_leg.store(), approval_leg)


def test_the_approval_suite_covers_the_whole_wired_surface() -> None:
    """Every store the container can wire has a leg in the matrix."""
    from maistro.capabilities.approval_store import (
        InMemoryApprovalStore,
        PgApprovalStore,
        SqliteApprovalStore,
    )

    from .conftest import BACKENDS

    wired = {InMemoryApprovalStore, SqliteApprovalStore, PgApprovalStore}
    assert len(wired) == len(BACKENDS), "one leg per container-wired store"
    assert set(BACKENDS) == {"memory", "sqlite", "postgres"}


def test_every_approval_check_is_named_by_its_function() -> None:
    """Registry keys cannot drift from the checks they run."""
    for name, check in APPROVAL_CHECKS.items():
        assert name == check.__name__, name
