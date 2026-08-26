"""The throttle and the equal-cost check, through the real endpoints (#366).

`maistro-core`'s `test_auth_throttle.py` and `test_passwords.py` prove the
policy. These prove it is *reached*: a correct policy nothing calls is the
shape #257 was filed about, and the login route in particular had to be
restructured — not merely have a call added — because `and` short-circuiting
was the defect.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture(autouse=True)
def _fresh_throttles():
    """A clean budget per test.

    The throttles are module-level singletons, which is right for a running
    server and wrong for a suite: one test spending a budget would refuse the
    next for reasons that have nothing to do with what it asserts.
    """
    import routes.auth as auth

    from maistro.security.auth_throttle import AuthThrottle, StricterLimits

    stricter = StricterLimits()
    auth._LOGIN_THROTTLE = AuthThrottle()
    auth._REGISTER_THROTTLE = AuthThrottle(stricter.register)
    auth._ELEVATE_THROTTLE = AuthThrottle(stricter.elevate)
    yield


def _client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, username: str, password: str = "wrong-password-here"):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


class TestLoginDoesNotRevealWhichAccountsExist:
    def test_an_unknown_account_and_a_wrong_password_answer_the_same(self) -> None:
        """Status and body both. A different status code is the loudest
        possible oracle."""
        client = _client()
        unknown = _login(client, "definitely-not-a-user")
        known_wrong = _login(client, "testuser")

        assert unknown.status_code == known_wrong.status_code == 401
        assert unknown.json() == known_wrong.json()

    def test_the_message_names_neither_the_username_nor_the_field(self) -> None:
        """ "Unknown user" and "wrong password" are the same failure to anyone
        who is not already logged in."""
        detail = _login(_client(), "definitely-not-a-user").json()["detail"].lower()

        assert "user" not in detail or "invalid credentials" in detail
        assert "definitely-not-a-user" not in detail

    def test_the_route_verifies_even_when_there_is_no_account(self) -> None:
        """The property the fix rests on, observed where it matters. Asserted
        on the call rather than on a clock — a timing assertion on shared CI
        measures the runner, not the code."""
        from unittest import mock

        import routes.auth as auth

        with mock.patch.object(
            auth, "_client_key", wraps=auth._client_key
        ):  # keep signature stable
            from maistro.security import passwords

            with mock.patch.object(
                passwords, "verify_password", wraps=passwords.verify_password
            ) as spy:
                _login(_client(), "definitely-not-a-user")

        assert spy.call_count == 1, "an unknown account skipped the password check"

    def test_the_route_no_longer_short_circuits_on_the_username(self) -> None:
        """Read from the source, because the defect was the *shape* of the
        expression: `username == x and verify_password(...)` never calls the
        right-hand side for a miss, and no amount of adding calls elsewhere
        fixes that."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "routes" / "auth.py").read_text(
            encoding="utf-8"
        )
        login = source[source.index('@router.post("/login")') :]
        login = login[: login.index('@router.post("/logout")')]
        # Comments stripped first: this route's comment *quotes* the old
        # expression to explain what was wrong with it, and a naive substring
        # check matches the explanation rather than the code. (It did.)
        code = "\n".join(line for line in login.splitlines() if not line.lstrip().startswith("#"))

        assert "and user.verify_password" not in code
        assert "equal_cost_verify" in code


