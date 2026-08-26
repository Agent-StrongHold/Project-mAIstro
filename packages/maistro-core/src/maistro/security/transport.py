"""Whether a request really arrived over TLS, and who is allowed to say so (#369).

Two middlewares — `hive-conductor`'s and `maistro-server`'s — each carried
their own copy of this:

    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",")[0].strip().lower() == "https"

The `request.url.scheme` half is fact: the ASGI server knows what it accepted.
The second half is a **claim by the client**, and nothing checked who was
making it. Any caller could send `X-Forwarded-Proto: https` to a plain-HTTP
deployment and be told, in the response, that the origin is HSTS-eligible for
two years including subdomains. A header a browser will not send is not much
of an attack on its own; a header that decides a security control, accepted
from anyone, is a control that is not enforced.

`X-Forwarded-Proto` is only meaningful when a reverse proxy you run set it. So
it is read only when the immediate peer — the address the socket is actually
connected to — is one the deployment named as a proxy. Nothing named means
nothing trusted, which is the safe direction to get wrong: a deployment that
forgets to configure its proxy loses HSTS and keeps its cookies, rather than
gaining a header anyone can forge.

Why the *immediate* peer rather than the header chain
-----------------------------------------------------
`X-Forwarded-For` can be appended to by anyone upstream, so walking it to find
"the real client" means trusting the very thing under test. The socket peer is
the one address in the request that a caller cannot choose. If a deployment
runs proxies in series, every hop that appends has to be listed — which is the
honest cost of the arrangement, not a limitation of this function.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from ipaddress import ip_address, ip_network
from typing import Any

#: The header a reverse proxy sets to report the scheme it terminated.
FORWARDED_PROTO_HEADER = "x-forwarded-proto"


class InsecureTransportError(Exception):
    """A deployment is configured to send session cookies over plaintext."""


def parse_trusted_proxies(spec: str | Iterable[str] | None) -> tuple[Any, ...]:
    """Parse a comma-separated list of proxy addresses or CIDR blocks.

    A bare address is accepted and read as a single-host network, because
    `10.0.0.7` is what an operator writes and `10.0.0.7/32` is what they mean.
    An entry that does not parse is dropped rather than raising: one typo in a
    list of five proxies should cost that proxy's trust, not the process.
    """
    if not spec:
        return ()
    entries = spec.split(",") if isinstance(spec, str) else list(spec)
    networks = []
    for raw in entries:
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            networks.append(ip_network(candidate, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def is_trusted_proxy(client_host: str | None, trusted_networks: Iterable[Any]) -> bool:
    """Whether `client_host` is one of the addresses allowed to forward.

    An absent or unparseable peer is not trusted. That case is real rather
    than theoretical: a request over a Unix socket has no peer address, and
    a deployment behind such a socket has to name it some other way than by
    IP — so the honest answer here is "no", not "probably fine".

    The parameter is `trusted_networks`, not `trusted`: vulture matches
    identities by *name* rather than by owner, so naming it `trusted` retired
    an unrelated `trusted` in `maistro/code_registry/types.py` from the
    dead-code ledger the moment this one was read — marking a symbol that is
    still dead as alive. `OutboundPolicy.origins` carries the same note for
    the same reason; this is the second time the trap has been sprung, which
    is why it is written down again here rather than only there.
    """
    if not client_host:
        return False
    try:
        address = ip_address(client_host)
    except ValueError:
        return False
    return any(address in network for network in trusted_networks)


def request_is_https(
    *,
    scheme: str,
    headers: Mapping[str, str],
    client_host: str | None,
    trusted_proxies: Iterable[Any] = (),
) -> bool:
    """Whether this request really arrived over TLS.

    The ASGI scheme is believed unconditionally — the server accepted the
    connection and knows. `X-Forwarded-Proto` is believed only from a peer the
    deployment named, for the reason in the module docstring.
    """
    if scheme.lower() == "https":
        return True
    if not is_trusted_proxy(client_host, trusted_proxies):
        return False
    forwarded = headers.get(FORWARDED_PROTO_HEADER, "")
    # The leftmost value is the scheme the *first* proxy saw, which is the one
    # facing the browser. Later entries describe hops behind it.
    return forwarded.split(",")[0].strip().lower() == "https"


def assert_session_transport_is_safe(
    *,
    cookie_secure: bool,
    allow_insecure_transport: bool,
    profile: str = "",
) -> None:
    """Refuse to start a deployment that would send session cookies in the clear.

    The AC's "production startup rejects insecure transport or Secure-disabled
    sessions unless an explicit local-development mode is active". The escape
    is a separate, single-purpose flag rather than a value of the same setting,
    so turning it on is a sentence an operator has to write on purpose and a
    reviewer can grep for — not a default they inherited.

    Raising at startup rather than warning is the whole point. A warning about
    a cookie is read once, by whoever ran the container, in a log nobody keeps.
    """
    if cookie_secure or allow_insecure_transport:
        return
    where = f" ({profile})" if profile else ""
    raise InsecureTransportError(
        f"Refusing to start{where}: SESSION_COOKIE_SECURE is false, so the session "
        f"cookie would travel over plaintext HTTP and any network between the "
        f"browser and this server could read it. Terminate TLS and leave the "
        f"default alone, or set ALLOW_INSECURE_TRANSPORT=true if this really is a "
        f"local development run."
    )


__all__ = [
    "FORWARDED_PROTO_HEADER",
    "InsecureTransportError",
    "assert_session_transport_is_safe",
    "is_trusted_proxy",
    "parse_trusted_proxies",
    "request_is_https",
]
