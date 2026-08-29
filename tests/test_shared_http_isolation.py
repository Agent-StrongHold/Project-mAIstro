"""The shared HTTP transport override does not outlive the test that set it (#414).

`maistro.http` keeps one process-global transport override so tests can run the
real client against a fake network. `set_test_transport()` has no scope: set it
and every later request in the process goes through that transport.

`tests/hive_conductor/test_airtable_cache.py` did exactly that and never
restored it, so a MockTransport answering 200 to every request stayed live for
the rest of the process. Two Conductor tests asserting that an unreachable URL
reports "disconnected" then read it as reachable — and only when the root suite
happened to share an interpreter with them, which no CI job does. Nothing was
red for as long as the jobs stayed partitioned the way they are.

These are about the leak rather than its symptom. The two Conductor tests are
where it surfaced this time; the next leak surfaces somewhere else.
"""

from __future__ import annotations

import httpx
import pytest

from maistro.http import _test_transport, override_transport, set_test_transport


def _mock() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={}))


class TestTheOverrideIsScoped:
    def test_override_transport_restores_on_exit(self):
        before = _test_transport
        with override_transport(_mock()):
            from maistro import http

            assert http._test_transport is not before
        from maistro import http

        assert http._test_transport is before

    def test_it_restores_even_when_the_body_raises(self):
        """The case a `try/finally` is for, and the one a bare setter loses."""
        from maistro import http

        before = http._test_transport
        with pytest.raises(RuntimeError), override_transport(_mock()):
            raise RuntimeError("boom")
        assert http._test_transport is before

    def test_nesting_restores_the_outer_override(self):
        from maistro import http

        outer, inner = _mock(), _mock()
        with override_transport(outer):
            with override_transport(inner):
                assert http._test_transport is inner
            assert http._test_transport is outer


class TestTheAutouseResetCatchesWhatEscapes:
    """The scoped API is the fix; this fixture is why the *next* bare setter
    cannot couple two suites. `packages/maistro-core/tests/conftest.py` has
    carried it all along — the root tree simply never got it, which is how a
    leak this specific survived."""

    def test_a_bare_setter_does_not_survive_this_test(self):
        """Deliberately leaks, to prove the autouse fixture cleans up after it.
        If the fixture is ever removed, the test that runs next sees this
        transport and this file becomes the thing it warns about."""
        set_test_transport(_mock())

    def test_the_previous_test_did_not_leak_into_this_one(self):
        """Ordering-dependent by design: it asserts on what the test above left
        behind. Runs after it within the class, which is the only guarantee
        needed and the one pytest gives for a file's declaration order."""
        from maistro import http

        assert http._test_transport is None

    def test_an_unreachable_host_is_still_unreachable_here(self):
        """The property the Conductor tests were asserting, at the layer the
        leak actually broke: with no override in force, a request must reach
        the real transport and fail, not be answered 200 by someone else's
        mock."""
        import asyncio

        from maistro.http import shared_client

        async def go() -> None:
            async with shared_client(timeout=1.0) as client:
                with pytest.raises(httpx.HTTPError):
                    await client.get("http://example.invalid")

        asyncio.run(go())