class TestLoginIsBounded:
    def test_repeated_failures_are_eventually_refused(self) -> None:
        client = _client()
        statuses = [_login(client, "testuser").status_code for _ in range(15)]

        assert 429 in statuses, "unbounded login attempts against one account"

    def test_the_refusal_says_nothing_about_which_limit(self) -> None:
        """ "You hit the per-account limit" confirms the account is real."""
        client = _client()
        for _ in range(15):
            response = _login(client, "testuser")
            if response.status_code == 429:
                break

        body = response.json()["detail"].lower()
        assert "account" not in body
        assert "client" not in body
        assert "ip" not in body

    def test_a_refusal_tells_the_caller_when_to_come_back(self) -> None:
        """A 429 with no Retry-After is a client that retries immediately."""
        client = _client()
        for _ in range(15):
            response = _login(client, "testuser")
            if response.status_code == 429:
                break

        assert response.headers.get("Retry-After")

    def test_an_unknown_account_is_bounded_too(self) -> None:
        """Otherwise the enumeration budget is infinite even though each answer
        is uninformative."""
        client = _client()
        statuses = [_login(client, "nobody-at-all").status_code for _ in range(15)]

        assert 429 in statuses

    def test_a_successful_login_still_works_after_a_few_failures(self) -> None:
        """The limit must not lock out the person who simply mistyped. If it
        does, someone turns it off and then there is no limit."""
        client = _client()
        for _ in range(3):
            _login(client, "testuser")
        ok = _login(client, "testuser", "testpass")

        assert ok.status_code == 200


class TestRegistrationIsBoundedSeparately:
    def test_it_has_its_own_budget(self) -> None:
        """Registration hashes unconditionally and creates rows, so it is the
        same 64 MiB primitive plus a storage attack."""
        import routes.auth as auth

        assert auth._REGISTER_THROTTLE is not auth._LOGIN_THROTTLE

    def test_it_is_throttled_before_the_availability_check(self) -> None:
        """Checking first would let an attacker walk the user list at zero
        cost, since a 409 is a definitive "this account exists"."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "routes" / "auth.py").read_text(
            encoding="utf-8"
        )
        register = source[source.index('@router.post("/register")') :]
        register = register[: register.index('@router.post("/login")')]

        assert register.index("_enforce(") < register.index("_username_taken(")


class TestElevationIsBoundedOnTheSession:
    def test_it_has_its_own_budget(self) -> None:
        import routes.auth as auth

        assert auth._ELEVATE_THROTTLE is not auth._LOGIN_THROTTLE

    def test_it_is_keyed_on_the_session_not_the_account(self) -> None:
        """Two people are not sharing a session, and keying on the account
        would let one stolen session lock the real owner out of their others."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "routes" / "auth.py").read_text(
            encoding="utf-8"
        )
        elevate = source[source.index('@router.post("/elevate")') :]

        assert "_enforce(_ELEVATE_THROTTLE, request, hive_session" in elevate


class TestTheClientKeyCannotBeSpoofed:
    def test_a_forwarded_header_from_an_untrusted_peer_is_ignored(self) -> None:
        """Otherwise an attacker mints a fresh per-client budget per request by
        varying the header, which is the same as having no per-client limit.
        #369 established the trusted-proxy check; this is the second thing that
        needed it."""
        import routes.auth as auth

        class _Req:
            client = type("C", (), {"host": "203.0.113.9"})()
            headers: ClassVar[dict[str, str]] = {"x-forwarded-for": "10.0.0.1"}

        assert auth._client_key(_Req()) == "203.0.113.9"

    def test_a_forwarded_header_from_a_trusted_proxy_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import routes.auth as auth
        from config import get_settings

        monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.0/8")
        get_settings.cache_clear()
        try:

            class _Req:
                client = type("C", (), {"host": "10.1.2.3"})()
                headers: ClassVar[dict[str, str]] = {"x-forwarded-for": "203.0.113.9, 10.1.2.3"}

            assert auth._client_key(_Req()) == "203.0.113.9"
        finally:
            get_settings.cache_clear()

    def test_a_request_with_no_peer_shares_one_bounded_bucket(self) -> None:
        """A Unix socket has no peer address. An empty key per request would be
        an unbounded number of budgets; one shared bucket is bounded."""
        import routes.auth as auth

        class _Req:
            client = None
            headers: ClassVar[dict[str, str]] = {}

        assert auth._client_key(_Req()) == "unattributed"
