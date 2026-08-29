"""Bounded cost for anonymous authentication attempts (#366).

Argon2id costs ~64 MiB and ~90 ms per verification, deliberately — that is what
makes a stolen hash expensive to crack. Nothing bounded how many times an
anonymous caller could ask for one.

These drive the policy directly. `hive-conductor`'s
`tests/test_auth_throttle_routes.py` drives it through the real endpoints,
because a correct policy nothing calls is the shape #257 was filed about.
"""

from __future__ import annotations

import pytest

from maistro.security.auth_throttle import (
    AuthLimits,
    AuthThrottle,
    InProcessThrottleStore,
    StricterLimits,
)


def _throttle(**overrides) -> AuthThrottle:
    return AuthThrottle(AuthLimits(**overrides))


class TestAnAttemptIsChargedToEveryScopeAtOnce:
    """A distributed attack spreads across addresses but converges on one
    account; a single-address attack does the reverse. One key catches
    neither reliably."""

    def test_one_client_is_cut_off_after_its_budget(self) -> None:
        throttle = _throttle(per_client=3, per_account=99, global_failures=99)
        for _ in range(3):
            throttle.record_failure(client_key="1.2.3.4", account=f"acct{_}")

        assert not throttle.check(client_key="1.2.3.4", account="anything").allowed

    def test_another_client_is_unaffected(self) -> None:
        """Per-client means per client. Cutting everyone off because one
        address misbehaved is the account-denial the AC warns about, one level
        up."""
        throttle = _throttle(per_client=3, per_account=99, global_failures=99)
        for i in range(3):
            throttle.record_failure(client_key="1.2.3.4", account=f"acct{i}")

        assert throttle.check(client_key="5.6.7.8", account="anything").allowed

    def test_one_account_is_cut_off_across_every_client(self) -> None:
        """The distributed case: each address stays well under its own budget,
        and they all converge on one account."""
        throttle = _throttle(per_client=99, per_account=3, global_failures=99)
        for i in range(3):
            throttle.record_failure(client_key=f"10.0.0.{i}", account="victim")

        assert not throttle.check(client_key="10.0.0.99", account="victim").allowed

    def test_another_account_is_unaffected(self) -> None:
        throttle = _throttle(per_client=99, per_account=3, global_failures=99)
        for i in range(3):
            throttle.record_failure(client_key=f"10.0.0.{i}", account="victim")

        assert throttle.check(client_key="10.0.0.99", account="someone-else").allowed

    def test_the_global_backstop_catches_what_slips_under_both(self) -> None:
        """Spread thin enough — a fresh address and a fresh account each time —
        and neither of the limits above ever fires. This is why there is a
        third."""
        throttle = _throttle(per_client=5, per_account=5, global_failures=10)
        for i in range(10):
            throttle.record_failure(client_key=f"10.0.0.{i}", account=f"acct{i}")

        decision = throttle.check(client_key="10.0.0.250", account="fresh")
        assert not decision.allowed
        assert decision.reason == "global"

    def test_the_global_limit_is_checked_before_the_narrower_ones(self) -> None:
        """So a report says the widest thing that is true. A defender reading
        "client" when the whole system is saturated would chase one address."""
        throttle = _throttle(per_client=1, per_account=1, global_failures=1)
        throttle.record_failure(client_key="1.2.3.4", account="acct")

        assert throttle.check(client_key="1.2.3.4", account="acct").reason == "global"


class TestFailuresAreCountedNotRequests:
    def test_a_successful_attempt_clears_the_client_and_the_account(self) -> None:
        """Someone who logs in successfully forty times is not attacking
        anything. A request counter cannot express that."""
        throttle = _throttle(per_client=3, per_account=3)
        for _ in range(2):
            throttle.record_failure(client_key="1.2.3.4", account="alice")
        throttle.record_success(client_key="1.2.3.4", account="alice")
        for _ in range(2):
            throttle.record_failure(client_key="1.2.3.4", account="alice")

        assert throttle.check(client_key="1.2.3.4", account="alice").allowed

    def test_a_success_does_not_clear_the_global_backstop(self) -> None:
        """Otherwise an attacker holding one valid account could reset the
        backstop indefinitely by logging into it between guesses."""
        throttle = _throttle(per_client=99, per_account=99, global_failures=3)
        for i in range(3):
            throttle.record_failure(client_key=f"10.0.0.{i}", account=f"acct{i}")
        throttle.record_success(client_key="10.0.0.1", account="acct1")

        assert not throttle.check(client_key="10.0.0.200", account="fresh").allowed

    def test_failures_age_out_of_the_window(self) -> None:
        """A lockout that never lifts is an account-denial primitive."""
        throttle = _throttle(per_client=2, window_seconds=100.0)
        throttle.record_failure(client_key="1.2.3.4", account="alice", now=0.0)
        throttle.record_failure(client_key="1.2.3.4", account="alice", now=1.0)

        assert not throttle.check(client_key="1.2.3.4", account="alice", now=50.0).allowed
        assert throttle.check(client_key="1.2.3.4", account="alice", now=200.0).allowed

    def test_an_account_is_matched_case_insensitively(self) -> None:
        """`Alice` and `alice` are one account to any sane lookup. Two keys
        would double an attacker's budget for free."""
        throttle = _throttle(per_account=2, per_client=99)
        throttle.record_failure(client_key="1.2.3.4", account="Alice")
        throttle.record_failure(client_key="5.6.7.8", account="  ALICE  ")

        assert not throttle.check(client_key="9.9.9.9", account="alice").allowed


