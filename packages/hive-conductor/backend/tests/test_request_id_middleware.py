"""Tests for Hive Conductor's request-id correlation middleware (#1063).

Hive had no `RequestIDMiddleware` and no `X-Request-ID` handling at all, so the
user-facing request, the Conductor->maistro-server service hop, and the
resulting canonical Run could not be followed by one correlation identity.
This reuses maistro-core's existing, already-tested `RequestIDMiddleware`
rather than a second implementation (see
`packages/maistro-core/tests/observability/test_middleware.py` for the
contract itself: validation pattern, normalization of invalid/duplicate
values, response echo). These tests hold the Hive-specific half: the
middleware is actually wired into `main:app`'s stack, and wraps enough of it
that an id is available even on an early rejection.

Written from scratch, following this test dir's convention of driving the
real ``main:app`` + middleware stack via TestClient (see
test_security_headers.py).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def _client() -> TestClient:
    return TestClient(app)


class TestRequestIDPresence:
    def test_a_fresh_id_is_generated_when_none_is_sent(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.headers["X-Request-ID"]

    def test_two_requests_get_two_different_generated_ids(self) -> None:
        c = _client()
        first = c.get("/health").headers["X-Request-ID"]
        second = c.get("/health").headers["X-Request-ID"]
        assert first != second

    def test_a_valid_client_supplied_id_is_echoed_back_unchanged(self) -> None:
        c = _client()
        r = c.get("/health", headers={"X-Request-ID": "caller-supplied-123"})
        assert r.headers["X-Request-ID"] == "caller-supplied-123"

    def test_an_invalid_client_supplied_id_is_replaced(self) -> None:
        """Same contract as maistro-server's RequestIDMiddleware: punctuation-only
        values (no letter/digit) are rejected rather than trusted verbatim."""
        c = _client()
        r = c.get("/health", headers={"X-Request-ID": "!!!"})
        assert r.headers["X-Request-ID"] != "!!!"
        assert r.headers["X-Request-ID"]

    def test_the_id_is_present_even_on_an_early_rejection(self) -> None:
        """RequestIDMiddleware must wrap AuthMiddleware, not sit inside it --
        an id is exactly as useful for correlating a 401 as a 200."""
        c = _client()
        r = c.get("/v1/tasks")
        assert r.status_code == 401
        assert r.headers["X-Request-ID"]

    def test_the_id_is_exposed_to_cross_origin_browser_callers(self) -> None:
        """Without `expose_headers`, `X-Request-ID` is sent but invisible to
        browser JS: only the CORS-safelisted header set is readable from
        `response.headers` cross-origin, so a server-generated id would have
        been an advertised correlation path no cross-origin UI could follow."""
        c = _client()
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert "x-request-id" in r.headers.get("access-control-expose-headers", "").lower()

    def test_the_id_is_present_on_an_unhandled_exception(self) -> None:
        """With no generic exception handler, an unhandled exception used to
        propagate straight past RequestIDMiddleware to Starlette's outer
        ServerErrorMiddleware, which has no way to attach an id it never
        saw -- exactly when a caller most needs it to report the failure.

        Built as an isolated app (same handler + middleware Hive registers,
        wired the same way) rather than mutating the shared `main.app`
        singleton every other test in this file (and the rest of the suite)
        also uses -- registering a route and an exception handler on that
        shared object is order-dependent on when Starlette caches its
        middleware stack relative to other tests' requests, and this way
        removes that dependency entirely."""
        from fastapi import FastAPI
        from main import unhandled_exception_handler

        from maistro.observability.middleware import RequestIDMiddleware

        test_app = FastAPI()
        test_app.add_middleware(RequestIDMiddleware)
        test_app.add_exception_handler(Exception, unhandled_exception_handler)

        @test_app.get("/boom")
        async def _boom() -> None:
            raise RuntimeError("synthetic failure for this test")

        c = TestClient(test_app, raise_server_exceptions=False)
        r = c.get("/boom")
        assert r.status_code == 500
        assert r.headers["X-Request-ID"]

    def test_the_handler_does_not_crash_with_no_id_bound(self) -> None:
        """`request.state.request_id` is only ever set by `RequestIDMiddleware`
        -- the handler itself must not assume it's always present, since a
        future caller could register it without that middleware."""
        from fastapi import FastAPI
        from main import unhandled_exception_handler

        test_app = FastAPI()
        test_app.add_exception_handler(Exception, unhandled_exception_handler)

        @test_app.get("/boom")
        async def _boom() -> None:
            raise RuntimeError("synthetic failure for this test")

        c = TestClient(test_app, raise_server_exceptions=False)
        r = c.get("/boom")
        assert r.status_code == 500
        assert "X-Request-ID" not in r.headers
