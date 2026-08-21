"""Event-loop isolation for the sync tests in this package.

`test_faux_provider.py` drives coroutines with the legacy
`asyncio.get_event_loop().run_until_complete(...)` pattern. Under pytest-asyncio
(auto mode) a preceding async test closes the loop it created, so a later sync
test's `get_event_loop()` can return a *closed* loop and fail — an ordering
landmine unrelated to what the test asserts. This autouse fixture hands every
sync test a fresh open loop; async tests are left to pytest-asyncio.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_event_loop_for_sync_tests(request: pytest.FixtureRequest):
    func = getattr(request, "function", None)
    if func is not None and asyncio.iscoroutinefunction(func):
        # Async test: pytest-asyncio owns the loop lifecycle.
        yield
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        loop.close()