class TestTheDelayIsProgressiveCappedAndUninformative:
    def test_an_ordinary_typo_costs_nothing(self) -> None:
        """Delay starts at zero. Punishing a mistake buys no security and
        every real user makes them."""
        throttle = _throttle()
        for _ in range(2):
            throttle.record_failure(client_key="1.2.3.4", account="alice")

        assert throttle.check(client_key="1.2.3.4", account="alice").delay_seconds == 0.0

    def test_it_grows_with_sustained_guessing(self) -> None:
        throttle = _throttle(per_client=99, per_account=99)
        delays = []
        for _ in range(8):
            throttle.record_failure(client_key="1.2.3.4", account="alice")
            delays.append(throttle.check(client_key="1.2.3.4", account="alice").delay_seconds)

        assert delays == sorted(delays)
        assert delays[-1] > delays[0]

    def test_it_is_capped(self) -> None:
        """An unbounded delay holds a worker, which is the resource an attacker
        would then be exhausting instead."""
        throttle = _throttle(per_client=999, per_account=999, max_delay_seconds=1.5)
        for _ in range(40):
            throttle.record_failure(client_key="1.2.3.4", account="alice")

        assert throttle.check(client_key="1.2.3.4", account="alice").delay_seconds == 1.5

    def test_a_refused_attempt_still_carries_the_delay(self) -> None:
        """The delay is what an allowed and a refused attempt have in common,
        so response time never says which limit a caller is near."""
        throttle = _throttle(per_client=4, per_account=99)
        for _ in range(4):
            throttle.record_failure(client_key="1.2.3.4", account="alice")
        decision = throttle.check(client_key="1.2.3.4", account="alice")

        assert not decision.allowed
        assert decision.delay_seconds > 0

    def test_an_untouched_account_and_a_throttled_one_are_told_apart_only_by_the_reason(
        self,
    ) -> None:
        """And `reason` never leaves the server — see the route's `_enforce`."""
        throttle = _throttle(per_account=2, per_client=99)
        throttle.record_failure(client_key="1.2.3.4", account="real")
        throttle.record_failure(client_key="1.2.3.4", account="real")

        refused = throttle.check(client_key="1.2.3.4", account="real")
        allowed = throttle.check(client_key="1.2.3.4", account="never-seen")

        assert refused.reason and not allowed.reason


class TestRegistrationAndElevationAreBoundedSeparately:
    def test_their_budgets_are_smaller_than_login(self) -> None:
        stricter = StricterLimits()
        default = AuthLimits()

        assert stricter.register.per_client < default.per_client
        assert stricter.elevate.per_client < default.per_client
        assert stricter.register.global_failures < default.global_failures

    def test_separate_throttles_do_not_share_a_budget(self) -> None:
        """Sharing state would let cheap registration attempts consume the
        budget a real login needs."""
        login = AuthThrottle(AuthLimits(per_client=2))
        register = AuthThrottle(StricterLimits().register)
        for _ in range(2):
            register.record_failure(client_key="1.2.3.4", account="alice")

        assert login.check(client_key="1.2.3.4", account="alice").allowed


class TestTheStoreCannotBecomeTheExhaustion:
    """A throttle that grows a key per attempt is the memory attack it exists
    to prevent, wearing a different hat."""

    def test_key_count_is_bounded(self) -> None:
        store = InProcessThrottleStore()
        for i in range(InProcessThrottleStore._MAX_KEYS + 500):
            store.record_failure(f"k{i}", now=float(i))

        assert len(store._failures) <= InProcessThrottleStore._MAX_KEYS

    def test_an_aged_out_key_stops_occupying_a_slot(self) -> None:
        store = InProcessThrottleStore()
        store.record_failure("k", now=0.0)

        assert store.count("k", since=100.0) == 0
        assert "k" not in store._failures

    def test_counting_an_unknown_key_is_zero_not_an_error(self) -> None:
        assert InProcessThrottleStore().count("never-seen", since=0.0) == 0

    def test_clearing_an_unknown_key_is_not_an_error(self) -> None:
        InProcessThrottleStore().clear("never-seen")


class TestTheDefaultsAreUsableByAHuman:
    """A limit that locks out a real person on their third try gets turned off,
    and then there is no limit."""

    def test_a_few_wrong_passwords_do_not_lock_anyone_out(self) -> None:
        throttle = AuthThrottle()
        for _ in range(4):
            throttle.record_failure(client_key="1.2.3.4", account="alice")

        assert throttle.check(client_key="1.2.3.4", account="alice").allowed

    def test_the_window_is_long_enough_to_matter(self) -> None:
        """A one-minute window against Argon2 is barely a limit: an attacker
        simply waits."""
        assert AuthLimits().window_seconds >= 300

    @pytest.mark.parametrize(
        "field", ["per_client", "per_account", "global_failures", "window_seconds"]
    )
    def test_every_limit_is_positive(self, field: str) -> None:
        """A zero would refuse everyone, which is the self-inflicted denial of
        service the AC warns against."""
        assert getattr(AuthLimits(), field) > 0
