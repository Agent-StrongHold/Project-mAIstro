"""One outbound policy, applied where the connection is actually made (#155).

The decision this implements is ADR-082326-5386.

#154 gave the engine a single SSRF validator. It reached three of the
twenty-five modules in `maistro-core` that issue an outbound HTTP request,
because it is a function every call site has to remember to call — and
twenty-two did not. A control you must remember to apply is a control that is
not applied; the 3-of-25 count is what that costs, measured.

Nearly all of those modules already route through `maistro.http.shared_client`,
so there is one seam that reaches them at once. This module is the policy layer
at that seam.

Why it is default-on with an allowlist
--------------------------------------
The obvious alternative is to guard only *caller-influenced* URLs — the ones an
agent or a manifest chose — and leave configured endpoints alone. The seam
cannot implement that, and the reason is worth stating plainly: **a transport
sees a URL and nothing about its provenance.** By the time a request reaches
here, "the operator configured this" and "a tool call named this" are the same
string. Any policy that depends on telling them apart has to be enforced at the
call sites, which is exactly the arrangement that produced 3-of-25.

So the guard is on for everything, and the *configured* destinations are named:
an origin the deployment actually configured is allowed, everything else is
validated. That inverts the failure mode. Forgetting to allow a real endpoint
is a refusal on the first request, loud and immediate; forgetting to guard a
call site is a hole nobody sees. Only one of those is safe to get wrong.

Where allowances come from
--------------------------
Two places, and both are derived rather than listed here, so moving a gateway
moves its allowance with it instead of leaving a stale entry behind and a
working deployment broken:

* `configured_endpoints(settings)` reads the endpoints a settings object names
  — the LiteLLM base, the Ollama base, the ntfy base, the task progress
  webhook — and the container and the server pass it at startup.
* A client whose endpoint is **not** in settings registers its own origin when
  it is constructed, because that is the only place the URL exists.
  `HomeAssistantIntegration` takes its URL as a constructor argument
  (defaulting to `http://localhost:8123`), and `OAuthService` takes a provider
  map that may name a self-hosted issuer; both call
  `configure_outbound_policy` in `__init__`. Without that, a real Home
  Assistant request is refused on a deployment that never touched settings —
  and the refusal hides behind `MockTransport` in the tests, which is how it
  went unnoticed the first time.

What an allowance does and does not widen
-----------------------------------------
An allowed entry is a full origin: scheme, host and port, compared exactly
after normalising the default port. `http://127.0.0.1:4000` allows that
gateway and nothing else — not `127.0.0.1:8080`, not another RFC1918 address,
not `https://` to the same host. It is not "allow private addresses"; it is
"allow this endpoint", which is the narrowest thing that still lets the engine
talk to its own LLM.

Redirects
---------
httpx re-enters the transport for every hop, so a chain that starts at a public
URL and lands on a private one is validated at the hop that matters, with no
call-site change. That is the main reason the policy lives at the transport
rather than in `shared_client`'s wrapper.

Proxies
-------
A deployment that egresses through an HTTP proxy is guarded and still reaches
its proxy. `maistro.http` lets httpx build its own proxy mounts from
`HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` and then wraps each of them, rather than
handing httpx a pre-built transport — which would have switched the environment
proxy lookup off entirely and left those deployments with no egress at all.
See `_guard_built_transports` for why the wrapping happens after construction.

Known limitations, stated rather than implied
---------------------------------------------
* **The rebinding window** #154 described is unchanged: this guard resolves the
  name and httpx resolves it again to connect. Pinning the resolved address
  into the connection is a deeper change and is still not done.
* **A transport that fabricates responses is not guarded**, because it opens no
  socket — `httpx.MockTransport` is how the whole test suite avoids the
  network. Nothing in production can install one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from maistro.security.ssrf import SSRFBlockedError, avalidate_outbound_url

#: Ports that need not be written out, so `http://host` and `http://host:80`
#: are one origin rather than two.
_DEFAULT_PORTS = {"http": 80, "https": 443}


class OutboundBlockedError(SSRFBlockedError, httpx.TransportError):
    """A refusal that satisfies both contracts the callers already rely on.

    `SSRFBlockedError` derives from `ToolError`. That is right for a call site
    that asked the guard a question directly, and wrong for one that only ever
    sees the guard through an `httpx.AsyncClient` — because those call sites
    catch what a client is documented to raise::

        except httpx.HTTPError:      # OAuth token exchange -> OAuthExchangeError
        except httpx.TransportError: # HTTP harness -> HarnessUnavailableError

    Moving the guard into the transport put a `ToolError` on a path where those
    handlers stand, so a refusal escaped them: the OAuth exchange lost its
    typed error, the harness lost its fallback, and the quota CLI lost its exit
    code. None of them are wrong to catch what they catch — the transport is
    wrong to raise something a transport cannot raise.

    Inheriting from both fixes it without asking every caller to learn a new
    exception: `except SSRFBlockedError` still catches this, and so does
    `except httpx.TransportError`. The MRO is well-formed because `AgentError`
    and `httpx.HTTPError` are siblings under `Exception`, and
    `AgentError.__init__`'s `super().__init__(message)` lands on
    `httpx.RequestError.__init__`, which takes exactly that positional message.
    """

    def __init__(
        self, detail: str = "", *, request: httpx.Request | None = None, reason: str = ""
    ) -> None:
        super().__init__(detail, reason=reason)
        if request is not None:
            # httpx's own property setter rather than the private attribute
            # behind it, so `.request` stays exactly the accessor httpx
            # documents. `RequestError.__init__` has already defaulted it to
            # `None`, which is what a caller that has no request gets.
            self.request = request


def outbound_origin(url: str) -> str:
    """The `scheme://host:port` an allowance is compared on.

    Normalised: lowercased, default port made explicit. Path, query, userinfo
    and fragment are dropped — an allowance is about *where* a request goes,
    and matching on anything longer would let a crafted path widen it.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        # Unparseable — `http://[::1` and friends. This function is called to
        # *describe* a refusal, so it must never be the thing that fails: it
        # raised `ValueError: Invalid IPv6 URL` from inside the handler that had
        # already correctly refused the same URL, and the exception escaped
        # (#430).
        #
        # A sentinel rather than an empty string, for the same reason the port
        # branch below returns one: this value is compared against configured
        # allowances, and an origin nobody can parse must never compare equal to
        # one an operator authorized. `://` cannot appear in a real origin, so
        # nothing can be configured that matches it.
        return "unparseable://:invalid"
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        # A malformed port is not an origin. Return something that matches no
        # allowance, so the URL falls through to validation and is refused
        # there with a message about its shape.
        return f"{scheme}://{host}:invalid"
    return f"{scheme}://{host}:{port or _DEFAULT_PORTS.get(scheme, 0)}"


