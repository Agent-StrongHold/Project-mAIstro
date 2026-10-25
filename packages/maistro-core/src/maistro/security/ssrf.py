"""The outbound URL SSRF guard — one implementation, for every caller (#154).

Blocks network calls from reaching private/loopback/link-local/metadata targets
when the target URL is influenced by caller or attacker input: a URL an agent
decided to fetch, a skill manifest someone asked to import, a connector endpoint.

**Why this lives in `security/`.** It used to be `tools/net_guard.py`, where the
skills subsystem did not find it and wrote a second copy
(`marketplace._block_ssrf`). Two implementations of one control is worse than
one in the wrong place: they drift, and a reader who finds either has no reason
to think the other exists. The control belongs beside the other trust-boundary
controls, and there is now exactly one.

Two stages, and the order matters:

1. **Shape** — scheme must be `http`/`https` and the host must be non-empty.
   Anything else (`file:`, `gopher:`, a bare string) is refused without a
   lookup. This is a whitelist, not a blocklist: an unrecognised scheme is
   refused rather than passed through.
2. **Resolution** — resolve the host and refuse if *any* returned address is
   private, loopback, link-local, reserved, multicast, unspecified, or in the
   RFC 6598 shared (CGNAT) range. This is the stage that does the real work,
   because it normalises every way of spelling an address: `2852039166`,
   `0x7f000001`, `127.1`, `[::ffff:169.254.169.254]` and
   `metadata.google.internal` all arrive here as the address they denote.

Stage 1 also refuses a host that *names* an internal endpoint — `localhost`,
`metadata.google.internal`, in-cluster Kubernetes DNS — because whether those
resolve at all is environment-dependent, and refusing them by name is clearer
than relying on the unresolvable-host rule to refuse them by accident. It is
belt-and-braces: stage 2 catches every one of them wherever they do resolve.

Both stage-1 rules read the **parsed** hostname. An earlier version matched
`url.startswith("https://kubernetes.")` and friends against the raw string,
which refused `https://kubernetes.io/docs/` and read the userinfo field of
`http://localhost@example.com/` as if it were the host. A guard that refuses
real public URLs teaches its callers to route around it.

**Refusing is the default.** A host that cannot be resolved is refused rather
than allowed: the previous behaviour returned "not blocked" on `gaierror` with
the reasoning that the connection would fail anyway, which quietly made a
transient SERVFAIL into a bypass of the only stage that inspects addresses.

**Known limitation — the rebinding window.** The guard resolves the name, then
the HTTP client resolves it again when it connects. A name that answers
differently between those two lookups is not caught. Closing that needs the
resolved address pinned into the connection, which is #155's territory; it is
stated here rather than silently implied to be handled.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from maistro.types.errors import ToolError

#: The only schemes an outbound fetch may use. A whitelist, deliberately: a
#: scheme nobody listed is a scheme nobody reasoned about.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Hostnames that name an internal endpoint by name rather than by address.
#:
#: Matched against the **parsed hostname**, never against the raw URL. The
#: previous version compared `url.startswith("https://kubernetes.")` and friends,
#: which refused `https://kubernetes.io/docs/` — a public documentation site —
#: along with `https://10.example.com/` and `http://localhost@example.com/`,
#: where the userinfo field is not the host at all. A guard that refuses real
#: public URLs teaches its callers to route around it, which costs more than the
#: obfuscation the prefix list was reaching for.
#:
#: The *address* half of the old list is gone entirely rather than rewritten:
#: `getaddrinfo` returns a literal IP unchanged, so `_offending_address` already
#: catches every RFC1918, loopback, link-local and unspecified literal — and it
#: catches the obfuscations (`2852039166`, `0x7f000001`, `127.1`) that no string
#: prefix ever could, because resolution normalises every spelling to the address
#: it denotes. What remains here is belt-and-braces for names whose *resolution*
#: is environment-dependent: outside a cloud VM `metadata.google.internal` does
#: not resolve, and this refuses it by name instead of relying on the
#: unresolvable-host rule to do it by accident.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.goog",  # GCP metadata, short form
        "instance-data",  # EC2 metadata, short form
        "kubernetes.default",  # in-cluster API server
    }
)

#: Suffixes of the same kind. `.internal` covers `metadata.google.internal`,
#: `.svc` and `.local` cover Kubernetes in-cluster DNS
#: (`kubernetes.default.svc`, `…svc.cluster.local`) and mDNS. None of the four
#: is a public gTLD, so none of them can match a name on the public internet.
_BLOCKED_HOSTNAME_SUFFIXES = (
    ".localhost",
    ".internal",
    ".local",
    ".svc",
)

#: Address ranges the stdlib predicates do not refuse, and that this guard
#: must (#67).
#:
#: `IPv4Address.is_private` is derived from the IANA special-purpose registry's
#: *private* fragment, and the registry files `100.64.0.0/10` under a different
#: name — shared address space — so no Python release this repo runs on calls an
#: RFC 6598 address private, loopback, link-local, reserved or anything else
#: this guard can hang a refusal on. Measured on 3.12: every predicate is False
#: for `100.64.0.1`, and the same is true upstream. From behind this guard an
#: RFC 6598 address is exactly as internal as an RFC 1918 one: carriers and
#: enterprise networks run it as their own NAT and management plane, so an SSRF
#: probe that lands there reaches infrastructure the public internet is not
#: supposed to see.
#:
#: The other translation/embedding spellings are handled by normalization
#: inside `_is_blocked_address` rather than by trusting the stdlib predicates:
#: an IPv4-mapped IPv6 address is converted to the IPv4 address it embeds
#: **before** the `_BLOCKED_NETWORKS` loop and before the predicates run, so a
#: mapped spelling cannot slip past an IPv4-only range — which is exactly the
#: bypass #67 was reopened over: `::ffff:100.64.0.1` passed every predicate
#: (the embedded CGNAT address is not private by the stdlib's reading) and the
#: IPv4 network membership check, which is version-checked to `False` for an
#: IPv6 address. 6to4 (`2002:7f00:1::`) and NAT64 (`64:ff9b::7f00:1`) have no
#: IPv4 form to normalize to and remain refused by the stdlib predicates
#: (`is_private` / `is_reserved` respectively, pinned by tests so a Python
#: upgrade that moves either is loud). A range belongs below only when a
#: supported Python lets it through **in both spellings** — the mapped form is
#: covered by construction the moment it is listed, because normalization
#: happens before the loop that reads this tuple.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 shared address space (CGNAT)
)


#: Why a URL was refused, as a value a caller can branch on (#368).
#:
#: The message alone cannot be branched on, and the difference matters to
#: anyone reporting the outcome: `UNRESOLVABLE` means the host is not there --
#: an operational fault, indistinguishable from a server being down -- while
#: every other reason is an authorization refusal that will recur until the
#: origin is configured or the URL is changed. Reporting those two the same way
#: is how a standing policy decision hides behind a transient-looking status.
BLOCK_SCHEME = "scheme"
BLOCK_NO_HOST = "no_host"
BLOCK_INTERNAL_HOSTNAME = "internal_hostname"
BLOCK_INTERNAL_ADDRESS = "internal_address"
BLOCK_NO_ADDRESSES = "no_addresses"
#: Covers both ways a host can fail to resolve: `socket.gaierror` (no answer)
#: and `UnicodeError` (input DNS cannot represent — an ASCII label longer than
#: 63 characters raises "label empty or too long" from `getaddrinfo` before any
#: lookup happens). Both mean the host is not there; only the first was
#: translated, so the second escaped the guard entirely (#430).
BLOCK_UNRESOLVABLE = "unresolvable"

#: The reasons that mean "this host is not reachable", as opposed to "this
#: deployment refuses to reach it".
OPERATIONAL_BLOCKS = frozenset({BLOCK_UNRESOLVABLE, BLOCK_NO_ADDRESSES})


class SSRFBlockedError(ToolError):
    """Raised when an outbound URL targets (or resolves to) a private,
    loopback, link-local, reserved, multicast, or metadata-endpoint
    network location, or cannot be shown to target anything else.

    `reason` carries one of the `BLOCK_*` constants above. It defaults to the
    empty string so existing raisers and handlers are unaffected.
    """

    def __init__(self, detail: str = "", *, reason: str = "") -> None:
        super().__init__(detail)
        self.reason = reason


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether `addr` names something outside the public internet.

    An IPv4-mapped IPv6 address is first normalized to the IPv4 address it
    embeds, and every rule below then runs on that address. This is the one
    point both policy checks converge on — the `_BLOCKED_NETWORKS` loop and
    the stdlib predicates — so normalizing here is normalizing for all of
    them, and no other spelling of a target can reach either check unnormalized.

    Why the predicates cannot be left to see through the mapping themselves:
    they do for *some* embeddings on *some* Pythons — 3.12's `is_private` and
    `is_loopback` inspect the embedded address, which is why `::ffff:127.0.0.1`
    was refused all along — but not for all of them: `::ffff:100.64.0.1` passed
    every predicate (the stdlib does not file RFC 6598 under *private*, which
    is the entire reason `_BLOCKED_NETWORKS` exists), and `IPv4Network.__contains__`
    answers `False` for an IPv6 address of any spelling rather than raising.
    Relying on which embeddings the predicates happen to unwrap is how the
    mapped-CGNAT bypass shipped (#67, reopened).

    `is_unspecified` is listed explicitly. `0.0.0.0` is not `is_reserved`, and
    on many stacks connecting to it reaches localhost — so leaving it to the
    other predicates would let the most quietly dangerous address through.
    `_BLOCKED_NETWORKS` covers the ranges no predicate names; see its comment.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if any(addr in network for network in _BLOCKED_NETWORKS):
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve(hostname: str) -> list[str]:
    """Every address `hostname` resolves to. Raises `socket.gaierror`."""
    addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    return [str(sockaddr[0]) for *_meta, sockaddr in addrinfos]


def _offending_address(addresses: list[str]) -> str | None:
    """The first address in `addresses` that is not on the public internet."""
    for ip_str in addresses:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_address(addr):
            return ip_str
    return None


def _blocked_hostname(hostname: str) -> bool:
    """Whether `hostname` names an internal endpoint by name.

    The trailing dot of a fully-qualified name is stripped first: `localhost.`
    and `localhost` denote the same host, and an exact-match set that sees only
    one of them is a bypass rather than a check.
    """
    host = hostname.strip().rstrip(".").lower()
    return host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOSTNAME_SUFFIXES)


def _check_shape(url: str) -> str:
    """Refuse anything that is not a well-formed http(s) URL. Returns the host.

    Parsing comes first, and every rule below is applied to what parsing
    produced. Deciding anything from the raw string means deciding it about
    text that may not be the host — which is how `http://localhost@example.com/`
    was refused for a hostname it does not have.
    """
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        # `urlsplit` raises on things like `http://[::1` (unterminated IPv6).
        # Letting that escape would mean the guard raised something its callers
        # do not catch as a block — `browse()` handles `SSRFBlockedError`, so a
        # bare `ValueError` would surface as an unhandled error rather than a
        # refusal, and a URL the guard could not parse would have bypassed it.
        raise SSRFBlockedError(f"Outbound URL blocked (unparseable): {url!r}") from exc
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFBlockedError(
            f"Outbound URL blocked (scheme {parsed.scheme!r} is not http or https): {url!r}",
            reason=BLOCK_SCHEME,
        )
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError(f"Outbound URL blocked (no host): {url!r}", reason=BLOCK_NO_HOST)
    if _blocked_hostname(hostname):
        raise SSRFBlockedError(
            f"Outbound URL blocked (internal target): {url!r}",
            reason=BLOCK_INTERNAL_HOSTNAME,
        )
    return hostname


def _check_addresses(url: str, hostname: str, addresses: list[str]) -> None:
    offending = _offending_address(addresses)
    if offending is not None:
        raise SSRFBlockedError(
            f"Outbound URL blocked (resolves to internal address {offending}): {url!r}",
            reason=BLOCK_INTERNAL_ADDRESS,
        )
    if not addresses:
        raise SSRFBlockedError(
            f"Outbound URL blocked (host {hostname!r} resolved to no addresses): {url!r}",
            reason=BLOCK_NO_ADDRESSES,
        )


def validate_outbound_url(url: str) -> None:
    """Raise `SSRFBlockedError` unless `url` demonstrably targets the public internet.

    Call this before handing a caller-influenced URL to any HTTP client, browser
    session, or subprocess that will connect to it. Blocking: it performs a DNS
    lookup on the calling thread. Async callers want
    :func:`avalidate_outbound_url`.
    """
    hostname = _check_shape(url)
    try:
        addresses = _resolve(hostname)
    except (socket.gaierror, UnicodeError) as exc:
        raise SSRFBlockedError(
            f"Outbound URL blocked (host {hostname!r} could not be resolved, so it "
            f"cannot be shown to be external): {url!r}",
            reason=BLOCK_UNRESOLVABLE,
        ) from exc
    _check_addresses(url, hostname, addresses)


async def avalidate_outbound_url(url: str) -> None:
    """`validate_outbound_url` without blocking the event loop.

    `socket.getaddrinfo` blocks, and every caller of this guard that matters is
    async — a browse, a skill import, an outbound tool call. Resolving on the
    loop's executor keeps a slow or unreachable resolver from stalling every
    other coroutine in the process, which on a DNS timeout is seconds.
    """
    hostname = _check_shape(url)
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(None, _resolve, hostname)
    except (socket.gaierror, UnicodeError) as exc:
        raise SSRFBlockedError(
            f"Outbound URL blocked (host {hostname!r} could not be resolved, so it "
            f"cannot be shown to be external): {url!r}",
            reason=BLOCK_UNRESOLVABLE,
        ) from exc
    _check_addresses(url, hostname, addresses)


__all__ = [
    "ALLOWED_SCHEMES",
    "SSRFBlockedError",
    "avalidate_outbound_url",
    "validate_outbound_url",
]
