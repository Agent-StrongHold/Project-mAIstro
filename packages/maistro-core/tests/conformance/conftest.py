"""Fixtures for the generalized conformance suites (#892).

One suite, one fixture, every production backend: the test modules never
name a backend — they receive a :class:`~tests.conformance._legs.ConformanceLeg`
and run the shared contract against it. The PostgreSQL leg skips without a
real server (see ``_legs.require_postgres_url``); a skipped leg is untested,
not passing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from ._legs import build_approval_leg, build_invocation_leg

BACKENDS = ["memory", "sqlite", "postgres"]


@pytest.fixture(params=BACKENDS)
async def invocation_leg(request: pytest.FixtureRequest, tmp_path: Any) -> AsyncIterator[Any]:
    """Every production InvocationStore implementation, one at a time."""
    leg = await build_invocation_leg(request.param, tmp_path)
    try:
        yield leg
    finally:
        await leg.aclose()


@pytest.fixture(params=BACKENDS)
async def approval_leg(request: pytest.FixtureRequest, tmp_path: Any) -> AsyncIterator[Any]:
    """Every production ApprovalStore implementation, one at a time."""
    leg = await build_approval_leg(request.param, tmp_path)
    try:
        yield leg
    finally:
        await leg.aclose()