@dataclass(frozen=True)
class OutboundPolicy:
    """Which origins this deployment reaches without validation.

    The field is `origins`, not `allowed_origins`: vulture matches identities by
    name rather than by owner, so a field named the same as
    `Settings.allowed_origins` would have retired that unrelated entry from the
    dead-code ledger the moment this one was read.
    """

    origins: frozenset[str] = frozenset()

    def allows(self, url: str) -> bool:
        """Whether `url` names a configured endpoint, exactly."""
        return outbound_origin(url) in self.origins

    def with_origins(self, urls: Iterable[str]) -> OutboundPolicy:
        """This policy plus the origins of `urls`. Empty strings are ignored.

        Ignoring empties is what lets a caller pass every optional endpoint it
        knows about — `settings.ntfy.base_url` is often unset — without each
        one needing its own conditional at the wiring site.
        """
        added = {outbound_origin(u) for u in urls if u and u.strip()}
        return OutboundPolicy(origins=self.origins | added)


_policy = OutboundPolicy()


def configure_outbound_policy(*urls: str) -> OutboundPolicy:
    """Allow the origins of `urls`, in addition to any already allowed.

    Additive on purpose: the LLM gateway is configured in one place and a Home
    Assistant URL is handed to its client somewhere else entirely, so a
    replacing setter would have the second caller silently revoke the first.
    """
    global _policy
    _policy = _policy.with_origins(urls)
    return _policy


def current_outbound_policy() -> OutboundPolicy:
    """The policy in force."""
    return _policy


def reset_outbound_policy() -> None:
    """Forget every allowance. For tests, and for a process reconfiguring."""
    global _policy
    _policy = OutboundPolicy()


def configured_endpoints(settings: object) -> list[str]:
    """Every endpoint a settings object says this deployment talks to.

    Read off the settings rather than listed here, so moving a gateway moves
    its allowance with it instead of leaving a stale entry and a broken
    deployment. Attributes are fetched defensively because the two settings
    objects in this repo — `maistro.config.settings.Settings` and
    `maistro.types.config.AgentConfig` — carry overlapping but different
    fields, and an optional endpoint that is unset should not need its own
    conditional at every wiring site.
    """
    litellm = getattr(settings, "litellm", None)
    ntfy_settings = getattr(settings, "ntfy", None)
    return [
        str(getattr(settings, "litellm_url", "") or ""),
        str(getattr(litellm, "base_url", "") or ""),
        str(getattr(settings, "ollama_base_url", "") or ""),
        str(getattr(ntfy_settings, "base_url", "") or ""),
        str(getattr(settings, "maistro_base_url", "") or ""),
        # Configured in the same breath as the LLM base and just as likely to
        # be an address on the operator's own network — a receiver on the
        # legacy conductor-router host is the usual case. Left out, the first
        # task progress POST of a real deployment is refused.
        str(getattr(settings, "task_progress_webhook_url", "") or ""),
    ]


async def enforce_outbound_policy(url: str) -> None:
    """Raise `SSRFBlockedError` unless `url` may be reached.

    A configured origin is reached without a lookup, which is also what keeps
    the engine's own LLM traffic off the resolver on every single call.
    """
    if _policy.allows(url):
        return
    await avalidate_outbound_url(url)


class GuardedTransport(httpx.AsyncBaseTransport):
    """Applies the outbound policy to every request, including redirect hops."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    @property
    def inner(self) -> httpx.AsyncBaseTransport:
        """The transport that does the work. Read by tests and by `guarded`."""
        return self._inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            await enforce_outbound_policy(str(request.url))
        except SSRFBlockedError as exc:
            # Re-raised as the dual-contract error so the handlers that already
            # stand on this path keep working — see `OutboundBlockedError`. The
            # translation belongs here rather than in `enforce_outbound_policy`,
            # which is also called directly by code that is not inside a client
            # and has no reason to see an httpx type.
            raise OutboundBlockedError(exc.detail, request=request, reason=exc.reason) from exc
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def guarded(transport: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
    """`transport` with the outbound policy in front of it.

    Returned unchanged for a transport that fabricates responses: there is no
    socket to guard, and wrapping it would make the test suite's fake hosts
    unreachable while protecting nothing. Already-guarded transports are
    returned unchanged too, so wrapping twice cannot double the resolver cost.
    """
    if isinstance(transport, httpx.MockTransport | GuardedTransport):
        return transport
    return GuardedTransport(transport)


__all__ = [
    "GuardedTransport",
    "OutboundBlockedError",
    "OutboundPolicy",
    "configure_outbound_policy",
    "configured_endpoints",
    "current_outbound_policy",
    "enforce_outbound_policy",
    "guarded",
    "outbound_origin",
    "reset_outbound_policy",
]
