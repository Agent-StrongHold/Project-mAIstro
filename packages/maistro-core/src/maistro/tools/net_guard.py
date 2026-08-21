"""Outbound URL SSRF guard.

Blocks tool-initiated network calls from reaching private/loopback/
link-local/metadata network targets when the target URL is influenced by
caller/attacker input (e.g. a URL an agent decided to fetch or browse).

Ported from stronghold's `tools/executor.py` (`_BLOCKED_URL_PREFIXES` +
`_resolve_blocks_private`) as a standalone, reusable helper. Pure stdlib
(`socket`, `ipaddress`, `urllib.parse`) — no external dependencies.

Two-stage check:
  1. Prefix blocklist — fast, catches literal internal hostnames/IPs and
     dangerous non-HTTP schemes without any DNS lookup.
  2. DNS resolution — resolves the hostname and blocks if any resolved
     address is private/loopback/link-local/reserved/multicast. This
     catches DNS-rebinding attacks where a public-looking hostname later
     resolves to an internal address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from maistro.types.errors import ToolError

# Covers full RFC1918, loopback, link-local, metadata, IPv6 private ranges,
# plus dangerous non-HTTP schemes.
_BLOCKED_URL_PREFIXES = (
    # HTTP variants
    "http://localhost",
    "http://127.",  # Full 127.0.0.0/8
    "http://0.",
    "http://0.0.0.0",
    "http://[::1]",  # IPv6 loopback
    "http://[fe80:",  # IPv6 link-local
    "http://[fc",  # IPv6 unique local (fc00::/7)
    "http://[fd",  # IPv6 unique local (fc00::/7)
    "http://169.254.",  # AWS/cloud metadata
    "http://metadata.",
    "http://kubernetes.",
    "http://10.",  # RFC1918 10.0.0.0/8
    "http://172.16.",
    "http://172.17.",
    "http://172.18.",
    "http://172.19.",
    "http://172.20.",
    "http://172.21.",
    "http://172.22.",
    "http://172.23.",
    "http://172.24.",
    "http://172.25.",
    "http://172.26.",
    "http://172.27.",
    "http://172.28.",
    "http://172.29.",
    "http://172.30.",
    "http://172.31.",
    "http://192.168.",  # RFC1918 192.168.0.0/16
    # HTTPS variants — redirects from public HTTPS to private IPs
    "https://localhost",
    "https://127.",
    "https://0.",
    "https://0.0.0.0",
    "https://[::1]",
    "https://[fe80:",
    "https://[fc",
    "https://[fd",
    "https://169.254.",
    "https://metadata.",
    "https://kubernetes.",
    "https://10.",
    "https://172.16.",
    "https://172.17.",
    "https://172.18.",
    "https://172.19.",
    "https://172.20.",
    "https://172.21.",
    "https://172.22.",
    "https://172.23.",
    "https://172.24.",
    "https://172.25.",
    "https://172.26.",
    "https://172.27.",
    "https://172.28.",
    "https://172.29.",
    "https://172.30.",
    "https://172.31.",
    "https://192.168.",
    # Dangerous schemes
    "file://",
    "gopher://",
    "ftp://",
    "dict://",
    "ldap://",
)


class SSRFBlockedError(ToolError):
    """Raised when an outbound URL targets (or resolves to) a private,
    loopback, link-local, reserved, multicast, or metadata-endpoint
    network location."""


def _resolve_blocks_private(hostname: str) -> str | None:
    """Resolve *hostname* via DNS and return the offending IP if any
    resolved address is private/internal. Returns None if all addresses
    are public (or the hostname cannot be resolved).

    This defeats DNS rebinding attacks where a hostname initially points
    at a public IP but later resolves to an internal one.
    """
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return None  # Unresolvable — will fail at connect time

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str: str = str(sockaddr[0])
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return ip_str
    return None


def validate_outbound_url(url: str) -> None:
    """Raise `SSRFBlockedError` if *url* targets a private/internal/
    metadata network location.

    Call this before handing a caller-influenced URL to any HTTP client,
    browser session, or subprocess that will actually connect to it.
    """
    lowered = url.strip().lower()
    for prefix in _BLOCKED_URL_PREFIXES:
        if lowered.startswith(prefix):
            raise SSRFBlockedError(f"Outbound URL blocked (internal target): {url!r}")

    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        return

    offending_ip = _resolve_blocks_private(hostname)
    if offending_ip is not None:
        raise SSRFBlockedError(
            f"Outbound URL blocked (resolves to internal address {offending_ip}): {url!r}"
        )


__all__ = ["SSRFBlockedError", "validate_outbound_url"]
