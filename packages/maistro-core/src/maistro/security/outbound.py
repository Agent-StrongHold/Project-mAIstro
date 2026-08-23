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

Allowed origins are seeded from settings — the LiteLLM base, the Ollama base,
the ntfy base, a Home Assistant URL handed to its client — rather than from a
hand-maintained list, so moving a gateway moves its allowance with it instead
of leaving a stale entry behind and a working deployment broken.

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

Known limitations, stated rather than implied
---------------------------------------------
* **Proxy mounts.** A client configured to reach the internet through an HTTP
  proxy sends matching requests through httpx's own proxy transport, which this
  seam does not wrap. Deployments that egress via a proxy are not covered here.
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

from maistro.security.ssrf import avalidate_outbound_url

#: Ports that need not be written out, so `http://host` and `http://host:80`
#: are one origin rather than two.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def outbound_origin(url: str) -> str:
    """The `scheme://host:port` an allowance is compared on.

    Normalised: lowercased, default port made explicit. Path, query, userinfo
    and fragment are dropped — an allowance is about *where* a request goes,
    and matching on anything longer would let a crafted path widen it.
    """
    parts = urlsplit(url)
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
        await enforce_outbound_policy(str(request.url))
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
    "OutboundPolicy",
    "configure_outbound_policy",
    "configured_endpoints",
    "current_outbound_policy",
    "enforce_outbound_policy",
    "guarded",
    "outbound_origin",
    "reset_outbound_policy",
]
