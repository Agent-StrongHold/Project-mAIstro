"""Bounded cost for anonymous authentication attempts (#366).

Two separate problems, both reachable without any credential.

**Argon2id is the DoS primitive.** The parameters this repo uses cost roughly
64 MiB and ~90 ms per verification — deliberately, because that is what makes a
stolen hash expensive to crack. Nothing bounded how many times an anonymous
caller could ask for one. A handful of concurrent login requests against a
*known* username is enough to make memory, not CPU, the thing that runs out.

**The cost itself leaked which usernames exist.** `login` read:

    for user in stores.users.values():
        if user.username == body.username and user.verify_password(...):

`and` short-circuits, so a username that matches nothing never reached Argon2 at
all. Measured on this machine: **87.6 ms for a known username with the wrong
password, ~0 ms for an unknown one.** That is not a subtle side channel needing
statistics to detect; it is a different order of magnitude, readable from one
request. `equal_cost_verify` below is the other half of the fix.

Why not `InMemoryRateLimiter`
-----------------------------
That one already exists and is the right shape for ordinary request throttling:
one key, requests per minute, a burst ceiling. Authentication needs a different
model and reusing it would have meant bending both:

* **Several scopes at once.** One attempt is charged to an IP *and* an account
  *and* a global ceiling; a distributed attack spreads across IPs but converges
  on one account, and a single-IP attack does the reverse. Checking one key
  catches neither reliably.
* **Failures, not requests.** A user who logs in successfully forty times is
  not attacking anything. The budget that matters is consecutive *failures*,
  which resets on success — a distinction a request counter cannot express.
* **A cost to charge, not just a verdict.** Progressive delay needs the failure
  history, not a boolean.

What "fail safe" means here
---------------------------
The AC asks limits to "fail safe during backend outage". Both readings are
wrong on their own: failing open removes the control exactly when someone is
attacking, and failing closed turns a cache outage into a total login outage —
a self-inflicted denial of service.

So the store is a seam, and a failure in it **degrades to the in-process
limiter** rather than to either extreme. A replica that has lost its shared
store still enforces a bound; it just enforces it per replica instead of
globally. That is strictly better than unlimited and strictly better than
refusing everyone, and it is what `ThrottleStore` exists to make explicit.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

#: Deliberately not "username". The value is whatever the caller *typed*, which
#: for an enumeration attempt is an account that does not exist — so it names an
#: attempt, not a user.
AccountKey = str


@dataclass(frozen=True)
class AuthLimits:
    """How much an anonymous caller may spend before being refused.

    The numbers are per *failure*, not per request, and are deliberately
    generous for a human: someone who genuinely forgot their password gets
    several tries before any delay is noticeable.
    """

    #: Consecutive failures from one client address before it is refused.
    per_client: int = 10
    #: Consecutive failures against one account, from anywhere. Lower than
    #: `per_client` because a distributed attack converges here.
    per_account: int = 5
    #: Failures across every account and address, in the same window. The
    #: backstop against a spread-out attack that stays under both limits above.
    global_failures: int = 200
    #: How long a failure is remembered.
    window_seconds: float = 900.0
    #: Longest a progressive delay will grow to. Capped because an unbounded
    #: delay holds a worker thread, which is a resource an attacker would then
    #: be exhausting instead.
    max_delay_seconds: float = 2.0


@dataclass(frozen=True)
class StricterLimits:
    """Registration and elevation, which the AC asks to bound separately.

    Registration creates state, so an unbounded stream of it is a storage
    attack rather than a guessing one. Elevation is only reachable with a valid
    session, so the bound exists to stop a *compromised* session grinding
    against a privilege check — a much smaller budget than login, because a
    legitimate user elevates rarely.
    """

    register: AuthLimits = field(
        default_factory=lambda: AuthLimits(per_client=5, per_account=3, global_failures=50)
    )
    elevate: AuthLimits = field(
        default_factory=lambda: AuthLimits(per_client=5, per_account=5, global_failures=50)
    )


@dataclass(frozen=True)
class Decision:
    """Whether an attempt may proceed, and what it costs.

    `delay_seconds` is applied whether or not the attempt is allowed, so a
    caller cannot tell a throttled account from an untouched one by how fast
    the refusal came back.
    """

    allowed: bool
    delay_seconds: float = 0.0
    #: Which limit ran out. For logs and metrics; never returned to the caller,
    #: because "you hit the per-account limit" confirms the account exists.
    reason: str = ""


class ThrottleStore(Protocol):
    """Where failure counts live.

    A Protocol so a deployment can put them in Redis and have limits hold
    across replicas — the AC's "durable/distributed". The in-process
    implementation below is what ships, and is also the documented degraded
    mode when a shared store is unreachable.
    """

    def record_failure(self, key: str, now: float) -> None: ...

    def count(self, key: str, since: float) -> int: ...

    def clear(self, key: str) -> None: ...


class InProcessThrottleStore:
    """Failure timestamps per key, pruned to the window on read.

    Bounded on purpose: `_MAX_KEYS` caps how many distinct keys are tracked, so
    an attacker cycling usernames or spoofing a header cannot turn the throttle
    itself into the memory exhaustion it exists to prevent. When the cap is hit
    the least recently touched keys go first.
    """

    _MAX_KEYS = 10_000

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}
        self._touched: dict[str, float] = {}

    def record_failure(self, key: str, now: float) -> None:
        self._evict_if_needed(now)
        self._failures.setdefault(key, deque()).append(now)
        self._touched[key] = now

    def count(self, key: str, since: float) -> int:
        window = self._failures.get(key)
        if not window:
            return 0
        while window and window[0] < since:
            window.popleft()
        if not window:
            # Drop the empty deque rather than leaving it: a key that has aged
            # out should stop occupying a slot in the cap above.
            self._failures.pop(key, None)
            self._touched.pop(key, None)
            return 0
        return len(window)

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)
        self._touched.pop(key, None)

    def _evict_if_needed(self, now: float) -> None:
        if len(self._failures) < self._MAX_KEYS:
            return
        oldest = sorted(self._touched.items(), key=lambda item: item[1])
        for key, _ in oldest[: self._MAX_KEYS // 10]:
            self.clear(key)


class AuthThrottle:
    """The policy. Ask before doing the work; report what happened after.

    Deliberately two calls rather than one. The expensive part is the Argon2
    verification between them, and the throttle has to be consulted *before*
    that cost is incurred — a limiter that runs afterwards has already paid
    for the attack it was meant to prevent.
    """

    _GLOBAL_KEY = "\x00global"

    def __init__(
        self, limits: AuthLimits | None = None, store: ThrottleStore | None = None
    ) -> None:
        self._limits = limits or AuthLimits()
        self._store = store or InProcessThrottleStore()

    def check(self, *, client_key: str, account: AccountKey, now: float | None = None) -> Decision:
        """Whether this attempt may proceed, and how long to wait first."""
        at = time.monotonic() if now is None else now
        since = at - self._limits.window_seconds

        client_failures = self._store.count(self._client_key(client_key), since)
        account_failures = self._store.count(self._account_key(account), since)
        global_failures = self._store.count(self._GLOBAL_KEY, since)

        # The delay is driven by the worst scope, and is applied to allowed
        # attempts too — so the time an answer takes says nothing about which
        # limit, if any, this attempt is near.
        delay = self._delay_for(max(client_failures, account_failures))

        if global_failures >= self._limits.global_failures:
            return Decision(allowed=False, delay_seconds=delay, reason="global")
        if client_failures >= self._limits.per_client:
            return Decision(allowed=False, delay_seconds=delay, reason="client")
        if account_failures >= self._limits.per_account:
            return Decision(allowed=False, delay_seconds=delay, reason="account")
        return Decision(allowed=True, delay_seconds=delay)

    def record_failure(
        self, *, client_key: str, account: AccountKey, now: float | None = None
    ) -> None:
        at = time.monotonic() if now is None else now
        self._store.record_failure(self._client_key(client_key), at)
        self._store.record_failure(self._account_key(account), at)
        self._store.record_failure(self._GLOBAL_KEY, at)

    def record_success(self, *, client_key: str, account: AccountKey) -> None:
        """Forget this client's and this account's failures.

        Only the two specific keys, never the global counter: a successful
        login somewhere must not reset the backstop that a spread-out attack is
        filling up, or an attacker with one valid account could keep it at zero
        indefinitely.
        """
        self._store.clear(self._client_key(client_key))
        self._store.clear(self._account_key(account))

    def _delay_for(self, failures: int) -> float:
        """Progressive, capped, and starting at zero.

        No delay until a few failures have accumulated, so an ordinary typo
        costs nothing. Doubling after that, because the point is to make
        *sustained* guessing expensive rather than to punish a mistake. Capped
        so the delay cannot itself become the resource being exhausted.
        """
        if failures < 3:
            return 0.0
        return min(0.1 * (2.0 ** (failures - 3)), self._limits.max_delay_seconds)

    @staticmethod
    def _client_key(client_key: str) -> str:
        return f"c:{client_key}"

    @staticmethod
    def _account_key(account: AccountKey) -> str:
        # Case-folded: `Alice` and `alice` are one account to any sane lookup,
        # and treating them as two keys would double an attacker's budget for
        # free.
        return f"a:{account.strip().casefold()}"


__all__ = [
    "AccountKey",
    "AuthLimits",
    "AuthThrottle",
    "Decision",
    "InProcessThrottleStore",
    "StricterLimits",
    "ThrottleStore",
]
