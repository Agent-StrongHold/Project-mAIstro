"""Router-agnostic rate-limit pacer.

Keeps an automated LLM loop (RSI agent turns, evolve tournaments, batch jobs)
just under each provider's rate ceiling — never crossing into 429 territory,
which is what trips abuse revocation and wastes a cycle on a benched model.

Design (see docs/model-rate-limit-headers.md):

* **Header-driven by default.** Every response from Mistral / Cerebras / Groq
  carries rate-limit headers. The pacer reads them off the *response* — so it
  works behind any router that forwards headers (LiteLLM forwards upstream
  headers as ``llm_provider-*``), or against a provider directly. It does NOT
  configure the router.
* **Static-counter fallback** for providers with no response headers
  (OpenRouter: 1000 req/day shared account-wide, counted locally, reset at UTC
  midnight; Gemini: ~5 req/min configured).
* **On a 429** (window-edge race): honor ``retry-after`` / ``reset`` if present,
  else exponential backoff. Never tight-loop a 429 — that is the abuse pattern.

The pacer wraps an async LLM-call callable: it sleeps *before* a call predicted
to cross the limit, and parses headers *after* each call to refresh its view.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Try the upstream-grounded (llm_provider-) variant first, then the gateway's
# normalized variant. Order matters: the upstream counter is the real one.
_TOKENS_REMAINING = [
    "llm_provider-x-ratelimit-remaining-tokens-minute",
    "llm_provider-x-ratelimit-remaining-tokens",
    "x-ratelimit-remaining-tokens",
]
_REQUESTS_REMAINING = [
    "llm_provider-x-ratelimit-remaining-req-minute",
    "llm_provider-x-ratelimit-remaining-requests-minute",
    "llm_provider-x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-requests",
]
_TOKENS_LIMIT = [
    "llm_provider-x-ratelimit-limit-tokens-minute",
    "llm_provider-x-ratelimit-limit-tokens",
    "x-ratelimit-limit-tokens",
]
_RESET = [
    "llm_provider-x-ratelimit-reset-tokens",
    "llm_provider-x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "x-ratelimit-reset-requests",
    "retry-after",
]


def _first(headers: dict[str, str], names: list[str]) -> str | None:
    for n in names:
        # headers are case-insensitive in practice; do a lowercase scan
        for k, v in headers.items():
            if k.lower() == n.lower() and v not in (None, ""):
                return v
    return None


@dataclass
class RateSnapshot:
    """The live rate-limit view parsed off one response (None where absent)."""

    remaining_tokens: float | None = None
    remaining_requests: float | None = None
    limit_tokens: float | None = None
    reset_seconds: float | None = None

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> RateSnapshot | None:
        rt = _first(headers, _TOKENS_REMAINING)
        rr = _first(headers, _REQUESTS_REMAINING)
        lt = _first(headers, _TOKENS_LIMIT)
        rs = _first(headers, _RESET)
        if rt is None and rr is None and rs is None:
            return None  # no rate-limit signal on this response
        snap = cls()
        try:
            if rt is not None:
                snap.remaining_tokens = float(rt)
            if rr is not None:
                snap.remaining_requests = float(rr)
            if lt is not None:
                snap.limit_tokens = float(lt)
            if rs is not None:
                snap.reset_seconds = _parse_duration(rs)
        except ValueError:
            pass
        return snap


_DURATION_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def _as_float(s: str) -> float | None:
    """float(s), or None when it isn't a number."""
    try:
        return float(s)
    except ValueError:
        return None


def _parse_clock_duration(s: str) -> float | None:
    """Sum a '1m26.4s' / '1h2m' unit run, falling back to bare seconds.

    Malformed numerals ('47..', '.') yield None rather than raising — these come
    off untrusted Retry-After/reset headers, and the declared contract is
    ``float | None``. The previous inline version let ValueError escape.
    """
    total = 0.0
    rest = s
    had_unit = False
    while rest and (rest[0].isdigit() or rest[0] == "."):
        i = 0
        while i < len(rest) and (rest[i].isdigit() or rest[i] == "."):
            i += 1
        unit = rest[i] if i < len(rest) else ""
        mult = _DURATION_UNITS.get(unit)
        if mult is None:
            # Trailing run carrying no recognised unit — read it as bare seconds.
            return _as_float(rest)
        # _as_float, not float(): a header like "47..s" or ".s" is malformed
        # input off the wire, and the docstring above promised None for it while
        # this line raised ValueError — the 429 retry path calls this outside
        # any exception handler, so a hostile header aborted the paced call.
        numeral = _as_float(rest[:i]) if i else 0.0
        if numeral is None:
            return None
        total += numeral * mult
        had_unit = True
        rest = rest[i + 1 :]
    return total if had_unit else _as_float(s)  # bare seconds / epoch


def _parse_duration(s: str) -> float | None:
    """Parse a reset/retry-after value: '1m26.4s', '562ms', or bare seconds."""
    s = s.strip().lower()
    if not s:
        return None
    if s.endswith("ms"):
        ms = _as_float(s[:-2])
        return None if ms is None else ms / 1000.0
    return _parse_clock_duration(s)


@dataclass
class StaticBudget:
    """Local counter for providers with no response headers (OpenRouter, Gemini).

    ``limit`` requests per ``window_seconds``; decremented per call; when
    exhausted the pacer sleeps until the window rolls over. OpenRouter free
    tier: limit=1000, window=86400 (UTC day).
    """

    limit: int
    window_seconds: int
    _remaining: float = field(init=False)
    _window_end: float = field(init=False)

    def __post_init__(self) -> None:
        self._remaining = float(self.limit)
        self._window_end = self._next_window_end()

    def _next_window_end(self) -> float:
        if self.window_seconds >= 86400:
            # align to UTC midnight for daily budgets
            now = datetime.now(UTC)
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return midnight.timestamp()
        return time.monotonic() + self.window_seconds

    def consume(self) -> None:
        now = time.time() if self.window_seconds >= 86400 else time.monotonic()
        if now >= self._window_end:
            self._remaining = float(self.limit)
            self._window_end = self._next_window_end()
        self._remaining -= 1.0

    def wait_seconds(self) -> float:
        if self._remaining > 0:
            return 0.0
        now = time.time() if self.window_seconds >= 86400 else time.monotonic()
        return max(0.0, self._window_end - now)


# well-known header-less providers → their static budgets
_STATIC_BUDGETS = {
    "openrouter": StaticBudget(limit=1000, window_seconds=86400),  # 1000/day shared
}


@dataclass
class RatePacer:
    """Wraps an async LLM call so the caller stays under the provider ceiling.

    Parameters:
        provider_key: lowercase provider hint (e.g. "mistral", "openrouter")
            — selects a StaticBudget fallback when no headers are present.
        token_floor: pause if parsed remaining-tokens would drop below this
            fraction of the limit (default 0.10). Parsed headers win over the
            static budget when present.
        request_floor: same, for remaining-requests.
        min_sleep / max_sleep: clamp on a paced wait.
    """

    provider_key: str = ""
    token_floor: float = 0.10
    request_floor: float = 0.10
    min_sleep: float = 0.5
    max_sleep: float = 65.0
    _last: RateSnapshot | None = field(default=None, repr=False)

    def _budget(self) -> StaticBudget | None:
        return _STATIC_BUDGETS.get(self.provider_key)

    # Hard ceiling on one throttle wait: a daily budget resets within 24h, and
    # anything longer can only come from a hostile/garbage reset header.
    _MAX_TOTAL_WAIT_S = 90_000.0

    def _required_wait(self) -> float:
        snap = self._last
        wait = 0.0
        if snap is not None:
            # pause if the next call is predicted to cross the token or request floor
            if (
                snap.remaining_tokens is not None
                and snap.limit_tokens
                and snap.remaining_tokens <= self.token_floor * snap.limit_tokens
            ):
                wait = max(wait, snap.reset_seconds or 60.0)
            if snap.remaining_requests is not None and snap.remaining_requests <= 1:
                wait = max(wait, snap.reset_seconds or 60.0)
        if wait == 0.0:
            bud = self._budget()
            if bud is not None:
                wait = bud.wait_seconds()
        return min(wait, self._MAX_TOTAL_WAIT_S)

    async def _throttle_before(self) -> None:
        wait = self._required_wait()
        if wait <= 0:
            return
        # Honor the FULL wait, sleeping in max_sleep chunks. The old clamp
        # slept at most max_sleep once and then unconditionally sent: with an
        # exhausted daily budget (reset at UTC midnight) that meant a request
        # every 65 seconds until midnight, each one a fresh 429 — the exact
        # behavior the pacer exists to prevent. The deadline is fixed up front
        # (header snapshots don't tick down), the budget is re-consulted each
        # chunk (it recomputes from wall clock and may extend).
        snap = self._last
        wait = max(self.min_sleep, wait)
        deadline = time.monotonic() + wait
        # False positive: the rule keys off "tokens" in the format string.
        # These are LLM rate-limit quota counters (how many tokens/requests
        # remain in the window) and a provider key name — no credential is
        # in scope here, let alone logged. The suppression must sit on the
        # line immediately before the match; semgrep ignores it otherwise.
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
        logger.info(
            "rate_pacer throttle provider=%s sleeping %.1fs (remaining_tokens=%s remaining_requests=%s)",
            self.provider_key,
            wait,
            snap.remaining_tokens if snap else None,
            snap.remaining_requests if snap else None,
        )
        while True:
            remaining = deadline - time.monotonic()
            bud = self._budget()
            if bud is not None:
                remaining = max(remaining, min(bud.wait_seconds(), self._MAX_TOTAL_WAIT_S))
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, self.max_sleep))

    def _observe(self, headers: dict[str, str] | None, status_code: int) -> None:
        if headers:
            snap = RateSnapshot.from_headers(headers)
            if snap is not None:
                self._last = snap
        bud = self._budget()
        if bud is not None and status_code < 400:
            bud.consume()

    async def call(
        self,
        llm_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call ``llm_fn`` with pacing. The callable must return an object with
        ``.headers`` (httpx.Response-style) and ``.status_code``; or be a raw
        dict carrying ``_rate_headers`` / ``status_code`` (test harness)."""
        backoff = 1.0
        for _ in range(6):  # bounded retry on 429 with backoff (never tight-loop)
            await self._throttle_before()
            resp = await llm_fn(*args, **kwargs)
            headers = getattr(resp, "headers", None) or (
                kwargs.get("_rate_headers") if isinstance(resp, dict) else None
            )
            status = getattr(resp, "status_code", None) or (
                resp.get("status_code") if isinstance(resp, dict) else 200
            )
            code = int(status) if status is not None else 200
            self._observe(headers, code)
            if code == 429:
                snap = self._last
                retry = (
                    snap.reset_seconds
                    if snap and snap.reset_seconds
                    else _parse_duration(
                        _first(headers or {}, ["retry-after", "x-ratelimit-reset-requests"]) or ""
                    )
                )
                sleep = retry if retry else backoff
                logger.warning(
                    "rate_pacer 429 provider=%s backing off %.1fs", self.provider_key, sleep
                )
                await asyncio.sleep(min(sleep, self.max_sleep))
                backoff = min(backoff * 2, 30.0)
                continue
            return resp
        return resp  # exhausted retries; return last (caller decides)
